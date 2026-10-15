"""Bad-name filter for self check-in (guests type their own name on their phone; staff-entered names are trusted).

Whole words only, so "Scunthorpe" or "Dickson" pass. Case-insensitive; simple leetspeak (0 1 3 4 5 @ $) is read as
letters; single letters spread with spaces or dots ("f u c k") are joined; stretched letters ("fuuuck") are squeezed.
A few real names (Lauda, Dick) are allowed as whole words. Cafes add their own words with [checkin] blocked_words.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

# A small default list: common English and Hindi/Hinglish profanity, slurs and a few obvious troll names.
DEFAULT_BLOCKED = frozenset("""
fuck fucker fucking fucked motherfucker shit shitty bullshit bitch bastard asshole ass arse cunt dick dickhead cock
pussy slut whore wank wanker twat piss cum porn sex nigger nigga fag faggot retard rape rapist nazi hitler penis
vagina boob boobs tits niga fagot pusy ashole bulshit shity
madarchod maderchod bhenchod behenchod bhosdike bhosdika bsdk chutiya chutiye chut gandu gaandu gaand
raand harami haramkhor kutta kamina lauda lawda loda lodu
""".split())

# Real names that a blocked word matches: whole words only, checked before the list ("Niki Lauda", "Dick Smith").
# A cafe that adds one of these to its own blocked_words blocks it after all.
ALLOWED = frozenset({"lauda", "dick"})

_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "@": "a", "$": "s"})
_TOKEN = re.compile(r"[a-z]+")
_REPEATS = re.compile(r"(.)\1+")


def _squeeze(word: str) -> str:
    return _REPEATS.sub(r"\1", word)


def _forms(text: str) -> set[str]:
    """Every word in the text, plus runs of single letters joined into one word."""
    folded = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    tokens = _TOKEN.findall(folded.casefold().translate(_LEET))
    words = set(tokens)
    run = ""
    for token in tokens + [""]:
        if len(token) == 1:
            run += token
            continue
        if len(run) > 1:
            words.add(run)
        run = ""
    return words


def is_blocked(name: str, extra: Iterable[str] = ()) -> bool:
    own = {w.strip().casefold().translate(_LEET) for w in extra if w and w.strip()}
    blocked = DEFAULT_BLOCKED | own
    allowed = ALLOWED - own
    for word in _forms(name):
        if word in allowed:
            continue
        # "fuuuck" -> "fuck": only the typed word is squeezed, list entries are compared as written
        if word in blocked or (len(word) >= 4 and _squeeze(word) in blocked):
            return True
    return False
