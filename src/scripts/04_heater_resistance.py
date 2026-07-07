"""Step 4 - measure the heater resistance in situ (4-wire) and check the drive.

Drives the 100 W output at a few small currents and reads the true 4-wire
voltage on AIO2, so:

    R_heater = V_sense / I          (exact -- current source + 4-wire voltage)
    P_heater = V_sense * I

This confirms the heater responds and gives R_heater at the current plate
temperature. Repeat at a few plate temperatures (via PID, or as the fridge
drifts) to see whether R changes over your 4.5-10 K working range -- the
calibration run also logs `r_heater_live` at every point.

    uv run python scripts/04_heater_resistance.py --ip 192.168.1.50
"""

from __future__ import annotations

import time

import _common


def _add(p):
    p.add_argument("--amps", type=float, nargs="+", default=[0.005, 0.010, 0.015],
                   help="drive currents to probe (A)")
    p.add_argument("--settle", type=float, default=3.0, help="seconds to settle per point")


def main() -> None:
    args = _common.parse(__doc__, add_args=_add)
    cfg, ctc = _common.connect_eth(args)
    ch = cfg.channels
    estimates: list[float] = []
    try:
        ctc.pid_mode(ch.heater, False)
        ctc.set_units(ch.heater, cfg.heater_units)
        ctc.set_high_limit(ch.heater, cfg.heater_hilmt)
        ctc.set_output(ch.heater, 0)
        ctc.outputs_on()
        print(f"nominal R_heater (reference) = {cfg.r_heater_ohm} ohm\n")
        print(f"{'I (mA)':>8} {'V_sense':>8} {'P (mW)':>8} {'R_heater':>9}")
        for amps in args.amps:
            ctc.set_output(ch.heater, amps)
            time.sleep(args.settle)
            current = ctc.read_channel(ch.heater)            # delivered current (A)
            v_sense = ctc.read_channel(ch.vsense)            # true 4-wire voltage
            if current <= 0:
                print(f"{amps*1e3:8.2f}    -- no current delivered (heater connected?)")
                continue
            r_heater = v_sense / current
            power = v_sense * current
            print(f"{current*1e3:8.2f} {v_sense:8.4f} {power*1e3:8.2f} {r_heater:9.2f}")
            estimates.append(r_heater)
    finally:
        ctc.set_output(ch.heater, 0)
        ctc.outputs_off()
        ctc.close()

    if estimates:
        mean = sum(estimates) / len(estimates)
        print(f"\nMean R_heater = {mean:.2f} ohm  (nominal {cfg.r_heater_ohm}).")
        print("Power in the calibration uses V_sense * I directly, so R is not "
              "assumed -- this is just a health check.")
    print("Heater is OFF.")


if __name__ == "__main__":
    main()
