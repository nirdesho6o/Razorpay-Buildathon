"""Order lifecycle management with SQLite persistence."""

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from src.checkout.models import CheckoutCartItem, Order, OrderStatus, PaymentAttempt

_db: sqlite3.Connection | None = None


def init_db(db_path: str = "orders.db") -> None:
    """Initialize SQLite orders table."""
    global _db
    _db = sqlite3.connect(db_path, check_same_thread=False)
    _db.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            internal_order_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            razorpay_order_id TEXT,
            payment_link_id TEXT,
            amount INTEGER NOT NULL,
            currency TEXT DEFAULT 'INR',
            status TEXT DEFAULT 'created',
            cart_json TEXT NOT NULL,
            payment_attempts_json TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            max_retries INTEGER DEFAULT 2
        )
    """)
    _db.commit()


def create_order(
    session_id: str,
    razorpay_order_id: str,
    payment_link_id: str,
    amount: int,
    cart: list[CheckoutCartItem],
    currency: str = "INR",
    retry_window_minutes: int = 10,
    max_retries: int = 2,
) -> Order:
    """Create a new order in the database."""
    internal_id = f"ord_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=retry_window_minutes)

    order = Order(
        internal_order_id=internal_id,
        session_id=session_id,
        razorpay_order_id=razorpay_order_id,
        payment_link_id=payment_link_id,
        amount=amount,
        currency=currency,
        status="created",
        cart=cart,
        payment_attempts=[],
        created_at=now,
        expires_at=expires,
        max_retries=max_retries,
    )

    if _db:
        _db.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                order.internal_order_id, order.session_id, order.razorpay_order_id,
                order.payment_link_id, order.amount, order.currency, order.status,
                json.dumps([c.model_dump() for c in cart]),
                json.dumps([]),
                now.isoformat(), expires.isoformat(), max_retries,
            ),
        )
        _db.commit()

    return order


def get_order(internal_order_id: str) -> Order | None:
    """Retrieve an order by internal ID."""
    if not _db:
        return None
    cursor = _db.execute("SELECT * FROM orders WHERE internal_order_id = ?", (internal_order_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return _row_to_order(row)


def get_order_by_razorpay_id(razorpay_order_id: str) -> Order | None:
    """Retrieve an order by Razorpay order ID."""
    if not _db:
        return None
    cursor = _db.execute("SELECT * FROM orders WHERE razorpay_order_id = ?", (razorpay_order_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return _row_to_order(row)


def record_payment_attempt(internal_order_id: str, payment_id: str | None, status: str) -> PaymentAttempt | None:
    """Record a payment attempt for an order."""
    order = get_order(internal_order_id)
    if not order:
        return None

    attempt = PaymentAttempt(
        attempt_number=len(order.payment_attempts) + 1,
        payment_id=payment_id,
        status=status,
        timestamp=datetime.now(timezone.utc),
    )

    attempts = order.payment_attempts + [attempt]

    new_status = order.status
    if status == "captured":
        new_status = "paid"
    elif status == "failed":
        if len(attempts) >= order.max_retries:
            new_status = "expired"
        else:
            new_status = "paying"

    if _db:
        _db.execute(
            "UPDATE orders SET payment_attempts_json = ?, status = ? WHERE internal_order_id = ?",
            (json.dumps([a.model_dump(mode="json") for a in attempts]), new_status, internal_order_id),
        )
        _db.commit()

    return attempt


def update_order_status(internal_order_id: str, status: str) -> None:
    """Update the status of an order."""
    if _db:
        _db.execute(
            "UPDATE orders SET status = ? WHERE internal_order_id = ?",
            (status, internal_order_id),
        )
        _db.commit()


def get_order_status(internal_order_id: str) -> OrderStatus | None:
    """Get order status by internal ID."""
    order = get_order(internal_order_id)
    if not order:
        return None
    return OrderStatus(
        internal_order_id=order.internal_order_id,
        razorpay_order_id=order.razorpay_order_id,
        status=order.status,
        amount=order.amount,
        currency=order.currency,
        payment_attempts=order.payment_attempts,
        created_at=order.created_at,
    )


def _row_to_order(row: tuple) -> Order:
    """Convert a database row to an Order object."""
    return Order(
        internal_order_id=row[0],
        session_id=row[1],
        razorpay_order_id=row[2] or "",
        payment_link_id=row[3] or "",
        amount=row[4],
        currency=row[5],
        status=row[6],
        cart=[CheckoutCartItem(**c) for c in json.loads(row[7])],
        payment_attempts=[PaymentAttempt(**a) for a in json.loads(row[8])],
        created_at=datetime.fromisoformat(row[9]),
        expires_at=datetime.fromisoformat(row[10]),
        max_retries=row[11],
    )
