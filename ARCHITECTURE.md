# Architecture reference

## Data models

### Product
```json
{
  "id": "prod_001",
  "name": "Cotton Kurta - Navy",
  "category": "kurta",
  "subcategory": "cotton",
  "sizes": ["S", "M", "L", "XL"],
  "base_price": 899,
  "currency": "INR",
  "inventory": 25,
  "tags": ["cotton", "casual", "navy", "summer"],
  "created_at": "2026-06-15T10:00:00Z",
  "description": "Lightweight cotton kurta, perfect for summer. Navy blue with contrast stitching."
}
```

### PricingPolicy
```json
{
  "version": "v1",
  "rules": {
    "bundle_discount": {
      "enabled": true,
      "min_items": 3,
      "discount_pct": 10.0
    },
    "volume_tier": {
      "enabled": true,
      "tiers": [
        { "min_qty": 5, "discount_pct": 8.0 },
        { "min_qty": 10, "discount_pct": 15.0 }
      ]
    },
    "time_decay": {
      "enabled": true,
      "days_threshold": 30,
      "discount_pct": 5.0
    },
    "concession": {
      "enabled": true,
      "max_rounds": 3,
      "concession_rate": 0.3
    }
  },
  "max_discount_pct": 25.0,
  "floor_multiplier": 0.65,
  "updated_at": "2026-08-01T00:00:00Z"
}
```

`floor_multiplier`: no item can sell below `base_price * floor_multiplier`. This is the hard floor.

`concession_rate`: in negotiation, the merchant agent moves 30% of the gap between current offer and floor per round. After `max_rounds`, final offer is the best computed price — take it or leave it.

### NegotiateRequest
```json
{
  "session_id": "sess_abc123",
  "cart": [
    { "product_id": "prod_001", "quantity": 3, "size": "M" },
    { "product_id": "prod_005", "quantity": 2, "size": "L" }
  ],
  "proposed_total": 3500,
  "round": 1
}
```

### NegotiationResult
```json
{
  "session_id": "sess_abc123",
  "decision": "counter",
  "computed_total": 3825,
  "breakdown": [
    {
      "product_id": "prod_001",
      "quantity": 3,
      "base_unit_price": 899,
      "final_unit_price": 764,
      "discounts_applied": [
        { "rule": "bundle_discount", "discount_pct": 10.0, "reason": "3+ items in cart" },
        { "rule": "volume_tier", "discount_pct": 0.0, "reason": "Below 5-unit threshold" },
        { "rule": "time_decay", "discount_pct": 5.0, "reason": "Product listed 47 days ago" }
      ]
    },
    {
      "product_id": "prod_005",
      "quantity": 2,
      "base_unit_price": 749,
      "final_unit_price": 674,
      "discounts_applied": [
        { "rule": "bundle_discount", "discount_pct": 10.0, "reason": "3+ items in cart" },
        { "rule": "volume_tier", "discount_pct": 0.0, "reason": "Below 5-unit threshold" },
        { "rule": "time_decay", "discount_pct": 0.0, "reason": "Product listed 12 days ago" }
      ]
    }
  ],
  "total_discount_pct": 15.0,
  "policy_version": "v1",
  "next_round": 2,
  "message": "Your proposed price of ₹3,500 is below our best offer of ₹3,825. The price reflects a 15% discount (bundle + time decay). Would you like to proceed at ₹3,825?"
}
```

### CheckoutRequest
```json
{
  "session_id": "sess_abc123",
  "accepted_total": 3825,
  "cart": [
    { "product_id": "prod_001", "quantity": 3, "size": "M" },
    { "product_id": "prod_005", "quantity": 2, "size": "L" }
  ],
  "buyer_info": {
    "name": "AI Buyer Agent",
    "email": "buyer@agent.test",
    "contact": "+919999999999"
  }
}
```

