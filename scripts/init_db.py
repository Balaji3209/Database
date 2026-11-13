"""Regenerate synthetic data, rebuild the SQLite database and print the headline results.

Usage:  python scripts/init_db.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dboptima.config import DB_PATH  # noqa: E402
from dboptima.data_generator import generate  # noqa: E402
from dboptima.pipeline import run  # noqa: E402


def main() -> None:
    frames = generate()
    print("Synthetic datasets:")
    for name, df in frames.items():
        print(f"  {name:<24} {len(df):>5} rows")
    a = run()
    print(f"\nSQLite database: {DB_PATH}")
    print("\nSuccess measures:")
    for v in a.kpis.values():
        print(f"  [{'MET' if v['met'] else 'NOT MET'}] {v['name']}: {v['actual']}% (target {v['target']}) - {v['detail']}")
    print("\nRecommendations:", a.recs.recommended_action.value_counts().to_dict())
    print("Readiness:      ", a.recs.readiness.value_counts().to_dict())


if __name__ == "__main__":
    main()
