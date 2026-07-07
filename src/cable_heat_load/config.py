"""Configuration for the heater-calibration measurement.

Heater drive uses a CTC100 **100 W screw-terminal output** (`Out1`/`Out2`), which
is a real current source. We drive it in **current (A)** so `Out1?` returns the
delivered current directly, and read the **true 4-wire heater voltage** on `AIO2`.
Heater power is then `P = V_sense * I` and live resistance `R = V_sense / I` --
no assumed resistance, and lead dissipation excluded (the output's own
voltage/resistance monitors are 2-wire and include the leads; AIO2 does not).

Two temperature sources:
  * the **Ethernet CTC100** we own -- the isolated 4 K plate (`sensor_a`) + heater;
  * the **40 K sub-plate** on a different USB CTC owned by the NEST FridgeControl
    GUI, read over RabbitMQ RPC (command `T40K`). See `Remote40K`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Channels:
    """Channel names on the **Ethernet** CTC100 (the one we own directly)."""

    sensor_a: str = "T4k"    # isolated 4 K plate diode (reads ~4 K, heater off)
    heater: str = "Out1"     # 100 W screw-terminal output, driven in Amps
    vsense: str = "AIO2"     # 4-wire heater voltage sense (Input)
    # Optional: if you instead drive the heater in Watts and enable the output
    # card's current Monitor channel (Monitors -> Show), put its name here to
    # read the true current from it. Leave None to read current from `heater`
    # directly (requires heater_units = 'A').
    heater_current_chan: str | None = None


@dataclass
class Remote40K:
    """40 K sub-plate, read over RabbitMQ from the FridgeControl server.

    The FridgeControl GUI answers `command` from its cached thermometry. Confirm
    it maps to *your* 40 K sensor (run scripts/check_40k_rpc.py).
    """

    enabled: bool = True
    rpc_queue: str = "fridge_control_rpc_queue"
    host: str = "localhost"
    command: str = "T40K"
    timeout: float = 10.0


@dataclass
class CalibrationConfig:
    # --- Ethernet CTC connection --- #
    ip: str = "192.168.1.100"          # set the CTC100's IP on its Setup screen
    port: int = 23                     # raw TCP / telnet port (fixed on CTC100)
    timeout: float = 3.0
    offline: bool = False              # True -> use in-process mocks (no hw/broker)
    mock_tau: float = 15.0             # mock thermal time constant (offline only)

    channels: Channels = field(default_factory=Channels)
    remote_40k: Remote40K = field(default_factory=Remote40K)

    # --- heater electrical --- #
    heater_units: str = "A"            # drive the 100 W output as a current source
    heater_hilmt: float = 0.05         # output high-limit safety clamp (in heater_units, A)
    # R_heater is now *measured* live (V_sense / I); these are only nominal
    # references (DMM: ~100 Ω at 300 K, ~79 Ω cold) used by the mock / sanity checks.
    r_heater_ohm: float = 90.0
    r_leads_drive_ohm: float = 17.7    # 9.1 + 8.6 (drive loop); not in the power calc anymore

    # --- diode sensor --- #
    sensor_type: str = "Diode"         # DT-670; select the standard diode curve on the CTC100

    # --- PID (drive is Amps/K; TUNE with scripts/06_pid_settle_test.py) --- #
    pid_p: float = 0.003
    pid_i: float = 0.001
    pid_d: float = 0.0
    pid_ramp: float = 0.0              # setpoint ramp rate (K/s); 0 = step

    # --- temperature setpoints (K) --- #
    # Spacing reproduces the previous team's 20250620.csv (fine near base,
    # coarsening upward). The heater-off baseline is recorded separately.
    setpoints: tuple[float, ...] = (
        4.6, 4.7, 4.8, 4.9, 5.0, 5.2, 5.4, 5.6, 5.8, 6.0,
        6.5, 7.0, 7.5, 8.0, 9.0, 10.0,
    )

    # --- stability detection --- #
    stability_tol: float = 0.01        # rel. std over the window must be < 1 %
    stability_window_s: float = 90.0   # rolling window that must stay flat
    poll_interval_s: float = 2.0       # how often to sample while settling
    settle_timeout_s: float = 1200.0   # give up on a setpoint after this long

    # --- output --- #
    run_description: str = "Heater calibration of isolated 4 K plate"
    cryostat: str = ""
    operator: str = ""
    db_path: str = "calibration.db"
    csv_path: str = "calibration_points.csv"
