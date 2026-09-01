"""Tests for the checkout flow — order creation, payment attempts, status transitions."""

import pytest

from src.checkout.models import CheckoutCartItem
from src.checkout.order_manager import (
    create_order,
    get_order,
    get_order_status,
    init_db,
    record_payment_attempt,
    update_order_status,
)


@pytest.fixture(autouse=True)
def setup(tmp_path):
    init_db(str(tmp_path / "test_orders.db"))


def test_create_order():
    """Creating an order should set status to 'created'."""
    order = create_order(
        session_id="test_sess",
        razorpay_order_id="order_test_001",
        payment_link_id="plink_test_001",
        amount=382500,
        cart=[CheckoutCartItem(product_id="prod_001", quantity=3, size="M")],
    )
    assert order.status == "created"
    assert order.amount == 382500
    assert len(order.payment_attempts) == 0


def test_get_order():
    """Should be able to retrieve an order by internal ID."""
    order = create_order(
        session_id="test_sess",
        razorpay_order_id="order_test_002",
        payment_link_id="plink_test_002",
        amount=100000,
        cart=[CheckoutCartItem(product_id="prod_002", quantity=1, size="L")],
    )
    retrieved = get_order(order.internal_order_id)
    assert retrieved is not None
    assert retrieved.razorpay_order_id == "order_test_002"


def test_payment_attempt_captured():
    """Captured payment should set order status to 'paid'."""
    order = create_order(
        session_id="test_sess",
        razorpay_order_id="order_test_003",
        payment_link_id="plink_test_003",
        amount=200000,
        cart=[CheckoutCartItem(product_id="prod_003", quantity=2, size="M")],
    )
    record_payment_attempt(order.internal_order_id, "pay_001", "captured")
    updated = get_order(order.internal_order_id)
    assert updated.status == "paid"


def test_payment_failure_then_success():
    """Order should stay active after first failure, then move to 'paid' on success."""
    order = create_order(
        session_id="test_sess",
        razorpay_order_id="order_test_004",
        payment_link_id="plink_test_004",
        amount=150000,
        cart=[CheckoutCartItem(product_id="prod_001", quantity=1, size="M")],
    )

    record_payment_attempt(order.internal_order_id, "pay_fail_001", "failed")
    updated = get_order(order.internal_order_id)
    assert updated.status == "paying"

    record_payment_attempt(order.internal_order_id, "pay_ok_001", "captured")
    updated = get_order(order.internal_order_id)
    assert updated.status == "paid"


def test_max_retries_expires_order():
    """Order should expire after max retries (2) are exhausted."""
    order = create_order(
        session_id="test_sess",
        razorpay_order_id="order_test_005",
        payment_link_id="plink_test_005",
        amount=100000,
        cart=[CheckoutCartItem(product_id="prod_001", quantity=1, size="M")],
        max_retries=2,
    )

    record_payment_attempt(order.internal_order_id, "pay_fail_1", "failed")
    record_payment_attempt(order.internal_order_id, "pay_fail_2", "failed")
    updated = get_order(order.internal_order_id)
    assert updated.status == "expired"


def test_order_status_endpoint():
    """get_order_status should return correct status shape."""
    order = create_order(
        session_id="test_sess",
        razorpay_order_id="order_test_006",
        payment_link_id="plink_test_006",
        amount=300000,
        cart=[CheckoutCartItem(product_id="prod_002", quantity=3, size="L")],
    )
    status = get_order_status(order.internal_order_id)
    assert status is not None
    assert status.razorpay_order_id == "order_test_006"
    assert status.status == "created"
