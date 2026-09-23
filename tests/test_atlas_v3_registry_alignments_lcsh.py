"""Tests for the REF-040 consolidated LCSH release.

Real-data assertions run behind one module-scoped fixture gated on the pinned
bulk file, LC external-links archive, EuroVoc-LCSH alignment, FAST archives and
the Northwestern MeSH-LCSH mapping (see ``gather_referenced_lcsh_iris``), kept
to one fixture because this release's own full-corpus scan takes tens of seconds.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from conftest import missing_pinned_input
from refspec.atlas.v3_registry_alignments_lcsh import (
    DEFAULT_SOURCE_ROOT,
    LCSH_BULK_FILENAME,
    LCSH_CONSOLIDATED_ATLAS_RELEASE_IRI,
    LCSH_CONSOLIDATED_RELEASE_KEY,
    LCSH_CONSOLIDATED_RELEASE_KEYS,
    RETIRED_LCSH_ENDPOINT_RELEASE_KEYS,
    _resource_labels,
    load_lcsh_consolidated_release,
)
from refspec.registry import fast_topical
from refspec.registry import lc_external_links as external
from refspec.registry import lcsh_mesh_mapping as mesh_lcsh
from refspec.registry.eurovoc_lcsh_alignment import EUROVOC_LCSH_ALIGNMENT_FILENAME
from refspec.registry.lcsh_topical import LcshTopicalLabel, LcshTopicalRecord

ROOT = Path(__file__).resolve().parents[1]


def _generator_module():
    """Import ``generate_atlas_v3_full`` from tools/ with that directory temporarily on sys.path."""

    sys.path.insert(0, str(ROOT / "tools"))
    try:
        return importlib.import_module("generate_atlas_v3_full")
    finally:
        sys.path.remove(str(ROOT / "tools"))


SOURCE_ROOT = DEFAULT_SOURCE_ROOT
REQUIRED_FILES = (
    SOURCE_ROOT / "lcsh-subjects-madsrdf-2026-08-06.jsonld.gz",
    SOURCE_ROOT / "eurovoc-lcsh-alignment-20240711.rdf",
    SOURCE_ROOT / external.LC_EXTERNAL_LINKS_FILENAME,
    SOURCE_ROOT / "mesh-lcsh-mapping-20210325.zip",
)
HAS_REAL_SOURCES = all(path.is_file() for path in REQUIRED_FILES)

# The real deprecated record this release's fidelity spec and the
# lcsh_topical mutation battery are both modeled on.
KNOWN_DEPRECATED_IRI = "http://id.loc.gov/authorities/subjects/sh00000273"
KNOWN_USE_INSTEAD = frozenset(
    {
        "http://id.loc.gov/authorities/subjects/sh2021004026",
        "http://id.loc.gov/authorities/subjects/sh2021004027",
    }
)


@pytest.fixture(scope="module")
def release():
    """Load the consolidated release once per module, skipping when the pinned sources are not cached."""

    if not HAS_REAL_SOURCES:
        missing_pinned_input("pinned LCSH consolidation sources are not cached")
    return load_lcsh_consolidated_release(SOURCE_ROOT)


def test_release_identity_and_shape(release) -> None:
    """Pins the release key, IRI, ring/profile/scope, and the 514,837 unique resources and 301,442 relations."""

    assert release.key == LCSH_CONSOLIDATED_RELEASE_KEY
    assert release.atlas_release_iri == LCSH_CONSOLIDATED_ATLAS_RELEASE_IRI
    assert release.ring == "subject"
    assert release.profile == "conceptScheme"
    assert release.scope == "captureSubset"
    assert len(release.resources) == 514_837
    assert len(release.relations) == 301_442
    assert len({resource.iri for resource in release.resources}) == 514_837


def test_release_metadata_states_the_scope_honestly(release) -> None:
    """Pins the capture-subset metadata: current and retained-deprecated
    counts, the publisher total, and the scope statement.
    """

    metadata = release.metadata
    assert metadata["currentHeadingCount"] == 513_210
    assert metadata["deprecatedHeadingsRetainedCount"] == 1_627
    assert metadata["deprecatedTotalInPublisherFile"] == 7_845
    assert metadata["deprecatedHeadingsExcludedCount"] == 7_845 - 1_627
    assert metadata["linesScanned"] == 521_055
    assert metadata["completePublisherRelease"] is False
    assert metadata["consolidatesRetiredReleases"] == list(RETIRED_LCSH_ENDPOINT_RELEASE_KEYS)
    assert "mapping-only" in metadata["scopeStatement"]
    assert "deprecated" in metadata["scopeStatement"]


def test_retains_the_known_deprecated_member_with_lc_status_verbatim(release) -> None:
    """A known deprecated heading keeps its status, useInstead targets and
    deletion note, with its variantLabel as the only preferred label.
    """

    resource = next(r for r in release.resources if r.iri == KNOWN_DEPRECATED_IRI)

    assert resource.status == "deprecated"
    deprecation = resource.native_payload["deprecation"]
    assert deprecation["deprecated"] is True
    assert set(deprecation["useInsteadIris"]) == KNOWN_USE_INSTEAD
    assert deprecation["deletionNote"] is not None
    assert "madsrdf:DeprecatedAuthority" in resource.native_payload["authorityTypes"]
    # A deprecated member's only label is its variantLabel, carried as this
    # release's preferred label; nothing here resolves useInstead into a
    # displayed successor.
    preferred = [label for label in resource.labels if label.role == "preferred"]
    assert len(preferred) == 1
    assert preferred[0].value == "Child concentration camp inmates"


def test_a_current_member_carries_no_deprecation_claim(release) -> None:
    """A current member states deprecated False, no useInstead targets, and no deletion note."""

    resource = next(r for r in release.resources if r.status == "current")

    deprecation = resource.native_payload["deprecation"]
    assert deprecation["deprecated"] is False
    assert deprecation["useInsteadIris"] == []
    assert deprecation["deletionNote"] is None


def test_referenced_deprecated_member_use_instead_targets_are_absolute_iris(release) -> None:
    """Every useInstead target is carried verbatim under the LC authority space, unfiltered by scheme."""
    # A successor is not always another subject: LC sometimes merges a
    # deprecated subject heading into a name authority
    # (id.loc.gov/authorities/names/...). This release does not resolve or
    # filter useInstead by scheme; it carries whatever LC states.
    for resource in release.resources:
        if resource.status != "deprecated":
            continue
        for iri in resource.native_payload["deprecation"]["useInsteadIris"]:
            assert iri.startswith("http://id.loc.gov/authorities/")


def test_consolidated_release_is_cached_across_callers(release) -> None:
    """A second load returns the identical object rather than rebuilding the release."""
    assert load_lcsh_consolidated_release(SOURCE_ROOT) is release


def test_release_declares_every_file_its_selection_actually_reads(release) -> None:
    """The release declares all nine input pins its selection actually reads.

    fix4 review finding 2: the retired endpoint loader declared the bulk pin plus
    its external and selection pins, and ``gather_referenced_lcsh_iris`` reads the
    same shape of sources -- the EuroVoc-LCSH alignment, LC external-links,
    MeSH-LCSH mapping and every pinned FAST archive -- so declaring only the bulk
    pin claimed one file where the release read nine. The bulk file stays first
    because ``generate_atlas_v3_full``'s ``_adapt_registry_release`` keys the
    emitted digest and path off it.
    """

    filenames = [Path(pin.logical_path).name for pin in release.inputs]
    assert len(filenames) == len(set(filenames)), "an input pin repeats"
    # The bulk file stays the primary parse source generate_atlas_v3_full's
    # _adapt_registry_release keys the emitted digest/path off of.
    assert filenames[0] == LCSH_BULK_FILENAME
    assert set(filenames) == {
        LCSH_BULK_FILENAME,
        EUROVOC_LCSH_ALIGNMENT_FILENAME,
        external.LC_EXTERNAL_LINKS_FILENAME,
        mesh_lcsh.LCSH_MESH_MAPPING_FILENAME,
        fast_topical.FAST_TOPICAL_NATIVE_BASE_PIN.filename,
        *(pin.filename for pin in fast_topical.FAST_TOPICAL_CHANGE_PINS),
    }
    assert len(release.inputs) == 9


def test_referenced_selection_pins_are_cached_and_include_fast_inputs() -> None:
    """The eight referenced-selection pins are cached across calls and ordered
    EuroVoc, external, MeSH, then the five FAST pins.
    """

    from refspec.atlas.v3_registry_alignments_lcsh import _lcsh_referenced_selection_pins

    if not HAS_REAL_SOURCES:
        missing_pinned_input("pinned LCSH consolidation sources are not cached")
    first = _lcsh_referenced_selection_pins(SOURCE_ROOT)
    second = _lcsh_referenced_selection_pins(SOURCE_ROOT)
    assert first is second
    assert len(first) == 8  # eurovoc + external + mesh + 5 FAST pins
    assert first[0].logical_path.endswith(EUROVOC_LCSH_ALIGNMENT_FILENAME)
    assert first[1].logical_path.endswith(external.LC_EXTERNAL_LINKS_FILENAME)
    assert first[2].logical_path.endswith(mesh_lcsh.LCSH_MESH_MAPPING_FILENAME)


def test_recipe_closure_pins_this_module() -> None:
    """The adapter recipe's closure must list this module as one of its inputs."""

    generator = _generator_module()
    recipe_inputs = generator._adapter_recipe_inputs(
        key=LCSH_CONSOLIDATED_RELEASE_KEY,
        kind="sourceRelease",
        source_module="refspec.registry.lcsh_topical",
    )
    pinned_paths = {row["path"] for row in recipe_inputs}
    assert "src/refspec/atlas/v3_registry_alignments_lcsh.py" in pinned_paths


