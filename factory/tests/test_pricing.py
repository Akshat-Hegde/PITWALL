import pytest

from factory import pricing
from factory.pricing import breakdown, format_inr, retail_price, upgrade_price


@pytest.mark.parametrize("rigs, price", [(1, 20_000), (3, 20_000), (4, 20_000), (5, 25_000), (6, 30_000),
                                         (24, 120_000)])
def test_retail_price(rigs, price):
    assert retail_price(rigs) == price
    assert retail_price(rigs, "9t7") == price


def test_unbranded_has_no_default_price():
    assert retail_price(6, "unbranded") is None


@pytest.mark.parametrize("bad", [0, -1, True, "6", 4.0])
def test_retail_price_refuses_nonsense(bad):
    with pytest.raises(ValueError):
        retail_price(bad)


@pytest.mark.parametrize("old, new, price", [(4, 6, 10_000), (6, 8, 10_000), (2, 6, 10_000), (2, 4, 0),
                                             (6, 4, 0), (5, 5, 0), (4, 5, 5_000)])
def test_upgrade_price(old, new, price):
    assert upgrade_price(old, new) == price


def test_upgrade_price_refuses_nonsense():
    with pytest.raises(ValueError):
        upgrade_price(0, 4)


def test_breakdown_9t7_with_discount():
    b = breakdown(6, 27_000)
    assert (b.base, b.base_rigs, b.extra_rigs, b.extra_rig_price, b.extra_total) == (20_000, 4, 2, 5_000, 10_000)
    assert (b.list_price, b.discount, b.other, b.total) == (30_000, 3_000, 0, 27_000)


def test_breakdown_9t7_list_price_and_extras_priced_by_hand():
    assert breakdown(4, 20_000).discount == 0 and breakdown(4, 20_000).extra_rigs == 0
    b = breakdown(4, 26_000)                     # e.g. an extra game priced by hand
    assert (b.discount, b.other, b.total) == (0, 6_000, 26_000)


def test_breakdown_unbranded_is_only_the_agreed_price():
    b = breakdown(6, 45_000, "unbranded")
    assert b.total == 45_000 and b.base is None and b.list_price is None and b.discount == 0


@pytest.mark.parametrize("bad", [-1, None, True, 1.5])
def test_breakdown_refuses_bad_price(bad):
    with pytest.raises(ValueError):
        breakdown(4, bad)


@pytest.mark.parametrize("amount, text", [(0, "₹0"), (500, "₹500"), (5_000, "₹5,000"), (20_000, "₹20,000"),
                                          (125_000, "₹1,25,000"), (12_345_678, "₹1,23,45,678"),
                                          (-3_000, "-₹3,000")])
def test_format_inr_indian_grouping(amount, text):
    assert format_inr(amount) == text


def test_constants_match_the_spec():
    assert (pricing.BASE_PRICE_INR, pricing.BASE_RIGS, pricing.EXTRA_RIG_INR) == (20_000, 4, 5_000)
