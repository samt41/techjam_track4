from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiments.semantic.concepts import (
    concepts_from_database,
    inventory_sha256,
    write_inventory,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a semantic concept inventory from catalog artifacts"
    )
    parser.add_argument(
        "--database",
        default="data/catalog.artifacts/catalog.sqlite3",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--feature-df-floor", type=int, default=2)
    args = parser.parse_args()
    concepts = concepts_from_database(
        args.database,
        feature_document_frequency_floor=args.feature_df_floor,
    )
    output = write_inventory(concepts, args.output)
    summary = {
        "output": str(output),
        "concept_count": len(concepts),
        "inventory_sha256": inventory_sha256(concepts),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
