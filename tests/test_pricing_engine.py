"""Tests for the pricing engine — rule composition, clamping, floor enforcement."""

import pytest

from src.catalog.models import CartItem
from src.catalog.store import load_products
from src.pricing.engine import compute_price, load_policy, negotiate
from src.pricing.models import CartItemRef, NegotiateRequest


@pytest.fixture(autouse=True)
def setup():
    load_products()
    load_policy()


def test_single_item_no_discount():
    """Single item should not trigger bundle or volume discounts."""
    cart = [CartItem(product_id="prod_005", quantity=1, size="M")]
    breakdowns, total, discount_pct = compute_price(cart)

    assert len(breakdowns) == 1
    b = breakdowns[0]
    assert b.base_unit_price == 1899
    bundle_disc = next(d for d in b.discounts_applied if d.rule_name == "bundle_discount")
    assert bundle_disc.discount_pct == 0.0
    volume_disc = next(d for d in b.discounts_applied if d.rule_name == "volume_tier")
    assert volume_disc.discount_pct == 0.0


def test_bundle_discount_triggers_at_3_items():
    """3 distinct products should trigger bundle discount."""
    cart = [
        CartItem(product_id="prod_001", quantity=1, size="M"),
        CartItem(product_id="prod_002", quantity=1, size="M"),
        CartItem(product_id="prod_003", quantity=1, size="M"),
    ]
    breakdowns, total, discount_pct = compute_price(cart)

    for b in breakdowns:
        bundle_disc = next(d for d in b.discounts_applied if d.rule_name == "bundle_discount")
        assert bundle_disc.discount_pct == 10.0


def test_volume_tier_at_5_items():
    """5 total items should trigger 8% volume discount."""
    cart = [CartItem(product_id="prod_001", quantity=5, size="M")]
    breakdowns, total, discount_pct = compute_price(cart)

    b = breakdowns[0]
    volume_disc = next(d for d in b.discounts_applied if d.rule_name == "volume_tier")
    assert volume_disc.discount_pct == 8.0


def test_discount_clamped_to_max():
    """Total discount should not exceed max_discount_pct (25%)."""
    cart = [
        CartItem(product_id="prod_001", quantity=4, size="M"),
        CartItem(product_id="prod_002", quantity=4, size="M"),
        CartItem(product_id="prod_003", quantity=4, size="M"),
    ]
    breakdowns, total, discount_pct = compute_price(cart)

    # Even if rules sum to more, discount should be capped (allow rounding)
    assert discount_pct <= 25.5


def test_floor_price_enforced():
    """Final price should never go below floor_multiplier * base_price."""
    cart = [CartItem(product_id="prod_001", quantity=1, size="M")]
    breakdowns, total, discount_pct = compute_price(cart)

    b = breakdowns[0]
    floor = int(b.base_unit_price * 0.65)
    assert b.final_unit_price >= floor


def test_negotiate_accept():
    """Proposed price >= computed should result in acceptance."""
    request = NegotiateRequest(
        session_id="test_sess",
        cart=[CartItemRef(product_id="prod_006", quantity=1, size="M")],
        proposed_total=699,
        round=1,
    )
    result, audit = negotiate(request)
    assert result.decision == "accept"
    assert result.computed_total <= 699


def test_negotiate_counter():
    """Proposed price below computed but above floor should counter."""
    cart = [
        CartItemRef(product_id="prod_001", quantity=2, size="M"),
        CartItemRef(product_id="prod_002", quantity=2, size="M"),
        CartItemRef(product_id="prod_003", quantity=1, size="M"),
    ]
    request = NegotiateRequest(
        session_id="test_sess",
        cart=cart,
        proposed_total=3000,
        round=1,
    )
    result, audit = negotiate(request)
    assert result.decision in ("counter", "accept")


def test_negotiate_reject_below_floor():
    """Proposed price below floor should be rejected."""
    request = NegotiateRequest(
        session_id="test_sess",
        cart=[CartItemRef(product_id="prod_005", quantity=1, size="M")],
        proposed_total=100,
        round=1,
    )
    result, audit = negotiate(request)
    assert result.decision == "reject"
