# 13. Frontend Performance

How the React dashboard stays fast, light and always current. It covers the browser-side data architecture, real-time updates, chart rendering, loading and caching. Page layouts and wireframes belong to [10](10-ui.md); this document is the technical foundation those pages are built on.

Decisions referenced: DD29–DD35 in [decisions.md](decisions.md).

## 13.1 What "fast" means here

The dashboard is not a content site. Its job is to show **the current alert state and the latest reading, immediately and correctly**, often left open for hours on an operator's PC, sometimes in several tabs, and during demos with the simulator replaying weather at 60× speed. The design is driven by four facts about this system:

| Fact | Consequence |
|---|---|
| Forecast runs are **immutable** once stored (AL-12) | A run can be cached forever by its ID |
| Readings arrive at a **fixed rhythm** (1/min/kit; 15 min / 1 h after resampling) | Timestamps of regular series need not be sent at all |
| Replay mode pushes **1–2 readings/s per kit** at 60–120× (TST-01), with several kits and event bursts | Rendering must be decoupled from the event rate |
| Operators keep **several tabs** open | One connection and one alert sound per browser, not per tab |

### Budgets

| Metric | Budget | Requirement |
|---|---|---|
| Server receive → value on screen | ≤ 1 s (requirement 5 s) | NFR-01 |
| Alert change → banner on screen | ≤ 1 s, never waits for charts | §7.6 |
| Login page JS (gzip) | ≤ 90 KB | — |
| Dashboard route JS incl. charts (gzip) | ≤ 350 KB | — |
| Dashboard usable after login (localhost) | ≤ 1.5 s | — |
| Main-thread work per live update | ≤ 4 ms average, no frame > 50 ms | — |
| Memory after 8 h open (one session) | Flat; no growth beyond the ring buffers | — |

## 13.2 Browser data architecture

```
                     ┌───────────────────────── one browser ─────────────────────────┐
                     │                                                               │
   /api/v1/ws ◄──────┤ Leader tab (Web Locks)                                        │
   (one socket)      │   └─ WebSocket client ──► Event router ──┬─► BroadcastChannel ─┼─► follower tabs
                     │                                          │                     │   (same router)
                     │                                          ▼                     │
                     │              ┌───────────────────────────┴────────────┐        │
                     │              │                                        │        │
                     │      Server-state cache                       Live store       │
                     │      (TanStack Query)                         ring buffers per │
                     │      REST resources, patched                  kit × variable   │
                     │      in place by events                       (typed arrays)   │
                     │              │                                        │        │
                     │              └──────────► Frame scheduler ◄───────────┘        │
                     │                      (one render per animation frame)          │
                     │                                   │                            │
                     │              urgent: banner, tiles │ deferred: charts, lists   │
                     └───────────────────────────────────────────────────────────────┘
```

Two stores, each holding one kind of data:

