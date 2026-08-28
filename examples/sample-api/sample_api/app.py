"""Small FastAPI application used by the TaskPilot demonstration."""

from fastapi import FastAPI

app = FastAPI(title="TaskPilot Sample API")

PRODUCTS = [
    {"id": 1, "name": "Keyboard"},
    {"id": 2, "name": "Mouse"},
    {"id": 3, "name": "Monitor"},
    {"id": 4, "name": "Dock"},
]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/products")
def list_products() -> list[dict[str, object]]:
    return PRODUCTS
