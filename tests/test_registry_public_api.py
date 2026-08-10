from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from refspec import registry
from refspec.registry import federal_register_topics_api
from refspec.registry.adapters import elsst_import_coverage
from refspec.registry.infrastructure.semantic_foundation import SEMANTIC_RINGS

ROOT = Path(__file__).resolve().parents[1]


def _load_tool_module(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_registry_exports_each_declared_public_name() -> None:
    assert len(registry.__all__) == len(set(registry.__all__))
    assert all(hasattr(registry, name) for name in registry.__all__)


def test_registry_exposes_managed_vocabulary_source_of_truth_interfaces() -> None:
    modules = (
        elsst_import_coverage,
        federal_register_topics_api,
    )

    for module in modules:
        for name in module.__all__:
            if name.isupper():
                continue
            assert getattr(registry, name) is getattr(module, name)


def test_semantic_rings_agree_across_every_python_site() -> None:
    """Every Python site that needs the semantic-ring set must import the one
    canonical definition in ``semantic_foundation``, not a local copy. This
    asserts identity (``is``), not just equality, so a site that reverts to
    hand-writing its own frozenset -- even with the *same* four values --
    fails here, not just a site that drifts to different values.
    """

    assert registry.SEMANTIC_RINGS is SEMANTIC_RINGS
    assert registry.RING_RELATIONS.keys() == SEMANTIC_RINGS

    from refspec import atlas_index
    from refspec.atlas import compact_pack, explorer_rdf, v3_source_data

    assert atlas_index.SEMANTIC_RINGS is SEMANTIC_RINGS
    assert compact_pack._SEMANTIC_RINGS is SEMANTIC_RINGS
    assert v3_source_data.SEMANTIC_RINGS is SEMANTIC_RINGS
    assert explorer_rdf._RINGS is SEMANTIC_RINGS

    coverage = _load_tool_module("generate_atlas_v3_registry_coverage")
    assert coverage.SEMANTIC_RINGS is SEMANTIC_RINGS
    assert coverage.RELATION_POLICY_RINGS == tuple(sorted(SEMANTIC_RINGS))
    assert coverage.RING_ENTRY_CLASSES.keys() == SEMANTIC_RINGS

    descriptors = _load_tool_module("generate_atlas_v3_registry_descriptors")
    assert descriptors.SEMANTIC_RINGS is SEMANTIC_RINGS


def test_registry_exposes_completed_resource_package_readers() -> None:
    assert registry.SEMANTIC_RINGS == {"subject", "entity", "value", "legalIdentity"}
    assert registry.RING_RELATIONS.keys() == registry.SEMANTIC_RINGS
    assert "EVIDENCE_PROOF_STATUSES" not in registry.__all__
    assert registry.EVIDENCE_USE_CEILINGS["machineQualified"] == "searchOnly"
    assert registry.EVIDENCE_USE_CEILINGS["machineReviewed"] == "notApplicable"
    assert registry.MACHINE_EVIDENCE_PROOF_VERSION == "1.0"
    assert registry.EvidenceAssertion is not None
    assert registry.MappingAssertion is not None
    assert registry.RightsMetadata is not None
    assert registry.IcpsrManagedReleaseView is not None
    assert registry.SourceControlledResourceView is not None
    assert registry.SourceConceptReleaseView is not None
    assert registry.CRSSourceConceptReleases is not None
    assert registry.LDAControlledListView is not None
    assert callable(registry.build_icpsr_managed_release)
    assert callable(registry.build_federal_register_topics_source_package)
    assert callable(registry.build_crs_source_packages)
    assert callable(registry.build_crs_source_concept_releases)
    assert callable(registry.build_source_concept_release_bundle)
    assert callable(registry.validate_evidence_assertions)
    assert callable(registry.validate_mapping_assertions)
    assert callable(registry.validate_machine_evidence_proof_pin)
    assert callable(registry.validate_rights_metadata_records)
    assert callable(registry.build_lda_general_issue_code_package)
    assert callable(registry.build_lda_filing_type_package)


def test_importing_source_controlled_resources_does_not_load_other_adapters() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import refspec.registry.infrastructure.source_controlled_resource; "
                "unexpected=[name for name in sys.modules if "
                "name.startswith(('refspec.registry.adapters', "
                "'refspec.registry.elsst', "
                "'refspec.registry.federal_register', 'refspec.registry.icpsr'))]; "
                "print(','.join(unexpected)); raise SystemExit(bool(unexpected))"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout
