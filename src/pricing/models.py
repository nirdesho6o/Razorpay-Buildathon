from datetime import datetime

from pydantic import BaseModel


class VolumeTier(BaseModel):
    min_qty: int
    discount_pct: float


class BundleDiscountRule(BaseModel):
    enabled: bool
    min_distinct_items: int
    discount_pct: float
    description: str


class VolumeTierRule(BaseModel):
    enabled: bool
    tiers: list[VolumeTier]
    description: str


class TimeDecayRule(BaseModel):
    enabled: bool
    days_threshold: int
    discount_pct: float
    description: str


class ConcessionRule(BaseModel):
    enabled: bool
    max_rounds: int
    concession_rate: float
    description: str


class PricingRules(BaseModel):
    bundle_discount: BundleDiscountRule
    volume_tier: VolumeTierRule
    time_decay: TimeDecayRule
    concession: ConcessionRule


class PricingPolicy(BaseModel):
    version: str
    rules: PricingRules
    max_discount_pct: float
    floor_multiplier: float
    updated_at: datetime


class DiscountResult(BaseModel):
    rule_name: str
    discount_pct: float
    reason: str


class ItemBreakdown(BaseModel):
    product_id: str
    quantity: int
    base_unit_price: int
    final_unit_price: int
    discounts_applied: list[DiscountResult]


class NegotiateRequest(BaseModel):
    session_id: str
    cart: list["CartItemRef"]
    proposed_total: int
    round: int = 1


class CartItemRef(BaseModel):
    product_id: str
    quantity: int
    size: str


class NegotiationResult(BaseModel):
    session_id: str
    decision: str  # "accept" | "counter" | "reject"
    computed_total: int
    breakdown: list[ItemBreakdown]
    total_discount_pct: float
    policy_version: str
    next_round: int | None = None
    message: str


class AuditRecord(BaseModel):
    id: str
    timestamp: datetime
    session_id: str
    event_type: str
    payload: dict
