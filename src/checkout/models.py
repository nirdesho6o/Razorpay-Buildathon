from datetime import datetime

from pydantic import BaseModel


class BuyerInfo(BaseModel):
    name: str
    email: str
    contact: str


class CheckoutRequest(BaseModel):
    session_id: str
    accepted_total: int
    cart: list["CheckoutCartItem"]
    buyer_info: BuyerInfo


class CheckoutCartItem(BaseModel):
    product_id: str
    quantity: int
    size: str


class CheckoutResult(BaseModel):
    session_id: str
    internal_order_id: str
    razorpay_order_id: str
    payment_link: str
    payment_link_id: str
    amount: int  # paise
    currency: str = "INR"
    status: str
    expires_at: datetime
    retry_window_minutes: int = 10
    max_retries: int = 2


class PaymentAttempt(BaseModel):
    attempt_number: int
    payment_id: str | None = None
    status: str  # "created" | "captured" | "failed"
    timestamp: datetime


class Order(BaseModel):
    internal_order_id: str
    session_id: str
    razorpay_order_id: str
    payment_link_id: str
    amount: int
    currency: str = "INR"
    status: str  # "created" | "paying" | "paid" | "failed" | "expired"
    cart: list[CheckoutCartItem]
    payment_attempts: list[PaymentAttempt] = []
    created_at: datetime
    expires_at: datetime
    max_retries: int = 2


class OrderStatus(BaseModel):
    internal_order_id: str
    razorpay_order_id: str
    status: str
    amount: int
    currency: str
    payment_attempts: list[PaymentAttempt]
    created_at: datetime


class WebhookEvent(BaseModel):
    event: str
    payload: dict
