from __future__ import annotations

import json
from pathlib import Path

from starter.shopping_agent.catalog_artifacts import CatalogArtifactBuilder


def sample_products() -> list[dict[str, object]]:
    products: list[dict[str, object]] = [
        {
            "parent_asin": "BOOT-1",
            "title": "Black winter boot",
            "features": ["warm lining"],
            "details": {"material": "leather", "color": "black"},
            "description": ["Cold weather footwear"],
            "categories": ["Clothing", "Boots"],
            "store": "Example",
            "average_rating": 4.7,
            "rating_number": 500,
            "price": 89.0,
        },
        {
            "parent_asin": "BOOT-2",
            "title": "Outdoor footwear",
            "features": ["winter boot traction"],
            "details": {"material": "rubber", "color": "brown"},
            "description": ["For wet paths"],
            "categories": ["Clothing", "Boots"],
            "store": "Example",
            "average_rating": 4.2,
            "rating_number": 50,
            "price": 69.0,
        },
    ]
    for number in range(3, 13):
        products.append({
            "parent_asin": f"BOOT-{number}",
            "title": f"Everyday boot {number}",
            "features": ["basic footwear"],
            "details": {"material": "synthetic", "color": "gray"},
            "description": ["General use"],
            "categories": ["Clothing", "Boots"],
            "store": "Example",
            "average_rating": 3.5 + number / 20,
            "rating_number": number * 3,
            "price": 40.0 + number,
        })
    return products


def excluded_prefix_products() -> list[dict[str, object]]:
    products: list[dict[str, object]] = []
    for number in range(200):
        products.append({
            "parent_asin": f"LEATHER-{number:03d}",
            "title": f"Premium leather boot {number}",
            "features": ["basic footwear"],
            "details": {"material": "leather", "color": "black"},
            "description": ["General use"],
            "categories": ["Clothing", "Boots"],
            "store": "Example",
            "average_rating": 5.0,
            "rating_number": 10_000,
            "price": 100.0,
        })
    for number in range(50):
        products.append({
            "parent_asin": f"CANVAS-{number:03d}",
            "title": f"Canvas boot {number}",
            "features": ["basic footwear"],
            "details": {"material": "canvas", "color": "black"},
            "description": ["General use"],
            "categories": ["Clothing", "Boots"],
            "store": "Example",
            "average_rating": 4.0,
            "rating_number": 100,
            "price": 70.0,
        })
    return products


def write_catalog(directory: Path, products: list[dict[str, object]]) -> Path:
    path = directory / "catalog.jsonl"
    path.write_text(
        "".join(json.dumps(product) + "\n" for product in products),
        encoding="utf-8",
    )
    return path


def build_test_artifacts(
    directory: Path,
    products: list[dict[str, object]],
    *,
    fts5_enabled: bool = True,
) -> tuple[Path, Path]:
    catalog_path = write_catalog(directory, products)
    artifact_path = directory / "catalog.artifacts"
    CatalogArtifactBuilder(fts5_enabled=fts5_enabled).build(
        catalog_path,
        artifact_path,
    )
    return catalog_path, artifact_path
