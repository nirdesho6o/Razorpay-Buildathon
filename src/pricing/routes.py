"""Pricing and negotiation API routes."""

from fastapi import APIRouter

from src.audit.logger import log_event
from src.pricing.engine import get_policy, negotiate
from src.pricing.models import NegotiateRequest, NegotiationResult, PricingPolicy

router = APIRouter(tags=["pricing"])


@router.get("/pricing-policy", response_model=PricingPolicy)
async def pricing_policy():
    """Return the merchant's pricing policy."""
    return get_policy()


@router.post("/negotiate", response_model=NegotiationResult)
async def negotiate_price(request: NegotiateRequest):
    """Process a negotiation request."""
    await log_event(request.session_id, "negotiate_request", {
        "proposed_total": request.proposed_total,
        "round": request.round,
        "total_items": sum(c.quantity for c in request.cart),
        "cart": [c.model_dump() for c in request.cart],
    })

    result, audit_payload = negotiate(request)

    await log_event(request.session_id, "negotiate_decision", audit_payload)

    return result
