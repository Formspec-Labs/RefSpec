from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from refspec.atlas import v3_registry_alignments as alignments
from refspec.atlas import v3_registry_codes as codes
from refspec.atlas import v3_registry_documents as documents
from refspec.atlas import v3_registry_large as large
from refspec.atlas import v3_registry_nonemitters as nonemitters
from refspec.atlas import v3_registry_vocabularies as vocabularies


def _release(key: str) -> Any:
    return SimpleNamespace(key=key)


def test_large_loader_opens_only_requested_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[tuple[str, Path]] = []

    for key, _loader, filename in large._large_registry_loader_specs():
        function_name = _loader.__name__

        def fake(path: Path, *, _key: str = key) -> Any:
            called.append((_key, path))
            return _release(_key)

        monkeypatch.setattr(large, function_name, fake)

    root = Path("/pinned")
    releases = large.load_large_registry_releases(
        root,
        only_keys={"fast-topical-current", "psc-april-2025"},
    )

    assert [release.key for release in releases] == [
        "fast-topical-current",
        "psc-april-2025",
    ]
    assert called == [
        ("fast-topical-current", root),
        ("psc-april-2025", root / "PSC-April-2025-wayback.xlsx"),
    ]


def test_vocabulary_loader_parses_only_intersecting_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    def eurovoc(
        _root: Path,
        **_kwargs: object,
    ) -> tuple[Any, ...]:
        called.append("eurovoc")
        return (_release("eurovoc-4.24"), _release("eurovoc-domains-4.24"))

    monkeypatch.setattr(vocabularies, "load_eurovoc_4_24_releases", eurovoc)
    for loader in vocabularies.REGISTRY_VOCABULARY_LOADERS:
        monkeypatch.setattr(
            vocabularies,
            loader.__name__,
            lambda _root, _name=loader.__name__: called.append(_name),
        )

    releases = vocabularies.load_all_registry_vocabulary_releases(
        Path("/pinned"),
        only_keys={"eurovoc-domains-4.24"},
    )

    assert [release.key for release in releases] == ["eurovoc-domains-4.24"]
    assert called == ["eurovoc"]


def test_eurovoc_domains_claim_input_skips_the_source_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_input = object()
    monkeypatch.setattr(
        vocabularies,
        "load_eurovoc_4_24_releases",
        lambda *_args, **_kwargs: pytest.fail(
            "the domain claim view opened the EuroVoc source parser"
        ),
    )
    monkeypatch.setattr(
        vocabularies,
        "load_eurovoc_4_24_domain_release_from_claims",
        lambda input_: (
            _release("eurovoc-domains-4.24")
            if input_ is claim_input
            else pytest.fail("the domain loader received a different claim input")
        ),
    )

    releases = vocabularies.load_all_registry_vocabulary_releases(
        Path("/unused"),
        only_keys={"eurovoc-domains-4.24"},
        registry_claim_inputs={"eurovoc-4.24": claim_input},  # type: ignore[dict-item]
    )

    assert [release.key for release in releases] == [
        "eurovoc-domains-4.24"
    ]


def test_main_eurovoc_claim_input_skips_the_source_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_input = object()
    monkeypatch.setattr(
        vocabularies,
        "acquire_eurovoc_release",
        lambda *_args, **_kwargs: pytest.fail(
            "the main claim view opened the EuroVoc source parser"
        ),
    )
    monkeypatch.setattr(
        vocabularies,
        "load_eurovoc_4_24_releases_from_claims",
        lambda input_: (
            (
                _release("eurovoc-4.24"),
                _release("eurovoc-domains-4.24"),
            )
            if input_ is claim_input
            else pytest.fail("the EuroVoc loader received a different claim input")
        ),
    )

    releases = vocabularies.load_all_registry_vocabulary_releases(
        Path("/unused"),
        only_keys={"eurovoc-4.24"},
        registry_claim_inputs={"eurovoc-4.24": claim_input},  # type: ignore[dict-item]
    )

    assert [release.key for release in releases] == ["eurovoc-4.24"]


