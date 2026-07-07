"""Minimal SQLite schema for heater calibration.

Two tables, per PLAN.md: a ``runs`` row per calibration session and one
``cal_points`` row per recorded equilibrium point. Deliberately *not* the
SNSPD wafer/device/measurement hierarchy -- this extends to phase-2 cable
measurements by adding a ``sample``/``cable`` column later.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Run(Base):
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, nullable=False, default=_utcnow)
    ended_at = Column(DateTime)
    description = Column(String)
    cryostat = Column(String)
    operator = Column(String)
    status = Column(String)          # success / failed / aborted
    r_heater_ohm = Column(Float)     # resistance assumed for P = V_sense^2 / R
    config_json = Column(String)     # full config snapshot (JSON text)

    points = relationship("CalPoint", back_populates="run",
                          cascade="all, delete-orphan")


class CalPoint(Base):
    __tablename__ = "cal_points"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, default=_utcnow)

    setpoint_k = Column(Float)         # PID setpoint (None for the baseline point)
    t_isolated_k = Column(Float)       # sensor A -- isolated 4 K plate
    t_40k_k = Column(Float)            # 40 K sub-plate (via RPC)
    heater_power_w = Column(Float)     # V_sense * I  (true, leads excluded)
    heater_v_sense = Column(Float)     # 4-wire voltage across the heater (AIO2)
    heater_current = Column(Float)     # delivered current from the 100 W output (A)
    r_heater_live = Column(Float)      # V_sense / I -- measured heater resistance
    stable = Column(Boolean)           # did it meet the stability criterion?
    stability_metric = Column(Float)   # rel. std over the settle window
    settle_time_s = Column(Float)      # time spent settling this point

    run = relationship("Run", back_populates="points")
