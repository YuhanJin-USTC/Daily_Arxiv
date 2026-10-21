"""Rebuild public researcher matches without editing historical papers."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "daily_arxiv"))
from ai.config import settings, subscribed_categories
from ai.storage import write_json
from daily_arxiv.researchers import build_index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_index(args.data, settings()["researchers"], subscribed_categories())
    write_json(args.output, result)
    print(f"Indexed {len(result['papers'])} matched papers")


if __name__ == "__main__":
    main()
