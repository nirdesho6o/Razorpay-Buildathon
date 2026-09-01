# MerchantAgent — Agentic Commerce on Razorpay

## What this is

A buildathon submission for Razorpay AI Buildathon 2026, Track 01 (AI Growth & Agentic Commerce).

An end-to-end demo where an AI buyer agent discovers products from a merchant's structured catalog, negotiates a price within merchant-defined rules, and completes checkout via Razorpay test-mode APIs — with no human in the loop. Every pricing decision and payment action is logged in an audit trail.

## Project structure

```
merchantagent/
├── CLAUDE.md                  # You are here
├── ARCHITECTURE.md            # System design, API contracts, data models
├── requirements.txt
├── .env.example               # RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, ANTHROPIC_API_KEY
├── src/
│   ├── __init__.py
│   ├── main.py                # FastAPI app entry point
│   ├── catalog/
│   │   ├── __init__.py
│   │   ├── models.py          # Product, CartItem, CatalogSearchQuery pydantic models
│   │   ├── store.py           # Load/query product data from JSON seed file
│   │   └── routes.py          # GET /catalog, GET /catalog/search, GET /catalog/{id}
│   ├── pricing/
│   │   ├── __init__.py
│   │   ├── models.py          # PricingPolicy, PricingRule, NegotiationResult, AuditRecord
│   │   ├── rules.py           # Individual rule functions (bundle, volume, time_decay, concession)
│   │   ├── engine.py          # Compose rules, clamp to merchant caps, produce decision + audit
│   │   └── routes.py          # GET /pricing-policy, POST /negotiate
│   ├── checkout/
│   │   ├── __init__.py
│   │   ├── models.py          # Order, PaymentAttempt, WebhookEvent
│   │   ├── razorpay_client.py # Wrapper around razorpay-python SDK
│   │   ├── order_manager.py   # Create order, handle payment lifecycle, retry logic
│   │   └── routes.py          # POST /checkout, POST /webhook, GET /orders/{id}
│   ├── audit/
│   │   ├── __init__.py
│   │   └── logger.py          # Append-only audit log (list of AuditRecord dicts, SQLite backed)
│   └── buyer_agent/
│       ├── __init__.py
│       └── agent.py           # LLM-powered buyer: takes shopping task, calls catalog/negotiate/checkout
├── data/
│   ├── products.json          # Seed catalog (~15 products, apparel store)
│   └── pricing_policy.json    # Merchant's pricing rules config
├── demo/
│   └── run_demo.py            # Scripted end-to-end demo (buyer agent executes a shopping task)
├── frontend/
│   └── index.html             # Single-file live dashboard (vanilla JS, no build step)
└── tests/
    ├── test_pricing_engine.py
    └── test_checkout_flow.py
```

## Tech stack

- **Python 3.11+**
- **FastAPI** — backend framework
- **uvicorn** — ASGI server
- **razorpay** — official Python SDK for Razorpay APIs (test mode)
- **anthropic** — Claude API SDK for the buyer agent's LLM calls
- **pydantic** — data validation and models
- **SQLite** (via stdlib sqlite3) — audit log and order state persistence
- **httpx** — buyer agent's HTTP calls to the catalog/pricing/checkout APIs
- **python-dotenv** — env var management

Frontend is a single `index.html` — vanilla HTML/CSS/JS, no build step, no npm. Served as a static file by FastAPI. Connects to the backend via Server-Sent Events (SSE) for live updates.

## Key design decisions

### Catalog
- Products stored in `data/products.json`. Load into memory on startup.
- Search endpoint: buyer agent sends natural language query → LLM (Claude) translates to structured filters (category, price range, size) → filter against product list → return matches as JSON.
- Keep it simple. No vector DB, no embeddings. Keyword + LLM filter translation is enough for 15 products.

### Pricing engine
- Pricing rules are Python functions with signature: `(cart: Cart, policy: PricingPolicy) -> DiscountResult`
- Each `DiscountResult` has: `discount_pct: float`, `reason: str`, `rule_name: str`
- Rules compose additively: sum all applicable discount percentages, clamp to `policy.max_discount_pct`
- Final price = base_price * (1 - clamped_discount)
- Price must stay above `policy.floor_price` for each item
- Every invocation produces an `AuditRecord` with: timestamp, cart hash, rules evaluated, rules fired, discounts applied, final price, policy version

### Negotiation flow
- Buyer agent POSTs to `/negotiate` with cart items + proposed total price
- Engine computes best price the buyer qualifies for
- If proposed >= computed: ACCEPT (buyer offered more than the best price — accept at computed price)
- If proposed < computed but above floor: COUNTER with computed price
- If proposed < floor: REJECT
- This is not "mechanism design" — it's a configurable rule system. But the structure is clean: the buyer's best move is to state their real budget because the mechanism already gives them the best qualifying price.

