#!/usr/bin/env python
"""Inject two known defect classes into a copy of the staging view.

Defect A -- warrant axis (the sh:xone class). One rkaf:EvidenceBinding's
rkaf:evidenceRole is retargeted to rkaf:mappingRationale. That value is IN the
per-axis sh:in enum, so every simple constraint still passes; what breaks is the
COMBINATION -- no sh:xone branch pins mappingRationale, so zero branches hold.
Expected: XoneConstraintComponent on that one focus node.

Defect B -- cardinality. One atlas:AtlasResource gets a second skosxl:prefLabel
pointing at an existing skosxl:Label owned by a different resource.
Expected: MaxCountConstraintComponent on that focus node, path skosxl:prefLabel.

Defect C -- sh:closed. The same atlas:AtlasResource gets one predicate no
sh:property of atlas:AtlasResourceShape declares. This is the suspect the
contingency protocol names first: sh:closed over a union view, where the second
member of the union is the inoculated ontology. Expected:
ClosedConstraintComponent on that focus node.

Each defect is written as its own view so none masks another, plus a combined
view of A and B.

Usage: inject_defects.py <data-triples.nt> <ontology-inoculated.nt> <out-dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

RKAF = "https://rulespec.org/ns/v1#"
SKOSXL = "http://www.w3.org/2008/05/skos-xl#"
RDF_TYPE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
EVIDENCE_ROLE = f"<{RKAF}evidenceRole>"
PREF_LABEL = f"<{SKOSXL}prefLabel>"


def main() -> None:
    data_path, onto_path, outdir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    outdir.mkdir(parents=True, exist_ok=True)
    lines = data_path.read_text(encoding="utf-8").splitlines(keepends=True)

    # --- pick the targets deterministically (lexicographically least subject) ---
    role_lines = [(i, ln) for i, ln in enumerate(lines) if f" {EVIDENCE_ROLE} " in ln]
    role_index, role_line = min(role_lines, key=lambda pair: pair[1])
    binding = role_line.split(" ", 1)[0]

    pref_lines = [(i, ln) for i, ln in enumerate(lines) if f" {PREF_LABEL} " in ln]
    pref_index, pref_line = min(pref_lines, key=lambda pair: pair[1])
    resource = pref_line.split(" ", 1)[0]
    # A label owned by some OTHER resource, so the extra edge adds a second
    # value without disturbing sh:disjoint or the label's own shape.
    donor = max(pref_lines, key=lambda pair: pair[1])[1].rsplit(" <", 1)[-1]
    donor_label = "<" + donor.rstrip(" .\n")

    print(f"defect A focus: {binding}\n  was: {role_line.strip()}")
    print(f"defect B focus: {resource}\n  extra: {resource} {PREF_LABEL} {donor_label} .")

    onto = onto_path.read_text(encoding="utf-8")

    xone = list(lines)
    xone[role_index] = f"{binding} {EVIDENCE_ROLE} <{RKAF}mappingRationale> .\n"
    (outdir / "view-defect-xone.nt").write_text("".join(xone) + onto, encoding="utf-8")

    card = list(lines)
    card.insert(pref_index + 1, f"{resource} {PREF_LABEL} {donor_label} .\n")
    (outdir / "view-defect-cardinality.nt").write_text("".join(card) + onto, encoding="utf-8")

    closed = list(lines)
    closed.insert(
        pref_index + 1,
        f'{resource} <https://refspec.org/ns/atlas/v3#undeclaredProperty> "x" .\n',
    )
    (outdir / "view-defect-closed.nt").write_text("".join(closed) + onto, encoding="utf-8")

    both = list(xone)
    both.insert(pref_index + 1, f"{resource} {PREF_LABEL} {donor_label} .\n")
    (outdir / "view-defect-both.nt").write_text("".join(both) + onto, encoding="utf-8")

    (outdir / "defect-targets.txt").write_text(
        f"xone_focus\t{binding}\ncardinality_focus\t{resource}\ndonor_label\t{donor_label}\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
