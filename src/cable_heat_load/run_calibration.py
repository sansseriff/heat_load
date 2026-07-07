"""Entry point: run the full heater calibration and save every point.

    uv run python -m cable_heat_load.run_calibration                # real CTC100 at cfg.ip
    uv run python -m cable_heat_load.run_calibration --offline      # dry run vs the mock
    uv run python -m cable_heat_load.run_calibration --ip 192.168.1.50

Ctrl-C aborts cleanly: the run unwinds and the heater is driven safe.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict

from lab_procedure import ProcedureRunner, RunStarted, StepEnded, StepProgress

from cable_heat_load.config import CalibrationConfig
from cable_heat_load.procedures import build_calibration
from cable_heat_load.session import connect_instruments


def _print_status(msg: object) -> None:
    if isinstance(msg, StepProgress):
        node = ".".join(msg.node_id)
        detail = f" — {msg.detail}" if msg.detail else ""
        print(f"  [{msg.fraction:5.1%}] {node}{detail}", flush=True)
    elif isinstance(msg, StepEnded):
        print(f"  · {'.'.join(msg.node_id)} -> {msg.status}", flush=True)


def run(cfg: CalibrationConfig) -> str:
    insts = connect_instruments(cfg)
    print(f"Connected: {insts.eth.description()}  [{insts.eth.label}]")

    runner = ProcedureRunner(instruments=insts)
    from cable_heat_load.data import CalibrationSaver

    saver = CalibrationSaver(
        cfg.db_path, cfg.csv_path,
        r_heater_ohm=cfg.r_heater_ohm,
        config_snapshot=asdict(cfg),
    )
    saver.attach(runner.context.data_bus)
    runner.context.status_bus.subscribe((StepProgress, StepEnded), _print_status)

    root = build_calibration(cfg)
    run_started = RunStarted(
        run_type="heater_calibration",
        description=cfg.run_description,
        cryostat=cfg.cryostat or None,
        operator=cfg.operator or None,
    )

    thread = runner.start(root, run_started)
    try:
        while thread.is_alive():
            thread.join(0.2)
    except KeyboardInterrupt:
        print("\nAborting — driving heater safe...", flush=True)
        runner.abort()
        thread.join()
    finally:
        _safe_off(insts.eth, cfg)
        insts.eth.close()

    status = (runner.status.value if runner.status else "unknown")
    print(f"\nRun finished: {status}. Saved to {cfg.db_path} / {cfg.csv_path}")
    return status


def _safe_off(ctc, cfg: CalibrationConfig) -> None:
    try:
        ctc.pid_mode(cfg.channels.heater, False)
        ctc.set_output(cfg.channels.heater, 0)
        ctc.outputs_off()
    except Exception:
        pass


def main() -> None:
    p = argparse.ArgumentParser(description="Run heater calibration")
    p.add_argument("--ip", help="CTC100 IP address (overrides config)")
    p.add_argument("--offline", action="store_true", help="use the in-process mock")
    args = p.parse_args()

    cfg = CalibrationConfig()
    if args.ip:
        cfg.ip = args.ip
    if args.offline:
        cfg.offline = True
    run(cfg)


if __name__ == "__main__":
    main()
