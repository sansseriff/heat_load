"""SRS CTC100 temperature controller driver, over Ethernet or USB.

Every CTC100 port accepts the same ASCII command set; only the transport
differs, so the high-level command methods live on ``CTC100`` and the wire
handling lives behind a small ``Transport``:

  * ``EthernetTransport`` -- raw TCP to port 23. Commands end with ``\\n``;
    replies end with ``\\r\\n``. The CTC100 accepts a **single client** and
    ignores others until the connection closes.
  * ``SerialTransport``   -- USB virtual COM port (FTDI). Commands framed as
    ``\\r\\n cmd \\r\\n`` per the reference driver / manual, replies read a line.
    NOTE: serial has **no instrument-side arbitration** -- only one process may
    hold the port at a time, or reads corrupt. Opened ``exclusive`` by default.
  * ``MockTransport``     -- routes to an in-process ``MockCTC100Backend``.

Construct via the classmethods:

    CTC100.ethernet("192.168.1.50")
    CTC100.serial("/dev/cu.usbserial-XXXX")
    CTC100.offline()
"""

from __future__ import annotations

import re
import socket
import time
from abc import ABC, abstractmethod
from typing import Optional

from cable_heat_load.instruments._mock import MockCTC100Backend

# Pull the *last* float-looking token from a reply, tolerating an echoed
# channel name (e.g. "In1 = 295.42") or trailing units ("5.913 K").
_FLOAT_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


# ====================================================================== #
# Transports
# ====================================================================== #
class Transport(ABC):
    @abstractmethod
    def connect(self) -> None: ...
    @abstractmethod
    def close(self) -> None: ...
    @abstractmethod
    def write(self, cmd: str) -> None: ...
    @abstractmethod
    def query(self, cmd: str) -> str: ...
    @abstractmethod
    def label(self) -> str: ...
    def drain(self) -> None:
        """Discard any buffered/pending bytes so the next query stays aligned."""


class EthernetTransport(Transport):
    def __init__(self, host: str, port: int = 23, timeout: float = 3.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._buf = b""

    def label(self) -> str:
        return f"{self.host}:{self.port} (Ethernet)"

    def connect(self) -> None:
        if not self.host:
            raise ValueError("CTC100 host/IP must be set for an Ethernet connection")
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        self._sock = sock
        self._buf = b""

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
                self._buf = b""

    def write(self, cmd: str) -> None:
        self._require().sendall((cmd.strip() + "\n").encode("ascii"))

    def query(self, cmd: str) -> str:
        sock = self._require()
        self.drain()
        sock.sendall((cmd.strip() + "\n").encode("ascii"))
        return self._read_line()

    def _require(self) -> socket.socket:
        if self._sock is None:
            raise ConnectionError("CTC100 (Ethernet) is not connected; call connect() first")
        return self._sock

    def _read_line(self) -> str:
        sock = self._require()
        while b"\r\n" not in self._buf and b"\n" not in self._buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("CTC100 closed the connection")
            self._buf += chunk
        line, _sep, rest = self._buf.partition(b"\n")
        self._buf = rest
        return line.decode("ascii", errors="replace").strip()

    def drain(self) -> None:
        sock = self._require()
        self._buf = b""
        sock.setblocking(False)
        try:
            while True:
                if not sock.recv(4096):
                    break
        except (BlockingIOError, OSError):
            pass
        finally:
            sock.setblocking(True)
            sock.settimeout(self.timeout)


class SerialTransport(Transport):
    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        timeout: float = 2.0,
        exclusive: bool = True,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.exclusive = exclusive
        self._ser = None

    def label(self) -> str:
        return f"{self.port} @ {self.baudrate} (USB/serial)"

    def connect(self) -> None:
        import serial  # local import so Ethernet-only use doesn't require pyserial

        # exclusive=True (POSIX TIOCEXCL) makes a contended port fail loudly
        # instead of silently corrupting reads shared with another process.
        self._ser = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout,
            exclusive=self.exclusive,
        )

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def _frame(self, cmd: str) -> bytes:
        return ("\r\n" + cmd.strip() + "\r\n").encode("ascii")

    def write(self, cmd: str) -> None:
        ser = self._require()
        ser.reset_input_buffer()
        ser.write(self._frame(cmd))

    def query(self, cmd: str) -> str:
        ser = self._require()
        ser.reset_input_buffer()
        ser.write(self._frame(cmd))
        for _ in range(5):  # skip any stray blank lines
            line = ser.readline().decode("ascii", errors="replace").strip()
            if line:
                return line
        return ""

    def drain(self) -> None:
        if self._ser is not None:
            self._ser.reset_input_buffer()

    def _require(self):
        if self._ser is None:
            raise ConnectionError("CTC100 (serial) is not connected; call connect() first")
        return self._ser


