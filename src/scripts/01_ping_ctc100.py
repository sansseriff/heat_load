"""Step 1 - confirm you can talk to the CTC100 over Ethernet.

Connects, asks for the instrument description, and fires a popup on the CTC100's
screen (a one-way check you can see from across the room).

    uv run python scripts/01_ping_ctc100.py --ip 192.168.1.50
    uv run python scripts/01_ping_ctc100.py --offline

If this hangs: check the CTC100's IP (Setup screen), that you're on the same
subnet / cabled directly, and that no other client holds port 23 (the CTC100
accepts one client at a time -- press System.IP.Close on the front panel).
"""

from __future__ import annotations

import _common


def main() -> None:
    args = _common.parse(__doc__)
    cfg, ctc = _common.connect_eth(args)
    try:
        print("description  :", ctc.description())
        ctc.popup("hello from cable_heat_load")
        print("Sent 'popup hello' -- check the CTC100 screen for a popup.")
        print("OK: Ethernet communication works.")
    finally:
        ctc.close()


if __name__ == "__main__":
    main()
