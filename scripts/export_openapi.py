"""Export the API contract and generate TypeScript types for the frontend.

Usage:
    ./.venv/bin/python -m scripts.export_openapi
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402

DOCS = ROOT / "docs" / "architecture" / "openapi.json"
TS_OUT = ROOT / "frontend" / "src" / "types" / "generated.ts"

TS_PRIMITIVES = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "null": "null",
}


def ts_type(schema: dict[str, Any] | None, *, indent: str = "  ") -> str:
    if not schema:
        return "unknown"
    if "$ref" in schema:
        return schema["$ref"].split("/")[-1]
    if "anyOf" in schema or "oneOf" in schema:
        variants = [ts_type(v, indent=indent) for v in schema.get("anyOf") or schema.get("oneOf") or []]
        return " | ".join(dict.fromkeys(variants)) or "unknown"
    if "enum" in schema:
        return " | ".join(json.dumps(str(value), ensure_ascii=False) for value in schema["enum"])
    kind = schema.get("type")
    if isinstance(kind, list):
        return " | ".join(ts_type({"type": k}, indent=indent) for k in kind)
    if kind == "array":
        return f"Array<{ts_type(schema.get('items'), indent=indent)}>"
    if kind == "object" or "properties" in schema:
        properties = schema.get("properties") or {}
        if not properties:
            additional = schema.get("additionalProperties")
            if isinstance(additional, dict):
                return f"Record<string, {ts_type(additional, indent=indent)}>"
            return "Record<string, unknown>"
        lines = ["{"]
        required = set(schema.get("required") or [])
        for name, sub in properties.items():
            optional = "" if name in required else "?"
            lines.append(f"{indent}{json.dumps(name, ensure_ascii=False)}{optional}: {ts_type(sub, indent=indent + '  ')};")
        lines.append(indent[:-2] + "}")
        return "\n".join(lines)
    if kind in TS_PRIMITIVES:
        return TS_PRIMITIVES[kind]
    return "unknown"


def generate_types(spec: dict[str, Any]) -> str:
    lines = [
        "/**",
        " * 由 scripts/export_openapi.py 从 FastAPI 的 OpenAPI 契约自动生成。",
        " * 请勿手工修改：重新运行 `./.venv/bin/python -m scripts.export_openapi` 即可。",
        " */",
        "",
    ]
    for name, schema in sorted((spec.get("components") or {}).get("schemas", {}).items()):
        body = ts_type(schema)
        lines.append(f"export type {name} = {body};")
        lines.append("")
    lines.append("export interface ApiPaths {")
    for path, operations in sorted(spec.get("paths", {}).items()):
        methods = ", ".join(sorted(m.upper() for m in operations if m in {"get", "post", "put", "patch", "delete"}))
        lines.append(f"  /** {methods} */")
        lines.append(f"  {json.dumps(path)}: {methods!r};")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    app = create_app(get_settings())
    spec = app.openapi()
    DOCS.parent.mkdir(parents=True, exist_ok=True)
    DOCS.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    TS_OUT.parent.mkdir(parents=True, exist_ok=True)
    TS_OUT.write_text(generate_types(spec), encoding="utf-8")
    print(f"wrote {DOCS.relative_to(ROOT)} ({len(spec['paths'])} paths)")
    print(f"wrote {TS_OUT.relative_to(ROOT)} ({(spec.get('components') or {}).get('schemas') and len(spec['components']['schemas'])} schemas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
