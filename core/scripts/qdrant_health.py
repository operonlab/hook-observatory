#!/usr/bin/env python3
"""Qdrant health check and collection stats.

Usage: ~/.local/bin/python3 core/scripts/qdrant_health.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.shared.qdrant_client import get_client, health_check


async def main():
    # Basic health
    status = await health_check()
    print(json.dumps(status, indent=2))

    if status.get("status") != "healthy":
        sys.exit(1)

    # Collection details
    client = await get_client()
    if client:
        try:
            from src.shared.qdrant_search import COLLECTION_NAME
            info = await client.get_collection(COLLECTION_NAME)
            print(f"\nCollection: {COLLECTION_NAME}")
            print(f"  Points: {info.points_count}")
            print(f"  Status: {info.status}")
            if hasattr(info, 'vectors_count'):
                print(f"  Vectors: {info.vectors_count}")
            if hasattr(info, 'indexed_vectors_count'):
                print(f"  Indexed: {info.indexed_vectors_count}")
        except Exception as e:
            print(f"\nCollection {COLLECTION_NAME}: not found or error — {e}")


if __name__ == "__main__":
    asyncio.run(main())
