"""RabbitMQ RPC client for the NEST FridgeControl temperature server.

The FridgeControl GUI (`FridgeControl_NEST_mcirillo.py`) owns the USB-connected
CTC100s and runs a RabbitMQ RPC consumer on `fridge_control_rpc_queue`. It
answers commands like ``T40K`` with the latest cached sensor reading. We ask for
the 40 K temperature that way instead of opening the serial port ourselves,
which would corrupt the server's reads (serial has no instrument-side
arbitration -- see PLAN.md / BRINGUP.md).

Each ``call`` uses a short-lived connection: RabbitMQ reads happen about once per
calibration point, and a fresh connection per call keeps this safe to use from
the procedure's worker thread (pika's BlockingConnection is not thread-safe if
shared across threads).
"""

from __future__ import annotations

import time
import uuid

import pika


class FridgeRPCClient:
    def __init__(
        self,
        rpc_queue: str = "fridge_control_rpc_queue",
        host: str = "localhost",
        command: str = "T40K",
        timeout: float = 10.0,
    ) -> None:
        self.rpc_queue = rpc_queue
        self.host = host
        self.command = command
        self.timeout = timeout

    def read_40k(self) -> float:
        """Return the 40 K reading (NaN if the server/broker is unreachable)."""
        return self.read_temperature(self.command)

    def read_temperature(self, command: str) -> float:
        resp = self.call(command)
        if resp is None:
            return float("nan")
        try:
            return float(resp)
        except ValueError:
            return float("nan")

    def call(self, message: str) -> str | None:
        """Send one RPC and return the reply string, or None on any failure."""
        try:
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=self.host,
                    socket_timeout=self.timeout,
                    blocked_connection_timeout=self.timeout,
                )
            )
        except Exception:
            return None

        response: dict[str, str | None] = {"body": None}
        corr_id = str(uuid.uuid4())
        try:
            channel = connection.channel()
            channel.queue_declare(queue=self.rpc_queue)
            callback_queue = channel.queue_declare(queue="", exclusive=True).method.queue

            def on_response(ch, method, props, body) -> None:
                if props.correlation_id == corr_id:
                    response["body"] = body.decode()

            channel.basic_consume(
                queue=callback_queue, on_message_callback=on_response, auto_ack=True
            )
            channel.basic_publish(
                exchange="",
                routing_key=self.rpc_queue,
                properties=pika.BasicProperties(
                    reply_to=callback_queue, correlation_id=corr_id
                ),
                body=str(message),
            )
            deadline = time.time() + self.timeout
            while response["body"] is None and time.time() < deadline:
                connection.process_data_events(time_limit=min(1.0, self.timeout))
            return response["body"]
        except Exception:
            return None
        finally:
            try:
                connection.close()
            except Exception:
                pass
