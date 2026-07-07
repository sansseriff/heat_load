# Bring-up & Commissioning Checklist

A step-by-step path from "cryostat is cold" to "run the full heater calibration."
Do the steps **in order** — each one de-risks the next. Every script runs
against real hardware *or* an offline mock (`--offline`), so you can rehearse the
whole flow at your desk before touching the fridge.

All commands are run from the `src/` directory.

```bash
cd src
uv sync          # one-time: install deps + the cable_heat_load package
```

Scripts live in `src/scripts/` and take `--ip <address>` (real CTC100) or
`--offline` (mock). Add `--offline` to any command below to dry-run it.

---

## 0. Before you plug anything in

**Two temperature sources** (this is important):
- The **Ethernet CTC100** (the one we own) has the **isolated 4 K plate** diode
  (`channels.sensor_a`) plus the **heater** (100 W output) and 4-wire sense (AIO2).
- The **40 K sub-plate** diode lives on a *different, USB-connected* CTC100 owned
  by the **NEST FridgeControl GUI**. We do **not** open that USB port (serial has
  no arbitration and two openers corrupt each other's reads). Instead we read it
  over **RabbitMQ RPC** (`remote_40k.command`, default `T40K`) — the FridgeControl
  server owns the port and answers temperature requests from its cache.

**Wiring recap** (from `goal.md` / `ref/IMG_7085.jpeg`):
- Heater is 4-wire → the **Ethernet** CTC. **Drive** = the two current leads to a
  **100 W screw-terminal output** (`Out1`), driven as a current source. **Sense** =
  loop A (9.4 + 9.2 Ω leads) → the **AIO2** BNC input (4-wire heater voltage).
  Power is `P = V_sense · I` and resistance `R = V_sense / I` — the current comes
  from the 100 W output (a real current source), the voltage from AIO2, so no
  resistance is assumed and the lead dissipation is excluded.
- Isolated-plate diode = **DT-670B-CU** on the Ethernet CTC's 9-pin D-sub.

**Prerequisite for the 40 K reading:** the **FridgeControl GUI**
(`FridgeControl_NEST_mcirillo.py`, the current version — it has the RabbitMQ
server) must be **running**, with a **RabbitMQ broker on localhost**. Verify with
`scripts/check_40k_rpc.py`.

**On the Ethernet CTC100 front panel (one-time):**
1. **Set the IP address**: System → Setup → set a static IP on your subnet (or
   direct Cat5 to the PC). Note it down — that's your `--ip`.
2. **Select the diode curve** for the isolated-plate input: Channel Setup →
   sensor type **Diode**, preloaded **DT-670** standard curve (33 curves are
   preloaded; DT-670 is standard, so **no USB calibration file is needed**). If
   only a generic "Diode" linearization is offered, load the DT-670 standard curve
   table from lakeshore.com/sensors once via USB.
3. Only **one client** may hold the Ethernet port at a time. If a script can't
   connect, press **System.IP.Close** on the CTC100, or power-cycle.

**Match the software to your hardware:** open `cable_heat_load/config.py` and set
`Channels.sensor_a/heater/vsense` to your Ethernet CTC's channel names (e.g.
`T4k`, `Out1`, `AIO2`) and `Remote40K.command` to whatever the FridgeControl
server calls your 40 K sensor. You'll confirm these in Step 2.

---

## Step 1 — Ethernet comms  (`01_ping_ctc100.py`)

```bash
uv run python scripts/01_ping_ctc100.py --ip 192.168.1.50
```
**Pass:** prints the instrument description and a popup appears on the CTC100
screen. **If it hangs:** wrong IP / subnet, cable, or another client holds
port 23 (press System.IP.Close).

## Step 2 — Read both temperature sources  (`02_read_sensors.py`)

First confirm the 40 K RPC path on its own:
```bash
uv run python scripts/check_40k_rpc.py            # expects ~40 K from the server
```
Then stream both sources together:
```bash
uv run python scripts/02_read_sensors.py --ip 192.168.1.50 --seconds 30
```
With the **heater off**, confirm `A` (Ethernet, isolated plate) reads ~4 K and
`40K` (RPC) reads ~40 K. **If `A` is mislabeled:** fix `channels.sensor_a` in
`config.py`. **If `40K` is NaN or wrong:** the FridgeControl GUI/broker isn't up,
or `remote_40k.command` maps to a different sensor — see `check_40k_rpc.py` and
the troubleshooting table.

## Step 3 — Configure the Ethernet CTC  (`03_configure_channels.py`)

