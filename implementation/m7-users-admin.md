# M7 Users, permissions, audit and admin pages

Can start any time after M1; needs M6 only for sending account emails (links are also shown to the admin and logged).

**Goal:** requirements 08 §8.5 phase 8: a kit can be added from the UI; every permission rule holds.
**Done when:** an admin adds a kit through the configuration editor, the generated permission suite covers every endpoint, and the lockout, last-admin and token rules pass.

---

- [ ] **M7.1 User lifecycle**
  - Do: invite (link in the response and by email), accept, resend (old link invalid), change role (WEB-05 rules), deactivate (ends sessions, WebSocket `4403`), reactivate; bulk CSV invite (could, last).
  - Check: TST-16 cases for last admin, own role, deactivated user's old session.
  - Ref: [design/02 §2.6.3](../design/02-api.md), [design/03 §3.11](../design/03-database-schema.md) · Needs: M1.10

- [ ] **M7.2 Passwords, reset, lockout**
  - Do: password change (ends other sessions), reset request (always `202`) and reset (1 h, one-time), lockout after 5 failures for 15 min.
  - Check: lockout with the fake clock; expired / reused / replaced tokens → `410`.
  - Ref: [design/02 §2.2](../design/02-api.md) · Needs: M7.1

- [ ] **M7.3 Audit log**
  - Do: every write and every login writes `audit_entry` + `audit_change`; `reason` required where design/02 says so; `/audit` with filters and cursor.
  - Check: a config save produces one entry with the field changes and the reason.
  - Ref: [design/02 §2.6.11](../design/02-api.md), DD20 · Needs: M7.1

- [ ] **M7.4 Rate limits**
  - Do: 120 requests/min per user; 10 logins/min and 5 resets/hour per IP; `429` with `Retry-After` (machine time).
  - Check: NFR-03 burst test.
  - Ref: [design/02 §2.1](../design/02-api.md) · Needs: M7.1

- [ ] **M7.5 Generated permission tests**
  - Do: test generator over the OpenAPI schema + role matrix: no session → `401`, operator on admin endpoint → `403`, write without CSRF → `403`, WebSocket without session or wrong origin refused, no admin-only fields for operators.
  - Check: a newly added endpoint is tested without writing a new test.
  - Ref: [design/02 §2.8](../design/02-api.md), [design/12 §12.3](../design/12-testing.md), DD93 · Needs: M7.3

- [ ] **M7.6 Admin pages: users and audit**
  - Do: users table with actions, disabled buttons with tooltips for WEB-05 rules, invite hint "opens only on this PC"; audit table with filters and infinite scroll.
  - Check: Playwright: invite → accept in a second browser context on the same PC → active.
  - Ref: [design/10 §10.4.6](../design/10-ui.md) · Needs: M7.1, M7.3

- [ ] **M7.7 Configuration editor and profile**
  - Do: `/admin/config` (site, kits, recipients, effective values with source, validate, save with reason, version-conflict dialog, history, import/export); `/profile` with name, password and email preferences.
  - Check: **M7 done-when** above; TST-13 conflict through the UI.
  - Ref: [design/10 §10.4.5](../design/10-ui.md), [design/02 §2.6.2](../design/02-api.md) · Needs: M3.2, M7.6
