from datetime import datetime

from pydantic import BaseModel


class Product(BaseModel):
    id: str
    name: str
    category: str
    subcategory: str
    sizes: list[str]
    base_price: int
    currency: str = "INR"
    inventory: int
    tags: list[str]
    created_at: datetime
    description: str


class CartItem(BaseModel):
    product_id: str
    quantity: int
    size: str


class CatalogSearchQuery(BaseModel):
    category: str | None = None
    subcategory: str | None = None
    max_price: int | None = None
    min_price: int | None = None
    sizes: list[str] | None = None
    tags: list[str] | None = None
