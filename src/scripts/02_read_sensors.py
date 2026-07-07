"""Step 2 - read the temperatures and confirm both sources.

Streams two things:
  * the isolated 4 K plate from the **Ethernet CTC** (`channels.sensor_a`)
  * the 40 K sub-plate from the **RabbitMQ RPC source** (`remote_40k.command`,
    served by the FridgeControl GUI that owns the USB CTC)

With the heater off, confirm A reads ~4 K and the 40 K value reads ~40 K. If the
40 K column is NaN, the FridgeControl GUI / RabbitMQ broker isn't reachable, or
the command doesn't map to your sensor (see scripts/check_40k_rpc.py).

    uv run python scripts/02_read_sensors.py --ip 192.168.1.50 --seconds 30
"""

from __future__ import annotations

import time

import _common


def _add(p):
    p.add_argument("--seconds", type=float, default=20.0, help="how long to stream")
    p.add_argument("--interval", type=float, default=1.0, help="seconds between reads")


def main() -> None:
    args = _common.parse(__doc__, add_args=_add)
    cfg, insts = _common.connect_all(args)
    ch = cfg.channels
    print(f"Reading  A='{ch.sensor_a}' (expect ~4 K, Ethernet)   "
          f"40K via RPC '{cfg.remote_40k.command}' (expect ~40 K)")
    print("Press Ctrl-C to stop early.\n")
    t0 = time.monotonic()
    try:
        while time.monotonic() - t0 < args.seconds:
            a = insts.eth.read_channel(ch.sensor_a)
            b = insts.t40k.read_40k() if insts.t40k is not None else float("nan")
            print(f"  t={time.monotonic()-t0:6.1f}s   A={a:8.3f} K   40K={b:8.3f} K", flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        insts.eth.close()
    print("\nDone. Confirm A~4 K (isolated plate) and 40K~40 K (sub-plate).")


if __name__ == "__main__":
    main()
