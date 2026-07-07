# Cable Heat-Load Measurement System — Plan

Goal (phase 1): build a heater-calibration system for the isolated 4 K plate in the
cryostat, controlled over Ethernet from a CTC100, organized with the `lab_procedure`
scheduling framework. Phase 2 (later) reuses the resulting calibration curve to infer
cable heat loads from 40 K → 4 K.

This document records findings, decisions, and a phased implementation plan.

> **Status (2026-07-07):** Phases 0–2 built and verified offline — CTC100 driver
> (Ethernet + USB transports) + physical mock, bring-up scripts (`src/scripts/`),
> and the full heater-calibration procedure with 2-table SQLite/CSV saving. See
> `BRINGUP.md` for the commissioning checklist. Remaining: bench bring-up on the
> real CTC100, then Phase 3 (curve fit) and Phase 4 (cable measurements).
>
> **40 K sensor architecture:** it lives on a *separate* USB-connected CTC100 owned
> by the NEST FridgeControl GUI. USB/serial has no instrument-side arbitration, so
> two processes sharing the port corrupt each other's reads. The current
> FridgeControl file (`FridgeControl_NEST_mcirillo.py`) already runs a **RabbitMQ
> RPC server** (queue `fridge_control_rpc_queue`, cmd `T40K`), so we read the 40 K
> value as an **RPC client** (`cable_heat_load/instruments/fridge_rpc.py`) instead
> of opening the port. It's optional/informational — the run degrades to `NaN`
> 40 K if the broker/GUI is down.

---

## 1. Findings & answers to open questions

### 1.1 Temperature sensors — do we need a calibration file on USB?
**No.** The sensors (photo `ref/SCR-20260706-jbwh.jpeg`) are **Lakeshore DT-670B-CU
silicon diodes** (this one hand-labeled "40K Amplifier Si Diode", serial D6122510).
The DT-670 family follows the **standard Lakeshore DT-670 response curve** — that is the
whole point of the "-B" accuracy band: they conform to the standard curve within a
tolerance band (~±0.5 K over our range), *without* individual calibration.

Implication for the CTC100:
- Set each channel's **sensor type = Diode**, and select the built-in **DT-670 standard
  curve** (the CTC100 ships with the standard silicon-diode curve).
- A per-sensor `.340` calibration file on USB is **optional** and only buys you the last
  fraction of a Kelvin of absolute accuracy. For distinguishing a ~4 K isolated plate
  from a ~40 K plate, and for measuring *changes* in the 4 K plate temperature, the
  standard curve is more than adequate. We can add individual cal files later if phase-2
  heat-load numbers demand it.
- Action item: on the CTC100, confirm the diode/DT-670 standard curve is selectable per
  channel; if only a generic "Diode" linearization exists, download the DT-670 standard
  curve table from lakeshore.com/sensors and load it once.

### 1.2 Talking to the CTC100 over Ethernet
Confirmed from the manual (Remote Programming, p.79–82):
- All ports (USB/RS-232/Ethernet/GPIB) accept the **same ASCII command set**.
- Ethernet: send **raw ASCII over TCP to port 23** (also supports UDP:23 and telnet:23).
  We will use **raw TCP socket to port 23**.
- **Line termination:** commands end with `\n` (LF) — or `\r\n`. Replies always end with
  `\r\n`.
- **Single-client lock:** once a client talks to port 23, the CTC100 ignores other
  clients until the connection closes/times out, `System.IP.Close` is pressed, or reboot.
  → our driver must own one persistent socket and close it cleanly.
- The IP address must be set on the instrument first (System Setup menu). Can be a direct
  Cat5 link to the PC (no switch needed).
- Smoke test: `popup hello` pops a window on the CTC; `description` returns a string.

The existing reference driver `ref/FridgeControlNEST/Hardware/CTC100.py` uses **serial**
(`serialInst`, `/dev/ttyUSB*`). Its command vocabulary is exactly what we need
(`getOutput`/`?`, `<chan> <value>`, `<chan>.PID.*`, `outputEnable on/off`, etc.). We will
**port that command vocabulary onto a TCP-socket transport** rather than reuse the serial
class.

### 1.3 Heater drive & the 4-wire power measurement
Wiring (photo `ref/IMG_7085.jpeg`, 9-pin D-sub, phosphor-bronze leads):
- Loop A: 9.4 Ω + 9.2 Ω in series with the heater → **118.6 Ω** total loop.
- Loop B: 9.1 Ω + 8.6 Ω in series with the heater → **117.7 Ω** total loop.
- Per goal: **use Loop B (117.7 Ω) to drive current (I)**, Loop A as the **voltage sense
  (V)**. Each loop is broken out to one BNC (inner = one heater terminal, outer = other).

