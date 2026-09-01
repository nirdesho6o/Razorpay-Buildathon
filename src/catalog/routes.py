"""Catalog API routes."""

import os

import anthropic
from fastapi import APIRouter, HTTPException, Query

from src.audit.logger import log_event
from src.catalog.models import CatalogSearchQuery, Product
from src.catalog.store import get_all_products, get_product_by_id, search_products

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("", response_model=list[Product])
async def list_products():
    """Return all products in the catalog."""
    return get_all_products()


@router.get("/search", response_model=list[Product])
async def search(q: str = Query(..., description="Natural language search query"), session_id: str = Query("default")):
    """Search catalog using natural language query."""
    await log_event(session_id, "catalog_search", {"query": q})

    structured_query = await _extract_filters(q)
    results = search_products(structured_query)

    await log_event(session_id, "catalog_results", {"query": q, "count": len(results)})
    return results


@router.get("/{product_id}", response_model=Product)
async def get_product(product_id: str):
    """Return a single product by ID."""
    product = get_product_by_id(product_id)
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
    return product


async def _extract_filters(query: str) -> CatalogSearchQuery:
    """Use Claude to extract structured filters from a natural language query."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return _fallback_filter(query)

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        messages=[{
            "role": "user",
            "content": (
                'Extract structured filters from this shopping query. Return JSON only, no explanation.\n'
                f'Query: "{query}"\n'
                'Schema: {{ "category": str|null, "subcategory": str|null, "max_price": int|null, '
                '"min_price": int|null, "sizes": list[str]|null, "tags": list[str]|null }}'
            ),
        }],
    )
    import json
    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    filters = json.loads(text)
    return CatalogSearchQuery(**filters)


def _fallback_filter(query: str) -> CatalogSearchQuery:
    """Simple keyword-based fallback when no API key is set."""
    q = query.lower()
    category = None
    subcategory = None
    max_price = None
    tags: list[str] = []

    if "kurta" in q:
        category = "kurta"
    elif "shirt" in q:
        category = "shirt"
    elif "trouser" in q or "chino" in q:
        category = "trousers"

    if "cotton" in q:
        subcategory = "cotton"
        tags.append("cotton")
    elif "linen" in q:
        subcategory = "linen"
        tags.append("linen")
    elif "silk" in q:
        subcategory = "silk_blend"

    import re
    price_match = re.search(r"under\s*₹?\s*(\d+)", q) or re.search(r"below\s*₹?\s*(\d+)", q)
    if price_match:
        max_price = int(price_match.group(1))

    return CatalogSearchQuery(
        category=category,
        subcategory=subcategory,
        max_price=max_price,
        tags=tags or None,
    )
