from __future__ import annotations

from refspec import registry
from refspec.registry import (
    elsst_import_coverage,
    elsst_managed_release,
    federal_register_topics_api,
    federal_register_topics_reconciliation,
)


def test_registry_exports_each_declared_public_name() -> None:
    assert len(registry.__all__) == len(set(registry.__all__))
    assert all(hasattr(registry, name) for name in registry.__all__)


def test_registry_exposes_managed_vocabulary_source_of_truth_interfaces() -> None:
    modules = (
        elsst_import_coverage,
        elsst_managed_release,
        federal_register_topics_api,
        federal_register_topics_reconciliation,
    )

    for module in modules:
        for name in module.__all__:
            if name.isupper():
                continue
            assert getattr(registry, name) is getattr(module, name)


def test_registry_exposes_completed_resource_package_readers() -> None:
    assert registry.IcpsrManagedReleaseView is not None
    assert registry.SourceControlledResourceView is not None
    assert registry.LDAControlledListView is not None
    assert callable(registry.build_icpsr_managed_release)
    assert callable(registry.build_federal_register_topics_source_package)
    assert callable(registry.build_crs_source_packages)
    assert callable(registry.build_lda_general_issue_code_package)
    assert callable(registry.build_lda_filing_type_package)
