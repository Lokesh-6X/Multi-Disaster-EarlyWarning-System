# Real kit (when the hardware is ready)

Requirements 08 §8.5 phase 2. The software side is small because the simulator already speaks the same contract.
**Done when:** real readings from the kit appear on the dashboard and its first day on the kit-health page shows no unexpected flags.

---

- [ ] **K1 Agree the contract with the hardware builders**
  - Do: hand over [requirements 02 §2.4](../requirements/02-hardware.md) (topics, payload, last will, one message per minute, UTC via NTP) and the kit's MQTT username (`KIT-xx`) and password.
  - Check: builders confirm their firmware sends exactly the contract fields.
  - Needs: M1.8

- [ ] **K2 Configure the kit**
  - Do: add the kit in the configuration editor or YAML: zone, position, elevation of the sensor, mount height, exposure, calibration offsets from the side-by-side calibration.
  - Check: `/config/effective?kit_id=…` shows the kit's values with source `kit`.
  - Ref: [design/14 §14.1.4](../design/14-operations.md) · Needs: M3.2

- [ ] **K3 Network**
  - Do: fixed IP for the laptop (router reservation); Windows Firewall rule for TCP 1883 on private networks only; Mosquitto user for the kit.
  - Check: the kit connects; `online` appears on the kit-health page.
  - Ref: [design/14 §14.1.4](../design/14-operations.md)

- [ ] **K4 First day on watch**
  - Do: watch kit health for a day: rejected messages (contract drift), clock offset, QC flags, BME280 vs DHT11 difference, RSSI.
  - Check: no rejected messages; clock offset within limits; flags explained.
  - Ref: [design/10 §10.4.4](../design/10-ui.md)

- [ ] **K5 After 4–8 weeks**
  - Do: confirm the normal offset was computed (after 28 days, D33); fine-tune the TFT on the kit's data and compare before/after (ML-06).
  - Check: `normal_offset` row exists; fine-tuned model registered only if better on the held-out days.
  - Ref: [design/06 §6.10](../design/06-ml-training.md), [design/07 §7.9](../design/07-forecast-worker.md)
