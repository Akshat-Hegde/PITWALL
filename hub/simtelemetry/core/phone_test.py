"""The phone test: can guests' phones reach the hub?

Check-in stickers and story cards only work for phones on a Wi-Fi that can reach this PC. The setup page and the
staff Health tab show a "Test from your phone" QR that opens the tiny /hello page; a visit from any address other
than this PC's own is recorded in <data>/phone-test.json, so setup can show "A phone reached the hub at 14:02".
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import json
import logging
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PHONE_TEST_FILE = "phone-test.json"
SAVE_EVERY_S = 10.0          # a phone reloading /hello doesn't rewrite the file each time

WIFI_ADVICE = ("Guests' phones must be on a Wi-Fi that can reach this PC: your main cafe Wi-Fi, or a guest network "
               "with 'client/guest isolation' turned off.")
FAIL_ADVICE = ("If the page doesn't open on a phone on the guest Wi-Fi, guests can't use check-in or cards: "
               "use the main Wi-Fi or turn off isolation.")
NO_NETWORK = "This PC isn't connected to a network, so phones can't reach it. Connect it to the cafe network first."
NOT_YET = "No phone has reached the hub yet."


def is_this_pc(client: str | None, own: Iterable[str | None]) -> bool:
    """True for a visit from this PC itself (loopback or one of its own addresses), or an unknown client."""
    if not client:
        return True
    try:
        ip = ipaddress.ip_address(client)
    except ValueError:
        return True
    mapped = getattr(ip, "ipv4_mapped", None)       # "::ffff:192.168.1.10" on a dual-stack socket
    if mapped is not None:
        ip = mapped
    if ip.is_loopback or ip.is_unspecified:
        return True
    return str(ip) in {a for a in own if a}


def usable_address(address: str | None) -> bool:
    """An address a phone could open: present and not loopback ("localhost", 127.x)."""
    if not address or address.strip().lower() == "localhost":
        return False
    try:
        return not ipaddress.ip_address(address).is_loopback
    except ValueError:
        return True             # a PC name: may work


class PhoneTest:
    def __init__(self, path: Path | None, clock=time.time) -> None:
        self._path = path               # None: kept in memory only (tests, replays)
        self._clock = clock
        self.reached_at: float | None = None      # Unix seconds of the last phone visit
        self._saved_at = 0.0
        self._pending = False           # a visit not written yet (within 10 s of the last write)
        if path is not None:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                at = data.get("at")
                self.reached_at = float(at) / 1000 if at else None
            except FileNotFoundError:
                pass
            except (OSError, ValueError, AttributeError, TypeError) as exc:
                log.warning("Ignoring unreadable %s: %s", path, exc)

    def record(self, client: str | None, own: Iterable[str | None]) -> bool:
        """Note a visit to /hello; True when it came from another device (a phone), not this PC."""
        if is_this_pc(client, own):
            return False
        now = self._clock()
        first = self.reached_at is None
        self.reached_at = now
        if first:
            log.info("A phone reached the hub (phone test)")
        self._pending = True
        self.flush_due()
        return True

    def flush_due(self) -> None:
        """Save a pending visit once 10 s have passed since the last write."""
        if self._pending and self._clock() - self._saved_at >= SAVE_EVERY_S:
            self.flush()

    def flush(self) -> None:
        """Save the latest visit if it isn't saved yet: called when the 10 s window has passed, from the status
        views, and when the hub stops, so the last visit is never lost."""
        if not self._pending or self._path is None or self.reached_at is None:
            self._pending = False
            return
        self._pending = False
        self._saved_at = self._clock()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"at": round(self.reached_at * 1000), "from_phone": True}) + "\n",
                           encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            log.exception("Could not save %s", self._path)

    def status_text(self, today: Callable[[], dt.date] = dt.date.today) -> str:
        if self.reached_at is None:
            return NOT_YET
        at = dt.datetime.fromtimestamp(self.reached_at)
        when = f"{at:%H:%M}" if at.date() == today() else f"{at:%H:%M} on {at:%a} {at.day} {at:%b}"
        return f"A phone reached the hub at {when}"

    def status(self, address: str | None, port: int, qr: Callable[[str], str] | None = None) -> dict[str, Any]:
        """What setup and staff Health show: the test QR (None without a usable address) and the last success."""
        self.flush_due()
        url = f"http://{address}:{port}/hello" if usable_address(address) else None
        return {"url": url, "svg": qr(url) if qr is not None and url else None,
                "reached": self.reached_at is not None,
                "reached_at": round(self.reached_at * 1000) if self.reached_at is not None else None,
                "text": self.status_text(), "problem": None if url else NO_NETWORK,
                "advice": WIFI_ADVICE, "fail_advice": FAIL_ADVICE}
