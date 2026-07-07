"""Diagnostic - check the 40 K reading over RabbitMQ RPC.

Talks to the FridgeControl GUI's RPC server (queue `fridge_control_rpc_queue`)
and requests the configured command (default `T40K`). Use this to confirm:

  * the FridgeControl GUI + RabbitMQ broker are running, and
  * the command maps to *your* 40 K sensor (the value should read ~40 K).

If it returns NaN: the GUI/broker isn't up, or nothing owns that USB CTC. If it
returns a wrong/!~40 K value, your sensor may be on a different thermometry slot
than the server's `40K` -- pick another command with --command, or add a case on
the server side (see FridgeControl_NEST_mcirillo.py `parse_queue_message`).

    uv run python scripts/check_40k_rpc.py
    uv run python scripts/check_40k_rpc.py --command T4K --host localhost
"""

from __future__ import annotations

import argparse
import time

from cable_heat_load.instruments import FridgeRPCClient


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="localhost", help="RabbitMQ broker host")
    p.add_argument("--queue", default="fridge_control_rpc_queue")
    p.add_argument("--command", default="T40K", help="RPC command to request")
    p.add_argument("--count", type=int, default=5, help="number of reads")
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--timeout", type=float, default=10.0)
    args = p.parse_args()

    client = FridgeRPCClient(
        rpc_queue=args.queue, host=args.host, command=args.command, timeout=args.timeout
    )
    print(f"Requesting '{args.command}' from '{args.queue}' on {args.host} ...\n")
    any_ok = False
    for i in range(args.count):
        raw = client.call(args.command)
        val = client.read_temperature(args.command)
        ok = val == val  # not NaN
        any_ok = any_ok or ok
        print(f"  [{i+1}/{args.count}] raw={raw!r:>12}  -> {val:8.3f} K"
              + ("" if ok else "   (unreachable / not a number)"))
        time.sleep(args.interval)

    if not any_ok:
        print("\nFAIL: no valid reading. Is the FridgeControl GUI + RabbitMQ running?")
    else:
        print(f"\nOK: RPC works. Confirm the value (~40 K) is really your 40 K sensor "
              f"(command '{args.command}').")


if __name__ == "__main__":
    main()
