"""Step 6 - single-setpoint PID test: verify closed-loop settling and tune gains.

Runs PID to one temperature setpoint, streams T_A and heater power, and reports
when it settles per the config's stability criterion (rel. std < tol over the
window). Use it to confirm PID works and to tune P/I/D before the full sweep.

    uv run python scripts/06_pid_settle_test.py --ip 192.168.1.50 --setpoint 6.0
    uv run python scripts/06_pid_settle_test.py --ip 192.168.1.50 --setpoint 6.0 -p 0.08 -i 0.03 -d 0

Watch for: overshoot (lower P/I), sluggishness (raise P), or oscillation (lower
P, add a little D). Because the 100 W output is driven in current, the plant gain
(dP/dI = 2*I*R) is small near base temperature, so the lowest setpoints settle
more slowly -- that's expected; integral action still gets there.
"""

from __future__ import annotations

import statistics
import time
from collections import deque

import _common
from cable_heat_load.procedures import read_vsense


def _add(p):
    p.add_argument("--setpoint", type=float, default=6.0, help="target temperature (K)")
    p.add_argument("-p", type=float, default=None, help="override PID P")
    p.add_argument("-i", type=float, default=None, help="override PID I")
    p.add_argument("-d", type=float, default=None, help="override PID D")
    p.add_argument("--timeout", type=float, default=None, help="settle timeout (s)")
    p.add_argument("--window", type=float, default=None, help="stability window (s)")


def main() -> None:
    args = _common.parse(__doc__, add_args=_add)
    cfg, ctc = _common.connect_eth(args)
    ch = cfg.channels
    pid_p = args.p if args.p is not None else cfg.pid_p
    pid_i = args.i if args.i is not None else cfg.pid_i
    pid_d = args.d if args.d is not None else cfg.pid_d
    timeout = args.timeout if args.timeout is not None else cfg.settle_timeout_s
    if args.window is not None:
        cfg.stability_window_s = args.window

    window: deque[tuple[float, float]] = deque()
    t0 = time.monotonic()
    settled_at = None
    try:
        ctc.set_units(ch.heater, cfg.heater_units)
        ctc.set_high_limit(ch.heater, cfg.heater_hilmt)
        ctc.configure_pid(ch.heater, ch.sensor_a, pid_p, pid_i, pid_d,
                          ramp_rate=cfg.pid_ramp, enable=True)
        ctc.set_setpoint(ch.heater, args.setpoint)
        ctc.outputs_on()
        print(f"PID -> {args.setpoint} K  (P={pid_p} I={pid_i} D={pid_d}). Ctrl-C to stop.\n")

        while True:
            now = time.monotonic()
            elapsed = now - t0
            temp = ctc.read_channel(ch.sensor_a)
            v_sense = read_vsense(ctc, cfg)
            current = ctc.read_channel(ch.heater_current_chan or ch.heater)
            power = v_sense * current
            window.append((now, temp))
            while window and now - window[0][0] > cfg.stability_window_s:
                window.popleft()
            metric = _rel_std(window)
            full = elapsed >= cfg.stability_window_s

            mtxt = f"{metric:.2%}" if metric is not None else "  -- "
            print(f"  t={elapsed:6.1f}s  T_A={temp:7.3f} K  P={power*1e3:6.2f} mW  "
                  f"relstd={mtxt}", flush=True)

            if full and metric is not None and metric < cfg.stability_tol:
                settled_at = elapsed
                print(f"\nSETTLED at {elapsed:.1f}s: T_A={temp:.3f} K, "
                      f"P={power*1e3:.2f} mW, relstd={metric:.2%}")
                break
            if elapsed > timeout:
                print(f"\nTIMEOUT after {timeout:.0f}s without settling.")
                break
            time.sleep(cfg.poll_interval_s)
    except KeyboardInterrupt:
        pass
    finally:
        ctc.pid_mode(ch.heater, False)
        ctc.set_output(ch.heater, 0)
        ctc.outputs_off()
        ctc.close()
    print("Heater is OFF." + ("" if settled_at else " (did not settle)"))


def _rel_std(window):
    if len(window) < 3:
        return None
    temps = [t for _, t in window]
    mean = statistics.fmean(temps)
    return statistics.pstdev(temps) / abs(mean) if mean else None


if __name__ == "__main__":
    main()