class MockTransport(Transport):
    def __init__(self, backend: MockCTC100Backend) -> None:
        self.backend = backend

    def label(self) -> str:
        return "offline mock"

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def write(self, cmd: str) -> None:
        self.backend.handle_write(cmd.strip())

    def query(self, cmd: str) -> str:
        return self.backend.handle_query(cmd.strip())


# ====================================================================== #
# Instrument
# ====================================================================== #
class CTC100:
    """CTC100 driver; transport-agnostic high-level command helpers."""

    def __init__(self, transport: Transport) -> None:
        self._t = transport

    # --- constructors --- #
    @classmethod
    def ethernet(cls, host: str, port: int = 23, timeout: float = 3.0) -> "CTC100":
        return cls(EthernetTransport(host, port, timeout))

    @classmethod
    def serial(
        cls, port: str, baudrate: int = 9600, timeout: float = 2.0, exclusive: bool = True
    ) -> "CTC100":
        return cls(SerialTransport(port, baudrate, timeout, exclusive))

    @classmethod
    def offline(cls, backend: Optional[MockCTC100Backend] = None, **mock_kwargs) -> "CTC100":
        return cls(MockTransport(backend or MockCTC100Backend(**mock_kwargs)))

    # --- lifecycle --- #
    @property
    def label(self) -> str:
        return self._t.label()

    def connect(self) -> "CTC100":
        self._t.connect()
        if not isinstance(self._t, MockTransport):
            self._setup_comms()
        return self

    def _setup_comms(self) -> None:
        """Put the CTC100 in Verbose=Low so it replies ONLY to queries.

        In Medium/High the CTC100 also replies to set-commands; since our
        writes are fire-and-forget, those stray replies would pile up and
        misalign later reads (a set-echo gets returned as a query's answer).
        Low mode eliminates that. We drain once after switching to clear the
        reply this very command generates in the pre-existing verbose mode.
        """
        try:
            self._t.write("System.COM.Verbose Low")
            time.sleep(0.15)
            self._t.drain()
        except Exception:
            pass

    def close(self) -> None:
        self._t.close()

    def __enter__(self) -> "CTC100":
        return self.connect()

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- transport passthrough --- #
    def write(self, cmd: str) -> None:
        self._t.write(cmd)

    def query(self, cmd: str) -> str:
        return self._t.query(cmd)

    # --- high-level commands --- #
    def description(self) -> str:
        return self.query("description")

    def read_channel(self, name: str) -> float:
        return _parse_float(self.query(f"{name}?"))

    def set_output(self, name: str, value: float) -> None:
        self.write(f"{name} {value}")

    def outputs_on(self) -> None:
        self.write("outputEnable on")

    def outputs_off(self) -> None:
        self.write("outputEnable off")

    def popup(self, message: str) -> None:
        self.write(f"popup {message}")

    # channel configuration
    def set_sensor(self, name: str, sensor: str) -> None:
        self.write(f"{name}.sensor {sensor}")

    def set_io_type(self, name: str, io_type: str) -> None:
        self.write(f"{name}.IOtype {io_type}")

    def set_units(self, name: str, unit: str) -> None:
        self.write(f"{name}.Units {unit}")

    def set_high_limit(self, name: str, value: float) -> None:
        self.write(f"{name}.HiLmt {value}")

    # PID
    def set_pid_input(self, output: str, input_channel: str) -> None:
        self.write(f"{output}.PID.Input {input_channel}")

    def set_pid_values(self, output: str, p: float, i: float, d: float) -> None:
        self.write(f"{output}.PID.P {p}")
        self.write(f"{output}.PID.I {i}")
        self.write(f"{output}.PID.D {d}")

    def set_pid_ramp(self, output: str, ramp_rate: float) -> None:
        self.write(f"{output}.PID.Ramp {ramp_rate}")

    def set_setpoint(self, output: str, setpoint: float) -> None:
        self.write(f"{output}.PID.Setpoint {setpoint}")

    def pid_mode(self, output: str, on: bool) -> None:
        self.write(f"{output}.PID.Mode {'On' if on else 'Off'}")

    def configure_pid(
        self,
        output: str,
        input_channel: str,
        p: float,
        i: float,
        d: float,
        *,
        ramp_rate: Optional[float] = None,
        enable: bool = True,
    ) -> None:
        self.set_pid_input(output, input_channel)
        self.set_pid_values(output, p, i, d)
        if ramp_rate is not None:
            self.set_pid_ramp(output, ramp_rate)
        if enable:
            self.pid_mode(output, True)


def _parse_float(reply: str) -> float:
    """Extract the value from a CTC100 reply line; NaN if none present."""
    matches = _FLOAT_RE.findall(reply.replace(",", ""))
    if not matches:
        return float("nan")
    return float(matches[-1])
