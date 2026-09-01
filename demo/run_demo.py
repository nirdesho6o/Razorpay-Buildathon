"""Scripted end-to-end demo — buyer agent executes a shopping task."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from src.buyer_agent.agent import BuyerAgent

load_dotenv()

console = Console()
BASE_URL = "http://localhost:8000"


async def run_demo():
    """Run the full demo: buyer agent shopping task + audit trail display."""
    console.print("\n[bold cyan]=== MerchantAgent Demo ===[/bold cyan]\n")

    task = "Buy 5 cotton kurtas under ₹4000"
    console.print(f'[bold]Shopping task:[/bold] "{task}"\n')

    # Verify server is running
    try:
        httpx.get(f"{BASE_URL}/catalog", timeout=5)
    except httpx.ConnectError:
        console.print("[red]Error: Server is not running. Start it with:[/red]")
        console.print("  uvicorn src.main:app --reload --port 8000")
        return

    agent = BuyerAgent(base_url=BASE_URL)
    console.print(f"[dim]Session ID: {agent.session_id}[/dim]\n")

    console.print("[bold yellow]Agent is shopping...[/bold yellow]\n")
    session_id = await agent.run(task)

    # Simulate payment flow via webhooks since we're in test mode
    await _simulate_payment_flow(session_id)

    # Fetch and display audit trail
    console.print("\n[bold cyan]=== Audit Trail ===[/bold cyan]\n")
    resp = httpx.get(f"{BASE_URL}/audit-trail/{session_id}", timeout=10)
    trail = resp.json()

    if not trail:
        console.print("[dim]No audit records found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Timestamp", style="dim", width=12)
    table.add_column("Event", width=20)
    table.add_column("Details", width=50)

    for record in trail:
        ts = record["timestamp"].split("T")[1][:8] if "T" in record["timestamp"] else record["timestamp"]
        event = record["event_type"]
        payload = record.get("payload", {})

        style = "green" if "succeed" in event or "completed" in event or "accept" in event else ""
        if "failed" in event or "expired" in event:
            style = "red"

        details = _format_details(event, payload)
        table.add_row(ts, f"[{style}]{event}[/{style}]" if style else event, details)

    console.print(table)
    console.print(f"\n[bold green]Demo complete.[/bold green] Session: {session_id}\n")


async def _simulate_payment_flow(session_id: str):
    """Simulate payment success via direct order status updates."""
    resp = httpx.get(f"{BASE_URL}/audit-trail/{session_id}", timeout=10)
    trail = resp.json()

    order_event = next((r for r in trail if r["event_type"] == "order_created"), None)
    if not order_event:
        return

    internal_order_id = order_event["payload"].get("internal_order_id", "")
    if not internal_order_id:
        return

    # Simulate a failed payment attempt
    from src.audit.logger import log_event
    from src.checkout.order_manager import record_payment_attempt, update_order_status

    await log_event(session_id, "payment_attempted", {"attempt": 1, "status": "failed"})
    record_payment_attempt(internal_order_id, "pay_sim_fail_001", "failed")
    await log_event(session_id, "payment_failed", {"attempt": 1, "retry_delay": 3})

    await asyncio.sleep(2)

    # Simulate successful payment
    await log_event(session_id, "payment_attempted", {"attempt": 2, "status": "capturing"})
    record_payment_attempt(internal_order_id, "pay_sim_ok_001", "captured")
    update_order_status(internal_order_id, "paid")
    await log_event(session_id, "payment_succeeded", {"payment_id": "pay_sim_ok_001"})

    # Decrement inventory
    from src.catalog.store import decrement_inventory
    order_resp = httpx.get(f"{BASE_URL}/orders/{internal_order_id}", timeout=10)
    if order_resp.status_code == 200:
        await log_event(session_id, "order_completed", {
            "internal_order_id": internal_order_id,
            "payment_id": "pay_sim_ok_001",
        })


def _format_details(event: str, payload: dict) -> str:
    """Format payload into a compact one-liner for the audit table."""
    if event == "catalog_search":
        return f'query="{payload.get("query", "")}"'
    elif event == "catalog_results":
        return f'found {payload.get("count", 0)} products'
    elif event == "negotiate_request":
        return f'round={payload.get("round", 1)}, proposed=₹{payload.get("proposed_total", 0):,}'
    elif event == "negotiate_decision":
        return f'{payload.get("decision", "")}, computed=₹{payload.get("computed_total", 0):,}, rules={len(payload.get("rules_fired", []))}'
    elif event == "order_created":
        return f'rzp_order={payload.get("razorpay_order_id", "")}, amount={payload.get("amount", 0)}'
    elif event == "payment_attempted":
        return f'attempt={payload.get("attempt", 1)}, status={payload.get("status", "")}'
    elif event == "payment_failed":
        return f'attempt={payload.get("attempt", 1)}, retry in {payload.get("retry_delay", 3)}s'
    elif event == "payment_succeeded":
        return f'payment_id={payload.get("payment_id", "")}'
    elif event == "order_completed":
        return f'payment_id={payload.get("payment_id", "")}'
    return str(payload)[:50]


if __name__ == "__main__":
    asyncio.run(run_demo())