### CheckoutResult
```json
{
  "session_id": "sess_abc123",
  "internal_order_id": "ord_int_001",
  "razorpay_order_id": "order_XXXXXXXXX",
  "payment_link": "https://rzp.io/i/XXXXXXXX",
  "payment_link_id": "plink_XXXXXXXXX",
  "amount": 382500,
  "currency": "INR",
  "status": "created",
  "expires_at": "2026-09-01T12:10:00Z",
  "retry_window_minutes": 10,
  "max_retries": 2
}
```

Note: Razorpay amounts are in paise (smallest currency unit). ₹3,825 = 382500 paise.

### AuditRecord
```json
{
  "id": "aud_001",
  "timestamp": "2026-09-01T12:00:01Z",
  "session_id": "sess_abc123",
  "event_type": "negotiate_decision",
  "payload": {
    "round": 1,
    "proposed_total": 3500,
    "computed_total": 3825,
    "decision": "counter",
    "rules_evaluated": ["bundle_discount", "volume_tier", "time_decay"],
    "rules_fired": ["bundle_discount", "time_decay"],
    "total_discount_pct": 15.0,
    "policy_version": "v1"
  }
}
```

## API endpoints detail

### GET /catalog
Returns all products. No auth required.

### GET /catalog/search?q={natural_language_query}
The `q` param is natural language from the buyer agent (e.g., "cotton kurtas under 1000 in medium").
Server-side: call Claude API to extract structured filters from the query, then filter product list.
Return matching products sorted by relevance.

LLM filter extraction prompt:
```
Extract structured filters from this shopping query. Return JSON only.
Query: "{q}"
Schema: { "category": str|null, "subcategory": str|null, "max_price": int|null, "min_price": int|null, "sizes": list[str]|null, "tags": list[str]|null }
```

### GET /catalog/{product_id}
Returns single product with full details including pricing bounds (floor price computed from policy).

### GET /pricing-policy
Returns the merchant's pricing policy. Machine-readable. The buyer agent can inspect available discounts before negotiating.

### POST /negotiate
Body: NegotiateRequest
Returns: NegotiationResult

Flow:
1. Validate cart (all product_ids exist, quantities available)
2. Compute base total from catalog prices
3. Run each enabled pricing rule against cart
4. Compose discounts (additive), clamp to max_discount_pct
5. Compute final price per item, ensure above floor
6. Compare buyer's proposed total against computed total
7. Return accept/counter/reject with full breakdown
8. Log AuditRecord

### POST /checkout
Body: CheckoutRequest
Returns: CheckoutResult

Flow:
1. Verify session has an accepted negotiation result
2. Create Razorpay order via Orders API:
   ```python
   client.order.create({
       "amount": amount_in_paise,
       "currency": "INR",
       "receipt": internal_order_id,
       "notes": {"session_id": session_id}
   })
   ```
3. Create payment link via Payment Links API:
   ```python
   client.payment_link.create({
       "amount": amount_in_paise,
       "currency": "INR",
       "description": f"Order {internal_order_id}",
       "customer": buyer_info,
       "notify": {"email": True},
       "callback_url": webhook_url,
       "callback_method": "get"
   })
   ```
4. Store order state in SQLite (status: created)
5. Log AuditRecord (event: order_created)
6. Return checkout result with payment link

### POST /webhook
Razorpay sends webhook events here.

Handle:
- `payment.authorized` → capture payment via `client.payment.capture(payment_id, amount)`
- `payment.captured` → update order status to "paid", log success, decrement inventory
- `payment.failed` → increment retry counter, if retries < max hold order, else expire order
- `order.paid` → final confirmation

Validate signature:
```python
client.utility.verify_webhook_signature(
    request.body,
    signature_header,
    webhook_secret
)
```

### GET /orders/{order_id}
Returns current order status, payment attempts, and associated audit records.

### GET /audit-trail/{session_id}
Returns all audit records for a session, chronologically ordered.

## Razorpay test mode specifics

