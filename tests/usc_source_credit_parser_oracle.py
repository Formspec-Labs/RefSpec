"""Frozen pre-port XML walker; test-only parity oracle."""
import io
import re
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterator


def flatten_credit(element: ElementTree.Element) -> str:
    """The credit's visible text.

    Only ASCII whitespace is collapsed. USLM writes ``§ 107`` with a narrow
    no-break space, and rewriting it would be editing the source to suit the
    expression rather than the other way round.
    """
    return re.sub(r"[ \t\r\n]+", " ", "".join(element.itertext())).strip()


def iter_source_credits(document: bytes | str) -> Iterator[tuple[str | None, str]]:
    """Yield ``(enclosing section identifier, credit text)`` for one USLM title.

    The identifier is the nearest **ancestor** ``<section>``'s, which is why
    this walks the tree: a credit that follows a nested section's close tag has
    a different nearest-preceding tag than it has ancestor.

    Each finished ``<section>`` is cleared. ``iterparse`` streams the events,
    not the tree, so without the clear every element seen stays resident and
    the peak is the whole title -- 113 MB for title 42. Measured on that title
    at release point 119-102: whole-process peak RSS 702 MB without the clear,
    181 MB with it, byte-identical output.
    """
    payload = document.encode("utf-8") if isinstance(document, str) else document
    stack: list[str | None] = []
    for event, element in ElementTree.iterparse(io.BytesIO(payload), events=("start", "end")):
        tag = element.tag.rsplit("}", 1)[-1]
        if event == "start":
            stack.append(element.get("identifier") if tag == "section" else None)
            continue
        if tag == "sourceCredit":
            yield next((s for s in reversed(stack) if s), None), flatten_credit(element)
        stack.pop()
        if tag == "section":
            # Every credit this section encloses is already yielded, and the
            # identifiers the enclosing sections still need are on the stack.
            element.clear()


