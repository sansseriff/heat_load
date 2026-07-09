"""Build the instrument set (real or mock) from a CalibrationConfig.

`Instruments` bundles the two temperature sources:
  * `eth`  -- the Ethernet CTC100 (isolated plate + heater drive/sense);
  * `t40k` -- the 40 K source (RabbitMQ RPC client, mock, or None if disabled).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cable_heat_load.config import CalibrationConfig
from cable_heat_load.instruments import CTC100, FridgeRPCClient
from cable_heat_load.instruments._mock import MockCTC100Backend, MockTemperatureSource


class TemperatureSource(Protocol):
    def read_40k(self) -> float: ...


@dataclass
class Instruments:
    eth: CTC100
    t40k: TemperatureSource | None = None


def build_eth(cfg: CalibrationConfig) -> CTC100:
    if cfg.offline:
        ch = cfg.channels
        mock = MockCTC100Backend(
            sensor_a=ch.sensor_a,
            heater=ch.heater,
            vsense=ch.vsense,
            vsense_lo=ch.vsense_lo,
            i_monitor=ch.i_monitor or "",
            v_monitor=ch.v_monitor or "",
            r_monitor=ch.r_monitor or "",
            r_leads_2wire=cfg.r_leads_drive_ohm,
            r_heater=cfg.r_heater_ohm,
            tau=cfg.mock_tau,
        )
        return CTC100.offline(mock)
    return CTC100.ethernet(cfg.ip, cfg.port, timeout=cfg.timeout)


def build_t40k(cfg: CalibrationConfig) -> TemperatureSource | None:
    if not cfg.remote_40k.enabled:
        return None
    if cfg.offline:
        return MockTemperatureSource(value=40.0)
    r = cfg.remote_40k
    return FridgeRPCClient(
        rpc_queue=r.rpc_queue, host=r.host, command=r.command, timeout=r.timeout
    )


def build_instruments(cfg: CalibrationConfig) -> Instruments:
    return Instruments(eth=build_eth(cfg), t40k=build_t40k(cfg))


def connect_instruments(cfg: CalibrationConfig) -> Instruments:
    """Build and connect. The Ethernet CTC is opened; the 40 K RPC source is
    connectionless (opens per call) but probed once so we warn early if the
    FridgeControl server / broker is unreachable."""
    insts = build_instruments(cfg)
    insts.eth.connect()
    if insts.t40k is not None and not cfg.offline:
        probe = insts.t40k.read_40k()
        if probe != probe:  # NaN
            print(
                f"WARNING: 40 K RPC source unreachable (queue "
                f"'{cfg.remote_40k.host}:{cfg.remote_40k.command}'). "
                "Is the FridgeControl GUI + RabbitMQ running? 40 K will log NaN."
            )
        else:
            print(f"40 K source OK via RPC '{cfg.remote_40k.command}' = {probe:.3f} K")
    return insts
