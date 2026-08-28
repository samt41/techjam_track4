from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from starter.shopping_agent.catalog_artifacts import (
    MANIFEST_FILENAME,
    ArtifactBuildError,
    ArtifactValidationError,
    CatalogArtifactBuilder,
)


def main(argv: tuple[str, ...] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the deterministic Track 4 catalog search artifact.",
    )
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)

    started_at = time.perf_counter()
    try:
        manifest = CatalogArtifactBuilder().build(
            arguments.catalog,
            arguments.output,
        )
    except (ArtifactBuildError, ArtifactValidationError, OSError) as error:
        print(f"artifact build failed: {error}", file=sys.stderr)
        return 1
    elapsed_ms = (time.perf_counter() - started_at) * 1_000.0
    manifest_size_bytes = (arguments.output / MANIFEST_FILENAME).stat().st_size
    print(f"catalog_sha256={manifest.catalog_sha256}")
    print(f"product_count={manifest.product_count}")
    print(f"catalog_size_bytes={manifest.catalog_size_bytes}")
    print(f"database_size_bytes={manifest.database_size_bytes}")
    print(f"manifest_size_bytes={manifest_size_bytes}")
    print(f"lexical_term_count={manifest.lexical_term_count}")
    print(f"fts5_built={str(manifest.fts5_built).lower()}")
    print(f"elapsed_ms={elapsed_ms:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
