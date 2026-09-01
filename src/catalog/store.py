"""Load and query product catalog from JSON seed file."""

import json
from datetime import datetime, timezone
from pathlib import Path

from src.catalog.models import CatalogSearchQuery, Product

_products: list[Product] = []


def load_products(path: str = "data/products.json") -> list[Product]:
    """Load products from JSON file into memory."""
    global _products
    raw = json.loads(Path(path).read_text())
    _products = [Product(**p) for p in raw]
    return _products


def get_all_products() -> list[Product]:
    """Return all products."""
    return _products


def get_product_by_id(product_id: str) -> Product | None:
    """Return a single product by ID."""
    for p in _products:
        if p.id == product_id:
            return p
    return None


def search_products(query: CatalogSearchQuery) -> list[Product]:
    """Filter products by structured query fields."""
    results = _products
    if query.category:
        results = [p for p in results if p.category == query.category]
    if query.subcategory:
        results = [p for p in results if p.subcategory == query.subcategory]
    if query.max_price is not None:
        results = [p for p in results if p.base_price <= query.max_price]
    if query.min_price is not None:
        results = [p for p in results if p.base_price >= query.min_price]
    if query.sizes:
        results = [p for p in results if any(s in p.sizes for s in query.sizes)]
    if query.tags:
        results = [p for p in results if any(t in p.tags for t in query.tags)]
    return results


def decrement_inventory(product_id: str, quantity: int) -> bool:
    """Decrease inventory for a product. Returns False if insufficient stock."""
    product = get_product_by_id(product_id)
    if not product or product.inventory < quantity:
        return False
    product.inventory -= quantity
    return True
