"""Assemble the heater-calibration Step tree.

    Heater calibration
    ├─ ConfigureInstrument
    ├─ Baseline (heater off)        -> one point at zero power
    ├─ Setpoint sweep               -> one point per configured setpoint
    │    └─ SetSetpoint / WaitForStability / RecordPoint
    └─ HeaterSafeOff
"""

from __future__ import annotations

from lab_procedure import Sequence, Step, Sweep

from cable_heat_load.config import CalibrationConfig
from cable_heat_load.procedures.steps import (
    ConfigureInstrument,
    HeaterSafeOff,
    RecordPoint,
    SetSetpoint,
    WaitForStability,
)


def build_calibration(cfg: CalibrationConfig) -> Step:
    def point_factory(setpoint: object) -> Step:
        sp = float(setpoint)  # type: ignore[arg-type]
        return Sequence(
            SetSetpoint(cfg, sp),
            WaitForStability(cfg),
            RecordPoint(cfg, sp),
            name=f"Point {sp} K",
        )

    baseline = Sequence(
        HeaterSafeOff(cfg),
        WaitForStability(cfg),
        RecordPoint(cfg, None),
        name="Baseline (heater off)",
    )
    sweep = Sweep("setpoint_k", cfg.setpoints, point_factory, name="Setpoint sweep")

    return Sequence(
        ConfigureInstrument(cfg),
        baseline,
        sweep,
        HeaterSafeOff(cfg),
        name="Heater calibration",
    )
