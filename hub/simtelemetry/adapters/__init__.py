"""Game adapters. Each adapter turns raw game packets into the core model.

Each adapter class has a `game_id`: the id licences and cafe profiles use for its game ("f1_25"). `registry()`
lists the adapters that exist, so the factory offers only games this build can read, and the hub drops the packets
of a game the licence doesn't include (Hub.on_datagram).
"""

from __future__ import annotations

from typing import Any


def registry() -> dict[str, type]:
    """Game id -> adapter class, for every game this build can read."""
    from .f1.adapter import F1Adapter
    return {F1Adapter.game_id: F1Adapter}


def game_id(adapter: Any) -> str | None:
    """The licence game id of an adapter instance (None for an adapter without one)."""
    return getattr(adapter, "game_id", None)