Getting *true heater power* independent of the phosphor-bronze lead resistance:
- The V-sense BNC connects to a high-impedance CTC100 input → essentially no current in
  the sense leads → the sensed voltage `V_sense` is the true voltage across the heater.
- Heater power is then **P = V_sense² / R_heater**, where `R_heater` is the heater's own
  resistance (lead resistance cancels because both R and V are 4-wire quantities). We
  characterize `R_heater` once with a 4-wire measurement at operating temperature.
  (If we can drive in constant-current mode and read back `I` directly, then
  `P = I · V_sense` exactly and we don't even need `R_heater`.)
- **Drive path — RESOLVED (manual p.9 & p.20):** the BNCs are the CTC100 **AIO (analog
  I/O) channels**: ±10 V, 16-bit DAC, but **"if used to drive a heater, each analog I/O
  channel can only supply up to 30 mA."** Into a ~100 Ω heater that caps deliverable power
  at `I²R = 0.030² × 100 ≈ 90 mW`. The previous team's real calibration
  (`ref/.../StandoffCalibrations/20250620.csv`) needs **0–46 mW to span 4.5→10 K**, and
  real 40–45 K→4 K cable measurements floated the plate to ~8 K (~24 mW). So **AIO has ~2×
  headroom for the intended ≤10 K working range and is adequate.** Note the AIO is a
  *voltage* DAC (not a current source), so power is not read directly — we compute
  `P = V_sense²/R_heater` from the 4-wire sense (the previous team did exactly this: their
  `VoltageDividerFactor = 0.792` on the NEST fridge is the same phosphor-bronze
  lead-resistance correction).
  - *If we ever need the plate above ~10–12 K*, AIO saturates at 90 mW; switch the heater
    leads to a **100 W screw-terminal output** (true current source, 50 V/2 A, native Watts
    + native PID, no `R_heater` math). The previous team excluded a 17 K point as "too
    high," so ≤10 K is the norm and AIO suffices — but the 100 W output is the strictly
    more capable, lower-friction option if re-terminating from BNC is acceptable.

### 1.4 PID-to-steady-state — is it a reasonable way to speed up calibration?
**Yes, and it's the better design.** Two equivalent ways to get a point on the P↔T curve:
- *Open loop:* set a fixed heater power, wait for thermal equilibrium, record (P, T).
- *Closed loop (recommended):* PID the heater to hold **sensor A at a target temperature
  setpoint**, wait until it settles, then record the **steady-state heater power P** and
  the temperature. At steady state the heater delivers exactly the power needed to hold T,
  so `(P_steady, T_setpoint)` is a valid point on the *same* calibration curve.

Closed loop is faster (PID drives toward the target instead of drifting there), gives
**evenly spaced temperature points** (we choose the setpoints), and the settle detector is
simple. So the calibration is a **sweep over temperature setpoints**; at each setpoint:
(a) set PID setpoint, (b) wait for stability, (c) record steady P and T.

"Stable to within 1%": watch sensor A over a rolling window and require both the
**temperature** and the **heater power** to be flat — e.g. rolling standard deviation / mean
below a threshold (and/or |slope| below a threshold) sustained for N seconds, with an
overall timeout. Record the stability metric alongside each point.

Note: the isolated 4 K plate is deliberately weakly coupled, so time constants may be
long. The calibration curve is expected to be monotonic and smooth (roughly
P ∝ (T⁴ − T_base⁴) if radiation-limited, or ∝ (T − T_base) if conduction-limited); we can
sanity-check the fit as we go.

---

## 2. Software architecture decision

### 2.1 Use `lab_procedure`, not the full `lab_wizard`, for phase 1
- `lab-procedure` (PyPI, v0.0.1, **zero dependencies**) is exactly the scheduling core we
  want: a composable `Step` tree (`Sequence`, `Repeat`, `Sweep`, `Wait`), a
  `ProcedureRunner` that runs it on a thread with abort support, and two `MessageBus`
  channels (`data_bus` for `Observation`s, `status_bus` for progress). This cleanly
  expresses "set setpoint → wait for stability → record point", swept over setpoints, with
  live progress and a clean abort — ideal for long unattended runs.
- `lab_wizard` is a much heavier SNSPD-oriented toolkit (typed instrument config tree,
  a Bun/JS wizard GUI, remote instrument servers, a SNSPD database). Its **instrument-model
  patterns** are worth borrowing (e.g. the `VisaDep`-style transport dependency, the
  offline-mock pattern in `keysight53220A.py`), but we do **not** need the GUI, the remote
  server, or its schema for heater calibration.
- Plan: `uv add lab-procedure` now. Keep the local `lab_wizard_repo` checkout as a
  reference for driver/instrument idioms. Adopt the full `lab_wizard` framework later
  (phase 2+) only if the project grows to need its config/GUI/multi-instrument features.

### 2.2 Database complexity — strip it down
`lab_wizard/lib/savers/schema.py` implements six tables
(`wafers → devices → runs → measurements → measurement_details`, + `cryostats`). That
hierarchy is designed for SNSPD device testing and is **overkill** here — there is no
wafer/device/pixel, and we don't need `measurement_details` bins.

**Recommendation: a minimal 2-table SQLite schema** (keeps the good "one row = one
observation, execution structure decoupled from storage" philosophy from
`database_plan.md`, drops the SNSPD entities):

- `runs`: `id, started_at, ended_at, cryostat, operator, description, config_json`
- `cal_points` (one row per recorded equilibrium point):
  `id, run_id (FK), timestamp, setpoint_K, t_isolated_K (sensor A), t_40k_K (sensor B),
  heater_power_W, heater_v_sense, heater_current, drive_setpoint, r_heater_ohm,
  stable (bool), stability_metric, metadata_json`

SQLite via SQLAlchemy (incremental durable writes survive Ctrl-C / power blips — important
for long runs). Also mirror each point to a flat **CSV/Parquet** for trivial plotting.
This is enough to answer every phase-1 question and trivially extends to phase-2 cable
runs (add a `cable_id`/`sample` column, or a small `cables` table). We are **not**
committing to the SNSPD schema.

---

## 3. Target project layout (`src/`)

```
src/
  pyproject.toml            # uv-managed; add lab-procedure, sqlalchemy, numpy, pyvisa(optional)
  cable_heat_load/
    instruments/
      ctc100.py             # Ethernet (TCP:23) CTC100 driver + offline mock
    procedures/
      steps.py              # SetSetpoint, WaitForStability, RecordPoint (lab_procedure Steps)
      heater_calibration.py # builds the Sweep(setpoints) procedure tree
    data/
      schema.py             # 2-table SQLAlchemy schema
      saver.py              # subscribes to data_bus -> writes runs/cal_points + CSV
    config.py               # channel names, IP/port, setpoint list, tolerances
    run_calibration.py      # entrypoint: wire instrument+runner+saver, start, print/plot
    analysis/
      fit_curve.py          # load cal_points, fit & plot P(T), export calibration
```

---

## 4. Phased implementation plan

**Phase 0 — project scaffold & connectivity (fast)**
1. `cd src && uv add lab-procedure sqlalchemy numpy` (confirm `lab-procedure` resolves on
   PyPI; else `uv add --editable ../../lab_wizard_repo/procedure_framework`).
2. Write `instruments/ctc100.py`: a `CTC100` class over a persistent TCP socket
   (host, port=23). Methods: `connect/close`, `write(cmd)` (append `\n`),
   `query(cmd)` (send, read to `\r\n`), `get_idn()`/`description()`, `read_channel(name)`,
   `set_output(name, value)`, `outputs_on/off()`, plus PID helpers
   (`set_pid(chan,P,I,D)`, `set_pid_input`, `set_setpoint`, `pid_mode(on/off)`) mirroring
   the reference driver's vocabulary. Include an **`offline=True` mock** (returns
   plausible numbers) so procedures can be developed without hardware.
