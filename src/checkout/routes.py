"""Checkout and webhook API routes."""

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from src.audit.logger import log_event
from src.catalog.store import decrement_inventory
from src.checkout.models import CheckoutRequest, CheckoutResult, OrderStatus
from src.checkout.order_manager import (
    create_order,
    get_order,
    get_order_by_razorpay_id,
    get_order_status,
    record_payment_attempt,
    update_order_status,
)
from src.checkout.razorpay_client import (
    capture_payment,
    create_order as rzp_create_order,
    create_payment_link,
    verify_webhook_signature,
)

router = APIRouter(tags=["checkout"])


@router.post("/checkout", response_model=CheckoutResult)
async def checkout(request: CheckoutRequest):
    """Create a Razorpay order and payment link."""
    amount_paise = request.accepted_total * 100

    rzp_order = rzp_create_order(
        amount_paise=amount_paise,
        currency="INR",
        receipt=f"sess_{request.session_id}",
        notes={"session_id": request.session_id},
    )

    callback_url = os.getenv("WEBHOOK_URL", "http://localhost:8000/webhook")
    plink = create_payment_link(
        amount_paise=amount_paise,
        currency="INR",
        description=f"MerchantAgent order for session {request.session_id}",
        customer={
            "name": request.buyer_info.name,
            "email": request.buyer_info.email,
            "contact": request.buyer_info.contact,
        },
        callback_url=callback_url,
    )

    order = create_order(
        session_id=request.session_id,
        razorpay_order_id=rzp_order["id"],
        payment_link_id=plink.get("id", ""),
        amount=amount_paise,
        cart=request.cart,
    )

    await log_event(request.session_id, "order_created", {
        "internal_order_id": order.internal_order_id,
        "razorpay_order_id": rzp_order["id"],
        "amount": amount_paise,
    })

    await log_event(request.session_id, "payment_link_created", {
        "payment_link_id": plink.get("id", ""),
        "short_url": plink.get("short_url", ""),
    })

    now = datetime.now(timezone.utc)
    return CheckoutResult(
        session_id=request.session_id,
        internal_order_id=order.internal_order_id,
        razorpay_order_id=rzp_order["id"],
        payment_link=plink.get("short_url", ""),
        payment_link_id=plink.get("id", ""),
        amount=amount_paise,
        currency="INR",
        status="created",
        expires_at=now + timedelta(minutes=10),
    )


@router.post("/webhook")
async def webhook(request: Request):
    """Handle Razorpay webhook events."""
    body = await request.body()
    body_str = body.decode("utf-8")
    signature = request.headers.get("X-Razorpay-Signature", "")
    secret = os.getenv("WEBHOOK_SECRET", "")

    if secret and signature:
        if not verify_webhook_signature(body_str, signature, secret):
            raise HTTPException(status_code=400, detail="Invalid webhook signature")

    import json
    payload = json.loads(body_str)
    event_type = payload.get("event", "")
    payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    order_id = payment_entity.get("order_id", "")
    payment_id = payment_entity.get("id", "")

    order = get_order_by_razorpay_id(order_id) if order_id else None
    session_id = order.session_id if order else "unknown"

    if event_type == "payment.authorized":
        if order:
            await log_event(session_id, "payment_attempted", {
                "attempt": len(order.payment_attempts) + 1,
                "payment_id": payment_id,
                "status": "authorized",
            })
            capture_payment(payment_id, order.amount)

    elif event_type == "payment.captured":
        if order:
            record_payment_attempt(order.internal_order_id, payment_id, "captured")
            update_order_status(order.internal_order_id, "paid")
            for item in order.cart:
                decrement_inventory(item.product_id, item.quantity)
            await log_event(session_id, "payment_succeeded", {"payment_id": payment_id})
            await log_event(session_id, "order_completed", {
                "internal_order_id": order.internal_order_id,
                "payment_id": payment_id,
            })

    elif event_type == "payment.failed":
        if order:
            attempt = record_payment_attempt(order.internal_order_id, payment_id, "failed")
            attempt_num = attempt.attempt_number if attempt else 1
            if attempt_num >= order.max_retries:
                update_order_status(order.internal_order_id, "expired")
                await log_event(session_id, "order_expired", {
                    "internal_order_id": order.internal_order_id,
                    "reason": "max retries exceeded",
                })
            else:
                await log_event(session_id, "payment_failed", {
                    "attempt": attempt_num,
                    "payment_id": payment_id,
                    "retry_delay": 3,
                })

    return {"status": "ok"}


@router.get("/orders/{order_id}", response_model=OrderStatus)
async def get_order_endpoint(order_id: str):
    """Get order status by internal order ID."""
    status = get_order_status(order_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    return status
