"""Tests for declarative two-layer Atlas release profiles, partitioned accounting, and validator registry loading."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from refspec.atlas.agency_projection import AGENCY_ROSTER_RELEASE_KEYS

ROOT = Path(__file__).resolve().parents[1]
BINDING_ROOT = ROOT / "bindings" / "atlas" / "3.1"
VALIDATE_PATH = BINDING_ROOT / "tools" / "validate.py"


def _load_generator():
    module_name = "refspec_test_generate_atlas_v3_full"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "tools" / "generate_atlas_v3_full.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_validator():
    tools_dir = str(BINDING_ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    module_name = "refspec_atlas_v3_validate"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(module_name, VALIDATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _sample_accounting() -> dict[str, Any]:
    gen = _load_generator()
    body = {
        "assertedInventoryDigest": "sha256:" + "a" * 64,
        "inputs": [
            {
                "dispositions": [
                    {
                        "atlasResources": ["https://example.org/concept/1"],
                        "sourceRecord": "urn:ref:source-record:alpha:1",
                        "status": "represented",
                    },
                    {
                        "reason": "deprecated source row",
                        "sourceRecord": "urn:ref:source-record:alpha:2",
                        "status": "excluded",
                    },
                ],
                "membershipMode": "complete",
                "sourceRelease": "urn:ref:source-release:alpha:2026-08-01",
            },
            {
                "dispositions": [
                    {
                        "atlasAssertions": ["urn:ref:atlas-assertion:beta:1"],
                        "sourceRecord": "urn:ref:source-record:beta:1",
                        "status": "represented",
                    },
                    {
                        "reason": "target outside scope",
                        "sourceRecord": "urn:ref:source-record:beta:2",
                        "status": "unresolved",
                    },
                ],
                "membershipMode": "partial",
                "sourceRelease": "urn:ref:source-release:beta:2026-08-01",
            },
        ],
        "totals": {
            "excluded": 1,
            "represented": 2,
            "sourceRecords": 4,
            "sourceReleases": 2,
            "unresolved": 1,
        },
        "type": "AtlasSourceAccounting",
        "version": "3.1",
    }
    return gen._identified_source_accounting(body)


def test_atlas_release_profiles_validate_and_cover_full_topology() -> None:
    """Declarative profiles cover every declared unit cleanly with disjoint core/bibliographic layers."""

    gen = _load_generator()
    doc = gen.load_atlas_release_profiles()
    assert doc["type"] == "AtlasReleaseProfiles"
    assert doc["defaultProfile"] == "full"

    declared = gen._declared_construction_unit_keys()
    declared_sources, declared_mappings = gen.split_construction_unit_keys(declared)

    full_sources, full_mappings = gen.resolve_profile_key_split("full")
    core_sources, core_mappings = gen.resolve_profile_key_split("core-regulatory")
    bib_sources, bib_mappings = gen.resolve_profile_key_split("bibliographic-crosswalk")

    assert full_sources == declared_sources
    assert full_mappings == declared_mappings
    assert core_sources & bib_sources == frozenset()
    assert core_mappings & bib_mappings == frozenset()
    assert core_sources | bib_sources == declared_sources

    cross_layer = frozenset(doc["profiles"]["full"]["additionalMappingKeys"])
    assert cross_layer == frozenset({"eurovoc-lcsh-alignment-20240711", "mesh-lcsh-mapping-2021-03-31"})
    assert core_mappings | bib_mappings | cross_layer == declared_mappings


def test_core_regulatory_excludes_lcsh_fast_and_foreign_stubs() -> None:
    """core-regulatory excludes LCSH, FAST, lc-external-* stubs, and bibliographic mappings."""

    gen = _load_generator()
    core_keys = gen.resolve_profile_release_keys("core-regulatory")

    forbidden_exact = {
        "lcsh-subjects-consolidated-2026-08-06",
        "fast-topical-current",
        "fast-bulk-see-also-endpoints-2026-07-27",
        "fast-lcsh-adopted-2026-08-15",
        "fast-bulk-external-links-delta-2026-07-27",
        "lcsh-external-links-mappings-2026-08-15",
        "eurovoc-lcsh-alignment-20240711",
        "mesh-lcsh-mapping-2021-03-31",
    }
    assert core_keys & forbidden_exact == frozenset()
    assert not any(key.startswith("lc-external-") for key in core_keys)
    assert not any("lcsh" in key for key in core_keys)
    assert not any(key.startswith("fast-") for key in core_keys)


def test_core_regulatory_retains_all_four_rings_and_closed_mappings() -> None:
    """core-regulatory keeps all 4 rings (subject, value, entity, legalIdentity) and closed mappings."""

    gen = _load_generator()
    doc = gen.load_atlas_release_profiles()
    core_sources, core_mappings = gen.resolve_profile_key_split("core-regulatory")
    core_spec = doc["profiles"]["core-regulatory"]

    assert set(core_spec["rings"]) == {"subject", "value", "entity", "legalIdentity"}

    # Curated regulatory/policy/science subject schemes
    required_subjects = {
        "federal-register-thesaurus-2025",
        "federal-register-api-topics-2026-08-03",
        "mesh-descriptors-2026",
        "doe-osti-semantic-thesaurus-2020",
        "nasa-thesaurus-skos",
        "eurovoc-4.24",
        "eurovoc-domains-4.24",
        "eurovoc-microthesauri-4.24",
        "gemet-4.2.3",
        "icpsr-subject-thesaurus",
        "gcmd-science-keywords-24-4",
        "elsst-r6",
        "umthes-gemet-endpoints-2026-08-15",
        "crs-legislative-subjects",
        "crs-policy-areas",
        "gao-published-topics-capture-subset-2026-09-01",
    }
    assert required_subjects <= core_sources

    # Value ring code lists
    required_values = {
        "naics-2022",
        "psc-april-2025",
        "billstatus-bill-types",
        "unified-agenda-priority-category",
        "gao-cra-priority-of-regulation",
        "opm-ehri-data-standards-2026-08-04",
    }
    assert required_values <= core_sources

    # Entity ring rosters + org:ChangeEvent successions
    assert set(AGENCY_ROSTER_RELEASE_KEYS) <= core_sources
    assert {"courtlistener-jurisdictions-2026-08-03", "crs-legislative-entities"} <= core_sources
    assert {"agency-registry-2026-09-26", "regulations-gov-agency-identity-2026-08-16"} <= core_mappings

    # legalIdentity ring CFR structures
    assert {"ecfr-cfr-titles", "cfr-subject-index-parts-2026-08-20"} <= core_sources

    # Closed curated mapping releases and strict split_construction_unit_keys closure
    expected_core_mappings = {
        "agency-registry-2026-09-26",
        "regulations-gov-agency-identity-2026-08-16",
        "unified-agenda-gao-cra-priority-2026-08-15",
        "eurovoc-gemet-alignment-20201218",
        "eurovoc-mesh-alignment-20171215",
        "gemet-eurovoc-alignments-4.2.3",
        "gemet-umthes-alignments-4.2.3",
    }
    assert core_mappings == expected_core_mappings
    split_sources, split_mappings = gen.split_construction_unit_keys(core_sources | core_mappings)
    assert split_sources == core_sources
    assert split_mappings == core_mappings


def test_bibliographic_crosswalk_profile_is_closed_and_s27_complete() -> None:
    """bibliographic-crosswalk keeps LCSH, FAST, lc-external-* stubs, and S27-paired mappings."""

    gen = _load_generator()
    bib_sources, bib_mappings = gen.resolve_profile_key_split("bibliographic-crosswalk")

    assert "lcsh-subjects-consolidated-2026-08-06" in bib_sources
    assert "fast-topical-current" in bib_sources
    assert "fast-bulk-see-also-endpoints-2026-07-27" in bib_sources
    lc_external = {key for key in bib_sources if key.startswith("lc-external-")}
    assert len(lc_external) == 15
    assert bib_mappings == frozenset(
        {
            "fast-lcsh-adopted-2026-08-15",
            "fast-bulk-external-links-delta-2026-07-27",
            "lcsh-external-links-mappings-2026-08-15",
        }
    )


def test_profile_loader_rejects_unclosed_mapping_and_unknown_profile(tmp_path: Path) -> None:
    """Profile loader fails closed on missing mapping endpoints or unknown profile names."""

    gen = _load_generator()
    base_doc = gen.load_atlas_release_profiles()

    # Add eurovoc-lcsh mapping to core-regulatory without lcsh in core-regulatory sourceKeys
    broken = copy.deepcopy(base_doc)
    broken["profiles"]["core-regulatory"]["mappingKeys"].append("eurovoc-lcsh-alignment-20240711")
    broken_path = tmp_path / "broken-profiles.json"
    broken_path.write_text(json.dumps(broken, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="not endpoint-closed"):
        gen.load_atlas_release_profiles(broken_path)

    with pytest.raises(ValueError, match="unknown Atlas release profile"):
        gen.resolve_profile_release_keys("nonexistent-profile")

    with pytest.raises(ValueError, match="cannot combine an Atlas release profile"):
        gen._effective_include_keys(
            include_keys=frozenset({"federal-register-thesaurus-2025"}),
            profile="core-regulatory",
        )


def test_cli_profile_routes_keys_and_rejects_only_release_combination(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI --profile routes exact keys to loaders, defaults full to None, and conflicts with --only-release."""

    gen = _load_generator()
    observed: list[tuple[object, object]] = []

    def fake_load_releases(*, include_keys: object, registry_claim_inputs: object) -> tuple[object, ...]:
        observed.append(("sources", include_keys))
        return ()

    def fake_load_mappings(*, include_keys: object, source_releases: object) -> tuple[object, ...]:
        observed.append(("mappings", include_keys))
        return ()

    monkeypatch.setattr(gen, "load_releases", fake_load_releases)
    monkeypatch.setattr(gen, "load_mapping_releases", fake_load_mappings)
    monkeypatch.setattr(gen, "verify_inputs", lambda rels, maps: {"status": "ok"})

    # 1. --profile core-regulatory --check-inputs
    monkeypatch.setattr(sys, "argv", ["gen", "--profile", "core-regulatory", "--check-inputs", "--quiet"])
    assert gen.main() == 0
    core_sources, core_mappings = gen.resolve_profile_key_split("core-regulatory")
    assert observed == [("sources", core_sources), ("mappings", core_mappings)]
    assert json.loads(capsys.readouterr().out) == {"status": "ok"}

    # 2. --profile full --check-inputs preserves full-build None semantics
    observed.clear()
    monkeypatch.setattr(sys, "argv", ["gen", "--profile", "full", "--check-inputs", "--quiet"])
    assert gen.main() == 0
    assert observed == [("sources", None), ("mappings", None)]
    capsys.readouterr()

    # 3. Mutually exclusive with --only-release
    monkeypatch.setattr(
        sys,
        "argv",
        ["gen", "--profile", "core-regulatory", "--only-release", "federal-register-thesaurus-2025"],
    )
    with pytest.raises(SystemExit) as exc_info:
        gen.main()
    assert exc_info.value.code == 2


