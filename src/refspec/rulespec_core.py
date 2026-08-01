"""Pinned, package-local Rulespec Core fixture access.

RefSpec builds against exact Rulespec artifacts. It never reads a Rulespec
checkout or database at build time.
"""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from typing import Any

from .canonical import CanonicalValueError, canonical_digest


CORE_RELEASE_FIXTURE_NAME = "rulespec-core-release-m2.json"
CORE_RELEASE_FIXTURE_SHA256 = (
    "06adfaf4d3ee8532c9ae76719d48a4844a4b012c7fea31e83e4a89f8033d1a63"
)
REFERENCE_RELEASE_SCHEMA_PACKAGE_NAME = (
    "rulespec-reference-resource-release.schema.json"
)
REFERENCE_RELEASE_SCHEMA_ARTIFACT_NAME = (
    "compiled/json-schema/core/reference-resource-release.schema.json"
)
REFERENCE_RELEASE_SCHEMA_SHA256 = (
    "737d0a5577c1cd6d4d3fd3c78ef13e7c0d102ce8cfada7bc444a1a66b4e66d84"
)
REFERENCE_RELEASE_FIXTURE_PACKAGE_NAME = (
    "rulespec-reference-resource-release-digest-positive.jsonld"
)
REFERENCE_RELEASE_FIXTURE_ARTIFACT_NAME = (
    "fixtures/reference-resource-release-digest-positive.jsonld"
)
REFERENCE_RELEASE_FIXTURE_SHA256 = (
    "40ad919ba8b6a717b1395f37b5ca0ff569df723bc93070dc925e9b356e081213"
)
CORE_RELEASE_FIELDS = {
    "record_type",
    "release_id",
    "release_digest",
    "release_status",
    "version",
    "schema_artifacts",
    "validator_artifacts",
    "conformance_fixture_artifacts",
}


def _load_pinned_json(name: str, sha256: str) -> dict[str, Any]:
    raw = files("refspec.fixtures").joinpath(name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise CanonicalValueError(f"package-local Rulespec artifact {name} is unpinned")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise CanonicalValueError(
            f"package-local Rulespec artifact {name} is not an object"
        )
    return value


def load_rulespec_core_release_fixture() -> dict[str, Any]:
    """Load the exact authoritative Rulespec Core conformance artifact."""

    release = _load_pinned_json(
        CORE_RELEASE_FIXTURE_NAME,
        CORE_RELEASE_FIXTURE_SHA256,
    )
    if set(release) != CORE_RELEASE_FIELDS:
        raise CanonicalValueError(
            "the Rulespec Core release fixture has unexpected root fields"
        )
    if release["record_type"] != "RulespecCoreRelease":
        raise CanonicalValueError("the Rulespec Core fixture has the wrong type")
    expected_digest = canonical_digest(
        release,
        omit_root_fields=("release_id", "release_digest"),
    )
    if release["release_digest"] != expected_digest:
        raise CanonicalValueError(
            "the Rulespec Core release fixture digest does not match its content"
        )
    if release["release_id"] != (
        "urn:rulespec:core:" + expected_digest.removeprefix("sha256:")
    ):
        raise CanonicalValueError(
            "the Rulespec Core release fixture identifier does not match its digest"
        )
    return release


def _require_release_artifact(
    *,
    collection: str,
    artifact_name: str,
    artifact_sha256: str,
) -> None:
    release = load_rulespec_core_release_fixture()
    expected = {
        "name": artifact_name,
        "media_type": (
            "application/schema+json"
            if collection == "schema_artifacts"
            else "application/ld+json"
        ),
        "artifact_digest": "sha256:" + artifact_sha256,
    }
    if expected not in release[collection]:
        raise CanonicalValueError(f"Rulespec Core release does not pin {artifact_name}")


def load_reference_resource_release_schema() -> dict[str, Any]:
    """Load the exact Rulespec Core ReferenceResourceRelease JSON Schema."""

    _require_release_artifact(
        collection="schema_artifacts",
        artifact_name=REFERENCE_RELEASE_SCHEMA_ARTIFACT_NAME,
        artifact_sha256=REFERENCE_RELEASE_SCHEMA_SHA256,
    )
    schema = _load_pinned_json(
        REFERENCE_RELEASE_SCHEMA_PACKAGE_NAME,
        REFERENCE_RELEASE_SCHEMA_SHA256,
    )
    definition = schema.get("$defs", {}).get("ReferenceResourceRelease")
    if not isinstance(definition, dict):
        raise CanonicalValueError(
            "Rulespec ReferenceResourceRelease schema lacks its definition"
        )
    return schema


def load_reference_resource_release_digest_fixture() -> dict[str, Any]:
    """Load the Rulespec Core RDFC-1.0 digest conformance vector."""

    _require_release_artifact(
        collection="conformance_fixture_artifacts",
        artifact_name=REFERENCE_RELEASE_FIXTURE_ARTIFACT_NAME,
        artifact_sha256=REFERENCE_RELEASE_FIXTURE_SHA256,
    )
    return _load_pinned_json(
        REFERENCE_RELEASE_FIXTURE_PACKAGE_NAME,
        REFERENCE_RELEASE_FIXTURE_SHA256,
    )


def rulespec_core_fixture_pin() -> dict[str, str]:
    """Return immutable provenance for the exact packaged Rulespec artifacts."""

    core = load_rulespec_core_release_fixture()
    load_reference_resource_release_schema()
    load_reference_resource_release_digest_fixture()
    return {
        "rulespec_core_release_fixture_name": CORE_RELEASE_FIXTURE_NAME,
        "rulespec_core_release_fixture_sha256": (
            "sha256:" + CORE_RELEASE_FIXTURE_SHA256
        ),
        "rulespec_core_release_status": core["release_status"],
        "rulespec_core_release_version": core["version"],
        "reference_resource_release_schema_name": (
            REFERENCE_RELEASE_SCHEMA_ARTIFACT_NAME
        ),
        "reference_resource_release_schema_digest": (
            "sha256:" + REFERENCE_RELEASE_SCHEMA_SHA256
        ),
        "reference_resource_release_fixture_name": (
            REFERENCE_RELEASE_FIXTURE_ARTIFACT_NAME
        ),
        "reference_resource_release_fixture_digest": (
            "sha256:" + REFERENCE_RELEASE_FIXTURE_SHA256
        ),
    }


def rulespec_core_release_ref() -> dict[str, str]:
    """Return the exact Rulespec Core release used by this RefSpec build."""

    core = load_rulespec_core_release_fixture()
    return {
        "release_id": core["release_id"],
        "release_digest": core["release_digest"],
    }
