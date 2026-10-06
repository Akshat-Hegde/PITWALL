"""asyncio UDP listener. Binding 0.0.0.0 receives both broadcast and direct-IP packets."""

from __future__ import annotations

import asyncio
import errno
import logging
import socket
import time
from collections.abc import Callable

log = logging.getLogger(__name__)

# Windows reports a taken port as WSAEADDRINUSE, or WSAEACCES when the other program
# bound it exclusively (SO_EXCLUSIVEADDRUSE).
_PORT_TAKEN_ERRNOS = {errno.EADDRINUSE, errno.EACCES, 10048, 10013}

DatagramHandler = Callable[[bytes, str, float], None]  # (data, source ip, wall time)


class PortInUseError(Exception):
    def __init__(self, protocol: str, host: str, port: int, cause: OSError) -> None:
        self.protocol, self.host, self.port, self.cause = protocol, host, port, cause
        super().__init__(f"{protocol} port {port} on {host} is already in use ({cause.strerror or cause})")


def bind_socket(kind: int, host: str, port: int) -> socket.socket:
    """Create and bind a socket, turning 'port taken' errors into PortInUseError.

    SO_REUSEADDR is deliberately not set: on Windows it would let two programs share the
    port silently and split the packets between them.
    """
    sock = socket.socket(socket.AF_INET, kind)
    try:
        sock.bind((host, port))
    except OSError as exc:
        sock.close()
        if exc.errno in _PORT_TAKEN_ERRNOS or getattr(exc, "winerror", None) in _PORT_TAKEN_ERRNOS:
            raise PortInUseError("UDP" if kind == socket.SOCK_DGRAM else "TCP", host, port, exc) from exc
        raise
    return sock


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, handler: DatagramHandler) -> None:
        self._handler = handler

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        self._handler(data, addr[0], time.time())

    def error_received(self, exc: Exception) -> None:
        # Windows reports ICMP port-unreachable for unrelated sends here; harmless for a listener.
        log.debug("UDP socket error: %s", exc)


class UdpListener:
    def __init__(self, host: str, port: int, receive_buffer_bytes: int, handler: DatagramHandler) -> None:
        self.host, self.port = host, port
        self.receive_buffer_bytes = receive_buffer_bytes
        self._handler = handler
        self._transport: asyncio.DatagramTransport | None = None

    async def start(self) -> None:
        sock = bind_socket(socket.SOCK_DGRAM, self.host, self.port)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.receive_buffer_bytes)
        actual = sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
        sock.setblocking(False)
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(lambda: _Protocol(self._handler), sock=sock)
        self.port = sock.getsockname()[1]
        log.info("Listening for UDP telemetry on %s:%d (receive buffer %d KB)", self.host, self.port, actual // 1024)

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
