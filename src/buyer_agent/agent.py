"""LLM-powered buyer agent that orchestrates the full shopping flow."""

import json
import os
import uuid

import anthropic
import httpx


SYSTEM_PROMPT = """You are an AI buying agent. Your task is to complete a purchase within the given budget.

You have access to a merchant's catalog and pricing APIs. Your goal:
1. Search for products matching the shopping task
2. Build a cart that fits the budget
3. Negotiate for the best price — start with your budget as the proposed price
4. If countered, decide whether to accept or re-propose (you have 3 rounds max)
5. Complete checkout once a price is agreed

Be strategic but honest about your budget. The pricing system rewards truthful reporting.
Always log your reasoning for each decision."""

TOOLS = [
    {
        "name": "search_catalog",
        "description": "Search the merchant's product catalog with a natural language query.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_pricing_policy",
        "description": "Get the merchant's pricing policy including available discounts.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "negotiate",
        "description": "Submit a price proposal for a cart of items.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cart": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "product_id": {"type": "string"},
                            "quantity": {"type": "integer"},
                            "size": {"type": "string"},
                        },
                        "required": ["product_id", "quantity", "size"],
                    },
                },
                "proposed_total": {"type": "integer", "description": "Proposed total price in INR"},
                "round": {"type": "integer", "description": "Negotiation round number (1-3)"},
            },
            "required": ["cart", "proposed_total", "round"],
        },
    },
    {
        "name": "checkout",
        "description": "Complete checkout at the agreed price.",
        "input_schema": {
            "type": "object",
            "properties": {
                "accepted_total": {"type": "integer", "description": "Agreed total price in INR"},
                "cart": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "product_id": {"type": "string"},
                            "quantity": {"type": "integer"},
                            "size": {"type": "string"},
                        },
                        "required": ["product_id", "quantity", "size"],
                    },
                },
            },
            "required": ["accepted_total", "cart"],
        },
    },
    {
        "name": "check_order",
        "description": "Check the status of an order.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Internal order ID"},
            },
            "required": ["order_id"],
        },
    },
]


class BuyerAgent:
    """AI buyer agent that completes shopping tasks via merchant APIs."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.session_id = f"sess_{uuid.uuid4().hex[:8]}"
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.http = httpx.Client(timeout=30)
        self.messages: list[dict] = []

    async def run(self, task: str) -> str:
        """Execute a shopping task end-to-end. Returns the session_id."""
        self.messages = [{"role": "user", "content": f"Shopping task: {task}\n\nYour session ID is: {self.session_id}"}]

        max_iterations = 15
        for _ in range(max_iterations):
            response = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=self.messages,
            )

            if response.stop_reason == "end_of_turn":
                final_text = ""
                for block in response.content:
                    if block.type == "text":
                        final_text += block.text
                self.messages.append({"role": "assistant", "content": response.content})
                return self.session_id

            self.messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = await self._execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })

            if tool_results:
                self.messages.append({"role": "user", "content": tool_results})

        return self.session_id

    async def _execute_tool(self, name: str, args: dict) -> dict:
        """Execute a tool call against the merchant's API."""
        if name == "search_catalog":
            resp = self.http.get(
                f"{self.base_url}/catalog/search",
                params={"q": args["query"], "session_id": self.session_id},
            )
            return resp.json()

        elif name == "get_pricing_policy":
            resp = self.http.get(f"{self.base_url}/pricing-policy")
            return resp.json()

        elif name == "negotiate":
            resp = self.http.post(
                f"{self.base_url}/negotiate",
                json={
                    "session_id": self.session_id,
                    "cart": args["cart"],
                    "proposed_total": args["proposed_total"],
                    "round": args.get("round", 1),
                },
            )
            return resp.json()

        elif name == "checkout":
            resp = self.http.post(
                f"{self.base_url}/checkout",
                json={
                    "session_id": self.session_id,
                    "accepted_total": args["accepted_total"],
                    "cart": args["cart"],
                    "buyer_info": {
                        "name": "AI Buyer Agent",
                        "email": "buyer@agent.test",
                        "contact": "+919999999999",
                    },
                },
            )
            return resp.json()

        elif name == "check_order":
            resp = self.http.get(f"{self.base_url}/orders/{args['order_id']}")
            return resp.json()

        return {"error": f"Unknown tool: {name}"}
