"""Prices for cafe licences (spec F6). Whole rupees, no paise.

- 9T7 variant: ₹20,000 including 4 rigs, plus ₹5,000 for each rig after that. The factory fills this in and the
  seller may change it (a discount).
- Unbranded variant: no default; the seller types the agreed price.
- Add-on rigs (an upgrade code): ₹5,000 for each rig added beyond the 4 the base price covers.
- Add-on games and features have no list price: the seller types their price by hand.

The certificate (factory/docs.py) shows `breakdown()`.
"""

from __future__ import annotations

from dataclasses import dataclass

BASE_PRICE_INR = 20_000
BASE_RIGS = 4
EXTRA_RIG_INR = 5_000

VARIANTS = ("9t7", "unbranded")


def _extra_rigs(rigs: int) -> int:
    return max(0, rigs - BASE_RIGS)


def retail_price(rigs: int, variant: str = "9t7") -> int | None:
    """The list price for a cafe with `rigs` rigs; None for the unbranded variant (the seller types the price)."""
    if variant != "9t7":
        return None
    if isinstance(rigs, bool) or not isinstance(rigs, int) or rigs < 1:
        raise ValueError("a cafe has at least 1 rig")
    return BASE_PRICE_INR + _extra_rigs(rigs) * EXTRA_RIG_INR


def upgrade_price(old_rigs: int, new_rigs: int) -> int:
    """The list price of adding rigs to a 9T7 licence: ₹5,000 for each new rig beyond the 4 the base price covers.
    Going from 2 to 6 rigs costs 2 rigs (rigs 3 and 4 were already paid for); fewer rigs cost nothing."""
    for n in (old_rigs, new_rigs):
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise ValueError("a cafe has at least 1 rig")
    return max(0, _extra_rigs(new_rigs) - _extra_rigs(old_rigs)) * EXTRA_RIG_INR


@dataclass(frozen=True)
class Breakdown:
    """The certificate's price lines. For an unbranded licence only `total` is set (a custom price)."""

    total: int
    base: int | None = None              # ₹20,000
    base_rigs: int | None = None         # 4
    extra_rigs: int = 0                  # rigs beyond the base
    extra_rig_price: int = EXTRA_RIG_INR
    extra_total: int = 0                 # extra_rigs × ₹5,000
    discount: int = 0                    # list price − agreed price, when the agreed price is lower
    other: int = 0                       # agreed price − list price, when higher (add-ons priced by hand)

    @property
    def list_price(self) -> int | None:
        return None if self.base is None else self.base + self.extra_total


def breakdown(rigs: int, price_inr: int, variant: str = "9t7") -> Breakdown:
    """Base, extra rigs, discount (or hand-priced extras) and the total for an agreed `price_inr`."""
    if isinstance(price_inr, bool) or not isinstance(price_inr, int) or price_inr < 0:
        raise ValueError("the price must be a whole number of rupees, 0 or more")
    listed = retail_price(rigs, variant)
    if listed is None:
        return Breakdown(total=price_inr)
    extra = _extra_rigs(rigs)
    return Breakdown(total=price_inr, base=BASE_PRICE_INR, base_rigs=BASE_RIGS, extra_rigs=extra,
                     extra_total=extra * EXTRA_RIG_INR, discount=max(0, listed - price_inr),
                     other=max(0, price_inr - listed))


def format_inr(amount: int) -> str:
    """₹1,25,000: Indian digit grouping (the last three digits, then pairs)."""
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ValueError("an amount in whole rupees")
    sign, digits = ("-", str(-amount)) if amount < 0 else ("", str(amount))
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return f"{sign}₹" + ",".join(groups + [tail])
