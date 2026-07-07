"""Step 4 - measure the heater resistance in situ (4-wire) and check the drive.

Drives the heater with a few small voltages (well under the 30 mA AIO limit) and
uses the 4-wire sense to get the true heater resistance:

    R_heater = R_leads * V_sense / (V_drive - V_sense)

where R_leads is the drive-loop lead resistance (config.r_leads_drive_ohm, from
the DMM loop measurement). This both confirms the heater responds and refines
the R_heater used for power = V_sense**2 / R_heater. Update
`r_heater_ohm` in config.py with the result.

    uv run python scripts/04_heater_resistance.py --ip 192.168.1.50
"""

from __future__ import annotations

import time

import _common


def _add(p):
    p.add_argument("--volts", type=float, nargs="+", default=[1.0, 1.5, 2.0],
                   help="drive voltages to probe (keep current < 30 mA)")
    p.add_argument("--settle", type=float, default=3.0, help="seconds to settle per point")


def main() -> None:
    args = _common.parse(__doc__, add_args=_add)
    cfg, ctc = _common.connect_eth(args)
    ch = cfg.channels
    r_leads = cfg.r_leads_drive_ohm
    estimates: list[float] = []
    try:
        ctc.pid_mode(ch.heater, False)
        ctc.set_output(ch.heater, 0)
        ctc.outputs_on()
        print(f"R_leads (drive loop) = {r_leads} ohm; nominal R_heater = {cfg.r_heater_ohm} ohm\n")
        print(f"{'V_drive':>8} {'V_sense':>8} {'I (mA)':>8} {'P (mW)':>8} {'R_heater':>9}")
        for v in args.volts:
            ctc.set_output(ch.heater, v)
            time.sleep(args.settle)
            v_drive = ctc.read_channel(ch.heater)
            v_sense = ctc.read_channel(ch.vsense)
            if v_drive - v_sense <= 0:
                print(f"{v_drive:8.4f} {v_sense:8.4f}   -- skipped (V_drive <= V_sense)")
                continue
            r_heater = r_leads * v_sense / (v_drive - v_sense)
            current = v_sense / r_heater
            power = v_sense**2 / r_heater
            flag = "  <-- near 30 mA limit!" if current > 0.027 else ""
            print(f"{v_drive:8.4f} {v_sense:8.4f} {current*1e3:8.2f} {power*1e3:8.2f} "
                  f"{r_heater:9.2f}{flag}")
            estimates.append(r_heater)
    finally:
        ctc.set_output(ch.heater, 0)
        ctc.outputs_off()
        ctc.close()

    if estimates:
        mean = sum(estimates) / len(estimates)
        print(f"\nMean R_heater = {mean:.2f} ohm  (nominal {cfg.r_heater_ohm}).")
        print("If this differs, set r_heater_ohm in config.py to the measured value.")
    print("Heater is OFF.")


if __name__ == "__main__":
    main()