| Store | Holds | Why separate |
|---|---|---|
| **Server-state cache** (TanStack Query) | Every REST resource by key (`['alerts','active']`, `['run', id]`, `['kit', 'KIT-01']`) | Request dedup, caching, background refresh, reconnect handling come built in |
| **Live store** (small module, read through React's `useSyncExternalStore`) | The last *N* minutes of live readings per kit and variable in fixed-size ring buffers | High-frequency numeric data must not go through a general cache or React state |

The client mirrors the database's normalization ([03](03-database-schema.md)): entities are stored once by ID (alert by `id`, kit by `kit_id`, run by `run_id`) and views reference them, so an `alert.changed` event updates one entry and every list, banner and detail panel showing that alert updates with it.

## 13.3 Ideas

### 13.3.1 One socket per browser, elected leader (DD29)

Each tab tries to take a Web Lock named `ews-socket`. The tab that holds it is the **leader**: it opens the only WebSocket ([02 §2.7](02-api.md)) and re-broadcasts every event on a `BroadcastChannel`. Other tabs are **followers** and feed the same event router from the channel. When the leader tab closes, the lock passes to another tab, which connects, receives `hello`, and broadcasts a `resync` so all tabs reload their state over REST (DD17).

| Benefit | Detail |
|---|---|
| **One alert sound** | Only the leader plays the sound for `alert.changed`, so three open tabs do not beep three times |
| One connection | The server's fan-out and the slow-client limit see one client per browser |
| Same state everywhere | All tabs apply the same ordered event stream |

Fallback: if Web Locks or BroadcastChannel are unavailable, every tab opens its own socket, which is still correct.

### 13.3.2 Events patch the cache; they do not trigger refetches

The event router maps each WebSocket event ([02 §2.7.3](02-api.md)) to a precise cache action:

| Event | Action |
|---|---|
| `reading.new` | Append to the live store; update the kit's "latest reading" entry |
| `alert.changed`, `alert.acknowledged`, `alert.note_added` | Patch the alert entity in place; insert into or remove from the active-alerts list |
| `kit.status`, `kit.qc_flag`, `kit.message_rejected`, `kit.maintenance_notice` | Patch the kit-health entry |
| `forecast.run_completed` | Set `latestRunId`; the forecast page fetches `/forecast/runs/{id}` once (§13.3.3) |
| `config.changed` | Mark config queries stale (admins); show a notice to others |
| `system.status` | Patch the status entry |
| `hello` (after any reconnect) | Refetch only the queries that are on screen; mark the rest stale (DD17) |

No polling while the socket is healthy. A typical hour on the dashboard costs a handful of REST calls, not hundreds.

### 13.3.3 Immutable, run-addressed forecasts (DD30)

A forecast run never changes after it is stored, so the forecast is addressed **by run**, not "latest":

1. The client learns the newest `run_id` from `GET /site`, `/live`, or the `forecast.run_completed` event.
2. It fetches `GET /forecast/runs/{run_id}` (and `/probabilities`), which the API serves with `Cache-Control: private, max-age=31536000, immutable`.
3. The browser HTTP cache and the query cache keep the run; going back to an earlier run, or comparing two runs, is instant and costs no request.
4. Chart options derived from a run are computed once per `run_id` (memoized by that key), not on every render.

`GET /forecast/latest` stays for convenience and simply returns the newest run in the same shape.

### 13.3.4 Implicit time axis for regular series (DD31)

Resampled readings and forecasts are on a fixed grid, so sending a timestamp per point is waste. The API offers `format=columnar`:

```json
// GET /kits/KIT-01/readings?from=…&to=…&resolution=15m&fields=temp_c,wind_gust_kmh&format=columnar
{
  "kit_id": "KIT-01", "resolution": "15m",
  "start": "2026-11-02T00:00:00Z", "step_s": 900, "count": 96,
  "columns": {
    "temp_c":        [26.8, 26.6, 26.5, null, 26.9],
    "wind_gust_kmh": [9.4, 11.0, 10.2, null, 12.1]
  }
}
```

- Point *i* is at `start + i × step_s`; gaps are `null` (kit offline, HW-09), which charts draw as breaks rather than misleading lines.
- Arrays go straight into ECharts `dataset` sources (or `Float32Array`s for the live store) with no per-point object allocation.
- About 40–60 % smaller than row objects before gzip and much cheaper to parse; the forecast response already uses arrays per variable ([02 §2.6.6](02-api.md)).
- Raw (1-minute) readings are not guaranteed regular (late or missing messages), so `resolution=raw` adds a `ts` column of epoch seconds.

### 13.3.5 Ring buffers and frame-coalesced rendering (DD32)

The live store keeps, per kit and variable, a `Float32Array` ring buffer of the last 6 h (360 points at 1/min) plus a parallel timestamp buffer. Memory is fixed: no growth over an 8-hour shift.

Rendering is decoupled from the event rate:

1. Events only write into the store and mark the affected views dirty.
2. A frame scheduler runs once per `requestAnimationFrame` and flushes all dirty views together: a burst of readings from several kits causes at most one chart update per frame, not one per reading.
3. Updates are split by priority: the alert banner and value tiles render as **urgent** updates; charts and long lists render inside `startTransition`, so the banner is never delayed by chart work (§7.6).
4. When the tab is hidden (Page Visibility API), nothing is drawn; data keeps flowing into the store, and one render happens when the tab becomes visible.

### 13.3.6 Draw only what the screen can show

| Technique | Where |
|---|---|
| **Automatic resolution**: the chart asks for `raw`, `15m` or `1h` so the number of points is at most ≈ 2× the chart's pixel width | History charts |
| ECharts `sampling: 'lttb'` (largest-triangle-three-buckets) for any series still denser than the pixel width | Long raw ranges in kit health |
| Canvas renderer (not SVG) for time series; `animation: false` for live updates | All charts |
| Uncertainty band P10–P90 drawn as one stacked area, not 72 separate shapes | Forecast charts |
| Virtualised rows (TanStack Virtual) + cursor pagination ([02](02-api.md), DD19) as infinite scroll | Alert history, audit log, email log, rejected messages |

### 13.3.7 Critical-first loading and code splitting (DD33)

```
login (≈ 90 KB) ─► shell + alert banner + live tiles (/live, tiny) ─► charts (lazy) ─► map / admin (lazy)
```

| Rule | Detail |
|---|---|
| Route-level splitting | Each page is a lazy route chunk; admin pages (config, users, audit, notifications) are separate chunks that **operators never download** |
| Modular ECharts | Import from `echarts/core` with only the line chart, custom series, mark-area, tooltip, grid, dataZoom and canvas renderer; about one third of the full bundle |
| Leaflet only on the map page | The map is a "could" feature (§7.2) and must not cost other pages anything |
| Shell first | The banner and tiles render from `/live` (one small request) before any chart chunk has loaded; charts show skeletons with the same size, so the layout does not jump |
| Prefetch on intent | Hovering or focusing a navigation link prefetches that route's chunk and its first query |
| No CSS-in-JS runtime | CSS modules + CSS custom properties; IMD colours defined once as variables (`--level-yellow`, `--level-orange`, `--level-red`) |

### 13.3.8 Honest freshness (NFR-04)

Speed is useless if stale data looks fresh. Every widget shows the age of what it displays, and the age is computed against **server time**, not the PC clock:

- `hello.server_time` gives the offset between the PC clock and the server; all "x s ago" labels use it.
- Live tiles fade and show "No data for 3 min" when the kit's readings stop; the kit badge shows Offline from the `kit.status` event.
- A connection pill shows Live / Reconnecting (with retry countdown) / Polling.
- **Degraded mode (DD34):** if the WebSocket fails three reconnects in a row but REST still works (e.g. a proxy blocks WebSockets), the client polls `/live`, `/alerts` and `/system/status` every 15 s and says so, so alerts stay visible.
- Times are formatted with one cached `Intl.DateTimeFormat` per site timezone (NFR-06); creating formatters per render is surprisingly expensive.

### 13.3.9 Safe caching across reloads

| Data | Persisted between page loads? |
|---|---|
| Forecast runs, model reports (immutable or rarely changing) | Yes: query cache persisted to IndexedDB, keyed by user |
| Alerts, live readings, kit health, config | No: always fetched fresh; a stale alert state must never be shown as current |
| Anything | Cleared on logout, on `4401`/`4403` close, and when a different user logs in |

No service worker and no offline mode: an early-warning dashboard that works offline would show outdated alert state with confidence.

## 13.4 What we deliberately do not do

| Not used | Why |
|---|---|
| Server-side rendering / Next.js | Login-only app on localhost; SSR adds a Node server and complexity for no gain |
| Redux or a global state framework | Server state lives in TanStack Query; the only client state is the live store and UI state |
| GraphQL | REST resources are already shaped per page; caching by run ID is simpler with plain HTTP |
| Service worker / offline mode | See §13.3.9 |
| Desktop push notifications | Not in the requirements (email is the only notification channel, D17); the banner + sound cover logged-in users |
| Web Workers for data processing | Payloads are small (a run is 72 × 5 × 3 values per kit); the main-thread budget is met without them. Revisit only if profiling shows a need |

## 13.5 API additions this needs

Applied to [02-api.md](02-api.md):

| Addition | Section |
|---|---|
| `format=columnar` on `GET /kits/{kit_id}/readings` (start + step + columns; `ts` column for raw) | 02 §2.6.4 |
| `Cache-Control: private, max-age=31536000, immutable` on `GET /forecast/runs/{run_id}` and its `/probabilities` | 02 §2.1, §2.6.6 |
| `latest_run_id` in `GET /site` and `GET /live` | 02 §2.6.4 |

## 13.6 Measuring

| Tool | Checks |
|---|---|
| `rollup-plugin-visualizer` in the Vite build | Bundle budgets per route; build fails if a budget is exceeded |
| `web-vitals` (logged to the console in development) | LCP, INP, CLS of the dashboard |
| A dev-only overlay | Events/s received, renders/s, ring-buffer fill, socket role (leader/follower), server clock offset |
| Replay at 60× with 5 simulated kits ([11](11-simulator.md)) | Frame budget holds; memory stays flat over a 1-hour run |
| Playwright test with three tabs | One socket, one sound, all tabs consistent after the leader tab closes |

These become test cases in [12](12-testing.md).

## 13.7 Library choices

| Need | Choice |
|---|---|
| Build | Vite + React + TypeScript (DD9) |
| Server state | TanStack Query (+ persister for IndexedDB, §13.3.9) |
| Routing | React Router with lazy routes |
| Charts | Apache ECharts, modular import |
| Map | Leaflet (lazy) |
| Virtual lists | TanStack Virtual |
| API types | Generated from FastAPI's OpenAPI schema |

## 13.8 Requirement coverage

| Requirement | Where |
|---|---|
| NFR-01 | §13.3.2, §13.3.5 (≤ 1 s budget) |
| NFR-03 | §13.3.3 (per-run caching on both sides) |
| NFR-04 | §13.3.1 resync, §13.3.8 freshness and degraded mode |
| NFR-06 | §13.3.8 timezone formatting |
| WEB-24 | §13.3.1, §13.3.2 |
| §7.6 banner + optional sound | §13.3.1 (one sound), §13.3.5 (urgent rendering) |
| TST-01 (replay 60×) | §13.3.5, §13.6 |
