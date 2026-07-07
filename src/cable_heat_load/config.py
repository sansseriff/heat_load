"""Configuration for the heater-calibration measurement.

Two temperature sources:
  * the **Ethernet CTC100** we own directly -- the isolated 4 K plate (`sensor_a`)
    plus the heater drive/sense AIO channels;
  * the **40 K sub-plate**, which lives on a *different* USB-connected CTC100 owned
    by the NEST FridgeControl GUI. We read it over RabbitMQ RPC (command `T40K`)
    rather than sharing the serial port. See `Remote40K`.

Edit the defaults here to match your hardware, or override IP / offline from the
command line (see `scripts/_common.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Channels:
    """Channel names on the **Ethernet** CTC100 (the one we own directly)."""

    sensor_a: str = "T4k"    # isolated 4 K plate (reads ~4 K, heater off)
    heater: str = "AIO1"     # heater drive output (volts)
    vsense: str = "AIO2"     # 4-wire heater voltage sense (volts)


@dataclass
class Remote40K:
    """40 K sub-plate, read over RabbitMQ from the FridgeControl server.

    The FridgeControl GUI answers `command` from its cached thermometry. Confirm
    that `command` maps to *your* 40 K sensor (run scripts/07_check_40k_rpc.py);
    if it's on a different slot you may need to add a case on the server side.
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
    # R_heater from the DMM loop measurements (IMG_7085): 117.7 = R_h + 9.1 + 8.6
    # and 118.6 = R_h + 9.4 + 9.2  both give R_h ~= 100 ohm. Refine in situ with
    # scripts/04_heater_resistance.py.
    r_heater_ohm: float = 100.0
    r_leads_drive_ohm: float = 17.7    # 9.1 + 8.6 (drive loop B), for the R cross-check
    heater_units: str = "V"            # AIO output is a voltage DAC
    heater_hilmt_v: float = 5.0        # output high-limit safety clamp (volts)

    # --- diode sensor --- #
    sensor_type: str = "Diode"         # DT-670; select the standard diode curve on the CTC100

    # --- PID (drive is volts/K; TUNE with scripts/06_pid_settle_test.py) --- #
    pid_p: float = 0.05
    pid_i: float = 0.02
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
