"""In-process physical mock of a CTC100, for hardware-free development.

Models the phase-1 setup closely enough to exercise both the bring-up scripts
and the calibration procedure without hardware:

  * sensor A -- the isolated 4 K plate; relaxes (first order) toward the
    equilibrium temperature implied by the delivered heater power, or toward the
    PID setpoint in closed loop;
  * sensor B -- the 40 K sub-plate, ~constant near 40-45 K;
  * heater drive (an AIO **voltage** output) + a 4-wire **voltage sense** input.

Drive physics (matches the real BNC/AIO path):

    I        = min(V_drive / (R_heater + R_leads), I_max)   # 30 mA AIO limit
    P_heater = I**2 * R_heater
    V_sense  = I * R_heater                                  # true 4-wire voltage
    V_out    = I * (R_heater + R_leads)                      # sags if I is capped

so ``P = V_sense**2 / R_heater`` recovers the true power independent of the
phosphor-bronze leads, and ``R_heater = R_leads * V_sense / (V_out - V_sense)``.
Thermal relation: ``P = k * (T**4 - T_base**4)``.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field


@dataclass
class MockTemperatureSource:
    """Stand-in for the RabbitMQ 40 K source, for offline development."""

    value: float = 40.0
    noise_k: float = 0.01
    seed: int | None = None

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def read_40k(self) -> float:
        return self.value + self._rng.gauss(0.0, self.noise_k)


@dataclass
class MockCTC100Backend:
    # Role -> CTC100 channel name (must match the config used by the caller).
    sensor_a: str = "In1"          # isolated 4 K plate
    sensor_b: str = "In2"          # 40 K sub-plate
    heater: str = "AIO1"           # drive output (volts)
    vsense: str = "AIO2"           # 4-wire voltage sense (volts)

    # Physical parameters, tuned to the previous team's real standoff
    # calibration (StandoffCalibrations/20250620.csv): base 4.485 K, ~46 mW->10 K.
    t_base: float = 4.485          # isolated-plate floor with no heat (K)
    t_40k: float = 44.0            # sub-plate temperature (~40-45 K in practice)
    r_heater: float = 100.0        # heater resistance (ohm)
    r_leads: float = 17.7          # drive-loop lead resistance, 9.1+8.6 (ohm)
    k: float = 4.75e-6             # P = k*(T^4 - t_base^4)  (W/K^4)
    tau: float = 15.0              # thermal time constant (s)
    noise_k: float = 0.003         # temperature noise (K rms)
    # AIO heater-drive current ceiling (CTC100 manual p.9); set to None to model
    # a 100 W screw-terminal output (effectively unlimited here).
    max_drive_current: float | None = 0.030   # A

    seed: int | None = None
    attrs: dict[str, str] = field(default_factory=dict)
    outputs_enabled: bool = False

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._t_a = self.t_base
        self._v_drive = 0.0     # last commanded open-loop drive voltage (V)
        # cached derived quantities, refreshed by _advance()
        self._power = 0.0
        self._vsense = 0.0
        self._vout = 0.0
        self._last = time.monotonic()

    # ------------------------------------------------------------------ #
    # Command handling
    # ------------------------------------------------------------------ #
    def handle_write(self, cmd: str) -> None:
        if not cmd:
            return
        tokens = cmd.split()
        head, low = tokens[0], tokens[0].lower()

        if low == "outputenable":
            self.outputs_enabled = len(tokens) > 1 and tokens[1].lower() == "on"
            return
        if low in {"popup", "description"}:
            return
        if "." in head:  # attribute set, e.g. "AIO1.PID.Setpoint 5"
            self.attrs[head.lower()] = " ".join(tokens[1:])
            return
        if len(tokens) >= 2:  # "<name> <value>" output set
            try:
                value = float(tokens[1])
            except ValueError:
                return
            if head == self.heater:
                self._advance()
                self._v_drive = max(value, 0.0)

    def handle_query(self, cmd: str) -> str:
        if cmd.lower() == "description":
            return "CTC100 (offline mock), SN MOCK-0001"
        name = cmd[:-1] if cmd.endswith("?") else cmd
        return f"{self._channel_value(name):.6g}"

    # ------------------------------------------------------------------ #
    # Simulation
    # ------------------------------------------------------------------ #
    def _pid_on(self) -> bool:
        return self.attrs.get(f"{self.heater.lower()}.pid.mode", "off").lower() == "on"

    def _setpoint(self) -> float | None:
        raw = self.attrs.get(f"{self.heater.lower()}.pid.setpoint")
        try:
            return float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    def _power_for(self, temp: float) -> float:
        return max(self.k * (temp**4 - self.t_base**4), 0.0)

    def _temp_for(self, power: float) -> float:
        return (self.t_base**4 + max(power, 0.0) / self.k) ** 0.25

    def _i_max(self) -> float:
        return math.inf if self.max_drive_current is None else self.max_drive_current

    def _advance(self) -> None:
        now = time.monotonic()
        dt = now - self._last
        self._last = now

        r_loop = self.r_heater + self.r_leads
        if not self.outputs_enabled:
            current = 0.0
        elif self._pid_on() and self._setpoint() is not None:
            # closed loop: PID sources the current needed to hold the setpoint
            current = math.sqrt(self._power_for(self._setpoint()) / self.r_heater)
        else:
            current = self._v_drive / r_loop      # open loop from commanded V
        current = min(current, self._i_max())      # AIO compliance limit

        self._power = current**2 * self.r_heater
        self._vsense = current * self.r_heater
        self._vout = current * r_loop
        target = self._temp_for(self._power)

        if dt > 0:
            decay = 1.0 - math.exp(-dt / self.tau)
            self._t_a += (target - self._t_a) * decay

    def _channel_value(self, name: str) -> float:
        self._advance()
        if name == self.sensor_a:
            return self._t_a + self._rng.gauss(0.0, self.noise_k)
        if name == self.sensor_b:
            return self.t_40k + self._rng.gauss(0.0, self.noise_k)
        if name == self.heater:
            return self._vout
        if name == self.vsense:
            return self._vsense
        return 0.0
