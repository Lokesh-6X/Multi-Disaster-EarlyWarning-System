# M6 Notifications

**Goal:** requirements 08 §8.5 phase 7: alert emails arrive for create, upgrade and cancel.
**Done when:** every email of Scenario 2 arrives in Mailpit with exactly the subjects of design/09 §9.3, as one thread per alert, and a stopped-then-restarted mailer sends only the newest state.

---

- [ ] **M6.1 Mailer loop**
  - Do: `mailer` process: wake on `email.queued`, poll every 30 s; claim with `FOR UPDATE SKIP LOCKED LIMIT 20` → `sending`; reset `sending` → `queued` at start-up; `Sender` protocol with an SMTP sender (Mailpit locally).
  - Check: two mailers running → no email sent twice (TST-13).
  - Ref: [design/09 §9.2, §9.11](../design/09-notifications.md) · Needs: M5.10

- [ ] **M6.2 Supersede, retries, failures**
  - Do: skip when a newer change of the same alert exists for the address; retries 30 s × 2ⁿ up to 15 min, 6 attempts (machine time); 5xx → failed at once; `email_attempt` rows.
  - Check: DD73 test (stop mailer, create + upgrade, start → only the upgrade); temporary failure → retried.
  - Ref: [design/09 §9.6–9.7](../design/09-notifications.md), DD71, DD73 · Needs: M6.1

- [ ] **M6.3 Templates**
  - Do: Jinja2 templates (text + HTML) for `alert_public`, `alert_operator`, `maintenance`, `invite`, `password_reset`; subjects with whole-hour windows; advice at send time; "open on the control PC"; "normal not yet calibrated".
  - Check: golden file for every template × change kind.
  - Ref: [design/09 §9.3–9.4, §9.12](../design/09-notifications.md) · Needs: M6.1

- [ ] **M6.4 Headers and demo prefix**
  - Do: `Message-ID`, `In-Reply-To`/`References` to the first email of the alert, `X-EWS-Alert-Id`, `X-EWS-Change`, `Auto-Submitted`; `[DEMO]` prefix in demo mode.
  - Check: DD72 test: all emails of one alert share `References`.
  - Ref: [design/09 §9.8](../design/09-notifications.md) · Needs: M6.3

- [ ] **M6.5 Maintenance and account emails**
  - Do: maintenance email once when a notice opens; account emails queued by `api` (used in M7); failed account email → link printed as `account_link.fallback` in the mailer log.
  - Check: Scenario 5 maintenance email once; forced SMTP failure prints the link.
  - Ref: [design/09 §9.7, §9.9](../design/09-notifications.md) · Needs: M6.3, M2.5

- [ ] **M6.6 Notifications admin API and Scenario 2 emails**
  - Do: `/notifications/emails`, `/{id}`, `/{id}/retry`; `failed_emails` in `/system/status`; Mailpit assertions in the Scenario 2 test.
  - Check: **M6 done-when** above.
  - Ref: [design/02 §2.6.10](../design/02-api.md), [design/12 §12.4](../design/12-testing.md) · Needs: M6.4, M5.12
