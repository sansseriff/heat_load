"""Step 3 - configure the Ethernet CTC's sensor + heater channels.

Applies the setup the calibration expects on the CTC100 we own directly:

  * isolated-plate diode input -> sensor type = Diode (DT-670 standard curve)
  * heater channel             -> 'Set out', units V, high-limit safety clamp
  * vsense channel             -> 'Input'

The 40 K sensor lives on a different CTC (owned by FridgeControl) and is read
over RPC -- we do NOT configure it here.

Note: the DT-670 standard curve must also be selected on the CTC100 itself
(Channel Setup screen) if 'Diode' alone doesn't pick it -- see BRINGUP.md.

    uv run python scripts/03_configure_channels.py --ip 192.168.1.50
"""

from __future__ import annotations

import _common


def main() -> None:
    args = _common.parse(__doc__)
    cfg, ctc = _common.connect_eth(args)
    ch = cfg.channels
    try:
        # make sure nothing is driving the heater while we reconfigure
        ctc.pid_mode(ch.heater, False)
        ctc.set_output(ch.heater, 0)
        ctc.outputs_off()

        ctc.set_sensor(ch.sensor_a, cfg.sensor_type)
        ctc.set_io_type(ch.heater, "Set out")
        ctc.set_units(ch.heater, cfg.heater_units)
        ctc.set_high_limit(ch.heater, cfg.heater_hilmt_v)
        ctc.set_io_type(ch.vsense, "Input")

        print("Applied configuration (Ethernet CTC):")
        print(f"  {ch.sensor_a}: sensor = {cfg.sensor_type}")
        print(f"  {ch.heater}: Set out, units {cfg.heater_units}, HiLmt {cfg.heater_hilmt_v}")
        print(f"  {ch.vsense}: Input (4-wire heater voltage sense)")
        print("\nReadback:")
        print(f"  A {ch.sensor_a} = {ctc.read_channel(ch.sensor_a):8.3f} K")
        print(f"  heater {ch.heater} = {ctc.read_channel(ch.heater):8.4f} V (should be ~0)")
        print(f"  vsense {ch.vsense} = {ctc.read_channel(ch.vsense):8.4f} V (should be ~0)")
        print("\nOK: channels configured. Heater is OFF.")
    finally:
        ctc.close()


if __name__ == "__main__":
    main()
