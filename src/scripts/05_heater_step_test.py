"""Step 5 - open-loop heater step: confirm the heater warms the plate.

Applies a fixed drive voltage (no PID), streams the isolated-plate temperature
and the computed heater power as it rises, then turns the heater off and watches
it fall back. This is the sanity check that heat actually reaches the isolated
stage before you trust PID and the full sweep.

Keep --volts modest (the AIO caps at ~30 mA / ~90 mW into ~100 ohm anyway).

    uv run python scripts/05_heater_step_test.py --ip 192.168.1.50 --volts 2.0 --seconds 120
"""

from __future__ import annotations

import time

import _common


def _add(p):
    p.add_argument("--volts", type=float, default=2.0, help="drive voltage to apply")
    p.add_argument("--seconds", type=float, default=120.0, help="heat-on duration")
    p.add_argument("--cooldown", type=float, default=40.0, help="heat-off observation")
    p.add_argument("--interval", type=float, default=3.0, help="seconds between reads")


def _stream(ctc, cfg, label, seconds, interval, t0):
    ch = cfg.channels
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        v_sense = ctc.read_channel(ch.vsense)
        power = v_sense**2 / cfg.r_heater_ohm
        a = ctc.read_channel(ch.sensor_a)
        print(f"  [{label}] t={time.monotonic()-t0:6.1f}s  T_A={a:7.3f} K  "
              f"P={power*1e3:6.2f} mW  Vsense={v_sense:6.4f} V", flush=True)
        time.sleep(interval)


def main() -> None:
    args = _common.parse(__doc__, add_args=_add)
    cfg, ctc = _common.connect_eth(args)
    ch = cfg.channels
    t0 = time.monotonic()
    try:
        ctc.pid_mode(ch.heater, False)
        ctc.set_high_limit(ch.heater, cfg.heater_hilmt_v)
        ctc.set_output(ch.heater, args.volts)
        ctc.outputs_on()
        print(f"Heater ON at {args.volts} V. Expect T_A to rise.\n")
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