- Test key IDs start with `rzp_test_`
- Test card: 4111 1111 1111 1111, any future expiry, any CVV
- Test UPI: success@razorpay (succeeds), failure@razorpay (fails)
- Webhooks in test mode: set up via Dashboard → Settings → Webhooks (separate URL for test/live)
- For local dev, use ngrok or similar to expose webhook endpoint
- No real money is deducted in test mode

## Buyer agent design

The buyer agent is a Claude-powered script that:

1. Receives a shopping task as a string (e.g., "Buy 5 cotton kurtas under ₹4000")
2. Calls GET /catalog/search with the task as query
3. Evaluates results, selects items, builds a cart
4. Calls GET /pricing-policy to understand available discounts
5. Computes a proposed price (budget-aware, informed by policy)
6. Calls POST /negotiate with cart + proposed price
7. If counter: adjusts proposal and retries (up to 3 rounds)
8. If accept: calls POST /checkout
9. "Pays" via the payment link (simulated in test mode)
10. Polls GET /orders/{id} until confirmed or failed

The agent uses Claude's tool-use / function-calling with these tools defined:
- `search_catalog(query: str) -> list[Product]`
- `get_pricing_policy() -> PricingPolicy`
- `negotiate(cart: list, proposed_total: int) -> NegotiationResult`
- `checkout(cart: list, accepted_total: int) -> CheckoutResult`
- `check_order(order_id: str) -> OrderStatus`

System prompt for the buyer agent:
```
You are an AI buying agent. Your task is to complete a purchase within the given budget.

You have access to a merchant's catalog and pricing APIs. Your goal:
1. Search for products matching the shopping task
2. Build a cart that fits the budget
3. Negotiate for the best price — start with your budget as the proposed price
4. If countered, decide whether to accept or re-propose (you have 3 rounds max)
5. Complete checkout once a price is agreed

Be strategic but honest about your budget. The pricing system rewards truthful reporting.
Always log your reasoning for each decision.
```

## Demo script flow

```
=== MerchantAgent Demo ===

Shopping task: "Buy 5 cotton kurtas under ₹4000"

[1] Searching catalog...
    Found 6 matching products

[2] Building cart...
    Selected: 3x Cotton Kurta Navy (₹899 ea) + 2x Cotton Kurta Olive (₹749 ea)
    Base total: ₹4,195

[3] Checking pricing policy...
    Available discounts: bundle (10%), volume tier (8% at 5+), time decay (5%)

[4] Negotiating — Round 1
    Proposed: ₹3,500
    Result: COUNTER at ₹3,825 (bundle 10% + time decay 5% applied)

[5] Negotiating — Round 2
    Proposed: ₹3,825 (accepted counter offer)
    Result: ACCEPT at ₹3,825

[6] Creating Razorpay order...
    Order ID: order_XXXXXXXXX
    Payment link: https://rzp.io/i/XXXXXXXX

[7] Processing payment...
    Attempt 1: FAILED (simulated)
    Retrying in 3s... (price locked, order held)
    Attempt 2: SUCCESS

[8] Payment confirmed via webhook
    Status: paid
    Inventory updated

=== Audit Trail ===
┌──────────────────────┬────────────────────┬─────────────────────────────────────┐
│ Timestamp            │ Event              │ Details                             │
├──────────────────────┼────────────────────┼─────────────────────────────────────┤
│ 12:00:01             │ catalog_search     │ query="cotton kurtas under 4000"    │
│ 12:00:02             │ negotiate_request  │ round=1, proposed=3500              │
│ 12:00:02             │ negotiate_decision │ counter, computed=3825, rules=2     │
│ 12:00:03             │ negotiate_request  │ round=2, proposed=3825              │
│ 12:00:03             │ negotiate_decision │ accept, final=3825                  │
│ 12:00:04             │ order_created      │ rzp_order=order_XXX, amount=382500  │
│ 12:00:05             │ payment_attempted  │ attempt=1, status=failed            │
│ 12:00:08             │ payment_attempted  │ attempt=2, status=captured          │
│ 12:00:08             │ order_completed    │ payment_id=pay_XXX                  │
└──────────────────────┴────────────────────┴─────────────────────────────────────┘
```

