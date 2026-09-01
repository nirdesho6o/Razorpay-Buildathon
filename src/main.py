"""FastAPI app entry point."""

import asyncio
import json

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse

from src.audit.logger import get_audit_trail, get_subscribers, init_db as init_audit_db
from src.catalog.routes import router as catalog_router
from src.catalog.store import load_products
from src.checkout.order_manager import init_db as init_orders_db
from src.checkout.routes import router as checkout_router
from src.pricing.engine import load_policy
from src.pricing.routes import router as pricing_router

load_dotenv()

app = FastAPI(title="MerchantAgent", description="Agentic Commerce on Razorpay")


@app.on_event("startup")
async def startup():
    """Initialize data stores on startup."""
    load_products()
    load_policy()
    init_audit_db()
    init_orders_db()


app.include_router(catalog_router)
app.include_router(pricing_router)
app.include_router(checkout_router)


@app.get("/events")
async def event_stream():
    """SSE endpoint for live dashboard updates."""
    queue: asyncio.Queue = asyncio.Queue()
    subscribers = get_subscribers()
    subscribers.append(queue)

    async def generate():
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, default=str)}\n\n"
        except asyncio.CancelledError:
            subscribers.remove(queue)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/audit-trail/{session_id}")
async def audit_trail(session_id: str):
    """Return all audit records for a session."""
    return get_audit_trail(session_id)


@app.get("/dashboard")
async def dashboard():
    """Serve the live dashboard."""
    return FileResponse("frontend/index.html")
