"""Append-only audit log backed by SQLite, with SSE broadcast."""

import asyncio
import json
import sqlite3
import uuid
from datetime import datetime, timezone


_db: sqlite3.Connection | None = None
_subscribers: list[asyncio.Queue] = []


def init_db(db_path: str = "audit.db") -> None:
    """Initialize SQLite audit log table."""
    global _db
    _db = sqlite3.connect(db_path, check_same_thread=False)
    _db.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            session_id TEXT NOT NULL
        )
    """)
    _db.commit()


def get_subscribers() -> list[asyncio.Queue]:
    """Return the list of SSE subscriber queues."""
    return _subscribers


async def log_event(session_id: str, event_type: str, payload: dict) -> dict:
    """Write an audit record and broadcast to SSE subscribers."""
    record_id = f"aud_{uuid.uuid4().hex[:8]}"
    ts = datetime.now(timezone.utc).isoformat()

    if _db:
        _db.execute(
            "INSERT INTO audit_log (id, timestamp, event_type, payload_json, session_id) VALUES (?, ?, ?, ?, ?)",
            (record_id, ts, event_type, json.dumps(payload), session_id),
        )
        _db.commit()

    display = _make_display(event_type, payload)
    event = {
        "id": record_id,
        "event_type": event_type,
        "timestamp": ts,
        "session_id": session_id,
        "display": display,
        "payload": payload,
    }
    await _broadcast(event)
    return event


def _make_display(event_type: str, payload: dict) -> dict:
    """Map raw audit event to frontend display fields."""
    mappings: dict[str, tuple[str, str, str]] = {
        "catalog_search": (
            "buyer", "searching",
            f"Searching for {payload.get('query', '...')}",
        ),
        "catalog_results": (
            "merchant", "searching",
            f"Found {payload.get('count', 0)} matching products",
        ),
        "negotiate_request": (
            "buyer", "negotiating",
            f"Proposing ₹{payload.get('proposed_total', 0):,} for {payload.get('total_items', 0)} items",
        ),
        "negotiate_decision": (
            "merchant", "negotiating",
            _format_negotiation(payload),
        ),
        "negotiate_accept": (
            "buyer", "negotiating",
            f"Accepting ₹{payload.get('accepted_total', 0):,}",
        ),
        "order_created": (
            "merchant", "checkout",
            f"Order created: {payload.get('razorpay_order_id', '')}",
        ),
        "payment_link_created": (
            "merchant", "checkout",
            "Payment link generated",
        ),
        "payment_attempted": (
            "system", "paying",
            f"Payment attempt {payload.get('attempt', 1)}...",
        ),
        "payment_failed": (
            "system", "paying",
            f"Payment failed — retrying in {payload.get('retry_delay', 3)}s",
        ),
        "payment_succeeded": (
            "system", "paying",
            f"Payment captured: {payload.get('payment_id', '')}",
        ),
        "order_completed": (
            "system", "complete",
            "Order complete — inventory updated",
        ),
        "order_expired": (
            "system", "failed",
            "Order expired after max retries",
        ),
    }
    actor, phase, summary = mappings.get(event_type, ("system", "searching", event_type))
    return {"actor": actor, "summary": summary, "phase": phase}


def _format_negotiation(payload: dict) -> str:
    """Format negotiation decision for display."""
    decision = payload.get("decision", "")
    computed = payload.get("computed_total", 0)
    rules = payload.get("rules_fired", [])
    if decision == "accept":
        return f"Accept at ₹{computed:,}"
    elif decision == "counter":
        rules_str = " + ".join(rules) if rules else "pricing rules"
        return f"Counter: ₹{computed:,} ({rules_str})"
    else:
        return f"Reject — below floor price"


def get_audit_trail(session_id: str) -> list[dict]:
    """Retrieve all audit records for a session."""
    if not _db:
        return []
    cursor = _db.execute(
        "SELECT id, timestamp, event_type, payload_json, session_id FROM audit_log WHERE session_id = ? ORDER BY timestamp",
        (session_id,),
    )
    rows = cursor.fetchall()
    return [
        {
            "id": r[0],
            "timestamp": r[1],
            "event_type": r[2],
            "payload": json.loads(r[3]),
            "session_id": r[4],
        }
        for r in rows
    ]


async def _broadcast(event: dict) -> None:
    """Push event to all SSE subscriber queues."""
    for queue in _subscribers:
        await queue.put(event)
