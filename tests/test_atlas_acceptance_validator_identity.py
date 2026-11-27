"""Producer, validator, and consumer controls for ss-b5n6 portable AtlasAcceptance validator identity."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from refspec.atlas.parquet_artifact import file_sha256
from refspec.atlas.parquet_view import seal_atlas_parquet_view
from refspec.seal import create_seal, verify_seal
from tests.test_agency_change_events_projection import (
    TEST_CREATED_AT,
    _construction_seeds_for,
    _synthetic_agency_change_event_case,
)
from tools import generate_atlas_v3_full as generator

ROOT = Path(__file__).resolve().parents[1]
BINDING_ROOT = ROOT / "bindings" / "atlas" / "3.1"
sys.path.insert(0, str(BINDING_ROOT / "tools"))
import validate as atlas_validate


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _build_fresh_distribution(
    tmp_path: Path,
    *,
    name: str = "dist",
    streamed: bool = False,
    parquet_tables: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Build a real small distribution through generate_atlas_v3_full under the running validator."""

    case_dir = tmp_path / f"{name}-inputs"
    case_dir.mkdir(parents=True, exist_ok=True)
    releases, mapping_releases = _synthetic_agency_change_event_case(case_dir)
    inventory = generator.verify_inputs(releases, mapping_releases)
    compiled_rows = generator._validate_compiled_producer_rows(releases, mapping_releases)
    seeds = _construction_seeds_for(releases, mapping_releases)
    plans = generator._release_pack_plans(releases, mapping_releases)
    dist = tmp_path / name / "distribution"

    if streamed:
        prebuild = generator.ProducerPrebuildValidation(
            compiled_rows=compiled_rows,
            construction_seeds=seeds,
            generation_report=generator._producer_generation_report(
                releases,
                mapping_releases,
                input_inventory=inventory,
                producer_validation=compiled_rows,
            ),
            input_inventory=inventory,
            pack_plans=plans,
        )
        spool_root = tmp_path / f"{name}-spool"
        spool_root.mkdir(parents=True, exist_ok=True)
        constructed = generator._stream_construct_graphs(
            list(releases),
            list(mapping_releases),
            prebuild=prebuild,
            spool_root=spool_root,
        )
        _result, manifest = generator._write_streamed_candidate_distribution(
            dist,
            constructed,
            plans,
            created_at=TEST_CREATED_AT,
            construction_seeds=seeds,
            parquet_tables=parquet_tables,
        )
        return dist, manifest

    graphs = generator._build_graphs(releases, mapping_releases=mapping_releases, include_projection=False)
    try:
        compiled_validation = generator._validate_compiled_producer_output(
            releases,
            graphs,
            compiled_rows,
            mapping_releases,
        )
        _result, manifest = generator._write_candidate_distribution(
            dist,
            graphs,
            releases=plans,
            compiled_validation=compiled_validation,
            construction_seeds=seeds,
            created_at=TEST_CREATED_AT,
            parquet_tables=parquet_tables,
        )
    finally:
        graphs.release()
    return dist, manifest


def _rewrite_acceptance(
    distribution: Path,
    acceptance: dict[str, Any],
    *,
    recompute_gates: bool = True,
) -> None:
    """Rewrite atlas-acceptance.json and re-seal atlas-manifest.json member digests."""

    if recompute_gates:
        for gate in acceptance["gates"]:
            gate["evidenceDigest"] = atlas_validate.acceptance_gate_evidence_digest(
                gate["name"],
                inputs=acceptance["inputs"],
                validator=acceptance["validator"],
            )
    acceptance_bytes = atlas_validate.canonical_json_bytes(acceptance)
    (distribution / "atlas-acceptance.json").write_bytes(acceptance_bytes)

    manifest_path = distribution / "atlas-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for member in manifest["members"]:
        if member["role"] == "acceptance":
            member["byteLength"] = len(acceptance_bytes)
            member["digest"] = _sha256(acceptance_bytes)
    payload = {key: value for key, value in manifest.items() if key != "canonicalPayloadDigest"}
    manifest["canonicalPayloadDigest"] = atlas_validate.canonical_sha256(payload, terminal_lf=False)
    manifest_path.write_bytes(atlas_validate.canonical_json_bytes(manifest))


