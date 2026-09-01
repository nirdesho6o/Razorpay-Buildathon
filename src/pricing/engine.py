"""Compose pricing rules, clamp to merchant caps, produce decision + audit."""

import json
from pathlib import Path

from src.catalog.models import CartItem
from src.catalog.store import get_product_by_id
from src.pricing.models import (
    DiscountResult,
    ItemBreakdown,
    NegotiateRequest,
    NegotiationResult,
    PricingPolicy,
)
from src.pricing.rules import bundle_discount, time_decay, volume_tier

_policy: PricingPolicy | None = None

RULE_FUNCTIONS = [bundle_discount, volume_tier, time_decay]


def load_policy(path: str = "data/pricing_policy.json") -> PricingPolicy:
    """Load pricing policy from JSON file."""
    global _policy
    raw = json.loads(Path(path).read_text())
    _policy = PricingPolicy(**raw)
    return _policy


def get_policy() -> PricingPolicy:
    """Return the loaded pricing policy."""
    if not _policy:
        return load_policy()
    return _policy


def compute_price(cart: list[CartItem]) -> tuple[list[ItemBreakdown], int, float]:
    """Evaluate all pricing rules against cart, return breakdown and totals."""
    policy = get_policy()
    breakdowns: list[ItemBreakdown] = []
    computed_total = 0

    for item in cart:
        product = get_product_by_id(item.product_id)
        if not product:
            raise ValueError(f"Product {item.product_id} not found")

        discounts: list[DiscountResult] = []
        total_discount = 0.0

        for rule_fn in RULE_FUNCTIONS:
            result = rule_fn(cart, policy, item.product_id)
            discounts.append(result)
            total_discount += result.discount_pct

        clamped_discount = min(total_discount, policy.max_discount_pct)
        floor_price = int(product.base_price * policy.floor_multiplier)
        final_unit_price = max(
            int(product.base_price * (1 - clamped_discount / 100)),
            floor_price,
        )

        breakdowns.append(ItemBreakdown(
            product_id=item.product_id,
            quantity=item.quantity,
            base_unit_price=product.base_price,
            final_unit_price=final_unit_price,
            discounts_applied=discounts,
        ))
        computed_total += final_unit_price * item.quantity

    actual_discount_pct = 0.0
    base_total = sum(b.base_unit_price * b.quantity for b in breakdowns)
    if base_total > 0:
        actual_discount_pct = round((1 - computed_total / base_total) * 100, 1)

    return breakdowns, computed_total, actual_discount_pct


def negotiate(request: NegotiateRequest) -> tuple[NegotiationResult, dict]:
    """Process a negotiation request and return result + audit payload."""
    policy = get_policy()
    cart_items = [CartItem(product_id=c.product_id, quantity=c.quantity, size=c.size) for c in request.cart]
    breakdowns, computed_total, total_discount_pct = compute_price(cart_items)

    rules_fired = []
    for b in breakdowns:
        for d in b.discounts_applied:
            if d.discount_pct > 0 and d.rule_name not in rules_fired:
                rules_fired.append(d.rule_name)

    floor_total = sum(
        int(get_product_by_id(item.product_id).base_price * policy.floor_multiplier) * item.quantity
        for item in cart_items
        if get_product_by_id(item.product_id)
    )

    if request.proposed_total >= computed_total:
        decision = "accept"
        message = f"Accepted at ₹{computed_total:,}. Your offer of ₹{request.proposed_total:,} qualifies for a {total_discount_pct}% discount."
        next_round = None
    elif request.proposed_total >= floor_total:
        decision = "counter"
        message = (
            f"Your proposed price of ₹{request.proposed_total:,} is below our best offer of ₹{computed_total:,}. "
            f"The price reflects a {total_discount_pct}% discount ({' + '.join(rules_fired)}). "
            f"Would you like to proceed at ₹{computed_total:,}?"
        )
        next_round = request.round + 1 if request.round < policy.rules.concession.max_rounds else None
    else:
        decision = "reject"
        message = f"Your proposed price of ₹{request.proposed_total:,} is below our floor. The minimum possible price is ₹{floor_total:,}."
        next_round = None

    result = NegotiationResult(
        session_id=request.session_id,
        decision=decision,
        computed_total=computed_total,
        breakdown=breakdowns,
        total_discount_pct=total_discount_pct,
        policy_version=policy.version,
        next_round=next_round,
        message=message,
    )

    audit_payload = {
        "round": request.round,
        "proposed_total": request.proposed_total,
        "computed_total": computed_total,
        "decision": decision,
        "rules_evaluated": [fn.__name__ for fn in RULE_FUNCTIONS],
        "rules_fired": rules_fired,
        "total_discount_pct": total_discount_pct,
        "total_items": sum(c.quantity for c in request.cart),
        "policy_version": policy.version,
    }

    return result, audit_payload
