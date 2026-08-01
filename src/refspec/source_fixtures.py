"""Digest-pinned vocabulary source fixtures shipped with RefSpec."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from importlib.resources import files
from typing import Any


FEDERAL_REGISTER_FIXTURE_NAME = "federal-register-thesaurus-2025-first-slice-v1.json"
FEDERAL_REGISTER_FIXTURE_SHA256 = (
    "8d44a0560e2f929a45f4fb7a027fbc46800efdcd1471734ccbfab9861a3b50b7"
)
FEDERAL_REGISTER_FIXTURE_ID = (
    "urn:refspec:fixture:federal-register-thesaurus:" "2025-04-01:first-slice-v1"
)
FEDERAL_REGISTER_PARSER_VERSION = "federal-register-thesaurus-2025-styled-pdf-v1"


def federal_register_source_fixture_pin() -> dict[str, str]:
    """Return the exact package fixture pin used by the first-slice builder."""

    return {
        "fixture_id": FEDERAL_REGISTER_FIXTURE_ID,
        "fixture_sha256": "sha256:" + FEDERAL_REGISTER_FIXTURE_SHA256,
        "parser_version": FEDERAL_REGISTER_PARSER_VERSION,
    }


def load_federal_register_source_fixture() -> dict[str, Any]:
    """Load the sealed source fixture and verify its exact bytes and identity."""

    raw = files("refspec.fixtures").joinpath(FEDERAL_REGISTER_FIXTURE_NAME).read_bytes()
    if hashlib.sha256(raw).hexdigest() != FEDERAL_REGISTER_FIXTURE_SHA256:
        raise ValueError("the Federal Register source fixture does not match its pin")
    fixture = json.loads(raw)
    if {
        "fixture_id": fixture.get("fixture_id"),
        "fixture_sha256": "sha256:" + FEDERAL_REGISTER_FIXTURE_SHA256,
        "parser_version": fixture.get("parser_version"),
    } != federal_register_source_fixture_pin():
        raise ValueError("the Federal Register source fixture identity is invalid")
    return deepcopy(fixture)
