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
) -> tuple[Path, Path]:
    catalog_path = write_catalog(directory, products)
    artifact_path = directory / "catalog.artifacts"
    CatalogArtifactBuilder().build(catalog_path, artifact_path)
    return catalog_path, artifact_path
