"""Capture normalized registry output receipts while direct tests execute."""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import importlib
import inspect
import json
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from pathlib import Path
from typing import Any

_MODULES: dict[str, dict[str, Any]] = {}
_CALL_DEPTH: ContextVar[int] = ContextVar("registry_receipt_call_depth", default=0)
_COUNT_FIELDS = frozenset(
    {
        "assignments",
        "codes",
        "concepts",
        "entries",
        "fields",
        "identifiers",
        "items",
        "labels",
        "mappings",
        "members",
        "observations",
        "records",
        "relations",
        "resources",
        "rows",
        "terms",
        "values",
    }
)
_MAX_SOURCE_EVIDENCE_SEQUENCE_ITEMS = 100


def pytest_addoption(parser: Any) -> None:
    group = parser.getgroup("refspec-registry-receipts")
    group.addoption("--registry-receipt-output", type=Path)


def _registry_module_names() -> tuple[str, ...]:
    registry = Path(__file__).resolve().parents[1] / "src" / "refspec" / "registry"
    return tuple(
        sorted(
            path.relative_to(registry).with_suffix("").as_posix()
            for path in registry.rglob("*.py")
            if path.name != "__init__.py"
        )
    )


def _type_name(value: object) -> str:
    value_type = type(value)
    return f"{value_type.__module__}.{value_type.__qualname__}"


