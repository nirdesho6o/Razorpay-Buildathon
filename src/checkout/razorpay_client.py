"""Wrapper around razorpay-python SDK for test mode."""

import os

import razorpay


_client: razorpay.Client | None = None


def get_client() -> razorpay.Client:
    """Get or create the Razorpay client."""
    global _client
    if _client is None:
        key_id = os.getenv("RAZORPAY_KEY_ID", "")
        key_secret = os.getenv("RAZORPAY_KEY_SECRET", "")
        if not key_id or not key_secret:
            raise RuntimeError("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set")
        _client = razorpay.Client(auth=(key_id, key_secret))
    return _client


def create_order(amount_paise: int, currency: str, receipt: str, notes: dict) -> dict:
    """Create a Razorpay order."""
    client = get_client()
    return client.order.create({
        "amount": amount_paise,
        "currency": currency,
        "receipt": receipt,
        "notes": notes,
    })


def create_payment_link(
    amount_paise: int,
    currency: str,
    description: str,
    customer: dict,
    callback_url: str,
) -> dict:
    """Create a Razorpay payment link."""
    client = get_client()
    return client.payment_link.create({
        "amount": amount_paise,
        "currency": currency,
        "description": description,
        "customer": customer,
        "notify": {"email": True},
        "callback_url": callback_url,
        "callback_method": "get",
    })


def capture_payment(payment_id: str, amount_paise: int) -> dict:
    """Capture an authorized payment."""
    client = get_client()
    return client.payment.capture(payment_id, amount_paise)


def verify_webhook_signature(body: str, signature: str, secret: str) -> bool:
    """Verify a Razorpay webhook signature."""
    client = get_client()
    try:
        client.utility.verify_webhook_signature(body, signature, secret)
        return True
    except razorpay.errors.SignatureVerificationError:
        return False