### Razorpay integration
- Use `razorpay` Python SDK
- Test mode only — no real money
- Flow: create order (Orders API) → generate payment link (Payment Links API) → buyer agent "pays" → webhook confirms (payment.captured / payment.failed)
- **Failure handling**: if payment fails, hold order for 10 min with price lock, allow 2 retries, then release. Log every attempt.
- Webhook endpoint at POST /webhook validates signature using `client.utility.verify_webhook_signature()`
- Store Razorpay order_id and payment_id in SQLite alongside internal order state

### Buyer agent
- Uses Claude API (claude-sonnet-4-6) via the `anthropic` SDK
- System prompt gives it the shopping task and available API endpoints
- Agent loop: parse intent → search catalog → pick items → negotiate → checkout
- Each step is a tool call (the agent calls our FastAPI endpoints via httpx)
- Keep the agent simple — it's a demo driver, not the core product

### Audit trail
- SQLite table: `audit_log(id, timestamp, event_type, payload_json, session_id)`
- Event types: `catalog_search`, `negotiate_request`, `negotiate_decision`, `order_created`, `payment_attempted`, `payment_succeeded`, `payment_failed`, `order_completed`, `order_expired`
- The demo script prints the full audit trail at the end as a formatted table
- This is what judges care about most: "show the audit trail and one failure handled gracefully"

## API contracts (see ARCHITECTURE.md for full schemas)

```
GET  /catalog                    → List[Product]
GET  /catalog/search?q=...       → List[Product]
GET  /catalog/{product_id}       → Product
GET  /pricing-policy             → PricingPolicy
POST /negotiate                  → NegotiationResult  (body: NegotiateRequest)
POST /checkout                   → CheckoutResult     (body: CheckoutRequest)
POST /webhook                    → 200 OK             (Razorpay webhook payload)
GET  /orders/{order_id}          → OrderStatus
GET  /audit-trail/{session_id}   → List[AuditRecord]
GET  /events                     → SSE stream (text/event-stream)
GET  /dashboard                  → serves frontend/index.html
```

## Build order (for Claude Code)

1. **Start with data models** — define all pydantic models in `catalog/models.py`, `pricing/models.py`, `checkout/models.py`. Get the types right first.
2. **Seed data** — create `data/products.json` (15 apparel products with id, name, category, sizes, base_price, created_at) and `data/pricing_policy.json` (floor prices, bundle threshold, volume tiers, time decay days, max discount cap, concession curve params).
3. **Catalog service** — `store.py` loads products, `routes.py` exposes endpoints. Test with curl.
4. **Pricing engine** — implement rules in `rules.py`, compose in `engine.py`, expose via `routes.py`. Write `test_pricing_engine.py` to verify rule composition and clamping.
5. **Razorpay checkout** — `razorpay_client.py` wraps SDK, `order_manager.py` handles lifecycle, `routes.py` exposes checkout + webhook. Test with Razorpay test mode keys.
6. **Audit logger** — SQLite-backed append-only log. Wire into all routes.
7. **Buyer agent** — `agent.py` orchestrates the full flow. Test with a sample shopping task.
8. **Demo script** — `demo/run_demo.py` runs the happy path + one failure scenario, prints audit trail.
9. **Live dashboard** — `frontend/index.html` connects to `GET /events` (SSE), renders the demo visually. Add `GET /events` SSE endpoint and static file serving to FastAPI. Build this LAST — only after the CLI demo works end-to-end.

## Commands

```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Fill in API keys

# Run server
uvicorn src.main:app --reload --port 8000

# Run demo
python demo/run_demo.py

# Run tests
pytest tests/ -v

# Open dashboard (while server is running)
# Navigate to http://localhost:8000/dashboard
# Then trigger the demo from another terminal:
python demo/run_demo.py
```

## Environment variables

```
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxxx
RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxxxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx
```

## What "done" looks like

1. Buyer agent receives task: "Buy 5 cotton kurtas under ₹4000"
2. Agent searches catalog, finds matching products
3. Agent builds cart, proposes a price
4. Pricing engine evaluates rules, returns accept/counter
5. If counter: agent adjusts and re-proposes (max 3 rounds)
6. Razorpay order created, payment link generated
7. Payment succeeds (or fails once then succeeds on retry)
8. Webhook confirms, inventory updated
9. Full audit trail printed: every decision, every rule fired, every payment attempt

Total demo runtime: ~30 seconds. Judges see the agent-to-agent transaction and the audit log.

## Style and code quality

- Type hints everywhere
- Docstrings on public functions
- Pydantic models for all request/response shapes
- No global mutable state outside the audit logger
- Error handling: don't swallow exceptions, log them to audit trail
- Keep files under 200 lines — split if growing

## Live dashboard (frontend/index.html)

This is a single HTML file. No React, no build step, no npm. Vanilla HTML + CSS + JS. FastAPI serves it at `/dashboard` as a static file.

### Purpose

Judges watch the demo on this screen. When `run_demo.py` executes in a terminal, the dashboard updates in real-time showing the agent-to-agent transaction happening live.

