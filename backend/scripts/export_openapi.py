"""Write the FastAPI OpenAPI document to contracts/openapi.json.

The frontend generates its API types from that file. Run from backend/:
    uv run python -m scripts.export_openapi
"""

import json
from pathlib import Path

from app.main import create_app

OUT = Path(__file__).resolve().parents[2] / "contracts" / "openapi.json"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
