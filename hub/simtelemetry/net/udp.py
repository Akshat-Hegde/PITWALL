"""asyncio UDP listener. Binding 0.0.0.0 receives both broadcast and direct-IP packets."""

from __future__ import annotations

import asyncio
import errno
import logging
import re
import socket
import subprocess
import sys
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


def port_shadows(port: int, addresses: tuple[str, ...] = ("127.0.0.1",)) -> list[str]:
    """Other programs bound to `port` on a specific address, which take the packets sent there.

    Windows allows a program to bind e.g. 127.0.0.1:20777 next to our 0.0.0.0:20777 socket, and
    then delivers everything sent to 127.0.0.1 to that program (e.g. wheel software such as
    SimPro Manager or SimHub). Checked by trying to bind the address ourselves. Windows only:
    elsewhere our own wildcard socket makes such a bind fail anyway.
    """
    if sys.platform != "win32":
        return []
    found = []
    for address in addresses:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.bind((address, port))
        except OSError:
            owner = _udp_owner(address, port)
            found.append(f"Another program{f' ({owner})' if owner else ''} is listening on {address}:{port}, so "
                         f"telemetry sent to {address} goes to it, not the hub. Close it, or set the game's "
                         f"UDP IP Address to this PC's network address instead of {address}.")
        finally:
            probe.close()
    return found


def _udp_owner(address: str, port: int) -> str | None:
    """Best-effort name of the process bound to address:port (Windows netstat + tasklist)."""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "UDP"], capture_output=True, text=True, timeout=5).stdout
        pid = next((line.split()[-1] for line in out.splitlines()
                    if re.search(rf"\s{re.escape(address)}:{port}\s", line)), None)
        if pid is None:
            return None
        task = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                              capture_output=True, text=True, timeout=5).stdout
        name = task.split(",")[0].strip('" \r\n')
        return name or f"process {pid}"
    except (OSError, subprocess.SubprocessError, StopIteration):
        return None


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
