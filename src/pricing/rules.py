"""Individual pricing rule functions."""

from datetime import datetime, timezone

from src.catalog.models import CartItem
from src.catalog.store import get_product_by_id
from src.pricing.models import DiscountResult, PricingPolicy


def bundle_discount(cart: list[CartItem], policy: PricingPolicy, product_id: str) -> DiscountResult:
    """Apply bundle discount if cart has enough distinct products."""
    rule = policy.rules.bundle_discount
    if not rule.enabled:
        return DiscountResult(rule_name="bundle_discount", discount_pct=0.0, reason="Rule disabled")

    distinct_items = len(set(item.product_id for item in cart))
    if distinct_items >= rule.min_distinct_items:
        return DiscountResult(
            rule_name="bundle_discount",
            discount_pct=rule.discount_pct,
            reason=f"{distinct_items} distinct items in cart (min {rule.min_distinct_items})",
        )
    return DiscountResult(
        rule_name="bundle_discount",
        discount_pct=0.0,
        reason=f"Only {distinct_items} distinct items (need {rule.min_distinct_items}+)",
    )


def volume_tier(cart: list[CartItem], policy: PricingPolicy, product_id: str) -> DiscountResult:
    """Apply volume discount based on total item count."""
    rule = policy.rules.volume_tier
    if not rule.enabled:
        return DiscountResult(rule_name="volume_tier", discount_pct=0.0, reason="Rule disabled")

    total_qty = sum(item.quantity for item in cart)
    applicable_tier = None
    for tier in sorted(rule.tiers, key=lambda t: t.min_qty, reverse=True):
        if total_qty >= tier.min_qty:
            applicable_tier = tier
            break

    if applicable_tier:
        return DiscountResult(
            rule_name="volume_tier",
            discount_pct=applicable_tier.discount_pct,
            reason=f"{total_qty} total items (tier: {applicable_tier.min_qty}+)",
        )
    return DiscountResult(
        rule_name="volume_tier",
        discount_pct=0.0,
        reason=f"{total_qty} total items — below minimum tier",
    )


def time_decay(cart: list[CartItem], policy: PricingPolicy, product_id: str) -> DiscountResult:
    """Apply time decay discount for older listings."""
    rule = policy.rules.time_decay
    if not rule.enabled:
        return DiscountResult(rule_name="time_decay", discount_pct=0.0, reason="Rule disabled")

    product = get_product_by_id(product_id)
    if not product:
        return DiscountResult(rule_name="time_decay", discount_pct=0.0, reason="Product not found")

    days_listed = (datetime.now(timezone.utc) - product.created_at).days
    if days_listed >= rule.days_threshold:
        return DiscountResult(
            rule_name="time_decay",
            discount_pct=rule.discount_pct,
            reason=f"Product listed {days_listed} days ago (threshold: {rule.days_threshold})",
        )
    return DiscountResult(
        rule_name="time_decay",
        discount_pct=0.0,
        reason=f"Product listed {days_listed} days ago (need {rule.days_threshold}+)",
    )