def _shape(value: object, *, depth: int = 0) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return type(value).__name__
    if depth >= 3:
        return _type_name(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            "type": _type_name(value),
            "fields": {
                field.name: _shape(getattr(value, field.name), depth=depth + 1)
                for field in dataclasses.fields(value)
            },
        }
    if isinstance(value, Mapping):
        keys = sorted(str(key) for key in value)[:20]
        sample_value = next(iter(value.values()), None)
        return {
            "type": "mapping",
            "count": len(value),
            "keys": keys,
            "valueShape": _shape(sample_value, depth=depth + 1),
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return {
            "type": type(value).__name__,
            "count": len(value),
            "itemShape": _shape(value[0], depth=depth + 1) if value else None,
        }
    if isinstance(value, (bytes, bytearray)):
        return {"type": type(value).__name__, "byteLength": len(value)}
    return _type_name(value)


def _counts(value: object, *, depth: int = 0) -> dict[str, int]:
    if depth >= 3:
        return {}
    result: dict[str, int] = {}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            child = getattr(value, field.name)
            if field.name in _COUNT_FIELDS and isinstance(child, (Mapping, Sequence)) and not isinstance(
                child, (bytes, bytearray, str)
            ):
                result[field.name] = len(child)
            for name, count in _counts(child, depth=depth + 1).items():
                result.setdefault(f"{field.name}.{name}", count)
    elif isinstance(value, Mapping):
        for key, child in list(value.items())[:20]:
            if str(key) in _COUNT_FIELDS and isinstance(child, (Mapping, Sequence)) and not isinstance(
                child, (bytes, bytearray, str)
            ):
                result[str(key)] = len(child)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        result["items"] = len(value)
    return dict(sorted(result.items()))


def _sample(value: object, *, depth: int = 0) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 240 else value[:237] + "..."
    if depth >= 3:
        return f"<{_type_name(value)}>"
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _sample(getattr(value, field.name), depth=depth + 1)
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {
            str(key): _sample(child, depth=depth + 1)
            for key, child in list(value.items())[:5]
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [_sample(child, depth=depth + 1) for child in value[:2]]
    if isinstance(value, (bytes, bytearray)):
        return {
            "byteLength": len(value),
            "sha256": "sha256:" + hashlib.sha256(value).hexdigest(),
        }
    return f"<{_type_name(value)}>"


def _source_evidence(value: object, result: dict[str, set[Any]], *, depth: int = 0) -> None:
    if depth >= 6 or value is None:
        return
    if isinstance(value, Path):
        rendered = str(value)
        if "pytest-of-" not in rendered and "/refspec-registry-audit-" not in rendered:
            result["paths"].add(rendered)
        return
    if isinstance(value, str):
        if value.startswith(("https://", "http://")):
            result["urls"].add(value)
        elif value.startswith("sha256:") and len(value) == 71:
            result["digests"].add(value)
        return
    if isinstance(value, bytes):
        result["byteLengths"].add(len(value))
        result["digests"].add("sha256:" + hashlib.sha256(value).hexdigest())
        return
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            child = getattr(value, field.name)
            if field.name in {"byte_length", "source_byte_length"} and isinstance(child, int):
                result["byteLengths"].add(child)
            _source_evidence(child, result, depth=depth + 1)
        return
    if isinstance(value, Mapping):
        for key, child in list(value.items())[:100]:
            if str(key) in {"byteLength", "sourceByteLength", "source_bytes"} and isinstance(child, int):
                result["byteLengths"].add(child)
            _source_evidence(child, result, depth=depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytearray, str)):
        # A source portfolio may legitimately contain more than ten pinned
        # artifacts (the EuroVoc alignment portfolio contains seventeen).
        # Keep the walk bounded, but do not silently drop ordinary portfolio
        # members from the fail-closed real-data receipt.
        for child in value[:_MAX_SOURCE_EVIDENCE_SEQUENCE_ITEMS]:
            _source_evidence(child, result, depth=depth + 1)


def _record(module_name: str, function_name: str, arguments: tuple[Any, ...], result_value: object) -> None:
    module = _MODULES[module_name]
    executions = module["executions"]
    evidence: dict[str, set[Any]] = {
        "paths": set(),
        "urls": set(),
        "digests": set(),
        "byteLengths": set(),
    }
    _source_evidence(arguments, evidence)
    _source_evidence(result_value, evidence)
    execution = {
        "function": function_name,
        "counts": _counts(result_value),
        "shape": _shape(result_value),
        "sample": _sample(result_value),
        "sourceEvidence": {key: sorted(values) for key, values in evidence.items()},
    }

    def evidence_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
        """Group repeat calls without combining distinct source artifacts."""

        source = candidate.get("sourceEvidence", {})
        digests = tuple(source.get("digests", ()))
        if digests:
            return (candidate.get("function"), "digests", digests)
        return (
            candidate.get("function"),
            "locations",
            tuple(source.get("paths", ())),
            tuple(source.get("urls", ())),
            tuple(source.get("byteLengths", ())),
        )

    def evidence_strength(candidate: Mapping[str, Any]) -> tuple[int, int, int, int, int, str]:
        source = candidate.get("sourceEvidence", {})
        byte_lengths = source.get("byteLengths", ())
        locations = (*source.get("paths", ()), *source.get("urls", ()))
        publisher_locations = sum(
            isinstance(location, str)
            and location.startswith(("https://", "http://"))
            and "example.test" not in location
            for location in locations
        )
        example_locations = sum(
            isinstance(location, str) and "example.test" in location
            for location in locations
        )
        return (
            sum(candidate.get("counts", {}).values()),
            publisher_locations,
            -example_locations,
            max(byte_lengths, default=0),
            len(locations),
            json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )

    key = evidence_key(execution)
    matching_index = next(
        (index for index, existing in enumerate(executions) if evidence_key(existing) == key),
        None,
    )
    if matching_index is None:
        executions.append(execution)
    elif evidence_strength(execution) > evidence_strength(executions[matching_index]):
        executions[matching_index] = execution


def _call_and_record(
    module_name: str,
    function_name: str,
    function: Any,
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
) -> Any:
    """Record one test-facing production call, not every nested helper call."""

    depth = _CALL_DEPTH.get()
    token = _CALL_DEPTH.set(depth + 1)
    try:
        result = function(*args, **kwargs)
    finally:
        _CALL_DEPTH.reset(token)
    if depth == 0:
        _record(module_name, function_name, (*args, dict(kwargs)), result)
    return result


def _wrap_module(module_name: str) -> None:
    qualified_name = "refspec.registry." + module_name.replace("/", ".")
    module = importlib.import_module(qualified_name)
    _MODULES[module_name] = {"module": f"{module_name}.py", "executions": []}
    for function_name, function in tuple(vars(module).items()):
        if function_name.startswith("_") or not inspect.isfunction(function) or function.__module__ != qualified_name:
            continue

        @functools.wraps(function)
        def wrapped(*args: Any, __function: Any = function, __name: str = function_name, **kwargs: Any) -> Any:
            return _call_and_record(module_name, __name, __function, args, kwargs)

        setattr(module, function_name, wrapped)

    for class_name, class_value in tuple(vars(module).items()):
        if (
            class_name.startswith("_")
            or not inspect.isclass(class_value)
            or class_value.__module__ != qualified_name
        ):
            continue
        for method_name, descriptor in tuple(vars(class_value).items()):
            if method_name.startswith("_") and method_name != "__call__":
                continue
            descriptor_type: type | None = None
            if isinstance(descriptor, staticmethod):
                method = descriptor.__func__
                descriptor_type = staticmethod
            elif isinstance(descriptor, classmethod):
                method = descriptor.__func__
                descriptor_type = classmethod
            elif inspect.isfunction(descriptor):
                method = descriptor
            else:
                continue
            if inspect.iscoroutinefunction(method):
                continue

            @functools.wraps(method)
            def wrapped_method(
                *args: Any,
                __method: Any = method,
                __name: str = f"{class_name}.{method_name}",
                **kwargs: Any,
            ) -> Any:
                return _call_and_record(module_name, __name, __method, args, kwargs)

            replacement = descriptor_type(wrapped_method) if descriptor_type is not None else wrapped_method
            setattr(class_value, method_name, replacement)


def pytest_configure(config: Any) -> None:
    if config.getoption("--registry-receipt-output") is None:
        return
    for module_name in _registry_module_names():
        _wrap_module(module_name)


def pytest_unconfigure(config: Any) -> None:
    output = config.getoption("--registry-receipt-output")
    if output is None:
        return
    payload = {
        "format": "refspec-registry-execution-receipts/v1",
        "moduleCount": len(_MODULES),
        "modules": [
            {
                "module": module["module"],
                "executions": sorted(
                    module["executions"],
                    key=lambda execution: (
                        execution["function"],
                        tuple(execution.get("sourceEvidence", {}).get("digests", ())),
                        tuple(execution.get("sourceEvidence", {}).get("urls", ())),
                        json.dumps(execution, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    ),
                ),
            }
            for module in _MODULES.values()
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
