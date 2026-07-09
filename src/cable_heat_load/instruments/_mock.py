"""In-process physical mock of a CTC100, for hardware-free development.

Models the phase-1 setup with the **100 W current-source output**:

  * sensor A -- isolated 4 K plate; relaxes (first order) toward the equilibrium
    temperature implied by the delivered heater power, or the PID setpoint;
  * the heater output (`Out1`) is driven in **Amps**: `Out1?` returns the
    current I; the 4-wire sense (`AIO2`) returns V = I * R_heater(T);
  * heater power P = I**2 * R_heater(T), with P = k * (T**4 - T_base**4).

Because it's a current source, the leads don't enter the measurement: I is set
and V_sense is a true 4-wire voltage, so P = V_sense * I and R = V_sense / I are
exact. `r_heater_tempco` lets R_heater drift with plate temperature so the
`r_heater_live` diagnostic has something to show offline.

The 40 K source is mocked separately by `MockTemperatureSource`.
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
    sensor_a: str = "T4k"          # isolated 4 K plate
    heater: str = "Out1"           # 100 W output, driven in Amps
    vsense: str = "AIO2"           # heater sense HIGH side (H+), vs ground
    vsense_lo: str = "AIO1"        # heater sense LOW side (H-), vs ground
    r_return: float = 0.0          # grounded return-lead resistance (shared-ground
                                   # artifact); >0 makes single-ended over-read
    i_monitor: str = "Out1I"       # output-card measured-current monitor
    v_monitor: str = "Out1V"       # output-card 2-wire voltage monitor (incl. leads)
    r_monitor: str = "Out1R"       # output-card 2-wire resistance monitor (incl. leads)
    r_leads_2wire: float = 0.0     # total drive-lead R the 2-wire monitor adds on top
                                   # of R_heater (the 4-wire sense excludes it)

    # Physical parameters, tuned to the previous team's real standoff
    # calibration (StandoffCalibrations/20250620.csv): base 4.485 K, ~46 mW->10 K.
    t_base: float = 4.485          # isolated-plate floor with no heat (K)
    r_heater: float = 90.0         # heater resistance at base (ohm)
    r_heater_tempco: float = 0.0   # fractional dR/R per K above t_base (0 = flat)
    k: float = 4.75e-6             # P = k*(T^4 - t_base^4)  (W/K^4)
    tau: float = 15.0              # thermal time constant (s)
    noise_k: float = 0.003         # temperature noise (K rms)
    max_drive_current: float | None = 1.0   # A (100 W output ceiling; way above our range)

    seed: int | None = None
    attrs: dict[str, str] = field(default_factory=dict)
    outputs_enabled: bool = False

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._t_a = self.t_base
        self._i_cmd = 0.0       # last commanded open-loop current (A)
        self._current = 0.0     # delivered current (A), refreshed by _advance
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
        if "." in head:  # attribute set, e.g. "Out1.PID.Setpoint 5"
            self.attrs[head.lower()] = " ".join(tokens[1:])
            return
        if len(tokens) >= 2:  # "<name> <value>" output set
            try:
                value = float(tokens[1])
            except ValueError:
                return
            if head == self.heater:
                self._advance()
                self._i_cmd = max(value, 0.0)

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

    def _r_at(self, temp: float) -> float:
        return self.r_heater * (1.0 + self.r_heater_tempco * (temp - self.t_base))

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

        r_now = self._r_at(self._t_a)
        if not self.outputs_enabled:
            current = 0.0
        elif self._pid_on() and self._setpoint() is not None:
            # closed loop: current the PID needs to hold the setpoint
            current = math.sqrt(self._power_for(self._setpoint()) / r_now)
        else:
            current = self._i_cmd                 # open loop, commanded current
        current = min(current, self._i_max())

        self._current = current
        power = current**2 * r_now
        target = self._temp_for(power)

        if dt > 0:
            decay = 1.0 - math.exp(-dt / self.tau)
            self._t_a += (target - self._t_a) * decay

    def _channel_value(self, name: str) -> float:
        self._advance()
        if name == self.sensor_a:
            return self._t_a + self._rng.gauss(0.0, self.noise_k)
        if name == self.heater:
            return self._current
        # H+ vs ground = drop across heater + grounded return lead;
        # H- vs ground = drop across the return lead. Difference = I * R_heater.
        if name == self.vsense:
            return self._current * (self._r_at(self._t_a) + self.r_return)
        if name == self.vsense_lo:
            return self._current * self.r_return
        # Output-card monitors: measured current, and 2-wire V/R that include
        # the drive leads (so they read higher than the 4-wire heater V/R).
        if name == self.i_monitor:
            return self._current
        if name == self.v_monitor:
            return self._current * (self._r_at(self._t_a) + self.r_leads_2wire)
        if name == self.r_monitor:
            return self._r_at(self._t_a) + self.r_leads_2wire
        return 0.0
