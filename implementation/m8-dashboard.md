# M8 Dashboard pages complete

**Goal:** requirements 08 §8.5 phase 6: all "M" pages of requirements 07 §7.2 work.
**Done when:** every "M" page works on the demo clock at 60× with 5 simulated kits, no frame takes longer than 50 ms, and the bundle budgets hold.

---

- [ ] **M8.1 Alert banner and alerts pages**
  - Do: persistent banner (most severe alert, counts, needs-acknowledgement, inline Acknowledge, sound once per escalation); `/alerts` active + history with filters; alert detail side panel with trend, history, notes, advice, suppress; "Raise alert" dialog; acknowledge-link flow (`?ack=1` asks for confirmation).
  - Check: Playwright: acknowledgement race in two contexts; escalation flashes the banner once.
  - Ref: [design/10 §10.3, §10.4.3](../design/10-ui.md), DD74, DD76, DD78 · Needs: M5.12

- [ ] **M8.2 Live dashboard complete**
  - Do: site status per hazard, all kits with tiles, sparklines, QC state, DHT11 badge, offline greying, squall precursors, next-24 h probability strip.
  - Check: offline kit shows "No data for …"; a faulty value shows "—".
  - Ref: [design/10 §10.4.1](../design/10-ui.md) · Needs: M4.7, M8.1

- [ ] **M8.3 Frontend data architecture**
  - Do: TanStack Query store patched by an event router; live store with `Float32Array` ring buffers; frame scheduler (urgent banner/tiles, deferred charts); nothing drawn while hidden. One socket per tab for now; leader-tab socket (DD29) only if time allows.
  - Check: Vitest for the event router and live store; 60× replay with 5 kits → no frame > 50 ms, memory flat over 30 min.
  - Ref: [design/13 §13.2–13.3](../design/13-frontend-performance.md) · Needs: M8.2

- [ ] **M8.4 Forecast page polish**
  - Do: compare two runs, "New run — view" notice, degraded/skipped banners, probability table shading; immutable run cache.
  - Check: switching to a previous run makes no network request.
  - Ref: [design/10 §10.4.2](../design/10-ui.md), DD30 · Needs: M4.8, M8.3

- [ ] **M8.5 Errors, reconnect, freshness**
  - Do: error handling by `code` (design/10 §10.8); reconnect backoff 1, 2, 5, 10, 30 s with reload; freshness on server time; degraded polling (DD34) if time allows.
  - Check: stop and start `api` during a session → reconnects and reloads (NFR-04).
  - Ref: [design/10 §10.7–10.8](../design/10-ui.md), [design/02 §2.7.1](../design/02-api.md) · Needs: M8.3

- [ ] **M8.6 Loading and budgets**
  - Do: route-level code splitting (admin chunks separate), modular ECharts, lazy map, shell first; bundle visualizer with failing budgets.
  - Check: **M8 done-when** above; login ≤ 90 KB, dashboard ≤ 350 KB gzip.
  - Ref: [design/13 §13.3.7, §13.6](../design/13-frontend-performance.md) · Needs: M8.5