3. Bench smoke test: connect, `description`, `popup hello`, read both diode channels.
   **Deliverable:** reliably read T_A and T_B over Ethernet.

**Phase 1 — instrument configuration & heater characterization**
4. Configure the two diode channels (sensor type = Diode / DT-670 standard curve, units K)
   and **identify which channel is the isolated 4 K plate (A) vs the 40 K sub-plate (B)**
   — with the heater off, A ≈ 4 K, B ≈ 40 K distinguishes them. Persist the mapping in
   `config.py`.
5. Configure the heater drive channel (AIO "Set out", or 100 W output per §6 Q1). Set a
   sensible `HiLmt` safety cap.
6. **Characterize `R_heater`** with a small known drive: 4-wire measure V_sense (and I if
   available) → `R_heater`. Store it; this is what makes `P = V_sense²/R_heater` valid.
   **Deliverable:** verified drive path + known heater resistance + labeled sensors.

**Phase 2 — the calibration procedure (`lab_procedure` Steps)**
7. Implement custom Steps:
   - `SetSetpoint(T)` — set PID input=sensor A, setpoint=T, mode On, outputs on.
   - `WaitForStability(sensor, tol=1%, window_s, min_hold_s, timeout_s)` — poll T (and P),
     maintain a rolling buffer, return `SUCCESS` when std/mean < tol (and |slope|<thr)
     held for `min_hold_s`; `FAILED` on timeout. Emit `StepProgress`.
   - `RecordPoint` — read T_A, T_B, V_sense (and I), compute P, `emit(Observation(...))`
     with all fields for one `cal_points` row.
