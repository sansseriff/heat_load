# cable_heat_load

Heater-calibration and (later) cable heat-load measurement for a cryostat,
driven by an **SRS CTC100** temperature controller over **Ethernet**.

See `../PLAN.md` for the full design and phased plan.

## Setup

```bash
uv sync
```

## Status

- **Phase 0–2 (done):** CTC100 driver (Ethernet + USB transports) with an offline
  mock, bring-up scripts, and the full heater-calibration procedure with
  SQLite/CSV saving.
- **Heater drive:** a CTC100 **100 W output** (`Out1`) as a current source + the
  **AIO2** 4-wire voltage sense, so power is `P = V_sense·I` and resistance
  `R = V_sense/I` are measured directly (no assumed R; `r_heater_live` is logged
  every point).
- **Two temperature sources:** the isolated 4 K plate + heater are on the
  **Ethernet CTC** we own; the **40 K sub-plate** lives on another (USB) CTC owned
  by the NEST FridgeControl GUI and is read over **RabbitMQ RPC** (command `T40K`)
  rather than by sharing the serial port.
- **Next (Phase 3):** fit the P(T) curve and export a calibration model for
  phase-2 cable heat-load inference.

## Quick start

```bash
uv sync
# Rehearse the whole flow with no hardware:
uv run python scripts/01_ping_ctc100.py --offline
uv run python -m cable_heat_load.run_calibration --offline --help
```

Bring the real rig up **in order** with `../BRINGUP.md` and the numbered
`scripts/`, then run the calibration:

```bash
uv run python -m cable_heat_load.run_calibration --ip 192.168.1.50
```

Edit `cable_heat_load/config.py` to match your hardware (channel names,
`r_heater_ohm`, PID gains, setpoints, stability tolerances).

## Layout

```
cable_heat_load/
  config.py                 # single source of truth for the measurement
  session.py                # build a CTC100 (real or mock) from config
  run_calibration.py        # entrypoint: python -m cable_heat_load.run_calibration
  instruments/
    ctc100.py               # CTC100 driver; Ethernet/Serial/Mock transports
    fridge_rpc.py           # RabbitMQ RPC client for the 40 K sensor
    _mock.py                # in-process mocks (CTC physical model + 40 K source)
  session.py                # Instruments container (eth CTC + 40 K source)
  procedures/
    steps.py                # ConfigureInstrument, SetSetpoint,
                            #   WaitForStability, RecordPoint, HeaterSafeOff
    heater_calibration.py   # builds the setpoint-sweep Step tree
  data/
    schema.py               # runs + cal_points (2-table SQLite)
    saver.py                # data-bus subscriber -> DB rows + CSV
scripts/                    # bring-up scripts (01..06) + check_40k_rpc.py
```
