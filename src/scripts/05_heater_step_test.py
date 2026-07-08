"""Step 5 - open-loop heater step: confirm the heater warms the plate.

Applies a fixed drive current (no PID) on the 100 W output, streams the
isolated-plate temperature and the true heater power (P = V_sense * I) as it
rises, then turns the heater off and watches it fall back. This is the sanity
check that heat actually reaches the isolated stage before you trust PID and the
full sweep.

Keep --amps modest (config `heater_hilmt` also clamps it).

    uv run python scripts/05_heater_step_test.py --ip 192.168.1.50 --amps 0.02 --seconds 120
"""

from __future__ import annotations

import time

import _common
from cable_heat_load.procedures import read_vsense


def _add(p):
    p.add_argument("--amps", type=float, default=0.015, help="drive current to apply (A)")
    p.add_argument("--seconds", type=float, default=120.0, help="heat-on duration")
    p.add_argument("--cooldown", type=float, default=40.0, help="heat-off observation")
    p.add_argument("--interval", type=float, default=3.0, help="seconds between reads")


def _stream(ctc, cfg, label, seconds, interval, t0):
    ch = cfg.channels
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        v_sense = read_vsense(ctc, cfg)
        current = ctc.read_channel(ch.heater_current_chan or ch.heater)
        power = v_sense * current
        r = v_sense / current if current else float("nan")
        a = ctc.read_channel(ch.sensor_a)
        print(f"  [{label}] t={time.monotonic()-t0:6.1f}s  T_A={a:7.3f} K  "
              f"P={power*1e3:6.2f} mW  I={current*1e3:6.2f} mA  Vs={v_sense:6.4f} V  "
              f"R={r:6.1f} Ω", flush=True)
        time.sleep(interval)



def main() -> None:
    args = _common.parse(__doc__, add_args=_add)
    cfg, ctc = _common.connect_eth(args)
    ch = cfg.channels
    if args.amps > cfg.heater_hilmt:
        print(f"Requested {args.amps*1e3:.1f} mA exceeds the {cfg.heater_hilmt*1e3:.0f} mA "
              f"safety cap; clamping to {cfg.heater_hilmt*1e3:.0f} mA.")
        args.amps = cfg.heater_hilmt
    t0 = time.monotonic()
    try:
        ctc.pid_mode(ch.heater, False)
        ctc.set_units(ch.heater, cfg.heater_units)
        ctc.set_high_limit(ch.heater, cfg.heater_hilmt)
        # Enable the output at zero first, THEN set the drive current. The CTC100
        # brings the output up at zero on `outputEnable on`, so a value set before
        # enabling gets clobbered back to 0 (this is what left Out1 stuck at zero).
        ctc.set_output(ch.heater, 0)
        ctc.outputs_on()
        ctc.set_output(ch.heater, args.amps)
        print(f"Heater ON at {args.amps*1e3:.1f} mA. Expect T_A to rise.\n")
        _stream(ctc, cfg, "heat", args.seconds, args.interval, t0)

        print("\nHeater OFF. Expect T_A to fall.\n")
        ctc.set_output(ch.heater, 0)
        ctc.outputs_off()
        _stream(ctc, cfg, "cool", args.cooldown, args.interval, t0)
    except KeyboardInterrupt:
        pass
    finally:
        ctc.set_output(ch.heater, 0)
        ctc.outputs_off()
        ctc.close()
    print("\nDone. Heater is OFF. If T_A rose with power and fell after, the heater works.")


if __name__ == "__main__":
    main()