```bash
uv run python scripts/03_configure_channels.py --ip 192.168.1.50
```
Sets the isolated-plate diode to `Diode`, the heater (`Out1`, a 100 W output) to
units **Amps** with a safety `HiLmt`, and the sense channel (`AIO2`) to `Input`.
Readback should show the plate sane and heater/sense ≈ 0. Leaves the heater
**off**. (The 40 K sensor is owned by FridgeControl — we don't configure it.)

## Step 4 — Heater resistance & drive check  (`04_heater_resistance.py`)

```bash
uv run python scripts/04_heater_resistance.py --ip 192.168.1.50
```
Drives `Out1` at a few small currents and reads the 4-wire voltage, so
`R_heater = V_sense / I` (exact — current source + 4-wire voltage). **Pass:**
`R_heater ≈ 79 Ω` (its cold value; ~100 Ω at 300 K), current delivered on each
step. The calibration computes power as `V_sense · I` directly, so **R is not
assumed** — this is a health check, and it logs `r_heater_live` at every
calibration point so you can *see* whether R drifts across 4.5–10 K.

> Optional cross-check: on the CTC100, **Monitors → Show** enables the output
> card's measured heater voltage/current/resistance channels. If you'd rather
> drive `Out1` in Watts (more linear PID), name the current-monitor channel in
> `channels.heater_current_chan` and set `heater_units = "W"`.

## Step 5 — Open-loop heater step  (`05_heater_step_test.py`)

```bash
uv run python scripts/05_heater_step_test.py --ip 192.168.1.50 --amps 0.02 --seconds 180
```
Applies a fixed current (no PID) and streams `T_A`, power (`V_sense·I`), current,
and live `R`. **Pass:** `T_A` rises while heating and falls after the heater turns
off. This proves heat reaches the isolated stage. Note the **thermal time
constant** — a weakly-linked plate can take minutes; size `stability_window_s` /
`settle_timeout_s` accordingly.

## Step 6 — PID settle & tuning  (`06_pid_settle_test.py`)

```bash
uv run python scripts/06_pid_settle_test.py --ip 192.168.1.50 --setpoint 6.0
# tune gains on the fly (gains are in Amps/K):
uv run python scripts/06_pid_settle_test.py --ip 192.168.1.50 --setpoint 6.0 -p 0.005 -i 0.002 -d 0
```
Runs closed-loop to one setpoint and reports when it settles (rel. std < 1 % over
the stability window). **Tune** `pid_p/i/d` in `config.py` until it settles
without overshoot or oscillation:
- sluggish → raise P; overshoot/ringing → lower P/I, maybe a little D.
- driving in current, the plant gain (`dP/dI = 2·I·R`) is small near base temp, so
  the lowest setpoints settle more slowly — expected. (The CTC100 can also
  auto-tune a 100 W output; see the manual's PID tuning section.)

---

## Step 7 — Full calibration run

Once Steps 1–6 pass and `config.py` reflects your hardware (channel names,
`remote_40k.command`, `r_heater_ohm`, tuned PID, `setpoints`, `stability_*`,
`settle_timeout_s`), and the FridgeControl GUI + RabbitMQ are running:

```bash
uv run python -m cable_heat_load.run_calibration --ip 192.168.1.50
```

At startup it probes the 40 K RPC source and warns if it's unreachable (the run
still proceeds, logging `NaN` for the 40 K column — it's informational, not
needed for the P-vs-plate-temperature calibration itself).

It records a heater-off baseline, then sweeps the setpoints, waiting for each to
stabilize and saving one row per point to `calibration.db` (SQLite) **and**
`calibration_points.csv`. Each point is committed as it lands, so **Ctrl-C is
safe** — it aborts the run and drives the heater off. Columns: `setpoint_k`,
`t_isolated_k`, `t_40k_k`, `heater_power_w` (= `V_sense·I`), `heater_v_sense`,
`heater_current`, `r_heater_live` (= `V_sense/I`), `stable`, `stability_metric`,
`settle_time_s`.

The result — heater power vs isolated-plate temperature — is exactly the
calibration curve the previous team stored in `StandoffCalibrations/*.csv`, and
what phase 2 uses to infer cable heat loads.

---

## Safety notes
- The heater is enabled only inside Steps 4–7, and every one of them turns it
  **off in a `finally`/`on_exit`** — including on Ctrl-C or an exception.
- `heater_hilmt` (config, in Amps) clamps the output current. Start setpoints low
  and ascend. The 100 W output also self-protects (shuts off if the card
  overheats or the heater reads < 1 Ω / > 10 kΩ).
- The isolated plate is low-mass and weakly linked — it heats quickly. Don't
  hand-set large drive voltages in Step 5.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Connect hangs / refused | Wrong IP or subnet; cable; another client on port 23 → press System.IP.Close, or reboot CTC100. |
| Plate reads `nan` or 0 | Wrong `channels.sensor_a` in `config.py`; diode curve not selected on the CTC100 (Step 0.2). |
| 40 K reads `NaN` | FridgeControl GUI or RabbitMQ broker not running; or `remote_40k.command` doesn't map to your sensor → `check_40k_rpc.py`, try another `--command`, or add a case in the server's `parse_queue_message`. |
| 40 K reads wrong value | `T40K` maps to a different thermometry slot than your sensor → pick the right command or re-slot the sensor on the FridgeControl side. |
| `r_heater_live` NaN / wild | No current delivered (heater open?) or AIO2 not sensing across the heater; check the screw-terminal and AIO2 wiring. |
| "heater disconnected" / can't tune | 100 W output measures heater R < 1 Ω or > 10 kΩ — check the heater connection at `Out1`. |
| Never settles / always times out | Time constant longer than `stability_window_s`; raise `settle_timeout_s`, widen the window, or loosen `stability_tol`. Lowest setpoints settle slowly (current-drive gain → 0 near base). |
