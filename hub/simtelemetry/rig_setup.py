"""The F1 25 telemetry settings every rig needs (U1), written once.

The setup page, the staff page's Health tab (both through `api.pages.render_page`) and the factory's setup guide all
take the words from here, so they never drift apart. The labels are the game's own, quoted word for word.
"""

from __future__ import annotations

GAME = "F1 25"
MENU = "Game Options › Settings › UDP Telemetry Settings"
HUB_ADDRESS = "the hub PC's address"          # what to type, when the real address isn't known (printed guides)
PORT = 20777                                  # hub.toml [network] udp_port's default
SEND_RATE = "20Hz"
FORMAT = "2025"
RESTRICTED_NOTE = "Your Telemetry may stay Restricted."
SAME_PC_NOTE = "A rig on the hub PC also uses the hub's address, not 127.0.0.1."


def settings(address: str = HUB_ADDRESS, port: int | str = PORT) -> tuple[tuple[str, str], ...]:
    """(label, value) for each setting, in the game's order."""
    return (("UDP Telemetry", "On"), ("UDP Broadcast Mode", "Off"), ("UDP IP Address", address),
            ("UDP Port", str(port)), ("UDP Send Rate", SEND_RATE), ("UDP Format", FORMAT))


def sentence(address: str = HUB_ADDRESS, port: int | str = PORT) -> str:
    """"Game Options › Settings › UDP Telemetry Settings: UDP Telemetry On, ..., UDP Format 2025." (U1)"""
    parts = [f"{label} = {value}" if label == "UDP IP Address" else f"{label} {value}"
             for label, value in settings(address, port)]
    return f"{MENU}: " + ", ".join(parts) + "."


# The sentence around the address and the port, for pages that fill those in live.
_ADDRESS, _PORT = "\x00address\x00", "\x00port\x00"
BEFORE_ADDRESS, _rest = sentence(_ADDRESS, _PORT).split(_ADDRESS)
BEFORE_PORT, AFTER_PORT = _rest.split(_PORT)
del _rest


def page_fill() -> dict[str, str]:
    """{{RIG_SETUP_...}} placeholders for the hub's HTML pages (plain text: none of it needs escaping)."""
    return {"RIG_SETUP_GAME": GAME, "RIG_SETUP_BEFORE_ADDRESS": BEFORE_ADDRESS, "RIG_SETUP_BEFORE_PORT": BEFORE_PORT,
            "RIG_SETUP_AFTER_PORT": AFTER_PORT, "RIG_SETUP_RESTRICTED": RESTRICTED_NOTE}
