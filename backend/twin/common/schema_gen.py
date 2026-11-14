"""Writes `shared/ws_schema.json`, the JSON Schema of every WebSocket message (PROMPT.md §6.1). The frontend
types are generated from this file.

    python -m twin.common.schema_gen          # write the file
    python -m twin.common.schema_gen --check  # exit 1 if it is out of date
"""

import argparse
import json
import sys
from pathlib import Path

from pydantic import TypeAdapter

from twin.common.config import REPO_ROOT
from twin.common.ws import SCHEMA_VERSION, ServerMessage

SCHEMA_PATH = REPO_ROOT / "shared" / "ws_schema.json"


def render() -> str:
    schema = TypeAdapter(ServerMessage).json_schema(mode="serialization", by_alias=True)
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ServerMessage",
        "description": f"Hospital Twin WebSocket messages, schema version {SCHEMA_VERSION}",
        **schema,
    }
    return json.dumps(schema, indent=1, sort_keys=True, ensure_ascii=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate shared/ws_schema.json")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--path", type=Path, default=SCHEMA_PATH)
    args = parser.parse_args(argv)
    path: Path = args.path
    text = render()
    if args.check:
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            print(f"{path} is out of date. Run: python -m twin.common.schema_gen", file=sys.stderr)
            return 1
        print(f"{path} is up to date")
        return 0
    path.write_text(text, encoding="utf-8")
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point; main() is tested directly
    sys.exit(main())