## SSE endpoint — GET /events

Server-Sent Events stream for the live dashboard. Each event is a JSON object on a `data:` line.

Content-Type: `text/event-stream`
Connection: kept alive, no timeout

### SSE event schema

Every event pushed to SSE has this shape:

```json
{
  "event_type": "negotiate_decision",
  "timestamp": "2026-09-01T12:00:02Z",
  "session_id": "sess_abc123",
  "display": {
    "actor": "merchant",
    "summary": "Counter: ₹3,825 (bundle 10% + time decay 5%)",
    "phase": "negotiating"
  },
  "payload": { ... }
}
```

The `display` object is specifically for the frontend — pre-formatted so the dashboard doesn't need to parse raw payloads:

- `actor`: `"buyer"` | `"merchant"` | `"system"` — determines which side the chat bubble appears on and its color
- `summary`: human-readable one-liner for the chat bubble
- `phase`: `"searching"` | `"negotiating"` | `"checkout"` | `"paying"` | `"complete"` | `"failed"` — drives the bottom status pipeline

### Event types and their display mappings

| event_type | actor | phase | example summary |
|---|---|---|---|
| `catalog_search` | buyer | searching | "Searching for cotton kurtas under ₹4000..." |
| `catalog_results` | merchant | searching | "Found 6 matching products" |
| `negotiate_request` | buyer | negotiating | "Proposing ₹3,500 for 5 items" |
| `negotiate_decision` | merchant | negotiating | "Counter: ₹3,825 (bundle + time decay)" |
| `negotiate_accept` | buyer | negotiating | "Accepting ₹3,825" |
| `order_created` | merchant | checkout | "Order created: order_XXXX" |
| `payment_link_created` | merchant | checkout | "Payment link generated" |
| `payment_attempted` | system | paying | "Payment attempt 1..." |
| `payment_failed` | system | paying | "Payment failed — retrying in 3s" |
| `payment_succeeded` | system | paying | "Payment captured: pay_XXXX" |
| `order_completed` | system | complete | "Order complete — inventory updated" |
| `order_expired` | system | failed | "Order expired after max retries" |

### Implementation in audit logger

When the audit logger writes a record to SQLite, it also constructs the `display` object and pushes the full event to all SSE subscriber queues. The display formatting logic lives in the audit logger, not the frontend — the frontend just renders what it receives.

```python
# In audit/logger.py — called after every SQLite insert
def _make_display(event_type: str, payload: dict) -> dict:
    """Map raw audit event to frontend display fields."""
    mappings = {
        "catalog_search": ("buyer", "searching", f"Searching for {payload.get('query', '...')}"),
        "negotiate_request": ("buyer", "negotiating", f"Proposing ₹{payload.get('proposed_total', 0):,} for {payload.get('total_items', 0)} items"),
        "negotiate_decision": ("merchant", "negotiating", _format_negotiation(payload)),
        "order_created": ("merchant", "checkout", f"Order created: {payload.get('razorpay_order_id', '')}"),
        "payment_attempted": ("system", "paying", f"Payment attempt {payload.get('attempt', 1)}..."),
        "payment_failed": ("system", "paying", f"Payment failed — retrying in {payload.get('retry_delay', 3)}s"),
        "payment_succeeded": ("system", "paying", f"Payment captured: {payload.get('payment_id', '')}"),
        "order_completed": ("system", "complete", "Order complete — inventory updated"),
    }
    actor, phase, summary = mappings.get(event_type, ("system", "searching", event_type))
    return {"actor": actor, "summary": summary, "phase": phase}
```

### Static file serving

```python
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Serve dashboard at /dashboard
@app.get("/dashboard")
async def dashboard():
    return FileResponse("frontend/index.html")
```