def test_cli_partitioned_accounting_flag_forwarded_to_build_distribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--partitioned-accounting is opt-in and defaults to False."""

    gen = _load_generator()
    captured: list[dict[str, object]] = []

    def fake_build(
        output: Path,
        *,
        registry_claim_inputs: object = None,
        include_keys: object = None,
        profile: object = None,
        parquet_view: bool = True,
        partitioned_accounting: bool = False,
    ) -> None:
        captured.append(
            {
                "include_keys": include_keys,
                "partitioned_accounting": partitioned_accounting,
            }
        )

    class _StubSelection:
        distribution = tmp_path / "distribution"

    monkeypatch.setattr(gen, "build_distribution", fake_build)
    monkeypatch.setattr(gen, "select_atlas_generation", lambda path: _StubSelection())

    monkeypatch.setattr(sys, "argv", ["gen", "--output", str(tmp_path / "out"), "--quiet"])
    assert gen.main() == 0
    assert captured[-1] == {"include_keys": None, "partitioned_accounting": False}

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gen",
            "--output",
            str(tmp_path / "out"),
            "--profile",
            "core-regulatory",
            "--partitioned-accounting",
            "--quiet",
        ],
    )
    assert gen.main() == 0
    assert captured[-1]["partitioned_accounting"] is True
    assert captured[-1]["include_keys"] == gen.resolve_profile_release_keys("core-regulatory")


def test_streaming_source_accounting_is_byte_identical_to_canonical_json(tmp_path: Path) -> None:
    """Streaming writer produces identical canonical REF JSON bytes and digest."""

    gen = _load_generator()
    accounting = _sample_accounting()
    expected_bytes = gen.ATLAS_VALIDATE.canonical_json_bytes(accounting)
    expected_digest = "sha256:" + hashlib.sha256(expected_bytes).hexdigest()

    out_file = tmp_path / "atlas-source-accounting.json"
    actual_digest = gen._write_canonical_source_accounting_stream(out_file, accounting)

    assert out_file.read_bytes() == expected_bytes
    assert actual_digest == expected_digest


def test_partitioned_source_accounting_roundtrip_and_tamper_rejection(tmp_path: Path) -> None:
    """Partitioned shards reassemble byte-identically and refuse tamper, symlinks, and traversal."""

    gen = _load_generator()
    accounting = _sample_accounting()
    canonical_bytes = gen.ATLAS_VALIDATE.canonical_json_bytes(accounting)
    monolithic_digest = "sha256:" + hashlib.sha256(canonical_bytes).hexdigest()

    part_dir = tmp_path / "source-accounting-partitions"
    manifest = gen.write_partitioned_source_accounting(
        accounting,
        part_dir,
        release_keys_by_source_iri={
            "urn:ref:source-release:alpha:2026-08-01": "alpha-release",
            "urn:ref:source-release:beta:2026-08-01": "beta-release",
        },
        monolithic_digest=monolithic_digest,
    )
    assert manifest["type"] == "AtlasPartitionedSourceAccounting"
    assert len(manifest["partitions"]) == 2
    assert (part_dir / "releases" / "alpha-release.json").is_file()
    assert (part_dir / "releases" / "beta-release.json").is_file()

    reassembled = gen.reassemble_partitioned_source_accounting(part_dir)
    assert reassembled == accounting
    assert gen.ATLAS_VALIDATE.canonical_json_bytes(reassembled) == canonical_bytes

    # Tampered shard byte must fail SHA-256 verification.
    shard = part_dir / "releases" / "alpha-release.json"
    original = shard.read_bytes()
    shard.write_bytes(original.replace(b"alpha", b"alphz", 1))
    with pytest.raises(ValueError, match="sha256 mismatch"):
        gen.reassemble_partitioned_source_accounting(part_dir)
    shard.write_bytes(original)

    # Symlinked shard must be refused.
    outside = tmp_path / "outside.json"
    outside.write_bytes(original)
    shard.unlink()
    shard.symlink_to(outside)
    with pytest.raises(ValueError, match="missing or unsafe"):
        gen.reassemble_partitioned_source_accounting(part_dir)
    shard.unlink()
    shard.write_bytes(original)

    # Path traversal in accounting-manifest.json must be refused.
    manifest_path = part_dir / "accounting-manifest.json"
    tampered_manifest = copy.deepcopy(manifest)
    tampered_manifest["partitions"][0]["path"] = "releases/../escape.json"
    manifest_path.write_bytes(gen.ATLAS_VALIDATE.canonical_json_bytes(tampered_manifest))
    with pytest.raises(ValueError, match="unsafe partition path"):
        gen.reassemble_partitioned_source_accounting(part_dir)
    manifest_path.write_bytes(gen.ATLAS_VALIDATE.canonical_json_bytes(manifest))


def test_partitioned_source_accounting_refuses_symlinked_releases_unlisted_files_and_double_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reassembly refuses symlinked releases/, parent symlinks, unlisted files, and never re-reads shards."""

    gen = _load_generator()
    accounting = _sample_accounting()
    canonical_bytes = gen.ATLAS_VALIDATE.canonical_json_bytes(accounting)
    monolithic_digest = "sha256:" + hashlib.sha256(canonical_bytes).hexdigest()

    part_dir = tmp_path / "source-accounting-partitions"
    gen.write_partitioned_source_accounting(
        accounting,
        part_dir,
        release_keys_by_source_iri={
            "urn:ref:source-release:alpha:2026-08-01": "alpha-release",
            "urn:ref:source-release:beta:2026-08-01": "beta-release",
        },
        monolithic_digest=monolithic_digest,
    )

    # 1. Single-read TOCTOU guarantee: ATLAS_VALIDATE._load_json must never be called to re-read files.
    def _forbid_reread(*args: object, **kwargs: object) -> object:
        raise AssertionError("reassemble_partitioned_source_accounting must parse raw_bytes without re-reading disk")

    monkeypatch.setattr(gen.ATLAS_VALIDATE, "_load_json", _forbid_reread)
    assert gen.reassemble_partitioned_source_accounting(part_dir) == accounting

    # 2. Unlisted extra file inside releases/ must be refused (closed membership).
    extra = part_dir / "releases" / "rogue-extra.json"
    extra.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected unlisted file in releases/"):
        gen.reassemble_partitioned_source_accounting(part_dir)
    extra.unlink()

    # 3. Unexpected subdirectory inside releases/ must also be refused.
    extra_dir = part_dir / "releases" / "nested"
    extra_dir.mkdir()
    with pytest.raises(ValueError, match="unsafe or non-regular entry in releases/"):
        gen.reassemble_partitioned_source_accounting(part_dir)
    extra_dir.rmdir()

    # 4. Symlinked releases/ directory must be refused.
    relocated = tmp_path / "external-releases"
    (part_dir / "releases").rename(relocated)
    (part_dir / "releases").symlink_to(relocated, target_is_directory=True)
    with pytest.raises(ValueError, match="releases directory is missing or unsafe"):
        gen.reassemble_partitioned_source_accounting(part_dir)
    (part_dir / "releases").unlink()
    relocated.rename(part_dir / "releases")

    # 5. Symlinked parent directory on partition_dir must be refused.
    parent_link = tmp_path / "linked-parent"
    parent_link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="traverses a symlinked parent directory"):
        gen.reassemble_partitioned_source_accounting(parent_link / "source-accounting-partitions")


