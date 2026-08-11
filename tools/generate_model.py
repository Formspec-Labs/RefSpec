#!/usr/bin/env python3
"""Generate REF JSON schemas and Python record types from the CUE model.

The model is deliberately written in JSON-compatible CUE. JSON is a strict
subset of CUE, so the authoritative source remains usable by CUE tooling while
this generator needs only Python's standard library.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import tempfile
import zlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "model" / "ref-records.cue"
RULESPEC_DEPENDENCY = ROOT / "profiles" / "rulespec-dependency.json"
CONFORMANCE_ROOT = ROOT / "bindings" / "json" / "1.0"
SCHEMA_NAME = re.compile(r"^[a-z][a-z0-9-]*\.schema\.json$")


class ModelGenerationError(ValueError):
    """The authoritative model cannot generate a complete artifact set."""


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            separators=(",", ": "),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def load_model(path: Path) -> dict[str, Any]:
    try:
        model = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelGenerationError(f"cannot read JSON-compatible CUE model {path}: {exc}") from exc
    if not isinstance(model, dict):
        raise ModelGenerationError("model root must be an object")
    if model.get("modelVersion") != "1.0":
        raise ModelGenerationError("modelVersion must be '1.0'")
    schemas = model.get("schemas")
    if not isinstance(schemas, dict) or not schemas:
        raise ModelGenerationError("schemas must be a non-empty object")
    for filename, schema in schemas.items():
        if not isinstance(filename, str) or not SCHEMA_NAME.fullmatch(filename):
            raise ModelGenerationError(f"invalid generated schema filename: {filename!r}")
        if not isinstance(schema, dict):
            raise ModelGenerationError(f"schema {filename!r} must be an object")
        expected_id = f"https://refspec.org/bindings/json/1.0/schemas/{filename}"
        if schema.get("$id") != expected_id:
            raise ModelGenerationError(
                f"schema {filename!r} must use the canonical $id {expected_id!r}"
            )
    return model


def python_name(filename: str, schema: Mapping[str, Any]) -> str:
    explicit = schema.get("x-ref-python-name")
    if isinstance(explicit, str) and re.fullmatch(r"[A-Z][A-Za-z0-9]*", explicit):
        return explicit
    words = filename.removesuffix(".schema.json").split("-")
    return "".join(word[:1].upper() + word[1:] for word in words) + "Data"


def literal_annotation(values: list[object]) -> str:
    if not values:
        return "Any"
    if all(isinstance(value, str) for value in values):
        return "Literal[" + ", ".join(repr(value) for value in values) + "]"
    return "Any"


def schema_annotation(schema: object) -> str:
    if not isinstance(schema, dict):
        return "Any"
    if "const" in schema:
        return literal_annotation([schema["const"]])
    enum = schema.get("enum")
    if isinstance(enum, list):
        return literal_annotation(enum)
    for union_key in ("oneOf", "anyOf"):
        options = schema.get(union_key)
        if isinstance(options, list) and options:
            annotations = list(dict.fromkeys(schema_annotation(option) for option in options))
            return " | ".join(annotations)
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        annotations = [
            {
                "null": "None",
                "string": "str",
                "integer": "int",
                "number": "int | float",
                "boolean": "bool",
                "array": "list[Any]",
                "object": "dict[str, Any]",
            }.get(str(item), "Any")
            for item in schema_type
        ]
        return " | ".join(dict.fromkeys(annotations))
    if schema_type == "string":
        return "str"
    if schema_type == "integer":
        return "int"
    if schema_type == "number":
        return "int | float"
    if schema_type == "boolean":
        return "bool"
    if schema_type == "array":
        return f"list[{schema_annotation(schema.get('items'))}]"
    if schema_type == "object" or "properties" in schema:
        return "dict[str, Any]"
    if "$ref" in schema:
        # References include both scalar definitions and nested objects. Keep
        # the generated top-level type honest rather than guessing across files.
        return "Any"
    return "Any"


def inherited_required(schema: Mapping[str, Any]) -> set[str]:
    required = schema.get("required")
    return {str(value) for value in required} if isinstance(required, list) else set()


def schema_properties(schema: Mapping[str, Any]) -> tuple[dict[str, Any], set[str]]:
    properties: dict[str, Any] = {}
    required: set[str] = set()
    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for branch in all_of:
            if not isinstance(branch, dict) or "$ref" in branch:
                continue
            branch_properties = branch.get("properties")
            if isinstance(branch_properties, dict):
                properties.update(branch_properties)
            required.update(inherited_required(branch))
    own_properties = schema.get("properties")
    if isinstance(own_properties, dict):
        properties.update(own_properties)
    required.update(inherited_required(schema))
    return properties, required


def render_python_types(model: Mapping[str, Any], model_digest: str) -> bytes:
    schemas = model["schemas"]
    assert isinstance(schemas, dict)
    lines = [
        '"""Generated REF JSON Binding record types. Do not edit by hand."""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Any, Literal, NotRequired, Required",
        "",
        # `TypedDict` stays on typing_extensions: only that one keeps
        # `__required_keys__` correct for `Required`/`NotRequired` before 3.12.
        "from typing_extensions import TypedDict",
        "",
        f'MODEL_SHA256 = "sha256:{model_digest}"',
        "",
        "",
        "class REFRecordData(TypedDict, total=False):",
        "    id: Required[str]",
        "    type: Required[str]",
        "    recordedAt: Required[str]",
        "    recordedBy: Required[str]",
        "    schemaVersion: Required[str]",
        "    operationalState: Required[str]",
        "",
        "",
    ]
    exported = ["REFRecordData"]
    for filename, schema in schemas.items():
        if filename in {"common.schema.json", "ref-record.schema.json"}:
            continue
        assert isinstance(schema, dict)
        name = python_name(filename, schema)
        properties, required = schema_properties(schema)
        lines.append(f"class {name}(REFRecordData, total=False):")
        if not properties:
            lines.append("    pass")
        for property_name, property_schema in properties.items():
            if property_name in {
                "id",
                "type",
                "recordedAt",
                "recordedBy",
                "schemaVersion",
                "operationalState",
            }:
                continue
            annotation = schema_annotation(property_schema)
            marker = "Required" if property_name in required else "NotRequired"
            lines.append(f"    {property_name}: {marker}[{annotation}]")
        lines.extend(["", ""])
        exported.append(name)
    lines.append("__all__ = [")
    lines.extend(f'    "{name}",' for name in sorted(exported))
    lines.extend(["]", ""])
    return "\n".join(lines).encode("utf-8")


def render_embedded_schemas(model: Mapping[str, Any], model_digest: str) -> bytes:
    schemas = model["schemas"]
    encoded = json.dumps(
        schemas,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    compressed = base64.b64encode(zlib.compress(encoded, level=9)).decode("ascii")
    chunks = [compressed[index : index + 100] for index in range(0, len(compressed), 100)]
    lines = [
        '"""Generated embedded REF schemas. Do not edit by hand."""',
        "",
        "from __future__ import annotations",
        "",
        "import base64",
        "import json",
        "import zlib",
        "from typing import Any",
        "",
        f'MODEL_SHA256 = "sha256:{model_digest}"',
        "",
        "_COMPRESSED_SCHEMA_BUNDLE = (",
        *(f'    "{chunk}"' for chunk in chunks),
        ")",
        "",
        "",
        "def load_schema_bundle() -> dict[str, dict[str, Any]]:",
        '    """Return a new copy of every generated JSON Schema."""',
        "",
        "    payload = zlib.decompress(base64.b64decode(_COMPRESSED_SCHEMA_BUNDLE))",
        "    value = json.loads(payload)",
        "    assert isinstance(value, dict)",
        "    return value",
        "",
        "",
        '__all__ = ["MODEL_SHA256", "load_schema_bundle"]',
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def render_embedded_rulespec_dependency(payload: bytes) -> bytes:
    """Embed the exact trusted dependency pin for installed-package gates."""

    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ModelGenerationError(
            f"cannot read Rulespec dependency manifest: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise ModelGenerationError(
            "Rulespec dependency manifest root must be an object"
        )
    encoded = base64.b64encode(payload).decode("ascii")
    chunks = [
        encoded[index : index + 100]
        for index in range(0, len(encoded), 100)
    ]
    digest = hashlib.sha256(payload).hexdigest()
    lines = [
        '"""Generated embedded Rulespec dependency pin. Do not edit by hand."""',
        "",
        "from __future__ import annotations",
        "",
        "import base64",
        "import json",
        "from typing import Any",
        "",
        f'RULESPEC_DEPENDENCY_SHA256 = "sha256:{digest}"',
        "",
        "_ENCODED_RULESPEC_DEPENDENCY = (",
        *(f'    "{chunk}"' for chunk in chunks),
        ")",
        "",
        "RULESPEC_DEPENDENCY_BYTES = base64.b64decode(",
        "    _ENCODED_RULESPEC_DEPENDENCY",
        ")",
        "",
        "",
        "def load_rulespec_dependency() -> dict[str, Any]:",
        '    """Return a new copy of the embedded dependency manifest."""',
        "",
        "    value = json.loads(RULESPEC_DEPENDENCY_BYTES)",
        "    assert isinstance(value, dict)",
        "    return value",
        "",
        "",
        "__all__ = [",
        '    "RULESPEC_DEPENDENCY_BYTES",',
        '    "RULESPEC_DEPENDENCY_SHA256",',
        '    "load_rulespec_dependency",',
        "]",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def conformance_asset_bytes() -> dict[str, bytes]:
    """Load the executable fixture corpus needed by an installed CLI."""

    paths = [
        *sorted((CONFORMANCE_ROOT / "fixtures").rglob("*.json")),
        CONFORMANCE_ROOT
        / "tests"
        / "requirement-to-test-manifest.json",
    ]
    assets: dict[str, bytes] = {}
    for path in paths:
        if not path.is_file():
            raise ModelGenerationError(
                f"conformance asset does not exist: {path}"
            )
        relative = path.relative_to(CONFORMANCE_ROOT).as_posix()
        assets[relative] = path.read_bytes()
    return assets


def render_embedded_conformance_assets(
    assets: Mapping[str, bytes],
) -> bytes:
    """Embed exact fixtures, including deliberately malformed raw JSON."""

    encoded_assets = {
        relative: base64.b64encode(payload).decode("ascii")
        for relative, payload in sorted(assets.items())
    }
    encoded = json.dumps(
        encoded_assets,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    compressed = base64.b64encode(
        zlib.compress(encoded, level=9)
    ).decode("ascii")
    chunks = [
        compressed[index : index + 100]
        for index in range(0, len(compressed), 100)
    ]
    digest = hashlib.sha256(encoded).hexdigest()
    lines = [
        '"""Generated embedded REF conformance assets. Do not edit by hand."""',
        "",
        "from __future__ import annotations",
        "",
        "import base64",
        "import json",
        "import zlib",
        "",
        f'CONFORMANCE_ASSET_BUNDLE_SHA256 = "sha256:{digest}"',
        "",
        "_COMPRESSED_CONFORMANCE_ASSETS = (",
        *(f'    "{chunk}"' for chunk in chunks),
        ")",
        "",
        "",
        "def _load_encoded_assets() -> dict[str, str]:",
        "    payload = zlib.decompress(",
        "        base64.b64decode(_COMPRESSED_CONFORMANCE_ASSETS)",
        "    )",
        "    value = json.loads(payload)",
        "    assert isinstance(value, dict)",
        "    return value",
        "",
        "",
        "_ENCODED_ASSETS = _load_encoded_assets()",
        "",
        "",
        "def conformance_asset_paths(prefix: str = \"\") -> tuple[str, ...]:",
        '    """Return embedded POSIX paths under an optional prefix."""',
        "",
        "    return tuple(",
        "        path for path in sorted(_ENCODED_ASSETS)",
        "        if path.startswith(prefix)",
        "    )",
        "",
        "",
        "def load_conformance_asset(path: str) -> bytes:",
        '    """Return one exact embedded conformance asset."""',
        "",
        "    try:",
        "        encoded = _ENCODED_ASSETS[path]",
        "    except KeyError as error:",
        "        raise FileNotFoundError(path) from error",
        "    return base64.b64decode(encoded)",
        "",
        "",
        "__all__ = [",
        '    "CONFORMANCE_ASSET_BUNDLE_SHA256",',
        '    "conformance_asset_paths",',
        '    "load_conformance_asset",',
        "]",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def artifact_bytes(model: Mapping[str, Any], model_bytes: bytes) -> dict[str, bytes]:
    schemas = model["schemas"]
    assert isinstance(schemas, dict)
    model_digest = hashlib.sha256(model_bytes).hexdigest()
    artifacts = {
        f"bindings/json/1.0/schemas/{filename}": canonical_json_bytes(schema)
        for filename, schema in schemas.items()
    }
    artifacts["src/refspec/generated_types.py"] = render_python_types(model, model_digest)
    artifacts["src/refspec/generated_schemas.py"] = render_embedded_schemas(
        model,
        model_digest,
    )
    try:
        dependency_payload = RULESPEC_DEPENDENCY.read_bytes()
    except OSError as exc:
        raise ModelGenerationError(
            f"cannot read Rulespec dependency manifest: {exc}"
        ) from exc
    artifacts["src/refspec/generated_rulespec_dependency.py"] = (
        render_embedded_rulespec_dependency(dependency_payload)
    )
    artifacts["src/refspec/generated_conformance_assets.py"] = (
        render_embedded_conformance_assets(conformance_asset_bytes())
    )
    manifest = {
        "schemaVersion": "1.0",
        "source": "model/ref-records.cue",
        "sourceSha256": f"sha256:{model_digest}",
        "artifacts": {
            relative: f"sha256:{hashlib.sha256(content).hexdigest()}"
            for relative, content in sorted(artifacts.items())
        },
    }
    artifacts["model/generated-artifacts.json"] = canonical_json_bytes(manifest)
    return artifacts


def compare_or_write(artifacts: Mapping[str, bytes], *, check: bool) -> list[str]:
    drift: list[str] = []
    for relative, expected in artifacts.items():
        path = ROOT / relative
        actual = path.read_bytes() if path.is_file() else None
        if actual == expected:
            continue
        if check:
            drift.append(relative)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(expected)
    return drift


def verify_idempotence(model_path: Path, artifacts: Mapping[str, bytes]) -> None:
    # Render twice from independently parsed model values. This catches stateful
    # or ordering-dependent generation even when the current tree is in sync.
    with tempfile.TemporaryDirectory(prefix="refspec-model-") as directory:
        copy = Path(directory) / model_path.name
        copy.write_bytes(model_path.read_bytes())
        second_model = load_model(copy)
        second = artifact_bytes(second_model, copy.read_bytes())
    if dict(artifacts) != second:
        raise ModelGenerationError("generation is not idempotent")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report generated-file drift without changing the worktree",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    model_path = args.model.resolve()
    try:
        model_bytes = model_path.read_bytes()
        model = load_model(model_path)
        artifacts = artifact_bytes(model, model_bytes)
        verify_idempotence(model_path, artifacts)
        drift = compare_or_write(artifacts, check=args.check)
    except (OSError, ModelGenerationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if drift:
        for relative in drift:
            print(f"DRIFT: {relative}", file=sys.stderr)
        return 1
    action = "verified" if args.check else "generated"
    print(f"RefSpec model: {len(artifacts) - 1} artifacts {action}; generation is idempotent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