### Layout (three panels + bottom strip)

```
┌─────────────────────────────────┬──────────────────────────────────┐
│                                 │                                  │
│    Agent conversation           │    Audit trail                   │
│    (left panel, ~55% width)     │    (right panel, ~45% width)     │
│                                 │                                  │
│                                 │                                  │
│                                 │                                  │
│                                 │                                  │
├─────────────────────────────────┴──────────────────────────────────┤
│  Order status pipeline:  Created → Paying → Failed → Retry → Paid │
└───────────────────────────────────────────────────────────────────-┘
```

### Left panel — Agent conversation

Shows the buyer-merchant interaction as a chat-style timeline. Each event renders as a bubble:

- **Buyer bubbles** (left-aligned, blue-ish): "Searching for cotton kurtas under ₹4000...", "Found 6 products", "Proposing ₹3,500 for cart of 5 items", "Accepting counter at ₹3,825"
- **Merchant bubbles** (right-aligned, teal-ish): "Counter: ₹3,825 (bundle 10% + time decay 5%)", "Order created: order_XXXX", "Payment link generated"
- **System bubbles** (centered, gray, smaller): "Payment attempt 1: failed", "Retrying...", "Payment captured", "Order complete"

Each bubble shows a timestamp and a short description. No raw JSON — format it human-readable. New bubbles animate in (simple fade-in or slide-up).

### Right panel — Audit trail

A scrolling table that grows as events arrive. Columns:

| Time | Event | Details |
|------|-------|---------|

Keep it compact. Time is `HH:MM:SS`. Event is the event_type (color-coded: green for success, red for failures, gray for info). Details is a one-line summary extracted from the payload.

Auto-scrolls to bottom as new rows arrive.

### Bottom strip — Order status pipeline

A horizontal stepper showing the order lifecycle:

`Searching → Negotiating → Checkout → Paying → ✓ Complete`

Each step is a pill/badge. The current step is highlighted (filled color). Completed steps have a checkmark. Failed steps flash red briefly then show retry. This gives judges an instant read on where the transaction is.

If payment fails, the "Paying" step turns red briefly, then a "Retry" state appears, then back to "Paying", then "Complete" turns green.

### SSE connection

```javascript
const eventSource = new EventSource('/events');
eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  // data.event_type: catalog_search, negotiate_request, negotiate_decision,
  //                  order_created, payment_attempted, payment_succeeded,
  //                  payment_failed, order_completed, order_expired
  // data.timestamp: ISO string
  // data.payload: event-specific data
  // data.session_id: current session
  renderEvent(data);
};
```

### SSE backend endpoint

Add to `src/main.py`:

```python
from fastapi.responses import StreamingResponse
import asyncio

# Global event queue — audit logger pushes events here
event_subscribers: list[asyncio.Queue] = []

@app.get("/events")
async def event_stream():
    queue = asyncio.Queue()
    event_subscribers.append(queue)
    async def generate():
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            event_subscribers.remove(queue)
    return StreamingResponse(generate(), media_type="text/event-stream")
```

The audit logger, when it logs an event, also pushes to all SSE subscribers:

```python
# In audit/logger.py
async def broadcast(event: dict):
    for queue in event_subscribers:
        await queue.put(event)
```

### Serving the dashboard

```python
from fastapi.responses import FileResponse

@app.get("/dashboard")
async def dashboard():
    return FileResponse("frontend/index.html")
```

### Design guidelines

- Dark background (`#0a0a0a` or `#111`) — looks good on projector screens during demos
- Monospace font for the audit trail, sans-serif for conversation bubbles
- Accent colors: blue for buyer, teal for merchant, coral for errors, green for success
- Keep it minimal — no logos, no decorative elements, no loading spinners beyond a simple pulse animation
- The page should look good at 1920x1080 (projector) and 1440x900 (laptop)
- Responsive: on smaller screens, stack panels vertically (conversation on top, audit below)
- Add a small header: "MerchantAgent — Live Demo" with the session ID

### What NOT to build

- No login/auth
- No manual controls (the demo script drives everything)
- No product browsing UI
- No settings or configuration panels
- No charts or graphs (the raw audit trail is more impressive to technical judges)
- No WebSocket — SSE is simpler and sufficient for one-way server → client streaming

### Demo flow from the judge's perspective

1. Judge sees the dashboard with empty panels and "Waiting for session..." state
2. Presenter runs `python demo/run_demo.py` in a terminal (can be off-screen or in a small terminal in the corner)
3. Dashboard lights up: buyer agent starts searching, bubbles appear
4. Negotiation plays out in real-time — judges see the counter-offer and the reasoning
5. Order creation, payment attempt, failure, retry, success — all animated in sequence
6. Final state: complete order, full audit trail visible, all steps green
7. Presenter walks through the audit trail: "Every pricing decision traces to a merchant policy. Here's the failure that was handled gracefully."

Total time: ~30-45 seconds of live demo, then walkthrough of the audit trail.