8. Compose with `Sweep("setpoint_K", setpoints, lambda T: Sequence(SetSetpoint(T),
   WaitForStability(...), RecordPoint()))`. Wrap in a `Sequence` that configures at start
   and turns the heater **off + outputs off in an `on_exit`/finally** (safety) at the end.
9. `data/saver.py`: subscribe to `data_bus`; on `RunStarted` open a `runs` row, on
   `Observation` insert a `cal_points` row + append CSV, on `RunEnded` close the run.
10. `run_calibration.py`: build `ProcedureRunner(instruments=ctc)`, attach saver, emit
    `RunStarted`, `runner.start(root)`, handle Ctrl-C → `runner.abort()` (which flows to
    `WaitForStability` and drives the heater safe via `on_exit`).
    **Deliverable:** unattended sweep producing a (setpoint, T_A, T_B, P) table.

**Phase 3 — analysis**
11. `analysis/fit_curve.py`: load `cal_points`, plot P vs T_A, fit (radiative
    `P=k(T⁴−T₀⁴)` and/or conductive), export a calibration function/coefficients for
    phase-2 cable heat-load inference.
    **Deliverable:** heater calibration curve + reusable `P(T)` (and inverse) model.

**Phase 4 (later) — cable heat-load measurement**
12. Reuse the same instrument + Step machinery. With a cable installed 40 K → isolated 4 K,
    the cable delivers heat `Q_cable`; measure the isolated-plate steady temperature with
    heater off (or trimmed), invert the calibration to read off `Q_cable`. Add a
    `sample/cable_id` column. Only here consider adopting fuller `lab_wizard` structure.

---

## 5. Safety / robustness notes (build in from the start)
- Always set heater `HiLmt` and drive-voltage caps; the isolated plate is low-mass and
  weakly linked → it can heat quickly. Start setpoints low and ascend.
- Guarantee heater-off on abort/exception/normal-exit via `Step.on_exit` and a top-level
  `finally` (`outputs_off()` + `PID.Mode Off`).
- Own exactly one socket (single-client lock); close it on shutdown so the CTC frees the
  port.
- Long time constants → generous `WaitForStability` timeouts; log the full time series (not
  just the final point) so a settle can be re-judged offline.

---

## 6. Decisions / open questions
- **Q1 (drive path) — RESOLVED (see §1.3).** AIO/BNC (±10 V, 30 mA → ~90 mW into ~100 Ω)
  is adequate for the intended ≤10 K range; compute `P = V_sense²/R_heater` from the 4-wire
  sense. Use a 100 W screw-terminal output only if we need the plate >~10–12 K. Evidence
  suggests the previous team drove with voltage through the BNC leads (their
  `VoltageDividerFactor = 0.792` PhBr correction is the fingerprint of voltage-drive-through
  -lossy-leads; a current source reports true Watts and needs no such factor).
- **Q2 (temperature range) — RESOLVED (from previous team's data).** Base ~4.485 K; calibrate
  the isolated plate from base up to ~10–12 K (occasionally warmer cables reach ~15 K, but
  ≥17 K was excluded as "too high"). Reuse the previous team's setpoint spacing
  (`20250620.csv`): fine near base (0.1 K) coarsening to ~1 K near the top, ~18 points,
  0→~46 mW. The hot side ("40 K stage", sensor B) actually sits ~40–45 K, set by the
  cryostat — we do not control it. *Still to pin down: per-point stability tolerance and
  max settle timeout.*
- **Q3 (storage) — DECIDED:** minimal 2-table SQLite + CSV (not the SNSPD schema).
- **Q4 (packaging) — CONFIRMED:** `lab-procedure` installs cleanly from PyPI via `uv add`.
