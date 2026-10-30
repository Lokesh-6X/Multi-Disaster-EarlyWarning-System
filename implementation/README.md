# Implementation Checklists

The working version of the [implementation plan](../analysis/09-implementation-plan.md): every milestone is a checklist of small tasks. Work top to bottom, tick the box when the task's **Check** passes, and move on.

## How to use

1. Open the file of the current milestone (table below) and take the **first unticked task** whose "Needs" are ticked.
2. Do what **Do** says, using the design section in **Ref** as the exact rule.
3. Run the **Check**. Only when it passes, tick the box (`- [x]`) and update the status table below.
4. If the design is wrong or unclear, stop and fix the design document first (new D/DD number; next free D42, DD136), then continue.

Each task is sized to be finished in one sitting (roughly a few hours to a day). The ML track (Kaggle, D40) runs in parallel with the backend milestones; [ml-track.md](ml-track.md) says which backend tasks each ML step needs.

## Status

| Milestone | File | Tasks | Done | State |
|---|---|---|---|---|
| M0 Foundations + week-1 checks | [m0-foundations.md](m0-foundations.md) | 12 | 12 | ✅ Done (2026-10-30) |
| M1 Skeleton (first demo) | [m1-skeleton.md](m1-skeleton.md) | 12 | 7 | ▶ In progress (next: M1.8) |
| M2 Data pipeline | [m2-data-pipeline.md](m2-data-pipeline.md) | 9 | 0 | Waiting |
| M3 Configuration API and onboarding | [m3-config-onboarding.md](m3-config-onboarding.md) | 8 | 0 | Waiting |
| M4 Forecast worker | [m4-forecast-worker.md](m4-forecast-worker.md) | 8 | 0 | Waiting |
| M5 Alert engine | [m5-alert-engine.md](m5-alert-engine.md) | 12 | 0 | Waiting |
| M6 Notifications | [m6-notifications.md](m6-notifications.md) | 6 | 0 | Waiting |
| M7 Users, permissions, audit, admin | [m7-users-admin.md](m7-users-admin.md) | 7 | 0 | Waiting |
| M8 Dashboard pages | [m8-dashboard.md](m8-dashboard.md) | 6 | 0 | Waiting |
| M9 Real models, reports, demo | [m9-release.md](m9-release.md) | 9 | 0 | Waiting |
| ML track (parallel, Kaggle) | [ml-track.md](ml-track.md) | 10 | 0 | T1 can start with M0 |
| Real kit (when hardware is ready) | [real-kit.md](real-kit.md) | 5 | 0 | Waiting for hardware |

## Order at a glance

```
M0 ─► M1 ─┬─► M2 ─────────────────────────┐
          ├─► M3 ─► M4 ─► M5 ─► M6        ├─► M8 ─► M9
          └─► M7 (any time after M1) ─────┘
ML: T1a/T1b (from M0) ─► T2a (needs M1.4) ─► … ─► T8 (needs M4.1) ─► M9.1
```

## Rules for every task (definition of done)

| Rule | Meaning |
|---|---|
| Tests first where rules live | Contract, QC, config, alert engine: write the test from the design table, then the code |
| `scripts/test.ps1` passes | Before ticking, the whole fast suite still passes |
| Matches the design | Behaviour follows the cited section; a difference means updating the design first |
| Logs | New log lines use a stable `event` code ([design/14 §14.2](../design/14-operations.md)) |
| Requirement IDs | Put the requirement ID (e.g. `AL-09`) in the test name or docstring |
| Still starts | `scripts/start.ps1` still brings the whole system up |
| Words | Always "site", never "campus" |

## Where things go

| Thing | Folder |
|---|---|
| Backend package `ews` (5 processes) | `backend/ews/` ([design/01 §1.6](../design/01-architecture.md)) |
| Database migrations | `backend/migrations/` |
| Tests | `backend/tests/{unit,integration,api,e2e,harness}/`, `frontend/src/**/*.test.ts` |
| Frontend | `frontend/` |
| Simulator | `simulator/` (never imports `ews`) |
| Training | `ml/` (notebooks + `ml/src/`) |
| Models | `models/` (`registry.json` committed, files ignored) |
| Config | `config/` (`defaults.yaml`, example and demo site files, Mosquitto) |
| Scripts | `scripts/` |
