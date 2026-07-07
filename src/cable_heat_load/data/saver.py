"""Saver that turns procedure messages into durable rows.

Subscribes to a ``lab_procedure`` data bus and, per message:

  * ``RunStarted``   -> open a ``runs`` row (and CSV header);
  * ``Observation``  -> insert one ``cal_points`` row + append a CSV line;
  * ``RunEnded``     -> stamp ``ended_at`` / ``status`` on the run.

Each point is committed as it arrives, so a long run is durable against
Ctrl-C / power blips (the reason for SQLite over a single dump at the end).
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone

from lab_procedure import Observation, RunEnded, RunStarted
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from cable_heat_load.data.schema import Base, CalPoint, Run

_CSV_FIELDS = [
    "timestamp", "setpoint_k", "t_isolated_k", "t_40k_k",
    "heater_power_w", "heater_v_sense", "heater_v_drive",
    "stable", "stability_metric", "settle_time_s",
]


class CalibrationSaver:
    def __init__(
        self,
        db_path: str = "calibration.db",
        csv_path: str | None = "calibration_points.csv",
        *,
        r_heater_ohm: float | None = None,
        config_snapshot: dict | None = None,
    ) -> None:
        self.engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(self.engine)
        self.csv_path = csv_path
        self.r_heater_ohm = r_heater_ohm
        self.config_snapshot = config_snapshot or {}
        self.run_id: int | None = None

    def attach(self, data_bus) -> None:
        """Subscribe to the run's data bus."""
        data_bus.subscribe(RunStarted, self._on_run_started)
        data_bus.subscribe(Observation, self._on_observation)
        data_bus.subscribe(RunEnded, self._on_run_ended)

    # ------------------------------------------------------------------ #
    def _on_run_started(self, msg: RunStarted) -> None:
        with Session(self.engine) as session:
            run = Run(
                description=msg.description,
                cryostat=msg.cryostat,
                operator=msg.operator,
                r_heater_ohm=self.r_heater_ohm,
                config_json=json.dumps(self.config_snapshot, default=str),
            )
            session.add(run)
            session.commit()
            self.run_id = run.id

        if self.csv_path and not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", newline="") as fh:
                csv.DictWriter(fh, fieldnames=_CSV_FIELDS).writeheader()

    def _on_observation(self, msg: Observation) -> None:
        if self.run_id is None:
            return
        d = msg.data
        with Session(self.engine) as session:
            session.add(CalPoint(
                run_id=self.run_id,
                setpoint_k=d.get("setpoint_k"),
                t_isolated_k=d.get("t_isolated_k"),
                t_40k_k=d.get("t_40k_k"),
                heater_power_w=d.get("heater_power_w"),
                heater_v_sense=d.get("heater_v_sense"),
                heater_v_drive=d.get("heater_v_drive"),
                stable=d.get("stable"),
                stability_metric=d.get("stability_metric"),
                settle_time_s=d.get("settle_time_s"),
            ))
            session.commit()

        if self.csv_path:
            row = {k: d.get(k) for k in _CSV_FIELDS}
            row["timestamp"] = datetime.now(timezone.utc).isoformat()
            with open(self.csv_path, "a", newline="") as fh:
                csv.DictWriter(fh, fieldnames=_CSV_FIELDS).writerow(row)

    def _on_run_ended(self, msg: RunEnded) -> None:
        if self.run_id is None:
            return
        with Session(self.engine) as session:
            run = session.get(Run, self.run_id)
            if run is not None:
                run.ended_at = datetime.now(timezone.utc)
                run.status = msg.status
                session.commit()
