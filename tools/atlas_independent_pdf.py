"""Verifier-owned positioned PDF readings; no producer semantic imports.

Page sorting is O(words log words); row assignment sweeps each page once.
The one pixel-reviewed reading is pinned to the complete PDF and exact field.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

PINS = {
    "ferc-document-class-types": (
        "af632c9c6adbf0e7919d17e018b3a65078d0746bd1ab69a8d9fa65043720d688",
        "https://www.ferc.gov/sites/default/files/2025-06/Document%20Class%20Types%20January%202025.pdf",
    ),
    "ferc-docket-prefixes": (
        "c32efae9f51a70b6f955821d2fb3d3025995ef0e17e57bf2d32dfa16c2508dcb",
        "https://elibrary.ferc.gov/eLibrary/assets/docket-prefix.pdf",
    ),
    "unified-agenda-legal-authority-citation-types": (
        "b7372fec456cf0c346bd23528ae227913e37f546bb1c03689da19ee6a44cb2a5",
        "https://www.reginfo.gov/public/jsp/eAgenda/StaticContent/202210/RiscPreamble.pdf",
    ),
}
FOLDS = str.maketrans(
    {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st", "‐": "-", "‑": "-"}
)
VISIBLE = "Form 549D-Quarterly Transportation & Storage Report for Intrastate Natural Gas and Hinshaw Pipe"
NS = {"h": "http://www.w3.org/1999/xhtml"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def norm(text):
    return " ".join(text.split()).translate(FOLDS)


def bands(words):
    result = []
    for word in sorted(words, key=lambda w: (w["yMin"], w["xMin"])):
        if not result or abs(result[-1][0]["yMin"] - word["yMin"]) > 1:
            result.append([])
        result[-1].append(word)
    return [sorted(row, key=lambda w: w["xMin"]) for row in result]


def reading_exception(digest, page, row, field, observed):
    """Return the reviewed replacement only for the exact observed discrepancy."""
    if (digest, page, row, field, observed) != (
        PINS["ferc-document-class-types"][0],
        7,
        233,
        "type_description",
        VISIBLE + " lines",
    ):
        raise ValueError("PDF reading differs from the exact reviewed exception")
    return {
        "source_sha256": digest,
        "page": page,
        "global_row_zero_based": row,
        "field": field,
        "text_layer": observed,
        "reviewed_reading": VISIBLE,
    }


def extract_tables(xml, kind):
    rows = []
    status = None
    for pn, page in enumerate(ET.fromstring(xml).findall(".//h:page", NS), 1):
        words = [
            {"text": w.text or "", **{k: float(w.attrib[k]) for k in ("xMin", "yMin")}}
            for w in page.findall(".//h:word", NS)
        ]
        lines = bands(words)
        if kind == "class":
            names = ("Category", "Library", "Classification", "Type")
        else:
            names = ("Prefix", "Library", "Definition")
            text = " ".join(w["text"] for line in lines for w in line)
            if "Table 1" in text or "Table 2" in text:
                status = "active"
            if "Table 3" in text:
                status = "discontinued"
        header = next(line for line in lines if all(any(w["text"] == n for w in line) for n in names))
        xs = [next(w["xMin"] - 1 for w in header if w["text"] == n) for n in names] + [1000]
        current = None
        for line in lines:
            if kind != "class" and line[0]["yMin"] <= header[0]["yMin"] + 1:
                continue
            cells = [
                norm(" ".join(w["text"] for w in line if xs[i] <= w["xMin"] < xs[i + 1])) for i in range(len(names))
            ]
            if kind == "class":
                if cells[0] in ("Issuance", "Submittal"):
                    if not all(cells):
                        raise ValueError("Incomplete class row")
                    rows.append(
                        {
                            "page": pn,
                            "native": dict(
                                zip(("category", "library", "classification", "type_description"), cells, strict=False)
                            ),
                        }
                    )
            elif re.fullmatch("[A-Z]{1,3}-?", cells[0]):
                if not status or not all(cells):
                    raise ValueError("Incomplete docket row")
                current = {
                    "page": pn,
                    "native": {"status": status, **dict(zip(("prefix", "library", "definition"), cells, strict=False))},
                }
                rows.append(current)
            elif current and line[0]["yMin"] < 720 and not cells[0]:
                for field, text in zip(("library", "definition"), cells[1:], strict=False):
                    if text:
                        current["native"][field] = norm(current["native"][field] + " " + text)
    return rows


def read_pdf_rows(key: str, raw: bytes) -> dict:
    digest, url = PINS[key]
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("PDF source pin mismatch: " + key)
    ua = key.startswith("unified-agenda")
    with tempfile.TemporaryDirectory(prefix="atlas-independent-pdf-") as directory:
        source = Path(directory) / "source.pdf"
        source.write_bytes(raw)
        args = ["pdftotext"] + (["-f", "18", "-l", "19", "-bbox-layout"] if ua else ["-bbox-layout"])
        text = subprocess.run([*args, str(source), "-"], check=True, capture_output=True).stdout.decode()
    exceptions = []
    if ua:
        positioned_lines = []
        for page in ET.fromstring(text).findall(".//h:page", NS):
            words = [
                {"text": w.text or "", **{k: float(w.attrib[k]) for k in ("xMin", "yMin")}}
                for w in page.findall(".//h:word", NS)
            ]
            positioned_lines.extend(" ".join(w["text"] for w in line) for line in bands(words))
        text = "\n".join(positioned_lines)
        glossary = text.split("V. Abbreviations", 1)[1]
        glossary = re.sub(r"^\s*(18|19)\s*$", "", glossary, flags=re.MULTILINE)
        markers = list(re.finditer(r"^([A-Za-z][A-Za-z. ]*) -- ", glossary, re.MULTILINE))
        definitions = {
            m.group(1): norm(glossary[m.end() : markers[i + 1].start() if i + 1 < len(markers) else len(glossary)])
            for i, m in enumerate(markers)
        }
        extracted = [{"value": label, "definition": definitions[label]} for label in ("U.S.C.", "Pub. L.", "E.O.")]
    else:
        extracted = extract_tables(text, "class" if key == "ferc-document-class-types" else "docket")
    rows = []
    for i, source in enumerate(extracted):
        if ua:
            label = source["value"]
            definition = source["definition"]
            notations = [label]
            status = None
            native = {
                "value": label,
                "identifier": {
                    "value": label,
                    "kind": "legalAuthorityCitationType",
                    "authority_uri": "https://www.reginfo.gov/",
                    "source_uri": url,
                    "observed_at": "2026-08-03T19:13:31Z",
                    "effective_at": None,
                    "source_digest": "sha256:" + digest,
                },
            }
        else:
            native = dict(source["native"])
            if key == "ferc-document-class-types":
                if i == 233:
                    exception = reading_exception(
                        digest, source["page"], i, "type_description", native["type_description"]
                    )
                    exceptions.append(exception)
                    native["type_description"] = exception["reviewed_reading"]
                native["text"] = " ".join(
                    native[f] for f in ("category", "library", "classification", "type_description")
                )
                label = native["type_description"]
                definition = None
                notations = []
                status = None
            else:
                label = native["definition"]
                definition = label
                notations = [native["prefix"]]
                status = native["status"]
        native.update(sourceArtifact=url, sourceMedium="pdf")
        path = f"$.legalAuthorityCitationTypes[{i}]" if ua else f"$.rows[{i}]"
        token = "unified-agenda-legal-authority" if ua else key
        stamp = "2026-08-03T19:13:31Z" if ua else "2026-08-03T19:18:32Z"
        seed = canonical({"source": url, "path": path, "notations": notations, "identityHint": label})
        bits = int.from_bytes(hashlib.sha256(seed).digest(), "big") >> (256 - 74)
        ms = int(datetime.datetime.fromisoformat(stamp).timestamp() * 1000)
        ident = uuid.UUID(int=(ms << 80) | (7 << 76) | ((bits >> 62) << 64) | (2 << 62) | (bits & ((1 << 62) - 1)))
        rows.append(
            {
                "iri": f"urn:ref:source-concept:v2:{token}:{ident}",
                "label": label,
                "definition": definition,
                "notations": notations,
                "status": status,
                "source_path": path,
                "native_payload": native,
                "source_locator": url,
                "input_digest": "sha256:" + digest,
            }
        )
    return {"rows": rows, "reading_exceptions": exceptions}


def register_sources(v):
    paths = {
        "ferc-document-class-types": ("output/registry-real-data-sources/ferc-class-types-january-2025.pdf", 193934),
        "ferc-docket-prefixes": ("output/registry-real-data-sources/ferc-docket-prefix-june-2025.pdf", 282729),
        "unified-agenda-legal-authority-citation-types": (
            "tests/fixtures/unified_agenda_codes/risc-preamble-202210.pdf",
            148467,
        ),
    }
    return tuple(
        v.SourceSpec(
            name=key,
            kind="vocabulary",
            release_keys=(key,),
            inputs=(
                v.SourcePin(
                    path=path if key.startswith("unified-agenda") else Path(path).name,
                    sha256="sha256:" + PINS[key][0],
                    byte_length=size,
                    fmt="pdf",
                    role="publisherSource",
                    source_iri=PINS[key][1],
                    construction_path=path,
                ),
            ),
            reader="independent-positioned-pdf",
            identity_policy="source-local-record",
            policies=v.DIRECT_SKOS_POLICIES,
            rdf_source=v._rdf_source_policy(
                frozenset(
                    {"sourceArtifact", "sourceMedium"}
                    | (
                        {"value", "identifier"}
                        if key.startswith("unified-agenda")
                        else {"category", "library", "classification", "type_description", "text"}
                        if key == "ferc-document-class-types"
                        else {"prefix", "library", "definition", "status"}
                    )
                )
            ),
        )
        for key, (path, size) in paths.items()
    )


def read_adapter(v, spec, payloads):
    result = read_pdf_rows(spec.name, payloads[spec.inputs[0]])
    records = []
    for row in result["rows"]:

        def literal(text, lang=None):
            return v._literal_value(text, lang, None)

        annotations = ((v.SKOS_DEFINITION, literal(row["definition"], "en")),) if row["definition"] else ()
        records.append(
            v._StockVocabularyRecord(
                resource=row["iri"],
                preferred_labels=(literal(row["label"], "en"),),
                alternate_labels=(),
                notations=tuple(literal(x) for x in row["notations"]),
                annotations=annotations,
                source_locator=row["source_locator"],
                source_digest=row["input_digest"],
                native_payload=row["native_payload"],
                is_skos_concept=False,
            )
        )
    view = v._stock_vocabulary_view(records, (), (), spec.inputs)
    return replace(view, reading_exceptions=tuple(result["reading_exceptions"]))
