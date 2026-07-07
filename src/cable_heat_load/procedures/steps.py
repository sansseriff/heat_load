"""lab_procedure Steps for heater calibration.

The building blocks of one calibration point:

    Sequence(SetSetpoint(T), WaitForStability(), RecordPoint(T))

swept over the configured temperature setpoints. All steps read the CTC100 from
``self.context.instruments`` and their parameters from a ``CalibrationConfig``.
"""

from __future__ import annotations

import statistics
import time
from collections import deque

from lab_procedure import Observation, Status, Step

from cable_heat_load.config import CalibrationConfig


def read_snapshot(instruments, cfg: CalibrationConfig) -> dict:
    """Read all sources and compute true heater power from I and the 4-wire V.

    The 100 W output (current source) gives the delivered current I; AIO2 gives
    the true 4-wire heater voltage. So P = V_sense * I and R = V_sense / I, with
    no assumed resistance and lead dissipation excluded. Isolated-plate temp
    comes from the Ethernet CTC; the 40 K sub-plate from the RPC source (NaN if
    disabled/unreachable).
    """
    ctc = instruments.eth
    ch = cfg.channels
    v_sense = ctc.read_channel(ch.vsense)
    current = ctc.read_channel(ch.heater_current_chan or ch.heater)
    power = v_sense * current
    r_live = v_sense / current if current else float("nan")
    t_40k = float("nan")
    if instruments.t40k is not None:
        try:
            t_40k = instruments.t40k.read_40k()
        except Exception:
            t_40k = float("nan")
    return {
        "t_isolated_k": ctc.read_channel(ch.sensor_a),
        "t_40k_k": t_40k,
        "heater_v_sense": v_sense,
        "heater_current": current,
        "heater_power_w": power,
        "r_heater_live": r_live,
    }


class ConfigureInstrument(Step):
    """One-time setup: diode sensor types, heater output mode + safety, PID."""

    def __init__(self, cfg: CalibrationConfig) -> None:
        super().__init__(name="ConfigureInstrument")
        self.cfg = cfg

    def run(self) -> Status:
        ctc = self.context.instruments.eth
        cfg, ch = self.cfg, self.cfg.channels
        ctc.set_sensor(ch.sensor_a, cfg.sensor_type)
        # 100 W outputs (Out1/Out2) are dedicated outputs -- no IOtype to set;
        # just choose units (Amps) and a safety high-limit.
        ctc.set_units(ch.heater, cfg.heater_units)
        ctc.set_high_limit(ch.heater, cfg.heater_hilmt)
        ctc.set_io_type(ch.vsense, "Input")
        ctc.configure_pid(
            ch.heater, ch.sensor_a,
            cfg.pid_p, cfg.pid_i, cfg.pid_d,
            ramp_rate=cfg.pid_ramp, enable=False,
        )
        return Status.SUCCESS


class SetSetpoint(Step):
    """Point the PID loop at a temperature setpoint and enable the heater."""

    def __init__(self, cfg: CalibrationConfig, setpoint_k: float) -> None:
        super().__init__(name=f"SetSetpoint({setpoint_k} K)")
        self.cfg = cfg
        self.setpoint_k = setpoint_k

    def run(self) -> Status:
        ctc = self.context.instruments.eth
        heater = self.cfg.channels.heater
        ctc.set_setpoint(heater, self.setpoint_k)
        ctc.pid_mode(heater, True)
        ctc.outputs_on()
        return Status.SUCCESS


class WaitForStability(Step):
    """Poll the isolated-plate sensor until it holds flat, or time out.

    "Flat" = relative standard deviation over a rolling ``stability_window_s``
    below ``stability_tol`` (default 1 %), with the window full. Stashes the
    achieved metric and settle time on the context for RecordPoint.
    """

    determinate = True

    def __init__(self, cfg: CalibrationConfig) -> None:
        super().__init__(name="WaitForStability")
        self.cfg = cfg

    def run(self) -> Status:
        cfg = self.cfg
        ctc = self.context.instruments.eth
        sensor = cfg.channels.sensor_a
        window: deque[tuple[float, float]] = deque()
        t0 = time.monotonic()

        while True:
            if self.aborted:
                return Status.ABORTED
            now = time.monotonic()
            elapsed = now - t0
            temp = ctc.read_channel(sensor)
            window.append((now, temp))
            while window and now - window[0][0] > cfg.stability_window_s:
                window.popleft()

            metric = self._rel_std(window)
            # Ready once we've observed at least a full window; by then the
            # pruned deque holds ~window/poll samples of the trailing window.
            ready = elapsed >= cfg.stability_window_s
            if ready and metric is not None and metric < cfg.stability_tol:
                self.context.set_parameter("stability_metric", metric)
                self.context.set_parameter("settle_time_s", elapsed)
                self.context.set_parameter("stable", True)
                self.report_progress(1.0, detail=f"stable T={temp:.3f} K")
                return Status.SUCCESS

            if elapsed > cfg.settle_timeout_s:
                self.context.set_parameter("stability_metric", metric or float("nan"))
                self.context.set_parameter("settle_time_s", elapsed)
                self.context.set_parameter("stable", False)
                return Status.FAILED

            detail = f"T={temp:.3f} K relstd={metric:.2%}" if metric else f"T={temp:.3f} K"
            self.report_progress(min(elapsed / cfg.settle_timeout_s, 0.99), detail=detail)
            if not self.sleep(cfg.poll_interval_s):
                return Status.ABORTED

    @staticmethod
    def _rel_std(window) -> float | None:
        if len(window) < 3:
            return None
        temps = [t for _, t in window]
        mean = statistics.fmean(temps)
        if mean == 0:
            return None
        return statistics.pstdev(temps) / abs(mean)


class RecordPoint(Step):
    """Read the settled state, compute power, and emit one Observation row."""

    def __init__(self, cfg: CalibrationConfig, setpoint_k: float | None) -> None:
        super().__init__(name="RecordPoint")
        self.cfg = cfg
        self.setpoint_k = setpoint_k

    def run(self) -> Status:
        params = self.context.parameters
        data = read_snapshot(self.context.instruments, self.cfg)
        data.update(
            setpoint_k=self.setpoint_k,
            stable=params.get("stable"),
            stability_metric=params.get("stability_metric"),
            settle_time_s=params.get("settle_time_s"),
        )
        self.context.data_bus.emit(Observation(data=data, temperature=data["t_isolated_k"]))
        return Status.SUCCESS


class HeaterSafeOff(Step):
    """Disable PID and zero the heater output. Safe to call any time."""

    def __init__(self, cfg: CalibrationConfig) -> None:
        super().__init__(name="HeaterSafeOff")
        self.cfg = cfg

    def run(self) -> Status:
        self._make_safe()
        return Status.SUCCESS

    def on_exit(self, status: Status) -> None:  # runs even if aborted/failed
        self._make_safe()

    def _make_safe(self) -> None:
        insts = self.context.instruments
        if insts is None:
            return
        ctc = insts.eth
        heater = self.cfg.channels.heater
        try:
            ctc.pid_mode(heater, False)
            ctc.set_output(heater, 0)
            ctc.outputs_off()
        except Exception:
            pass