def test_recipe_closure_release_keys_constant_is_ready_for_the_group_wiring() -> None:
    """The cross-file fix's constant already exists and names exactly this release, so wiring it is two lines."""
    # The constant the cross-file fix needs to import already exists and names
    # exactly this release, so wiring it up is a two-line change once made.
    assert LCSH_CONSOLIDATED_RELEASE_KEYS == frozenset({LCSH_CONSOLIDATED_RELEASE_KEY})


def test_resource_labels_prefers_authoritative_label_and_deduplicates() -> None:
    """Labels prefer the authoritative preferred label, deduplicate by value,
    and demote variant labels to alternates.
    """

    record = LcshTopicalRecord(
        concept_iri="https://example.test/lcsh/one",
        lccn=None,
        preferred_label=LcshTopicalLabel(value="Main heading", language="en"),
        variant_labels=(
            LcshTopicalLabel(value="Main heading", language="en-Latn"),
            LcshTopicalLabel(value="Search synonym", language="en-Latn"),
            LcshTopicalLabel(value="Terme francais", language="fr"),
        ),
        broader_iris=(),
        authority_types=("madsrdf:Authority",),
        source_url="https://example.test/lcsh.ndjson",
        line_number=1,
        raw_line=b"{}",
    )

    labels = _resource_labels(record)

    assert [(label.value, label.role, label.language) for label in labels] == [
        ("Main heading", "preferred", "en"),
        ("Search synonym", "alternate", "en"),
    ]


def test_resource_labels_uses_variant_label_field_for_a_deprecated_record() -> None:
    """A deprecated record's variantLabel becomes its preferred label, sourced from ``line-1:madsrdf:variantLabel``."""

    record = LcshTopicalRecord(
        concept_iri="https://example.test/lcsh/deprecated-one",
        lccn=None,
        preferred_label=LcshTopicalLabel(value="Old heading", language="en"),
        variant_labels=(),
        broader_iris=(),
        authority_types=("madsrdf:DeprecatedAuthority", "madsrdf:Topic", "madsrdf:Variant"),
        source_url="https://example.test/lcsh.ndjson",
        line_number=1,
        raw_line=b"{}",
        use_instead_iris=("https://example.test/lcsh/new-one",),
    )

    labels = _resource_labels(record)

    assert len(labels) == 1
    assert labels[0].role == "preferred"
    assert labels[0].value == "Old heading"
    assert labels[0].source_path == "line-1:madsrdf:variantLabel"