@pytest.fixture(scope="module")
def baseline_distribution(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    """Build one real distribution once per module so mutation tests copy bytes instead of rebuilding RDF."""

    return _build_fresh_distribution(tmp_path_factory.mktemp("ss-b5n6-baseline"), name="baseline")


def _copy_distribution(baseline: Path, target: Path) -> Path:
    shutil.copytree(baseline, target)
    return target


def _edited_tools_copy(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for relative in atlas_validate.BINDING_TOOL_PATHS:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(atlas_validate.BINDING_ROOT / relative, target)
    validator_file = root / "tools" / "validate.py"
    validator_file.write_bytes(validator_file.read_bytes() + b"\n# simulated validator implementation change\n")
    return root


@pytest.mark.parametrize("streamed", (False, True), ids=("whole-graph", "streamed"))
def test_producer_emits_shared_validator_identity_and_separates_it_from_binding_and_content(
    tmp_path: Path,
    streamed: bool,
) -> None:
    """Both producer paths reuse toolsDigest/runtime directly without polluting binding or content identity."""

    dist, manifest = _build_fresh_distribution(tmp_path, name=f"fresh-{streamed}", streamed=streamed)
    acceptance = json.loads((dist / "atlas-acceptance.json").read_text(encoding="utf-8"))
    expected_validator = atlas_validate.validator_identity()
    cache_identity = atlas_validate._validation_cache_identity(manifest)

    # Exact reuse of the local validation cache's single identity owner (no parallel hasher).
    assert acceptance["validator"] == expected_validator
    assert acceptance["validator"]["toolsDigest"] == cache_identity["toolsDigest"] == atlas_validate._binding_tool_digest()
    assert acceptance["validator"]["runtime"] == cache_identity["runtime"] == atlas_validate.binding_runtime()
    assert acceptance["validator"]["name"] == atlas_validate.VALIDATOR_ID
    assert acceptance["validator"]["version"] == atlas_validate.VALIDATOR_VERSION

    # Implementation identity stays strictly separated from binding semantics and inputs.
    assert "toolsDigest" not in manifest["binding"]
    assert "runtime" not in manifest["binding"]
    assert "toolsDigest" not in acceptance["inputs"]
    assert "runtime" not in acceptance["inputs"]

    # Portable acceptance verification and strict full validation both pass.
    receipt = atlas_validate.verify_portable_acceptance(dist)
    assert receipt["validatorIdentityStatus"] == "current"
    assert receipt["verdict"] == "passed"
    assert receipt["validator"] == expected_validator
    assert atlas_validate.validate_distribution(dist, require_current_validator=True)["counts"]["resources"] == 8


def test_changing_validator_tools_or_runtime_preserves_content_and_binding_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing validator tools/runtime moves only the acceptance identity, never content or contractDigest."""

    dist_a, manifest_a = _build_fresh_distribution(tmp_path, name="build-a")
    acceptance_a = json.loads((dist_a / "atlas-acceptance.json").read_text(encoding="utf-8"))

    changed_tools = _edited_tools_copy(tmp_path / "changed-tools")
    bumped_runtime = {**atlas_validate.binding_runtime(), "pyshacl": "9.9.9-test"}
    monkeypatch.setattr(
        generator.ATLAS_VALIDATE,
        "_binding_tool_paths",
        lambda: tuple(changed_tools / relative for relative in atlas_validate.BINDING_TOOL_PATHS),
    )
    monkeypatch.setattr(generator.ATLAS_VALIDATE, "binding_runtime", lambda: bumped_runtime)

    dist_b, manifest_b = _build_fresh_distribution(tmp_path, name="build-b")
    acceptance_b = json.loads((dist_b / "atlas-acceptance.json").read_text(encoding="utf-8"))

    assert acceptance_a["validator"]["toolsDigest"] != acceptance_b["validator"]["toolsDigest"]
    assert acceptance_a["validator"]["runtime"] != acceptance_b["validator"]["runtime"]
    assert acceptance_a["gates"] != acceptance_b["gates"]

    # Content and binding semantics are completely invariant.
    assert manifest_a["distributionId"] == manifest_b["distributionId"]
    assert manifest_a["binding"] == manifest_b["binding"]
    assert manifest_a["graphs"] == manifest_b["graphs"]
    assert manifest_a["packs"] == manifest_b["packs"]
    assert acceptance_a["inputs"] == acceptance_b["inputs"]


def test_changed_validator_tools_refuses_portable_acceptance_and_invalidates_stale_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    baseline_distribution: tuple[Path, dict[str, Any]],
) -> None:
    """Changed validator executable refuses portable receipt reuse and forces fresh validation."""

    base_dist, manifest = baseline_distribution
    dist = _copy_distribution(base_dist, tmp_path / "tools-drift")
    cache_dir = tmp_path / "cache"
    expected = atlas_validate.validate_distribution(dist, cache_dir=cache_dir, require_current_validator=True)
    assert atlas_validate.verify_portable_acceptance(dist)["validatorIdentityStatus"] == "current"

    changed_tools = _edited_tools_copy(tmp_path / "edited-tools")
    monkeypatch.setattr(
        atlas_validate,
        "_binding_tool_paths",
        lambda: tuple(changed_tools / relative for relative in atlas_validate.BINDING_TOOL_PATHS),
    )

    with pytest.raises(atlas_validate.AtlasValidationError) as exc_portable:
        atlas_validate.verify_portable_acceptance(dist)
    assert exc_portable.value.code == "acceptance.validator-tools"

    with pytest.raises(atlas_validate.AtlasValidationError) as exc_strict:
        atlas_validate.validate_distribution(dist, require_current_validator=True)
    assert exc_strict.value.code == "acceptance.validator-tools"

    with pytest.raises(atlas_validate.AtlasValidationError) as exc_smoke:
        atlas_validate.smoke_check(dist, require_current_validator=True)
    assert exc_smoke.value.code == "acceptance.validator-tools"

    # Non-strict re-validation must still miss the stale cache and re-parse from scratch.
    original_parse = atlas_validate._parse_packed_dataset
    parses = 0

    def counted_parse(*args: object, **kwargs: object) -> Any:
        nonlocal parses
        parses += 1
        return original_parse(*args, **kwargs)

    monkeypatch.setattr(atlas_validate, "_parse_packed_dataset", counted_parse)
    assert atlas_validate.validate_distribution(dist, cache_dir=cache_dir) == expected
    assert parses == 1
    assert atlas_validate._binding_digests()["contractDigest"] == manifest["binding"]["contractDigest"]


def test_stale_validator_runtime_is_refused_and_invalidates_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    baseline_distribution: tuple[Path, dict[str, Any]],
) -> None:
    """Changed runtime dependency refuses portable receipt reuse and strict validation."""

    dist = _copy_distribution(baseline_distribution[0], tmp_path / "runtime-drift")
    cache_dir = tmp_path / "cache"
    atlas_validate.validate_distribution(dist, cache_dir=cache_dir, require_current_validator=True)

    bumped_runtime = {**atlas_validate.binding_runtime(), "pyshacl": "0.99.0-changed"}
    monkeypatch.setattr(atlas_validate, "binding_runtime", lambda: bumped_runtime)

    with pytest.raises(atlas_validate.AtlasValidationError) as exc_portable:
        atlas_validate.verify_portable_acceptance(dist)
    assert exc_portable.value.code == "acceptance.validator-runtime"

    with pytest.raises(atlas_validate.AtlasValidationError) as exc_strict:
        atlas_validate.validate_distribution(dist, require_current_validator=True)
    assert exc_strict.value.code == "acceptance.validator-runtime"

    # Stale cache receipt from previous runtime cannot be reused.
    manifest = json.loads((dist / "atlas-manifest.json").read_text(encoding="utf-8"))
    assert atlas_validate._read_validation_receipt(cache_dir, manifest) is None


def test_missing_validator_identity_fails_closed_unless_explicitly_audited_as_legacy(
    tmp_path: Path,
    baseline_distribution: tuple[Path, dict[str, Any]],
) -> None:
    """A pre-ss-b5n6 receipt omitting toolsDigest/runtime is refused by default and explicitly flagged in legacy audit."""

    dist = _copy_distribution(baseline_distribution[0], tmp_path / "legacy")
    acceptance = json.loads((dist / "atlas-acceptance.json").read_text(encoding="utf-8"))
    acceptance["validator"] = {
        "name": atlas_validate.VALIDATOR_ID,
        "version": atlas_validate.VALIDATOR_VERSION,
    }
    _rewrite_acceptance(dist, acceptance, recompute_gates=True)

    for call in (
        lambda: atlas_validate.verify_portable_acceptance(dist),
        lambda: atlas_validate.verify_portable_acceptance(
            dist, require_current_validator=True, allow_legacy_validator=True
        ),
        lambda: atlas_validate.validate_distribution(dist),
        lambda: atlas_validate.smoke_check(dist),
    ):
        with pytest.raises(atlas_validate.AtlasValidationError) as exc_info:
            call()
        assert exc_info.value.code == "binding.validator"
        assert "missing executable toolsDigest and runtime" in exc_info.value.detail

    # Explicit non-current historical audit recognizes the legacy receipt and never labels it "current".
    legacy_receipt = atlas_validate.verify_portable_acceptance(
        dist,
        require_current_validator=False,
        allow_legacy_validator=True,
    )
    assert legacy_receipt["validatorIdentityStatus"] == "legacy-unpinned"
    assert atlas_validate.validate_distribution(dist, allow_legacy_validator=True)["counts"]["resources"] == 8


@pytest.mark.parametrize(
    ("mutate_validator", "recompute_gates", "expected_code"),
    (
        (
            lambda v: {"name": v["name"], "version": v["version"], "toolsDigest": v["toolsDigest"]},
            True,
            "json.schema",
        ),
        (
            lambda v: {"name": v["name"], "version": v["version"], "runtime": v["runtime"]},
            True,
            "json.schema",
        ),
        (
            lambda v: {**v, "extra": "forbidden"},
            True,
            "json.schema",
        ),
        (
            lambda v: {**v, "toolsDigest": "not-a-sha256"},
            True,
            "json.schema",
        ),
        (
            lambda v: {**v, "runtime": {k: val for k, val in v["runtime"].items() if k != "pyshacl"}},
            True,
            "binding.validator",
        ),
        (
            lambda v: {**v, "runtime": {**v["runtime"], "unexpected-lib": "1.0.0"}},
            True,
            "binding.validator",
        ),
        (
            lambda v: {**v, "runtime": {**v["runtime"], "python": "three-twelve"}},
            True,
            "binding.validator",
        ),
        (
            lambda v: {**v, "toolsDigest": "sha256:" + "0" * 64},
            False,
            "acceptance.evidence",
        ),
        (
            lambda v: {**v, "runtime": {**v["runtime"], "rdflib": "0.0.0-tampered"}},
            False,
            "acceptance.evidence",
        ),
    ),
    ids=(
        "tools-without-runtime",
        "runtime-without-tools",
        "closed-schema-extra-key",
        "malformed-tools-digest",
        "runtime-missing-dependency",
        "runtime-extra-dependency",
        "malformed-python-version",
        "contradictory-tools-digest-vs-gates",
        "contradictory-runtime-vs-gates",
    ),
)
def test_partial_malformed_and_contradictory_validator_identities_are_refused(
    tmp_path: Path,
    mutate_validator,
    recompute_gates: bool,
    expected_code: str,
    baseline_distribution: tuple[Path, dict[str, Any]],
) -> None:
    """Closed schema, runtime completeness, and gate evidence bindings refuse every malformed/contradictory form."""

    dist = _copy_distribution(baseline_distribution[0], tmp_path / "malformed")
    acceptance = json.loads((dist / "atlas-acceptance.json").read_text(encoding="utf-8"))
    acceptance["validator"] = mutate_validator(acceptance["validator"])
    _rewrite_acceptance(dist, acceptance, recompute_gates=recompute_gates)

    with pytest.raises(atlas_validate.AtlasValidationError) as exc_info:
        atlas_validate.verify_portable_acceptance(
            dist,
            require_current_validator=False,
            allow_legacy_validator=True,
        )
    assert exc_info.value.code == expected_code

    with pytest.raises(atlas_validate.AtlasValidationError) as exc_full:
        atlas_validate.validate_distribution(dist, allow_legacy_validator=True)
    assert exc_full.value.code == expected_code


def test_cli_verify_acceptance_and_require_current_validator_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    baseline_distribution: tuple[Path, dict[str, Any]],
) -> None:
    """Standalone CLI --verify-acceptance and --require-current-validator enforce validator identity fail-closed."""

    dist = _copy_distribution(baseline_distribution[0], tmp_path / "cli")

    assert atlas_validate.main(["--verify-acceptance", str(dist), "--quiet"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["validatorIdentityStatus"] == "current"
    assert payload["validator"] == atlas_validate.validator_identity()

    assert atlas_validate.main(["--distribution", str(dist), "--require-current-validator", "--quiet"]) == 0
    capsys.readouterr()

    changed_tools = _edited_tools_copy(tmp_path / "cli-edited-tools")
    monkeypatch.setattr(
        atlas_validate,
        "_binding_tool_paths",
        lambda: tuple(changed_tools / relative for relative in atlas_validate.BINDING_TOOL_PATHS),
    )
    assert atlas_validate.main(["--verify-acceptance", str(dist), "--quiet"]) == 1
    assert "acceptance.validator-tools" in capsys.readouterr().err

    assert atlas_validate.main(["--distribution", str(dist), "--require-current-validator", "--quiet"]) == 1
    assert "acceptance.validator-tools" in capsys.readouterr().err


def test_existing_content_binding_and_seal_checks_remain_valid(tmp_path: Path) -> None:
    """Content checks, binding checks, and detached distribution seals remain intact with validator identity present."""

    staged = tmp_path / "sealed" / "staged-tables"
    dist, _manifest = _build_fresh_distribution(tmp_path, name="sealed", parquet_tables=staged)
    view_dir = tmp_path / "sealed" / "parquet-view"
    seal_atlas_parquet_view(
        dist,
        staged,
        view_dir,
        expected_manifest_digest=file_sha256(dist / "atlas-manifest.json"),
        agency_projection={
            "status": "notEmitted",
            "missingReleaseKeys": ["regulations-gov-agency-identity-2026-08-16"],
        },
        derived_relations={"status": "notEmitted"},
    )

    # Detached seal mint + verify works end-to-end with the new AtlasAcceptance bytes.
    import subprocess

    key_path = tmp_path / "test_key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key_path)],
        check=True,
    )
    allowed = tmp_path / "allowed_signers"
    pub = (tmp_path / "test_key.pub").read_text(encoding="utf-8").strip()
    allowed.write_text(f"test-signer@refspec {pub}\n", encoding="utf-8")

    seal_path = create_seal(dist, key_path, "test-signer@refspec", parquet_view_path=view_dir)
    verified = verify_seal(dist, seal_path, allowed, parquet_view_path=view_dir)
    assert verified.acceptance_sha256 == file_sha256(dist / "atlas-acceptance.json")

    # Existing binding digest tamper is still caught as binding.digest.
    acceptance = json.loads((dist / "atlas-acceptance.json").read_text(encoding="utf-8"))
    acceptance["inputs"]["contractDigest"] = "sha256:" + "1" * 64
    _rewrite_acceptance(dist, acceptance, recompute_gates=True)
    with pytest.raises(atlas_validate.AtlasValidationError) as exc_binding:
        atlas_validate.verify_portable_acceptance(dist)
    assert exc_binding.value.code == "binding.digest"


def test_verify_portable_acceptance_guards_acceptance_file_and_producer_validation(
    tmp_path: Path,
    baseline_distribution: tuple[Path, dict[str, Any]],
) -> None:
    """verify_portable_acceptance refuses missing/symlinked acceptance and tampered/forged producerValidation."""

    # 1. Missing atlas-acceptance.json -> distribution.file (not uncaught FileNotFoundError).
    missing_dist = _copy_distribution(baseline_distribution[0], tmp_path / "missing-acceptance")
    (missing_dist / "atlas-acceptance.json").unlink()
    with pytest.raises(atlas_validate.AtlasValidationError) as exc_missing:
        atlas_validate.verify_portable_acceptance(missing_dist)
    assert exc_missing.value.code == "distribution.file"

    # 2a. External symlinked atlas-acceptance.json -> distribution.path (escapes root).
    ext_symlink_dist = _copy_distribution(baseline_distribution[0], tmp_path / "ext-symlink-acceptance")
    external = tmp_path / "external-acceptance.json"
    shutil.move(str(ext_symlink_dist / "atlas-acceptance.json"), str(external))
    (ext_symlink_dist / "atlas-acceptance.json").symlink_to(external)
    with pytest.raises(atlas_validate.AtlasValidationError) as exc_ext_symlink:
        atlas_validate.verify_portable_acceptance(ext_symlink_dist)
    assert exc_ext_symlink.value.code == "distribution.path"

    # 2b. Internal symlinked atlas-acceptance.json -> distribution.file (is_symlink guard).
    int_symlink_dist = _copy_distribution(baseline_distribution[0], tmp_path / "int-symlink-acceptance")
    internal = int_symlink_dist / "atlas-acceptance-target.json"
    shutil.move(str(int_symlink_dist / "atlas-acceptance.json"), str(internal))
    (int_symlink_dist / "atlas-acceptance.json").symlink_to(internal.name)
    with pytest.raises(atlas_validate.AtlasValidationError) as exc_int_symlink:
        atlas_validate.verify_portable_acceptance(int_symlink_dist)
    assert exc_int_symlink.value.code == "distribution.file"

    # 3. Tampered atlas-producer-validation.json on disk (same byte length -> distribution.digest,
    #    different length -> distribution.length, missing -> distribution.file).
    tamper_dist = _copy_distribution(baseline_distribution[0], tmp_path / "tampered-producer")
    producer_path = tamper_dist / "atlas-producer-validation.json"
    original_bytes = producer_path.read_bytes()
    flipped = original_bytes.replace(b'"passed"', b'"pazzad"', 1)
    assert len(flipped) == len(original_bytes)
    producer_path.write_bytes(flipped)
    with pytest.raises(atlas_validate.AtlasValidationError) as exc_digest:
        atlas_validate.verify_portable_acceptance(tamper_dist)
    assert exc_digest.value.code == "distribution.digest"

    producer_path.write_bytes(original_bytes + b" ")
    with pytest.raises(atlas_validate.AtlasValidationError) as exc_length:
        atlas_validate.verify_portable_acceptance(tamper_dist)
    assert exc_length.value.code == "distribution.length"

    producer_path.unlink()
    with pytest.raises(atlas_validate.AtlasValidationError) as exc_missing_pv:
        atlas_validate.verify_portable_acceptance(tamper_dist)
    assert exc_missing_pv.value.code == "distribution.file"

    # 4. Forged inputs.producerValidationDigest in re-sealed acceptance -> producer.validation.
    forged_dist = _copy_distribution(baseline_distribution[0], tmp_path / "forged-producer-digest")
    acceptance = json.loads((forged_dist / "atlas-acceptance.json").read_text(encoding="utf-8"))
    acceptance["inputs"]["producerValidationDigest"] = "sha256:" + "9" * 64
    _rewrite_acceptance(forged_dist, acceptance, recompute_gates=True)
    with pytest.raises(atlas_validate.AtlasValidationError) as exc_forged:
        atlas_validate.verify_portable_acceptance(forged_dist)
    assert exc_forged.value.code == "producer.validation"

    # 5. Stripped inputs.producerValidationDigest while manifest still declares producerValidation.
    stripped_dist = _copy_distribution(baseline_distribution[0], tmp_path / "stripped-producer-digest")
    acceptance = json.loads((stripped_dist / "atlas-acceptance.json").read_text(encoding="utf-8"))
    del acceptance["inputs"]["producerValidationDigest"]
    _rewrite_acceptance(stripped_dist, acceptance, recompute_gates=True)
    with pytest.raises(atlas_validate.AtlasValidationError) as exc_stripped:
        atlas_validate.verify_portable_acceptance(stripped_dist)
    assert exc_stripped.value.code == "producer.validation"


def test_cli_require_current_validator_refuses_bare_binding_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--require-current-validator without --distribution/--smoke/--verify-acceptance fails closed."""

    assert atlas_validate.main(["--require-current-validator", "--quiet"]) == 1
    assert "binding.validator" in capsys.readouterr().err


def test_validate_preparsed_distribution_enforces_validator_identity_policies(
    tmp_path: Path,
    baseline_distribution: tuple[Path, dict[str, Any]],
) -> None:
    """validate_preparsed_distribution enforces require_current_validator and allow_legacy_validator directly."""

    dist = _copy_distribution(baseline_distribution[0], tmp_path / "preparsed")
    manifest = json.loads((dist / "atlas-manifest.json").read_text(encoding="utf-8"))
    accounting = json.loads((dist / "atlas-source-accounting.json").read_text(encoding="utf-8"))
    acceptance = json.loads((dist / "atlas-acceptance.json").read_text(encoding="utf-8"))
    producer_validation = json.loads((dist / "atlas-producer-validation.json").read_text(encoding="utf-8"))
    construction_summary = json.loads((dist / "atlas-construction-summary.json").read_text(encoding="utf-8"))
    member_digests = {member["path"]: member["digest"] for member in manifest["members"]}
    graph_ids = {row["role"]: atlas_validate.URIRef(row["id"]) for row in manifest["graphs"]}
    dataset, graphs = atlas_validate._parse_packed_dataset(dist, manifest, graph_ids)
    try:
        # 1. Fresh receipt passes with require_current_validator=True.
        passed = atlas_validate.validate_preparsed_distribution(
            manifest,
            accounting,
            acceptance,
            graphs,
            member_digests=member_digests,
            producer_validation=producer_validation,
            construction_summary=construction_summary,
            require_current_validator=True,
        )
        assert passed["distributionId"] == manifest["distributionId"]

        # 2. Stale toolsDigest is refused when require_current_validator=True.
        stale_tools = json.loads(json.dumps(acceptance))
        stale_tools["validator"]["toolsDigest"] = "sha256:" + "a" * 64
        with pytest.raises(atlas_validate.AtlasValidationError) as exc_tools:
            atlas_validate.validate_preparsed_distribution(
                manifest,
                accounting,
                stale_tools,
                graphs,
                member_digests=member_digests,
                producer_validation=producer_validation,
                construction_summary=construction_summary,
                require_current_validator=True,
            )
        assert exc_tools.value.code == "acceptance.validator-tools"

        # 3. Stale runtime is refused when require_current_validator=True.
        stale_runtime = json.loads(json.dumps(acceptance))
        stale_runtime["validator"]["runtime"]["rdflib"] = "0.0.1"
        with pytest.raises(atlas_validate.AtlasValidationError) as exc_runtime:
            atlas_validate.validate_preparsed_distribution(
                manifest,
                accounting,
                stale_runtime,
                graphs,
                member_digests=member_digests,
                producer_validation=producer_validation,
                construction_summary=construction_summary,
                require_current_validator=True,
            )
        assert exc_runtime.value.code == "acceptance.validator-runtime"

        # 4. Legacy {name, version} receipt is refused by default and admitted only with allow_legacy_validator=True.
        legacy_dist = _copy_distribution(baseline_distribution[0], tmp_path / "preparsed-legacy")
        legacy_acceptance = json.loads((legacy_dist / "atlas-acceptance.json").read_text(encoding="utf-8"))
        legacy_acceptance["validator"] = {
            "name": atlas_validate.VALIDATOR_ID,
            "version": atlas_validate.VALIDATOR_VERSION,
        }
        _rewrite_acceptance(legacy_dist, legacy_acceptance, recompute_gates=True)
        legacy_manifest = json.loads((legacy_dist / "atlas-manifest.json").read_text(encoding="utf-8"))
        legacy_acceptance = json.loads((legacy_dist / "atlas-acceptance.json").read_text(encoding="utf-8"))
        legacy_member_digests = {member["path"]: member["digest"] for member in legacy_manifest["members"]}

        with pytest.raises(atlas_validate.AtlasValidationError) as exc_legacy_default:
            atlas_validate.validate_preparsed_distribution(
                legacy_manifest,
                accounting,
                legacy_acceptance,
                graphs,
                member_digests=legacy_member_digests,
                producer_validation=producer_validation,
                construction_summary=construction_summary,
            )
        assert exc_legacy_default.value.code == "binding.validator"

        legacy_ok = atlas_validate.validate_preparsed_distribution(
            legacy_manifest,
            accounting,
            legacy_acceptance,
            graphs,
            member_digests=legacy_member_digests,
            producer_validation=producer_validation,
            construction_summary=construction_summary,
            require_current_validator=False,
            allow_legacy_validator=True,
        )
        assert legacy_ok["distributionId"] == legacy_manifest["distributionId"]
    finally:
        del dataset