def test_document_loader_calls_only_requested_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    def fake(_root: Path) -> Any:
        called.append("topic")
        return _release("gao-topics-observed-on-gao-26-108505")

    monkeypatch.setattr(documents, "load_gao_topic_release", fake)
    releases = documents.load_registry_document_releases(
        Path("/repo"),
        only_keys={"gao-topics-observed-on-gao-26-108505"},
    )

    assert [release.key for release in releases] == [
        "gao-topics-observed-on-gao-26-108505"
    ]
    assert called == ["topic"]


def test_code_loader_parses_one_group_and_filters_its_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    def billstatus(_root: Path, _temporary: Path) -> tuple[Any, ...]:
        called.append("billstatus")
        return tuple(
            _release(key)
            for key in (
                "billstatus-bill-types",
                "billstatus-summary-version-codes",
                "billstatus-action-codes",
            )
        )

    monkeypatch.setattr(codes, "_load_billstatus", billstatus)
    releases = codes.load_registry_code_releases(
        Path("/repo"),
        only_keys={"billstatus-action-codes"},
    )

    assert [release.key for release in releases] == ["billstatus-action-codes"]
    assert called == ["billstatus"]


def test_nonemitter_loader_parses_one_group_and_filters_its_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    def nppes(_root: Path) -> tuple[Any, ...]:
        called.append("nppes")
        return (
            _release("nppes-data-dissemination-layout-v2-2026-08-03"),
            _release("nppes-npi-provider-sample-2026-08-03"),
        )

    monkeypatch.setattr(nonemitters, "_nppes_releases", nppes)
    releases = nonemitters.load_registry_nonemitter_releases(
        Path("/repo"),
        only_keys={"nppes-npi-provider-sample-2026-08-03"},
    )

    assert [release.key for release in releases] == [
        "nppes-npi-provider-sample-2026-08-03"
    ]
    assert called == ["nppes"]


def test_mapping_and_alignment_loaders_skip_empty_selections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        alignments,
        "load_eurovoc_lcsh_mapping_release",
        lambda _root: pytest.fail("empty mapping selection parsed a source"),
    )
    monkeypatch.setattr(
        alignments,
        "load_lcsh_alignment_endpoint_release",
        lambda _root: pytest.fail("empty endpoint selection parsed a source"),
    )

    assert alignments.load_all_registry_mapping_releases(only_keys=set()) == ()
    assert (
        alignments.load_all_registry_alignment_endpoint_releases(only_keys=set())
        == ()
    )


@pytest.mark.parametrize(
    "loader,args",
    (
        (large.load_large_registry_releases, ()),
        (vocabularies.load_all_registry_vocabulary_releases, ()),
        (documents.load_registry_document_releases, ()),
        (codes.load_registry_code_releases, (Path("/repo"),)),
        (nonemitters.load_registry_nonemitter_releases, (Path("/repo"),)),
        (alignments.load_all_registry_mapping_releases, ()),
        (alignments.load_all_registry_alignment_endpoint_releases, ()),
    ),
)
def test_selective_loaders_reject_unknown_keys_before_parsing(
    loader: Any,
    args: tuple[Any, ...],
) -> None:
    with pytest.raises(ValueError, match="does not know release keys"):
        loader(*args, only_keys={"not-a-release"})


def test_empty_code_and_nonemitter_selections_do_not_open_any_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codes,
        "_load_billstatus",
        lambda *_args: pytest.fail("empty code selection parsed a source"),
    )
    monkeypatch.setattr(
        nonemitters,
        "_agrovoc_releases",
        lambda *_args: pytest.fail("empty nonemitter selection parsed a source"),
    )

    assert codes.load_registry_code_releases(Path("/repo"), only_keys=set()) == ()
    assert (
        nonemitters.load_registry_nonemitter_releases(
            Path("/repo"), only_keys=set()
        )
        == ()
    )
