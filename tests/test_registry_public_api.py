from __future__ import annotations

import subprocess
import sys

from refspec import registry
from refspec.registry import federal_register_topics_api
from refspec.registry.adapters import elsst_import_coverage


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


def test_registry_exposes_completed_resource_package_readers() -> None:
    assert registry.SEMANTIC_RINGS == {"subject", "entity", "value", "legalIdentity"}
    assert registry.RING_RELATIONS.keys() == registry.SEMANTIC_RINGS
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
