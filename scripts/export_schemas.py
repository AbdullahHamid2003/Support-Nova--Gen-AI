"""Export the GenAI structured-output JSON Schemas (schemas/ai/*.schema.json) from the Pydantic
contracts in backend/src/supportnova/genai_pipeline/schemas.py.

Run from the repository root:  python scripts/export_schemas.py [--check]
--check exits non-zero when the committed files differ from the models (CI / pre-commit use).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from supportnova.genai_pipeline.schemas import MODELS, generate_schema


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="only verify the committed files are up to date")
    args = parser.parse_args()
    out_dir = ROOT / "schemas" / "ai"
    out_dir.mkdir(parents=True, exist_ok=True)
    stale = []
    for name in MODELS:
        path = out_dir / f"{name}.schema.json"
        content = json.dumps(generate_schema(name), indent=2, sort_keys=False) + "\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(path.name)
        else:
            path.write_text(content, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        print("stale schema files:", ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
