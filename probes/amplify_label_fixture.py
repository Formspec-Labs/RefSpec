#!/usr/bin/env python3
"""Build a bounded stress fixture from the staging SKOS-XL label records."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

RDF_TYPE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
LABEL = "<http://www.w3.org/2008/05/skos-xl#Label>"
IN_RELEASE = "<https://refspec.org/ns/atlas/v3#inRelease>"
SOURCE_RECORD = "<https://refspec.org/ns/atlas/v3#sourceRecord>"


def terms(line: str) -> tuple[str, str, str]:
    subject, predicate, remainder = line.rstrip("\n").split(" ", 2)
    return subject, predicate, remainder


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--copies", type=int, default=8)
    args = parser.parse_args()

    label_nodes: set[str] = set()
    with args.source.open() as source:
        for line in source:
            subject, predicate, remainder = terms(line)
            if predicate == RDF_TYPE and remainder == f"{LABEL} .":
                label_nodes.add(subject)

    label_lines: list[tuple[str, str]] = []
    referenced_nodes: set[str] = set()
    with args.source.open() as source:
        for line in source:
            subject, predicate, remainder = terms(line)
            if subject not in label_nodes:
                continue
            label_lines.append((subject, line[len(subject) :]))
            if predicate in {IN_RELEASE, SOURCE_RECORD}:
                referenced_nodes.add(remainder.removesuffix(" ."))

    reference_type_lines: list[str] = []
    with args.source.open() as source:
        for line in source:
            subject, predicate, _ = terms(line)
            if subject in referenced_nodes and predicate == RDF_TYPE:
                reference_type_lines.append(line)

    args.destination.parent.mkdir(parents=True, exist_ok=True)
    with args.destination.open("w") as destination:
        destination.writelines(reference_type_lines)
        for copy_number in range(args.copies):
            for original_subject, tail in label_lines:
                digest = hashlib.sha256(original_subject.encode()).hexdigest()
                subject = f"<urn:shacl-survey:label:{copy_number}:{digest}>"
                destination.write(subject + tail)

    print(
        f"labels={len(label_nodes)} label_lines={len(label_lines)} "
        f"reference_type_lines={len(reference_type_lines)} copies={args.copies}"
    )


if __name__ == "__main__":
    main()
