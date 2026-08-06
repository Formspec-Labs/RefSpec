from __future__ import annotations

import pytest

from refspec.atlas.v3_source_data import RegistryLabel, RegistryResource


def _resource(labels: tuple[RegistryLabel, ...]) -> RegistryResource:
    return RegistryResource(
        iri="urn:example:resource",
        labels=labels,
        native_payload={"id": "example"},
        source_locator="urn:example:source-record",
        source_digest="sha256:" + ("0" * 64),
    )


def test_registry_resource_accepts_publisher_alternate_only_identity() -> None:
    resource = _resource(
        (
            RegistryLabel(
                value="Publisher alternate",
                role="alternate",
                source_path="$.labels[0]",
            ),
        )
    )

    assert resource.labels[0].role == "alternate"


def test_registry_resource_rejects_multiple_preferred_labels() -> None:
    labels = tuple(
        RegistryLabel(value=value, role="preferred", source_path=f"$.labels[{index}]")
        for index, value in enumerate(("First", "Second"))
    )

    with pytest.raises(ValueError, match="more than one preferred"):
        _resource(labels)


def test_registry_resource_rejects_duplicate_label_claim() -> None:
    label = RegistryLabel(
        value="Repeated",
        role="alternate",
        source_path="$.labels[0]",
    )

    with pytest.raises(ValueError, match="repeats label claim"):
        _resource((label, label))


def test_registry_resource_rejects_label_value_across_roles() -> None:
    with pytest.raises(ValueError, match="reuses label value.*across roles"):
        _resource(
            (
                RegistryLabel(
                    value="Same value",
                    role="preferred",
                    source_path="$.labels[0]",
                ),
                RegistryLabel(
                    value="Same value",
                    role="hidden",
                    source_path="$.labels[1]",
                ),
            )
        )


def test_registry_resource_requires_at_least_one_label() -> None:
    with pytest.raises(ValueError, match="has no English label"):
        _resource(())
