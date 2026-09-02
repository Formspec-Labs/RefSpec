"""GAO's published /topics index: pinned capture and strict parse."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import gao_published_topics as gao

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "tests" / "fixtures" / "gao_published_topics" / "gao-topics-2026-08-15.html").read_bytes()
SCIENCE_PAGE = (
    ROOT / "tests" / "fixtures" / "gao_published_topics" / "gao-science-and-technology-2026-09-01.html"
).read_bytes()


def test_index_carries_the_thirty_published_topics() -> None:
    index = gao.parse_gao_published_topics(PAGE)

    assert len(index.topics) == 30
    assert index.listing_title == "Browse Topics Alphabetically"
    assert index.source_sha256 == gao.GAO_TOPICS_2026_08_15.expected_sha256
    assert index.source_byte_length == gao.GAO_TOPICS_2026_08_15.expected_byte_length

    slugs = [topic.slug for topic in index.topics]
    assert slugs[0] == "agriculture-and-food"
    assert slugs[-1] == "worker-and-family-assistance"
    assert "gao-mission-and-operations" in slugs
    assert len(set(slugs)) == 30

    names = [topic.name for topic in index.topics]
    assert names == sorted(names, key=str.casefold)


def test_topics_carry_publisher_identity_not_minted_identity() -> None:
    # The REF-032-deleted unit carried one observed label with RefSpec-minted
    # UUIDv7 identity. Here both identifiers are the publisher's own: the
    # /topics/<slug> path and the numeric Drupal taxonomy term id rendered in
    # the publisher's markup.
    index = gao.parse_gao_published_topics(PAGE)
    by_slug = index.by_slug()

    agriculture = by_slug["agriculture-and-food"]
    assert agriculture.term_id == "151"
    assert agriculture.name == "Agriculture and Food"
    assert agriculture.page_url == "https://www.gao.gov/topics/agriculture-and-food"
    assert agriculture.description.startswith("Agricultural industry, markets, and food production")

    # Term ids are persistent publisher identity, not render ordinals: the
    # later-added GAO Mission and Operations term sits mid-alphabet with an
    # id far outside its neighbours' sequence.
    mission = by_slug["gao-mission-and-operations"]
    assert mission.term_id == "896"

    term_ids = {topic.term_id for topic in index.topics}
    assert len(term_ids) == 30
    assert all(topic.description for topic in index.topics)


def test_topic_page_supplies_the_publisher_identity_missing_from_the_browse_listing() -> None:
    """A publisher topic page is vocabulary evidence; product rows alone are not.

    The old 30-row browse adapter existed to avoid turning observed product
    assignments into a vocabulary.  Keep that reason.  This addition is
    admissible because GAO's own topic page independently states the slug,
    label, Drupal taxonomy-term id, and ``vocabulary-topic`` class.
    """

    topic = gao.parse_gao_topic_page(
        SCIENCE_PAGE,
        pin=gao.GAO_SCIENCE_AND_TECHNOLOGY_2026_09_01,
    )

    assert topic.slug == "science-and-technology"
    assert topic.term_id == "276"
    assert topic.name == "Science and Technology"
    assert topic.page_url == "https://www.gao.gov/topics/science-and-technology"
    assert topic.source_sha256 == gao.GAO_SCIENCE_AND_TECHNOLOGY_2026_09_01.expected_sha256
    assert topic.source_byte_length == len(SCIENCE_PAGE)
    assert topic.retrieved_at == "2026-09-01T23:33:02Z"


def test_topic_page_identity_drift_is_refused() -> None:
    text = SCIENCE_PAGE.decode("utf-8")
    drifted = text.replace('id="taxonomy-term-276"', 'id="taxonomy-term-277"', 1).encode("utf-8")

    with pytest.raises(gao.GaoSourceDriftError, match="taxonomy identity"):
        gao.parse_gao_topic_page(drifted, pin=_repinned(drifted, source_url=gao.GAO_SCIENCE_AND_TECHNOLOGY_URL))


def test_topic_page_label_must_come_from_the_declared_page_title_block() -> None:
    """A matching H1 elsewhere cannot justify the retained CSS source path."""

    moved = SCIENCE_PAGE.replace(
        b'id="block-gao-uswds-page-title"',
        b'id="moved-gao-page-title"',
        1,
    )

    with pytest.raises(gao.GaoSourceDriftError, match="page-title block"):
        gao.parse_gao_topic_page(
            moved,
            pin=_repinned(moved, source_url=gao.GAO_SCIENCE_AND_TECHNOLOGY_URL),
        )


def test_featured_content_nodes_are_reported_but_not_topics() -> None:
    index = gao.parse_gao_published_topics(PAGE)

    assert index.featured_entry_hrefs == (
        "/america-250",
        "/fraud-improper-payments",
        "/science-technology",
        "/cybersecurity",
    )
    featured = set(index.featured_entry_hrefs)
    assert all(topic.page_href not in featured for topic in index.topics)


def test_drifted_page_bytes_are_refused() -> None:
    with pytest.raises(gao.GaoSourceDriftError, match="digest drift"):
        gao.parse_gao_published_topics(PAGE[:-1] + bytes([PAGE[-1] ^ 0x01]))
    with pytest.raises(gao.GaoSourceDriftError, match="byte length drift"):
        gao.parse_gao_published_topics(PAGE + b" ")


def test_structural_drift_is_refused_not_repaired() -> None:
    # A page that lost its listing title, or whose topic count moved, must be
    # re-reviewed rather than silently re-parsed.
    text = PAGE.decode("utf-8")

    untitled = text.replace("Browse Topics Alphabetically", "Browse Topics").encode("utf-8")
    with pytest.raises(gao.GaoSourceDriftError, match="listing title drifted"):
        gao.parse_gao_published_topics(untitled, pin=_repinned(untitled))

    shrunk = text.replace(
        'id="taxonomy-term-296" class="small taxonomy-term vocabulary-topic"',
        'id="taxonomy-term-296" class="small taxonomy-term vocabulary-other"',
    ).encode("utf-8")
    # The message says what the count bounds: the browse listing, not GAO's
    # vocabulary. /topics/science-and-technology is a live term the listing
    # omits, so a capture naming 31 topics would be news rather than an error.
    with pytest.raises(gao.GaoSourceDriftError, match="browse listing drifted"):
        gao.parse_gao_published_topics(shrunk, pin=_repinned(shrunk))

    misordered = text.replace(
        ">Agriculture and Food</div>",
        ">Zzz Agriculture and Food</div>",
    ).encode("utf-8")
    with pytest.raises(gao.GaoSourceDriftError, match="not alphabetical"):
        gao.parse_gao_published_topics(misordered, pin=_repinned(misordered))


def _repinned(payload: bytes, *, source_url: str = gao.GAO_TOPICS_URL) -> gao.GaoPagePin:
    return gao.GaoPagePin(
        source_url=source_url,
        retrieved_at=gao.GAO_TOPICS_2026_08_15.retrieved_at,
        expected_sha256=gao.sha256_digest(payload),
        expected_byte_length=len(payload),
    )
