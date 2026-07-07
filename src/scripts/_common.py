"""Shared setup for the bring-up scripts.

Each script builds a CalibrationConfig, optionally overridden from the command
line, then connects what it needs:

  * `connect_eth`  -> just the Ethernet CTC100 (isolated plate + heater)
  * `connect_all`  -> Instruments (Ethernet CTC + the 40 K RPC source)

    uv run python scripts/01_ping_ctc100.py --ip 192.168.1.50
    uv run python scripts/01_ping_ctc100.py --offline
"""

from __future__ import annotations

import argparse

from cable_heat_load.config import CalibrationConfig
from cable_heat_load.instruments import CTC100
from cable_heat_load.session import Instruments, build_eth, connect_instruments


def parse(description: str, add_args=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--ip", help="CTC100 IP address (overrides config default)")
    p.add_argument("--offline", action="store_true", help="use the in-process mock")
    p.add_argument("--mock-tau", type=float, default=None,
                   help="offline only: thermal time constant in s (smaller = faster)")
    if add_args is not None:
        add_args(p)
    return p.parse_args()


def config_from_args(args: argparse.Namespace) -> CalibrationConfig:
    cfg = CalibrationConfig()
    if getattr(args, "ip", None):
        cfg.ip = args.ip
    if getattr(args, "offline", False):
        cfg.offline = True
    if getattr(args, "mock_tau", None) is not None:
        cfg.mock_tau = args.mock_tau
    return cfg


def connect_eth(args: argparse.Namespace) -> tuple[CalibrationConfig, CTC100]:
    cfg = config_from_args(args)
    where = "offline mock" if cfg.offline else f"{cfg.ip}:{cfg.port}"
    print(f"Connecting to Ethernet CTC100 ({where}) ...")
    ctc = build_eth(cfg)
    ctc.connect()
    return cfg, ctc


def connect_all(args: argparse.Namespace) -> tuple[CalibrationConfig, Instruments]:
    cfg = config_from_args(args)
    where = "offline mock" if cfg.offline else f"{cfg.ip}:{cfg.port}"
    print(f"Connecting to Ethernet CTC100 ({where}) + 40 K RPC source ...")
    return cfg, connect_instruments(cfg)
