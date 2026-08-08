"""Lossless, closed registry claim releases backed by Parquet.

Registry-specific readers finish their parsing and derivation before this
boundary.  A bundle then carries source-shaped claims, exact raw captures, and
the recipes and limitations needed to interpret those claims.  Consumers open
the bundle with an externally supplied manifest digest; they do not import the
producer's parser.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal, cast

import pyarrow as pa
import pyarrow.parquet as pq
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    sha256_digest,
)

REGISTRY_CLAIM_RELEASE_VERSION = "1.0"
REGISTRY_CLAIM_RELEASE_KIND = "registryClaimRelease"
REGISTRY_CLAIM_RELEASE_MEDIA_TYPE = (
    "application/vnd.refspec.registry-claim-release+json"
)
CLAIMS_MEDIA_TYPE = "application/vnd.apache.parquet"
MANIFEST_FILE = "release-manifest.json"
CLAIMS_FILE = "claims.parquet"
SCHEMA_DIRECTORY = "schemas"
CLAIM_RECORD_SCHEMA_FILE = f"{SCHEMA_DIRECTORY}/registry-claim.schema.json"
MANIFEST_SCHEMA_FILE = (
    f"{SCHEMA_DIRECTORY}/registry-claim-release-manifest.schema.json"
)
PARQUET_VERSION = "2.6"
ROW_GROUP_SIZE = 50_000
COMPRESSION = "zstd"
COMPRESSION_LEVEL = 9

ClaimObjectKind = Literal["iri", "literal"]
ClaimOrigin = Literal[
    "observed",
    "scraped",
    "normalized",
    "inferred",
    "extrapolated",
]

OBJECT_KINDS = frozenset({"iri", "literal"})
ORIGINS = frozenset(
    {"observed", "scraped", "normalized", "inferred", "extrapolated"}
)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:\S+$")


class RegistryClaimReleaseError(ValueError):
    """A registry claim release is incomplete, mutable, or inconsistent."""


_SCHEMA_SOURCE_ROOT = Path(__file__).with_name("schemas")
_SCHEMA_MEMBERS = (
    ("claimRecord", CLAIM_RECORD_SCHEMA_FILE),
    ("manifest", MANIFEST_SCHEMA_FILE),
)


def _schema_payload(logical_path: str) -> Mapping[str, Any]:
    source = _SCHEMA_SOURCE_ROOT / PurePosixPath(logical_path).name
    try:
        payload = json.loads(source.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RegistryClaimReleaseError(
            f"registry claim schema is unavailable or invalid: {logical_path}"
        ) from error
    if not isinstance(payload, Mapping):
        raise RegistryClaimReleaseError(
            f"registry claim schema must be an object: {logical_path}"
        )
    try:
        Draft202012Validator.check_schema(payload)
    except SchemaError as error:
        raise RegistryClaimReleaseError(
            f"registry claim schema is invalid: {logical_path}"
        ) from error
    return payload


def _schema_bytes(logical_path: str) -> bytes:
    return canonical_json_bytes(_schema_payload(logical_path))


CLAIM_RECORD_JSON_SCHEMA = _schema_payload(CLAIM_RECORD_SCHEMA_FILE)
MANIFEST_JSON_SCHEMA = _schema_payload(MANIFEST_SCHEMA_FILE)


def _claim_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("release_id", pa.string(), nullable=False),
            pa.field("subject", pa.string(), nullable=False),
            pa.field("predicate", pa.string(), nullable=False),
            pa.field("object_kind", pa.string(), nullable=False),
            pa.field("object_iri", pa.string()),
            pa.field("lexical_value", pa.string()),
            pa.field("language", pa.string()),
            pa.field("datatype", pa.string()),
            pa.field("source_record_id", pa.string(), nullable=False),
            pa.field("source_locator", pa.string(), nullable=False),
            pa.field("source_path", pa.string(), nullable=False),
            pa.field("source_digest", pa.string(), nullable=False),
            pa.field("origin", pa.string(), nullable=False),
            pa.field("recipe_id", pa.string(), nullable=False),
            pa.field("confidence", pa.string()),
            pa.field("limitation_ids", pa.list_(pa.string()), nullable=False),
        ]
    )


CLAIM_SCHEMA = _claim_schema()
CLAIM_COLUMNS = tuple(field.name for field in CLAIM_SCHEMA)


def _schema_descriptor(schema: pa.Schema) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "nullable": item.nullable,
            "type": str(item.type),
        }
        for item in schema
    ]


def _schema_digest(schema: pa.Schema) -> str:
    return sha256_digest(canonical_json_bytes(_schema_descriptor(schema)))


CLAIM_SCHEMA_DIGEST = _schema_digest(CLAIM_SCHEMA)


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RegistryClaimReleaseError(f"{label} must be non-empty text")
    return value


def _require_iri(value: object, label: str) -> str:
    iri = _require_text(value, label)
    if _ABSOLUTE_IRI.fullmatch(iri) is None:
        raise RegistryClaimReleaseError(f"{label} must be an absolute IRI")
    return iri


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RegistryClaimReleaseError(
            f"{label} must be sha256:<64 lowercase hex>"
        )
    return value


def _safe_relative_path(value: object, label: str) -> PurePosixPath:
    text = _require_text(value, label)
    posix = PurePosixPath(text)
    windows = PureWindowsPath(text)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or ".." in posix.parts
        or ".." in windows.parts
        or "\\" in text
        or text in {".", ".."}
    ):
        raise RegistryClaimReleaseError(f"{label} must be a safe relative path")
    return posix


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _logical_rows_digest(rows: Sequence[RegistryClaim]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(canonical_json_bytes(row.as_record()))
    return "sha256:" + digest.hexdigest()


@dataclass(frozen=True, slots=True)
class RegistryClaim:
    """One source-visible IRI or literal assertion with exact evidence."""

    release_id: str
    subject: str
    predicate: str
    object_kind: ClaimObjectKind
    source_record_id: str
    source_locator: str
    source_path: str
    source_digest: str
    origin: ClaimOrigin
    recipe_id: str
    object_iri: str | None = None
    lexical_value: str | None = None
    language: str | None = None
    datatype: str | None = None
    confidence: str | None = None
    limitation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_iri(self.release_id, "claim release_id")
        _require_iri(self.subject, "claim subject")
        _require_iri(self.predicate, "claim predicate")
        _require_iri(self.source_record_id, "claim source_record_id")
        _require_iri(self.source_locator, "claim source_locator")
        _require_text(self.source_path, "claim source_path")
        _require_digest(self.source_digest, "claim source_digest")
        _require_iri(self.recipe_id, "claim recipe_id")
        if self.object_kind not in OBJECT_KINDS:
            raise RegistryClaimReleaseError(
                f"unsupported claim object_kind: {self.object_kind!r}"
            )
        if self.origin not in ORIGINS:
            raise RegistryClaimReleaseError(
                f"unsupported claim origin: {self.origin!r}"
            )
        if self.object_kind == "iri":
            _require_iri(self.object_iri, "IRI claim object_iri")
            if any(
                value is not None
                for value in (self.lexical_value, self.language, self.datatype)
            ):
                raise RegistryClaimReleaseError(
                    "IRI claims must not carry literal fields"
                )
        else:
            if self.object_iri is not None:
                raise RegistryClaimReleaseError(
                    "literal claims must not carry object_iri"
                )
            if self.lexical_value is None:
                raise RegistryClaimReleaseError(
                    "literal claims must carry lexical_value"
                )
            if self.language is not None and self.datatype is not None:
                raise RegistryClaimReleaseError(
                    "literal claims must not carry both language and datatype"
                )
            if self.datatype is not None:
                _require_iri(self.datatype, "claim literal datatype")
        if self.confidence is not None:
            _require_text(self.confidence, "claim confidence")
        if tuple(sorted(set(self.limitation_ids))) != self.limitation_ids:
            raise RegistryClaimReleaseError(
                "claim limitation_ids must be sorted and unique"
            )
        for limitation_id in self.limitation_ids:
            _require_iri(limitation_id, "claim limitation_id")

    def sort_key(self) -> tuple[Any, ...]:
        return (
            self.release_id,
            self.subject,
            self.predicate,
            self.object_kind,
            self.object_iri or "",
            self.lexical_value if self.lexical_value is not None else "",
            self.language or "",
            self.datatype or "",
            self.source_record_id,
            self.source_locator,
            self.source_path,
            self.source_digest,
            self.origin,
            self.recipe_id,
            self.confidence or "",
            self.limitation_ids,
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "subject": self.subject,
            "predicate": self.predicate,
            "object_kind": self.object_kind,
            "object_iri": self.object_iri,
            "lexical_value": self.lexical_value,
            "language": self.language,
            "datatype": self.datatype,
            "source_record_id": self.source_record_id,
            "source_locator": self.source_locator,
            "source_path": self.source_path,
            "source_digest": self.source_digest,
            "origin": self.origin,
            "recipe_id": self.recipe_id,
            "confidence": self.confidence,
            "limitation_ids": list(self.limitation_ids),
        }

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> RegistryClaim:
        if set(value) != set(CLAIM_COLUMNS):
            raise RegistryClaimReleaseError(
                "claim row fields differ from the declared schema"
            )
        limitation_ids = value["limitation_ids"]
        if not isinstance(limitation_ids, Sequence) or isinstance(
            limitation_ids, (str, bytes)
        ):
            raise RegistryClaimReleaseError("claim limitation_ids must be an array")
        return cls(
            release_id=cast(str, value["release_id"]),
            subject=cast(str, value["subject"]),
            predicate=cast(str, value["predicate"]),
            object_kind=cast(ClaimObjectKind, value["object_kind"]),
            object_iri=cast(str | None, value["object_iri"]),
            lexical_value=cast(str | None, value["lexical_value"]),
            language=cast(str | None, value["language"]),
            datatype=cast(str | None, value["datatype"]),
            source_record_id=cast(str, value["source_record_id"]),
            source_locator=cast(str, value["source_locator"]),
            source_path=cast(str, value["source_path"]),
            source_digest=cast(str, value["source_digest"]),
            origin=cast(ClaimOrigin, value["origin"]),
            recipe_id=cast(str, value["recipe_id"]),
            confidence=cast(str | None, value["confidence"]),
            limitation_ids=tuple(cast(Sequence[str], limitation_ids)),
        )


@dataclass(frozen=True, slots=True)
class RegistryRawInput:
    """One exact raw capture copied into the closed release."""

    path: Path
    logical_path: str
    source_locator: str
    role: str = "publisherSource"
    archive_members: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        _safe_relative_path(self.logical_path, "raw input logical_path")
        if self.logical_path in {MANIFEST_FILE, CLAIMS_FILE}:
            raise RegistryClaimReleaseError(
                "raw input path collides with a required bundle member"
            )
        _require_iri(self.source_locator, "raw input source_locator")
        _require_text(self.role, "raw input role")
        if not self.path.is_file() or self.path.is_symlink():
            raise RegistryClaimReleaseError(
                f"raw input is missing or unsafe: {self.logical_path}"
            )


def _normalized_named_rows(
    values: Sequence[Mapping[str, Any]],
    *,
    label: str,
) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            raise RegistryClaimReleaseError(f"{label}[{index}] must be an object")
        row = json.loads(canonical_json_bytes(value))
        identifier = _require_iri(row.get("id"), f"{label}[{index}].id")
        if identifier in identifiers:
            raise RegistryClaimReleaseError(f"{label} repeats id {identifier}")
        identifiers.add(identifier)
        rows.append(row)
    return tuple(sorted(rows, key=lambda row: row["id"]))


def _write_claims(path: Path, claims: Sequence[RegistryClaim]) -> None:
    table = pa.Table.from_pylist(
        [claim.as_record() for claim in claims],
        schema=CLAIM_SCHEMA,
    )
    pq.write_table(
        table,
        path,
        version=PARQUET_VERSION,
        compression=COMPRESSION,
        compression_level=COMPRESSION_LEVEL,
        use_dictionary=False,
        write_statistics=True,
        data_page_version="2.0",
        row_group_size=ROW_GROUP_SIZE,
    )


def _raw_descriptor(value: RegistryRawInput, root: Path) -> dict[str, Any]:
    target = root / value.logical_path
    descriptor: dict[str, Any] = {
        "byteLength": target.stat().st_size,
        "mediaType": "application/octet-stream",
        "path": value.logical_path,
        "role": value.role,
        "sha256": _file_digest(target),
        "sourceLocator": value.source_locator,
    }
    if value.archive_members:
        descriptor["archiveMembers"] = _verify_archive_members(
            target,
            value.archive_members,
        )
    return descriptor


def _verify_archive_members(
    path: Path,
    values: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    descriptors: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(path) as archive:
            for index, value in enumerate(values):
                if not isinstance(value, Mapping) or set(value) != {
                    "byteLength",
                    "path",
                    "sha256",
                }:
                    raise RegistryClaimReleaseError(
                        f"archive member descriptor {index} is unsupported"
                    )
                member_path = _safe_relative_path(
                    value.get("path"),
                    f"archive member {index} path",
                ).as_posix()
                expected_size = value.get("byteLength")
                if not isinstance(expected_size, int) or expected_size < 0:
                    raise RegistryClaimReleaseError(
                        f"archive member {member_path} byteLength is invalid"
                    )
                expected_digest = _require_digest(
                    value.get("sha256"),
                    f"archive member {member_path} sha256",
                )
                try:
                    member = archive.getinfo(member_path)
                except KeyError as error:
                    raise RegistryClaimReleaseError(
                        f"archive member is missing: {member_path}"
                    ) from error
                if member.is_dir() or member.file_size != expected_size:
                    raise RegistryClaimReleaseError(
                        f"archive member size differs: {member_path}"
                    )
                digest = hashlib.sha256()
                with archive.open(member) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                if "sha256:" + digest.hexdigest() != expected_digest:
                    raise RegistryClaimReleaseError(
                        f"archive member digest differs: {member_path}"
                    )
                descriptors.append(
                    {
                        "byteLength": expected_size,
                        "path": member_path,
                        "sha256": expected_digest,
                    }
                )
    except zipfile.BadZipFile as error:
        raise RegistryClaimReleaseError(
            f"raw input is not a valid ZIP archive: {path.name}"
        ) from error
    if descriptors != sorted(descriptors, key=lambda item: item["path"]):
        raise RegistryClaimReleaseError("archive member paths must be sorted")
    paths = [item["path"] for item in descriptors]
    if len(set(paths)) != len(paths):
        raise RegistryClaimReleaseError("archive member paths must be unique")
    return descriptors


def _manifest_payload(
    *,
    release_id: str,
    release_key: str,
    issued: str,
    release_scope: Mapping[str, Any],
    language_scope: Mapping[str, Any],
    recipes: Sequence[Mapping[str, Any]],
    limitations: Sequence[Mapping[str, Any]],
    claims: Sequence[RegistryClaim],
    raw_inputs: Sequence[RegistryRawInput],
    root: Path,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    claims_path = root / CLAIMS_FILE
    origin_counts = Counter(claim.origin for claim in claims)
    object_counts = Counter(claim.object_kind for claim in claims)
    return {
        "claimTable": {
            "byteLength": claims_path.stat().st_size,
            "logicalDigest": _logical_rows_digest(claims),
            "mediaType": CLAIMS_MEDIA_TYPE,
            "objectKindCounts": dict(sorted(object_counts.items())),
            "originCounts": dict(sorted(origin_counts.items())),
            "path": CLAIMS_FILE,
            "rowCount": len(claims),
            "schema": _schema_descriptor(CLAIM_SCHEMA),
            "schemaDigest": CLAIM_SCHEMA_DIGEST,
            "sha256": _file_digest(claims_path),
        },
        "issued": issued,
        "languageScope": dict(language_scope),
        "limitations": list(limitations),
        "mediaType": REGISTRY_CLAIM_RELEASE_MEDIA_TYPE,
        "metadata": dict(metadata),
        "packageKind": REGISTRY_CLAIM_RELEASE_KIND,
        "rawInputs": [_raw_descriptor(value, root) for value in raw_inputs],
        "recipes": list(recipes),
        "releaseId": release_id,
        "releaseKey": release_key,
        "releaseScope": dict(release_scope),
        "schemaVersion": REGISTRY_CLAIM_RELEASE_VERSION,
        "schemas": [
            {
                "byteLength": (root / path).stat().st_size,
                "mediaType": "application/schema+json",
                "path": path,
                "role": role,
                "sha256": _file_digest(root / path),
            }
            for role, path in _SCHEMA_MEMBERS
        ],
    }


def build_registry_claim_release(
    output: Path,
    *,
    release_id: str,
    release_key: str,
    issued: str,
    release_scope: Mapping[str, Any],
    language_scope: Mapping[str, Any],
    recipes: Sequence[Mapping[str, Any]],
    limitations: Sequence[Mapping[str, Any]] = (),
    claims: Iterable[RegistryClaim],
    raw_inputs: Sequence[RegistryRawInput],
    metadata: Mapping[str, Any] | None = None,
) -> RegistryClaimReleaseView:
    """Write one immutable release and reopen it through the verified reader."""

    if output.exists() or output.is_symlink():
        raise RegistryClaimReleaseError(
            f"refusing to replace existing release: {output}"
        )
    _require_iri(release_id, "release_id")
    _require_text(release_key, "release_key")
    _require_text(issued, "issued")
    if not raw_inputs:
        raise RegistryClaimReleaseError("registry claim release requires raw inputs")
    recipe_rows = _normalized_named_rows(recipes, label="recipes")
    limitation_rows = _normalized_named_rows(limitations, label="limitations")
    recipe_ids = {row["id"] for row in recipe_rows}
    limitation_ids = {row["id"] for row in limitation_rows}
    claim_rows = tuple(sorted(claims, key=RegistryClaim.sort_key))
    if not claim_rows:
        raise RegistryClaimReleaseError("registry claim release requires claims")
    if any(claim.release_id != release_id for claim in claim_rows):
        raise RegistryClaimReleaseError("claim release_id differs from the bundle")
    unknown_recipes = sorted({row.recipe_id for row in claim_rows} - recipe_ids)
    unknown_limitations = sorted(
        {
            limitation
            for row in claim_rows
            for limitation in row.limitation_ids
        }
        - limitation_ids
    )
    if unknown_recipes or unknown_limitations:
        raise RegistryClaimReleaseError(
            "claims reference undeclared recipes or limitations: "
            f"recipes={unknown_recipes}, limitations={unknown_limitations}"
        )
    ordered_inputs = tuple(sorted(raw_inputs, key=lambda value: value.logical_path))
    logical_paths = [value.logical_path for value in ordered_inputs]
    if len(set(logical_paths)) != len(logical_paths):
        raise RegistryClaimReleaseError("raw input paths must be unique")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent)
    )
    try:
        for _, logical_path in _SCHEMA_MEMBERS:
            target = temporary / logical_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_schema_bytes(logical_path))
        for raw_input in ordered_inputs:
            target = temporary / raw_input.logical_path
            target.parent.mkdir(parents=True, exist_ok=True)
            with raw_input.path.open("rb") as source, target.open("xb") as sink:
                shutil.copyfileobj(source, sink, length=1024 * 1024)
        _write_claims(temporary / CLAIMS_FILE, claim_rows)
        manifest = _manifest_payload(
            release_id=release_id,
            release_key=release_key,
            issued=issued,
            release_scope=release_scope,
            language_scope=language_scope,
            recipes=recipe_rows,
            limitations=limitation_rows,
            claims=claim_rows,
            raw_inputs=ordered_inputs,
            root=temporary,
            metadata={} if metadata is None else metadata,
        )
        (temporary / MANIFEST_FILE).write_bytes(canonical_json_bytes(manifest))
        manifest_digest = _file_digest(temporary / MANIFEST_FILE)
        RegistryClaimReleaseView.open(
            temporary,
            expected_manifest_digest=manifest_digest,
        )
        os.rename(temporary, output)
        return RegistryClaimReleaseView.open(
            output,
            expected_manifest_digest=manifest_digest,
        )
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _strict_json(path: Path, *, expected_digest: str) -> Mapping[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RegistryClaimReleaseError("registry claim release manifest is missing")
    if _file_digest(path) != expected_digest:
        raise RegistryClaimReleaseError("registry claim release manifest digest differs")
    payload = path.read_bytes()

    def pairs(values: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise RegistryClaimReleaseError(
                    f"registry claim release JSON repeats key {key!r}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(payload, object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RegistryClaimReleaseError(
            "registry claim release manifest is not valid UTF-8 JSON"
        ) from error
    if not isinstance(value, Mapping):
        raise RegistryClaimReleaseError(
            "registry claim release manifest must be an object"
        )
    if canonical_json_bytes(value) != payload:
        raise RegistryClaimReleaseError(
            "registry claim release manifest is not canonical"
        )
    return value


def _verify_member(root: Path, descriptor: Mapping[str, Any]) -> Path:
    relative = _safe_relative_path(descriptor.get("path"), "member path")
    path = root.joinpath(*relative.parts)
    if path.is_symlink() or not path.is_file():
        raise RegistryClaimReleaseError(f"release member is missing: {relative}")
    if path.stat().st_size != descriptor.get("byteLength"):
        raise RegistryClaimReleaseError(f"release member size differs: {relative}")
    expected = _require_digest(descriptor.get("sha256"), f"{relative} sha256")
    if _file_digest(path) != expected:
        raise RegistryClaimReleaseError(f"release member digest differs: {relative}")
    return path


@dataclass(frozen=True, slots=True)
class RegistryClaimReleaseView:
    """A claim release reopened after external and internal verification."""

    root: Path
    manifest: Mapping[str, Any]
    manifest_digest: str
    claims: tuple[RegistryClaim, ...]

    @classmethod
    def open(
        cls,
        path: Path | str,
        *,
        expected_manifest_digest: str,
    ) -> RegistryClaimReleaseView:
        expected = _require_digest(
            expected_manifest_digest,
            "expected registry claim release manifest digest",
        )
        root = Path(path)
        if root.is_symlink() or not root.is_dir():
            raise RegistryClaimReleaseError(
                "registry claim release must be a regular directory"
            )
        manifest = _strict_json(root / MANIFEST_FILE, expected_digest=expected)
        required = {
            "claimTable",
            "issued",
            "languageScope",
            "limitations",
            "mediaType",
            "metadata",
            "packageKind",
            "rawInputs",
            "recipes",
            "releaseId",
            "releaseKey",
            "releaseScope",
            "schemaVersion",
            "schemas",
        }
        if set(manifest) != required:
            raise RegistryClaimReleaseError(
                "registry claim release manifest fields are unsupported"
            )
        if (
            manifest["schemaVersion"] != REGISTRY_CLAIM_RELEASE_VERSION
            or manifest["packageKind"] != REGISTRY_CLAIM_RELEASE_KIND
            or manifest["mediaType"] != REGISTRY_CLAIM_RELEASE_MEDIA_TYPE
        ):
            raise RegistryClaimReleaseError(
                "registry claim release kind or version is unsupported"
            )
        try:
            Draft202012Validator(MANIFEST_JSON_SCHEMA).validate(manifest)
        except ValidationError as error:
            raise RegistryClaimReleaseError(
                f"registry claim release manifest fails its schema: {error.message}"
            ) from error
        release_id = _require_iri(manifest["releaseId"], "manifest releaseId")
        _require_text(manifest["releaseKey"], "manifest releaseKey")
        _require_text(manifest["issued"], "manifest issued")
        recipe_rows = _normalized_named_rows(
            cast(Sequence[Mapping[str, Any]], manifest["recipes"]),
            label="manifest recipes",
        )
        limitation_rows = _normalized_named_rows(
            cast(Sequence[Mapping[str, Any]], manifest["limitations"]),
            label="manifest limitations",
        )
        if list(recipe_rows) != manifest["recipes"]:
            raise RegistryClaimReleaseError("manifest recipes are not sorted")
        if list(limitation_rows) != manifest["limitations"]:
            raise RegistryClaimReleaseError("manifest limitations are not sorted")

        claim_table = manifest["claimTable"]
        if not isinstance(claim_table, Mapping) or set(claim_table) != {
            "byteLength",
            "logicalDigest",
            "mediaType",
            "objectKindCounts",
            "originCounts",
            "path",
            "rowCount",
            "schema",
            "schemaDigest",
            "sha256",
        }:
            raise RegistryClaimReleaseError("claim table descriptor is unsupported")
        if (
            claim_table["path"] != CLAIMS_FILE
            or claim_table["mediaType"] != CLAIMS_MEDIA_TYPE
            or claim_table["schema"] != _schema_descriptor(CLAIM_SCHEMA)
            or claim_table["schemaDigest"] != CLAIM_SCHEMA_DIGEST
        ):
            raise RegistryClaimReleaseError("claim table schema declaration differs")
        claim_path = _verify_member(root, claim_table)
        parquet = pq.ParquetFile(claim_path)
        if parquet.schema_arrow != CLAIM_SCHEMA:
            raise RegistryClaimReleaseError("claim Parquet schema differs")
        if parquet.metadata.num_rows != claim_table["rowCount"]:
            raise RegistryClaimReleaseError("claim Parquet row count differs")
        records = pq.read_table(claim_path, schema=CLAIM_SCHEMA).to_pylist()
        claims = tuple(RegistryClaim.from_record(record) for record in records)
        if claims != tuple(sorted(claims, key=RegistryClaim.sort_key)):
            raise RegistryClaimReleaseError("claim rows are not canonically sorted")
        if any(claim.release_id != release_id for claim in claims):
            raise RegistryClaimReleaseError("claim row release_id differs")
        if _logical_rows_digest(claims) != claim_table["logicalDigest"]:
            raise RegistryClaimReleaseError("claim logical digest differs")
        if Counter(row.origin for row in claims) != Counter(
            claim_table["originCounts"]
        ):
            raise RegistryClaimReleaseError("claim origin counts differ")
        if Counter(row.object_kind for row in claims) != Counter(
            claim_table["objectKindCounts"]
        ):
            raise RegistryClaimReleaseError("claim object-kind counts differ")
        recipe_ids = {row["id"] for row in recipe_rows}
        limitation_ids = {row["id"] for row in limitation_rows}
        if {row.recipe_id for row in claims} - recipe_ids:
            raise RegistryClaimReleaseError("claims use undeclared recipes")
        if {
            limitation
            for row in claims
            for limitation in row.limitation_ids
        } - limitation_ids:
            raise RegistryClaimReleaseError("claims use undeclared limitations")

        raw_inputs = manifest["rawInputs"]
        if not isinstance(raw_inputs, Sequence) or isinstance(
            raw_inputs, (str, bytes)
        ):
            raise RegistryClaimReleaseError("manifest rawInputs must be an array")
        expected_files = {MANIFEST_FILE, CLAIMS_FILE}
        schema_rows = manifest["schemas"]
        if not isinstance(schema_rows, Sequence) or isinstance(
            schema_rows, (str, bytes)
        ):
            raise RegistryClaimReleaseError("manifest schemas must be an array")
        expected_schema_rows = []
        for role, logical_path in _SCHEMA_MEMBERS:
            matching = [
                row
                for row in schema_rows
                if isinstance(row, Mapping) and row.get("role") == role
            ]
            if len(matching) != 1:
                raise RegistryClaimReleaseError(
                    f"manifest must declare one {role} schema"
                )
            row = matching[0]
            if row.get("path") != logical_path:
                raise RegistryClaimReleaseError(
                    f"manifest {role} schema path differs"
                )
            schema_path = _verify_member(root, row)
            if schema_path.read_bytes() != _schema_bytes(logical_path):
                raise RegistryClaimReleaseError(
                    f"bundled {role} schema differs from the supported schema"
                )
            expected_files.add(logical_path)
            expected_schema_rows.append(row)
        if list(schema_rows) != expected_schema_rows:
            raise RegistryClaimReleaseError("manifest schemas are not canonical")
        raw_paths: list[str] = []
        evidence_pins: set[tuple[str, str]] = set()
        for index, raw in enumerate(raw_inputs):
            if not isinstance(raw, Mapping):
                raise RegistryClaimReleaseError(
                    f"manifest rawInputs[{index}] must be an object"
                )
            allowed = {
                "archiveMembers",
                "byteLength",
                "mediaType",
                "path",
                "role",
                "sha256",
                "sourceLocator",
            }
            if not set(raw).issubset(allowed) or not {
                "byteLength",
                "mediaType",
                "path",
                "role",
                "sha256",
                "sourceLocator",
            }.issubset(raw):
                raise RegistryClaimReleaseError(
                    f"manifest rawInputs[{index}] fields are unsupported"
                )
            raw_path = _verify_member(root, raw)
            raw_paths.append(cast(str, raw["path"]))
            expected_files.add(raw_path.relative_to(root).as_posix())
            source_locator = _require_iri(
                raw["sourceLocator"],
                "raw input sourceLocator",
            )
            _require_text(raw["role"], "raw input role")
            evidence_pins.add((source_locator, cast(str, raw["sha256"])))
            archive_members = raw.get("archiveMembers")
            if archive_members is not None:
                if not isinstance(archive_members, Sequence) or isinstance(
                    archive_members, (str, bytes)
                ):
                    raise RegistryClaimReleaseError(
                        "raw input archiveMembers must be an array"
                    )
                verified_members = _verify_archive_members(
                    raw_path,
                    cast(Sequence[Mapping[str, Any]], archive_members),
                )
                if verified_members != archive_members:
                    raise RegistryClaimReleaseError(
                        "raw input archiveMembers are not canonical"
                    )
                evidence_pins.update(
                    (source_locator, cast(str, member["sha256"]))
                    for member in verified_members
                )
        if raw_paths != sorted(raw_paths) or len(set(raw_paths)) != len(raw_paths):
            raise RegistryClaimReleaseError(
                "manifest raw input paths must be sorted and unique"
            )
        unpinned_claim_evidence = sorted(
            {
                (claim.source_locator, claim.source_digest)
                for claim in claims
                if (claim.source_locator, claim.source_digest) not in evidence_pins
            }
        )
        if unpinned_claim_evidence:
            raise RegistryClaimReleaseError(
                "claims refer to source evidence absent from raw input pins: "
                f"{unpinned_claim_evidence}"
            )
        observed_files = {
            item.relative_to(root).as_posix()
            for item in root.rglob("*")
            if item.is_file() or item.is_symlink()
        }
        if observed_files != expected_files:
            raise RegistryClaimReleaseError(
                "registry claim release file membership is not closed"
            )
        return cls(
            root=root,
            manifest=manifest,
            manifest_digest=expected,
            claims=claims,
        )


__all__ = [
    "CLAIMS_FILE",
    "CLAIM_COLUMNS",
    "CLAIM_RECORD_JSON_SCHEMA",
    "CLAIM_RECORD_SCHEMA_FILE",
    "CLAIM_SCHEMA",
    "CLAIM_SCHEMA_DIGEST",
    "MANIFEST_FILE",
    "MANIFEST_JSON_SCHEMA",
    "MANIFEST_SCHEMA_FILE",
    "RegistryClaim",
    "RegistryClaimReleaseError",
    "RegistryClaimReleaseView",
    "RegistryRawInput",
    "build_registry_claim_release",
]