def test_validate_loads_derived_rule_admissions_from_json_without_hardcoded_literal() -> None:
    """validate.py removes hardcoded _DERIVED_RULE_ADMISSIONS debt and enforces closed typed loading."""

    validate = _load_validator()

    # AST check: _DERIVED_RULE_ADMISSIONS must be assigned from _load_derived_rule_admissions(),
    # never a hardcoded dict literal of _DerivedRuleAdmission(...) calls.
    tree = ast.parse(VALIDATE_PATH.read_text(encoding="utf-8"))
    found_assignment = False
    for node in tree.body:
        target_name: str | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value = node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target_name = node.targets[0].id
            value = node.value
        if target_name == "_DERIVED_RULE_ADMISSIONS":
            found_assignment = True
            assert isinstance(value, ast.Call), "_DERIVED_RULE_ADMISSIONS must be loaded via function call"
            assert isinstance(value.func, ast.Name) and value.func.id == "_load_derived_rule_admissions"
    assert found_assignment, "_DERIVED_RULE_ADMISSIONS binding not found in validate.py"

    # Loaded roster matches bindings/atlas/3.1/admitted-derived-rules.json exactly.
    registry_doc = validate._load_json(validate.DERIVED_RULE_REGISTRY_PATH, require_canonical=True)
    assert len(validate._DERIVED_RULE_ADMISSIONS) == len(registry_doc["rules"]) == 6
    assert validate._check_derived_rule_registry() == registry_doc

    # Closed typed loader negative checks:
    # 1. Unknown rule IRI
    bad_rule = copy.deepcopy(registry_doc)
    bad_rule["rules"][0]["rule"] = "urn:ref:rule:unknown-synthetic-rule"
    with pytest.raises(validate.AtlasValidationError) as exc_unknown:
        validate._parse_derived_rule_registry(bad_rule)
    assert exc_unknown.value.code == "binding.derived-rule-registry"

    # 2. Missing executable handler coverage (omitted rule)
    omitted = copy.deepcopy(registry_doc)
    omitted["rules"].pop()
    with pytest.raises(validate.AtlasValidationError) as exc_omitted:
        validate._parse_derived_rule_registry(omitted)
    assert exc_omitted.value.code == "binding.derived-rule-registry"

    # 3. Mismatched mirrorPredicate vs admittedPredicates
    bad_mirror = copy.deepcopy(registry_doc)
    bad_mirror["rules"][0]["admittedPredicates"] = [str(validate.SKOS.closeMatch)]
    with pytest.raises(validate.AtlasValidationError) as exc_mirror:
        validate._parse_derived_rule_registry(bad_mirror)
    assert exc_mirror.value.code == "binding.derived-rule-registry"

    # 4. Unexpected property on a rule row
    bad_field = copy.deepcopy(registry_doc)
    bad_field["rules"][0]["extraPolicy"] = True
    with pytest.raises(validate.AtlasValidationError) as exc_field:
        validate._parse_derived_rule_registry(bad_field)
    assert exc_field.value.code == "binding.derived-rule-registry"
