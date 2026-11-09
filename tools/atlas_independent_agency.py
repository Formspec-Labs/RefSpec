"""Read-only independent agency artifact check; no refspec/producer imports or fetching.

Run with the repository's Python (rdflib, pyarrow, backports.zstd, openpyxl). The
expected rows come directly from each batch's candidate JSON and recorded owner
answers (batch 1, the succession batch, then the alias batch), the roster JSON
captures, OPM's EHRI workbook and REF-038's adjudication file; every cited alias
record is re-hashed and its quoted passage found in the retained bytes. The
generic fidelity verifier calls this bounded agency comparison.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

import openpyxl
import pyarrow.parquet as pq
import rdflib
from backports import zstd
from rdflib.plugins.serializers.nt import _quoteLiteral

A = rdflib.Namespace("https://refspec.org/ns/atlas/v3#")
R = rdflib.Namespace("https://rulespec.org/ns/v1#")
RDF = rdflib.RDF
KEY = "agency-registry-2026-09-26"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sorted_rows(rows):
    return sorted(rows, key=canonical)


def differences(expected, actual, path=""):
    if type(expected) is not type(actual):
        return [{"path": path, "expected": expected, "actual": actual}]
    if isinstance(expected, dict):
        out = []
        for key in sorted(set(expected) | set(actual)):
            if key not in expected or key not in actual:
                out.append(
                    {
                        "path": path + "/" + key,
                        "expected": expected.get(key, "<missing>"),
                        "actual": actual.get(key, "<missing>"),
                    }
                )
            else:
                out.extend(differences(expected[key], actual[key], path + "/" + key))
        return out
    if isinstance(expected, list):
        out = []
        if len(expected) != len(actual):
            out.append({"path": path + "/length", "expected": len(expected), "actual": len(actual)})
        for i, (e, a) in enumerate(zip(expected, actual, strict=False)):
            out.extend(differences(e, a, path + "/" + str(i)))
        return out
    return [] if expected == actual else [{"path": path, "expected": expected, "actual": actual}]


def expected_from_plans(c, d):
    decisions = d["decisions"]
    reviewer = d["reviewer_iri"]

    def decision(item_id):
        return {**decisions[item_id], "note": decisions[item_id].get("note"), "reviewer": reviewer}

    def parent(endpoint):
        return (endpoint.get("parent") or {}).get("resource_iri")

    bridges = []
    events = []
    non = []
    event_details = {}
    members = defaultdict(list)
    for row in c["candidates"]:
        if row.get("event_id"):
            members[row["event_id"]].append(row)
    for row in c["candidates"]:
        if row.get("relation") != "sameEntityAs" or decisions[row["candidate_id"]]["answer"] != "yes":
            continue
        s, o = row["source"], row["target"]
        bridges.append(
            {
                "candidate_id": row["candidate_id"],
                "subject": s["resource_iri"],
                "subject_publisher_name": s["publisher_name"],
                "subject_parent": parent(s),
                "object": o["resource_iri"],
                "object_release_key": o["release_key"],
                "object_publisher_name": o["publisher_name"],
                "object_parent": parent(o),
                "relation": row["relation_iri"],
                "basis": row["proposed_basis"],
                "reasoning": row["reasoning"],
                "evidence_tier": "E4",
                "warrant": "humanReview",
                "decision": decision(row["candidate_id"]),
            }
        )
    for event in c["events"]:
        eid = event["event_id"]
        details = []
        assert decisions[eid]["answer"] in ("accept", "accept-every-row", "1")
        rows = members[eid]
        assert set(event["rows"]) == {r["candidate_id"] for r in rows}
        for row in rows:
            target = row["target"]
            events.append(
                {
                    "event_id": eid,
                    "effective_date": event["effective_date"],
                    "date_basis": event["date_basis"],
                    "originals": [o["resource_iri"] for o in event["originals"]],
                    "original_parents": [parent(o) for o in event["originals"]],
                    "result": target["resource_iri"],
                    "result_publisher_name": target["publisher_name"],
                    "functions_taken": row.get("functions_taken"),
                    "reasoning": row["reasoning"],
                    "public_records": event["public_records"],
                    "evidence_tier": "E4",
                    "warrant": "humanReview",
                    "decision": decision(eid),
                }
            )
            item = {
                "publisherName": target["publisher_name"],
                "reasoning": row["reasoning"],
                "resourceIri": target["resource_iri"],
                "rowId": row["candidate_id"],
            }
            if row.get("functions_taken") is not None:
                item["functionsTaken"] = row["functions_taken"]
            details.append(item)
        event_details[eid] = {
            "dateBasis": event["date_basis"],
            "effectiveDate": event["effective_date"],
            "eventId": eid,
            "originals": [
                {"publisherName": o["publisher_name"], "resourceIri": o["resource_iri"]} for o in event["originals"]
            ],
            "results": sorted(details, key=lambda r: r["rowId"]),
        }
    special = {
        "same:fr151:ecfr:export-import-bank": ("2", "sameOrganizationReverseLookupCostRejected"),
        "same:fr296:fh:300000070": ("1", "heldForStatutoryRenameBasis"),
    }
    for row in c["candidates"]:
        item_id = row["candidate_id"]
        if item_id not in special:
            continue
        answer, reason = special[item_id]
        assert decisions[item_id]["answer"] == answer
        non.append(
            {
                "item_id": item_id,
                "reason": reason,
                "reasoning": row["owner_question"]["options"][int(answer) - 1],
                "subject": row["source"]["resource_iri"],
                "subject_value": None,
                "object": row["target"]["resource_iri"],
                "closest_alternative": None,
                "decision": decision(item_id),
            }
        )
    for row in c["non_emissions"]:
        item_id = row["candidate_id"]
        assert decisions[item_id]["answer"] == "confirm"
        non.append(
            {
                "item_id": item_id,
                "reason": "withdrawn",
                "reasoning": row["reason"],
                "subject": row["source"]["resource_iri"],
                "subject_value": None,
                "object": row["target"]["resource_iri"],
                "closest_alternative": row.get("closest_alternative"),
                "decision": decision(item_id),
            }
        )
    for row in c["no_fr_bridge"]:
        item_id = row["value_id"]
        assert decisions[item_id]["answer"] == "confirm"
        non.append(
            {
                "item_id": item_id,
                "reason": row["reason"],
                "reasoning": row["reasoning"],
                "subject": None,
                "subject_value": row["value"],
                "object": None,
                "closest_alternative": None,
                "decision": decision(item_id),
            }
        )
    aliases = []
    for row in c.get("aliases", ()):
        item_id = row["alias_id"]
        if item_id not in decisions:
            continue  # An undecided alias is held, not emitted and not refused.
        effect = row["answer_effects"].get(decisions[item_id]["answer"])
        if effect is None:
            raise ValueError(f"{item_id} answer has no effect in its own answer_effects")
        if effect["outcome"] == "nonEmission":
            non.append(
                {
                    "item_id": item_id,
                    "reason": "aliasRejectedByOwner",
                    "reasoning": row["why"],
                    "subject": None,
                    "subject_value": row["name_key"],
                    "object": None,
                    "closest_alternative": None,
                    "decision": decision(item_id),
                }
            )
            continue
        if effect["outcome"] != "alias":
            raise ValueError(f"{item_id} answer has outcome {effect['outcome']!r}, which no alias rule names")
        target, fr = row["target"] or {}, row["fr_record"] or {}
        aliases.append(
            {
                "alias_id": item_id,
                "name_key": row["name_key"],
                "target": target.get("resource_iri"),
                "target_release_key": target.get("release_key"),
                "target_publisher_name": target.get("publisher_name"),
                "fr_resource": fr.get("resource_iri"),
                "fr_publisher_name": fr.get("publisher_name"),
                "fr_relation": effect["fr_relation"],
                "basis": row["basis"],
                "reasoning": row["reasoning"],
                "records": [
                    {k: r[k] for k in ("citation", "kind", "file", "url", "sha256", "passage")} for r in row["records"]
                ],
                "decision": decision(item_id),
            }
        )
    return {
        "bridges": sorted_rows(bridges),
        "events": sorted_rows(events),
        "non-emissions": sorted_rows(non),
        "aliases": sorted_rows(aliases),
    }, event_details


def expected_from_batches(batches):
    """Every batch's expected rows together, and the current successors derived from all their events."""
    expected = {"bridges": [], "events": [], "non-emissions": [], "aliases": []}
    details = {}
    for c, d in batches:
        rows, event_details = expected_from_plans(c, d)
        for key, value in rows.items():
            expected[key].extend(value)
        details.update(event_details)
    expected = {key: sorted_rows(value) for key, value in expected.items()}
    expected["current-successors"] = current_successors(expected["events"])
    return expected, details


def merged_plans(batches):
    """One plan over every batch, for the checks that read candidates and decisions together."""
    reviewers = {d["reviewer_iri"] for _, d in batches}
    if len(reviewers) != 1:
        raise ValueError("agency registry batches name different reviewers")
    rosters = {}
    for c, _ in batches:
        for key, digest in c["inputs"]["roster_releases"].items():
            if rosters.setdefault(key, digest) != digest:
                raise ValueError("agency registry batches read different roster releases: " + key)
    plan = {key: [row for c, _ in batches for row in c[key]] for key in COVERED}
    plan["inputs"] = {"roster_releases": rosters}
    decisions = {"reviewer_iri": reviewers.pop(), "decisions": {}}
    for _, d in batches:
        if set(d["decisions"]) & set(decisions["decisions"]):
            raise ValueError("an item is decided in two agency registry batches")
        decisions["decisions"].update(d["decisions"])
    return plan, decisions


def current_successors(events):
    """Each event original read forward until no result is itself an original; a fixpoint, not the producer's walk."""
    results = defaultdict(set)
    for row in events:
        for original in row["originals"]:
            results[original].add(row["result"])
    rows = []
    for original in results:
        frontier = set(results[original])
        for _ in range(len(results) + 1):
            if not frontier & results.keys():
                break
            frontier = {successor for result in frontier for successor in results.get(result, {result})}
        else:
            raise ValueError(f"agency change events form a cycle through {original}")
        rows.extend({"original": original, "successor": successor} for successor in frontier)
    return sorted_rows(rows)


FR_ROSTER = "tests/fixtures/federal_register_native_controls/fr-agencies-2026-08-15.json"
ECFR_ROSTER = "tests/fixtures/cfr_list_of_subjects/ecfr-agencies-2026-08-15.json"
FH_PAGES = tuple(f"tests/fixtures/federal_hierarchy_complete/fh-orgs-all-page-{i}.json" for i in range(5))
REGS_ROSTER = "tests/fixtures/regulations_gov_agencies/regulations-gov-agencies-2026-08-16.json"
OPM_WORKBOOK = "output/registry-real-data-sources/EHRI-Data-Standards-20260804.xlsx"
FR_IRI = "urn:ref:federal-register-agency:"
ECFR_IRI = "urn:ref:ecfr-agency:"
FH_IRI = "urn:ref:federal-hierarchy-org:"
REGS_IRI = "urn:ref:regulations-gov-agency:"
OPM_IRI = "urn:ref:opm-ehri-agency-subelement:"


def read_rosters(repo, source_paths=None):
    """The FR, eCFR, Federal Hierarchy and regulations.gov captures, indexed by their own keys, read once."""
    source_paths = source_paths or {}
    paths = {
        name: Path(source_paths.get(name, Path(repo) / name))
        for name in (FR_ROSTER, ECFR_ROSTER, *FH_PAGES, REGS_ROSTER)
    }
    ecfr = {}

    def visit(rows, parent=None):
        for row in rows:
            ecfr[row["slug"]] = (row, parent)
            visit(row.get("children", []), row["slug"])

    visit(json.loads(paths[ECFR_ROSTER].read_text())["agencies"])
    return {
        "paths": paths,
        "digests": {name: sha(path) for name, path in paths.items()},
        "fr": {r["id"]: r for r in json.loads(paths[FR_ROSTER].read_text())},
        "ecfr": ecfr,
        "fh": {r["fhorgid"]: (r, name) for name in FH_PAGES for r in json.loads(paths[name].read_text())["orglist"]},
        "regs": {r["id"]: r for r in json.loads(paths[REGS_ROSTER].read_text())["data"]},
    }


def read_opm_names(repo, source_paths=None):
    """OPM EHRI agency/subelement code -> the explanations the workbook's current values give it."""
    path = Path((source_paths or {}).get(OPM_WORKBOOK, Path(repo) / OPM_WORKBOOK))
    names = defaultdict(set)
    workbook = openpyxl.load_workbook(path, read_only=True)
    try:
        rows = workbook["CurrentValues"].iter_rows(values_only=True)
        if next(rows)[:3] != ("Name", "Code", "Explanation"):
            raise ValueError("EHRI CurrentValues header drifted")
        for kind, code, explanation, *_ in rows:
            if kind == "AGENCY/SUBELEMENT":
                names[code].add(explanation)
    finally:
        workbook.close()
    return names


def roster_name(rosters, opm, iri):
    """The publisher name a roster capture gives one resource IRI, or None when no capture holds it."""
    kind, _, key = iri.rpartition(":")
    kind += ":"
    if kind == FR_IRI and int(key) in rosters["fr"]:
        return rosters["fr"][int(key)]["name"], "federal-register-agencies-roster-2026-08-15"
    if kind == ECFR_IRI and key in rosters["ecfr"]:
        return rosters["ecfr"][key][0]["name"], "ecfr-agencies-roster-2026-08-15"
    if kind == FH_IRI and int(key) in rosters["fh"]:
        return rosters["fh"][int(key)][0]["fhorgname"], "federal-hierarchy-orgs-complete-2026-08-15"
    if kind == OPM_IRI and opm is not None and len(opm.get(key, ())) == 1:
        return next(iter(opm[key])), "opm-ehri-agency-subelement-2026-08-04"
    return None


def check_raw_endpoints(repo, c, source_paths=None, rosters=None):
    """Read source JSON fields directly, without producer roster readers."""
    rosters = rosters or read_rosters(repo, source_paths)
    paths = rosters["paths"]
    logical_paths = {path: name for name, path in paths.items()}
    fr_path, ecfr_path, fh_paths = paths[FR_ROSTER], paths[ECFR_ROSTER], [paths[name] for name in FH_PAGES]
    fr, ecfr = rosters["fr"], rosters["ecfr"]
    fh = {key: (raw, paths[name]) for key, (raw, name) in rosters["fh"].items()}
    endpoints = {}
    for row in c["candidates"] + c["non_emissions"]:
        for role in ("source", "target"):
            e = row[role]
            endpoints[e["resource_iri"]] = e
    for event in c["events"]:
        for e in event["originals"]:
            endpoints[e["resource_iri"]] = e
    errors = []
    receipts = []
    file_digests = {paths[name]: digest for name, digest in rosters["digests"].items()}
    for iri, e in sorted(endpoints.items()):
        if e["roster"] == "federal-register-agencies":
            raw = fr[e["id"]]
            path = fr_path
            name = raw["name"]
            parent = raw["parent_id"]
            parent_value = (
                None
                if parent is None
                else {
                    "resource_iri": "urn:ref:federal-register-agency:" + str(parent),
                    "publisher_name": fr[parent]["name"],
                }
            )
            context = {k: raw[k] for k in ("id", "slug", "name", "short_name", "parent_id")}
        elif e["roster"] == "ecfr-agencies":
            raw, parent = ecfr[e["slug"]]
            path = ecfr_path
            name = raw["name"]
            parent_value = (
                None
                if parent is None
                else {"resource_iri": "urn:ref:ecfr-agency:" + parent, "publisher_name": ecfr[parent][0]["name"]}
            )
            context = {k: raw[k] for k in ("slug", "name", "short_name")}
            context["parentSlugFromNesting"] = parent
        elif e["roster"] == "federal-hierarchy-organizations":
            raw, path = fh[int(iri.rsplit(":", 1)[1])]
            name = raw["fhorgname"]
            parent = raw["fhdeptindagencyorgid"]
            parent_value = (
                None
                if parent == raw["fhorgid"]
                else {
                    "resource_iri": "urn:ref:federal-hierarchy-org:" + str(parent),
                    "publisher_name": fh[parent][0]["fhorgname"],
                }
            )
            context = {
                k: raw[k] for k in ("fhorgid", "fhorgname", "fhorgtype", "fhdeptindagencyorgid", "fhagencyorgname")
            }
        else:
            raise ValueError("unexpected endpoint roster " + e["roster"])
        observed = {"publisher_name": name, "parent": parent_value}
        wanted = {k: e[k] for k in observed}
        delta = differences(wanted, observed, "raw-endpoint/" + iri)
        errors.extend(delta)
        receipts.append(
            {
                "resourceIri": iri,
                "sourcePath": logical_paths[path],
                "resolvedSourcePath": str(path),
                "sourceSha256": file_digests[path],
                "sourceContext": context,
                "match": not delta,
            }
        )
    return errors, receipts, [fr_path, ecfr_path, *fh_paths]


ALIAS_RECORDS_DIR = "research/evidence/agency-alias-records-2026-11-08"


class _Text(HTMLParser):
    """Visible text of a retained HTML record: script and style dropped, each text node one space apart."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        self.hidden += tag in ("script", "style")

    def handle_endtag(self, tag):
        self.hidden -= tag in ("script", "style") and self.hidden > 0

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def retained_text(path, raw):
    """A retained record's words, whitespace collapsed; HTML is parsed, everything else read as UTF-8 text."""
    text = raw.decode("utf-8", errors="replace")
    if path.suffix in (".htm", ".html"):
        parser = _Text()
        parser.feed(text)
        parser.close()
        text = " ".join(parser.parts)
    return " ".join(text.split())


def check_alias_records(repo, alias_batch, source_paths=None):
    """Re-hash every record an alias cites and find its quoted passage in the retained bytes; one read per file."""
    source_paths = source_paths or {}
    c, _ = alias_batch
    pin = c["inputs"]["records_manifest"]
    manifest_path = Path(source_paths.get(pin["path"], Path(repo) / pin["path"]))
    errors = differences(pin["sha256"], "sha256:" + sha(manifest_path), "alias-records/manifest")
    listed = {row["file"]: row for row in json.loads(manifest_path.read_text())}
    texts, receipts = {}, []
    for alias in c["aliases"]:
        for record in alias["records"]:
            name = record["file"]
            label = f"alias-records/{alias['alias_id']}/{name}"
            if name not in texts:
                path = child(Path(repo) / ALIAS_RECORDS_DIR, name)
                path = Path(source_paths.get(f"{ALIAS_RECORDS_DIR}/{name}", path))
                if path.is_symlink() or not path.is_file():
                    texts[name] = (None, None)
                else:
                    raw = path.read_bytes()
                    texts[name] = ("sha256:" + hashlib.sha256(raw).hexdigest(), retained_text(path, raw))
            observed, text = texts[name]
            entry = listed.get(name, {})
            delta = differences(
                {
                    "sha256": record["sha256"],
                    "manifestSha256": record["sha256"],
                    "url": record["url"],
                    "passageFound": True,
                },
                {
                    "sha256": observed,
                    "manifestSha256": entry.get("sha256"),
                    "url": entry.get("final_url"),
                    "passageFound": text is not None and " ".join(record["passage"].split()) in text,
                },
                label,
            )
            errors.extend(delta)
            receipts.append({"aliasId": alias["alias_id"], "file": name, "sha256": observed, "match": not delta})
    return errors, receipts


def name_key(text):
    """The published match key, re-implemented from the candidates file's own ``name_key.doc``."""
    folded = unicodedata.normalize("NFKC", text).casefold().replace("&", " and ")
    folded = " ".join(re.sub(r"[^a-z0-9]+", " ", re.sub(r"\([^)]*\)", " ", folded)).split())
    return " ".join(re.sub(r"\b(the|u s|us|united states|of america)\b", " ", folded).split())


ORGANIZATION_WORDS = (
    "administration",
    "agency",
    "board",
    "bureau",
    "center",
    "commission",
    "corps",
    "council",
    "department",
    "institute",
    "office",
    "service",
)


def check_alias_rosters(alias_batch, rosters, opm, projection):
    """Each decided alias's named records against the raw captures, its FR relation against FR ancestry, and a
    mechanical alias's key against the rule it names."""
    c, d = alias_batch
    errors = []
    fr = rosters["fr"]
    regs_by_fr = defaultdict(set)
    for row in projection:
        regs_by_fr[row["org"]].add(rosters["regs"][row["source_value"]]["attributes"]["name"])
    for alias in c["aliases"]:
        aid = alias["alias_id"]
        if aid not in d["decisions"]:
            continue
        errors.extend(differences(alias["name_key"], name_key(alias["name_key"]), aid + "/name-key-fixpoint"))
        for side in ("target", "fr_record"):
            record = alias[side]
            if record is None:
                continue
            observed = roster_name(rosters, opm, record["resource_iri"])
            errors.extend(
                differences(
                    [record["publisher_name"], record["release_key"]],
                    list(observed) if observed else None,
                    f"{aid}/{side}/raw-roster",
                )
            )
        target, fr_record = alias["target"] or {}, alias["fr_record"]
        relation = alias["answer_effects"][d["decisions"][aid]["answer"]].get("fr_relation")
        if fr_record is not None and target.get("resource_iri", "").startswith(FR_IRI):
            # Where the target is itself an FR record, the roster states its ancestry: "same" is the record,
            # "partOf" a proper ancestor of it.
            ancestors, node = [], int(target["resource_iri"].rpartition(":")[2])
            while node is not None and node not in ancestors:
                ancestors.append(node)
                node = fr[node]["parent_id"] if node in fr else None
            if relation == "same":
                errors.extend(differences(target["resource_iri"], fr_record["resource_iri"], aid + "/same-target"))
            elif relation == "partOf" and fr_record["id"] not in ancestors[1:]:
                errors.append({"path": aid + "/part-of-ancestry", "expected": ancestors[1:], "actual": fr_record["id"]})
        if alias["class"] != "mechanical":
            continue
        raw = fr[fr_record["id"]]
        keys = {
            "frShortNameEquality": {name_key(raw["short_name"] or "")},
            "frNameWordOrder": {
                f"{m['word']} of {m['head']}"
                for m in [
                    re.fullmatch(rf"(?P<head>.+) (?P<word>{'|'.join(ORGANIZATION_WORDS)})", name_key(raw["name"]))
                ]
                if m
            },
            "reviewedIdentityPublisherName": {name_key(n) for n in regs_by_fr[fr_record["resource_iri"]]},
        }
        for basis in alias["basis"]:
            if alias["name_key"] not in keys.get(basis, set()):
                errors.append(
                    {
                        "path": f"{aid}/mechanical/{basis}",
                        "expected": alias["name_key"],
                        "actual": sorted(keys.get(basis, ())),
                    }
                )
    return errors


def expected_organizations(rosters, projection, successors):
    """All pinned FR agencies: the capture's own fields, the REF-038 codes selecting each, its current successors."""
    codes, current = defaultdict(list), defaultdict(list)
    for row in projection:
        codes[row["org"]].append(row["source_value"])
    for row in successors:
        current[row["original"]].append(row["successor"])
    rows = []
    for raw in rosters["fr"].values():
        iri = FR_IRI + str(raw["id"])
        rows.append(
            {
                "resource_iri": iri,
                "fr_id": raw["id"],
                "slug": raw["slug"],
                "name": raw["name"],
                "short_name": raw["short_name"],
                "parent": None if raw["parent_id"] is None else FR_IRI + str(raw["parent_id"]),
                "regulations_gov_codes": sorted(codes[iri]),
                "current_successors": sorted(current[iri]),
            }
        )
    return sorted_rows(rows)


REF_038_ADJUDICATION = "research/evidence/agency-identifier-census-2026-08-16/census.json"
REF_038_ADJUDICATION_SHA256 = "sha256:11c58cf263496e9c0a320ab4fb1985ff7e17214d6a43996b6722336164143339"
REF_038_COUNTS = (321, 10)
#: Each roster's one capture locator; Federal Hierarchy's is per page and regulations.gov's per record.
_LOCATORS = {
    "federal-register-agencies-roster-2026-08-15": "https://www.federalregister.gov/api/v1/agencies",
    "ecfr-agencies-roster-2026-08-15": "https://www.ecfr.gov/api/admin/v1/agencies.json",
}


def _label(text):
    return " ".join(text.split())


def expected_projection(repo, rosters, roster_releases, source_paths=None):
    """REF-038's 331 regulations.gov ids from the raw captures: an id exactly one FR short name equals, else (FR
    short names colliding or absent) exactly one eCFR short name, else the owner's residue decision in the
    adjudication file; adopted rows and abstentions."""
    path = Path((source_paths or {}).get(REF_038_ADJUDICATION, Path(repo) / REF_038_ADJUDICATION))
    adjudication = pinned_json(path, REF_038_ADJUDICATION_SHA256)["agencyIdentityAdjudication"]
    residue = {row["sourceValue"]: row for row in adjudication["decisions"]}
    fr, ecfr, fh, regs = rosters["fr"], rosters["ecfr"], rosters["fh"], rosters["regs"]
    fr_short, ecfr_short = defaultdict(list), defaultdict(list)
    for raw in fr.values():
        if raw["short_name"]:
            fr_short[raw["short_name"]].append(raw["id"])
    for slug, (raw, _) in ecfr.items():
        if raw["short_name"]:
            ecfr_short[raw["short_name"]].append(slug)

    def endpoint(iri):
        """(release key, publisher name, name field, parent IRI, preferred label, alternate labels, capture file)."""
        kind, _, key = iri.rpartition(":")
        kind += ":"
        if kind == FR_IRI:
            raw = fr[int(key)]
            parent = None if raw["parent_id"] is None else FR_IRI + str(raw["parent_id"])
            alternates = [raw["short_name"]] if raw["short_name"] else []
            return (
                "federal-register-agencies-roster-2026-08-15",
                raw["name"],
                "name",
                parent,
                raw["name"],
                alternates,
                FR_ROSTER,
            )
        if kind == ECFR_IRI:
            # eCFR's preferred label is its display name ("..., Library of Congress"); name and short name alternate.
            raw, parent = ecfr[key]
            parent = None if parent is None else ECFR_IRI + parent
            return (
                "ecfr-agencies-roster-2026-08-15",
                raw["name"],
                "name",
                parent,
                raw["display_name"],
                [raw["name"], raw["short_name"] or ""],
                ECFR_ROSTER,
            )
        if kind == FH_IRI:
            raw, name = fh[int(key)]
            parent = raw["fhdeptindagencyorgid"]
            parent = None if parent == raw["fhorgid"] else FH_IRI + str(parent)
            return (
                "federal-hierarchy-orgs-complete-2026-08-15",
                raw["fhorgname"],
                "fhorgname",
                parent,
                raw["fhorgname"],
                [],
                name,
            )
        raise ValueError("REF-038 target outside FR, eCFR and Federal Hierarchy: " + iri)

    def record(release_key, iri, field, value, name, source_file, locator=None):
        fixed = _LOCATORS.get(release_key)
        if fixed is None and locator is None:
            page = int(source_file.rsplit("-", 1)[1].split(".")[0])
            locator = f"https://api.sam.gov/prod/federalorganizations/v1/orgs?limit=200&offset={page * 200}"
        return {
            "release_key": release_key,
            "release_digest": roster_releases[release_key],
            "resource": iri,
            "source_locator": locator or fixed,
            "source_digest": "sha256:" + rosters["digests"][source_file],
            "field": field,
            "value": value,
            "publisher_name": name,
        }

    rows, unresolved = [], []
    for value, raw in sorted(regs.items()):
        source_iri = REGS_IRI + value
        source_name = raw["attributes"]["name"]
        regs_parent = raw["attributes"]["parent"]
        if len(fr_short[value]) == 1 or len(ecfr_short[value]) == 1:
            iri = FR_IRI + str(fr_short[value][0]) if len(fr_short[value]) == 1 else ECFR_IRI + ecfr_short[value][0]
            release_key, target_name, _, parent, preferred, alternates, source_file = endpoint(iri)
            label = "Federal Register" if iri.startswith(FR_IRI) else "eCFR"
            basis = (
                "federalRegisterShortNameEqualsRegulationsGovAgencyId"
                if iri.startswith(FR_IRI)
                else "ecfrAgencyShortNameEqualsRegulationsGovAgencyId"
            )
            field, target_value = "short_name", value
            reasoning = (
                f"regulations.gov id {value} equals the publisher acronym on the {label} record; regulations.gov "
                f"names {source_name!r} and the target publisher names {target_name!r}."
            )
            if value in residue:
                raise ValueError(f"REF-038 adjudicates {value}, which its acronym rule already resolves")
        else:
            decision = residue.pop(value, None)
            if decision is None:
                raise ValueError(f"REF-038 leaves {value} undecided")
            if decision["sourcePublisherName"] != source_name or decision["sourceResource"] != source_iri:
                raise ValueError(f"REF-038 adjudication of {value} names another source record")
            if decision["decision"] == "abstained":
                closest = decision.get("closestNonAdoptedCandidate")
                unresolved.append(
                    {
                        "source_value_kind": "regulationsGovAgencyId",
                        "source_value": value,
                        "source_org": source_iri,
                        "pref_label": _label(source_name),
                        "source_parent_org": None if regs_parent is None else REGS_IRI + regs_parent,
                        "reason": decision["reason"],
                        "reasoning": decision["reasoning"],
                        "candidate_resources": [] if closest is None else [closest["resource"]],
                        "closest_non_adopted_candidate": closest,
                    }
                )
                continue
            if decision["decision"] != "adopted":
                raise ValueError(f"REF-038 decision for {value} is neither adopted nor abstained")
            iri = decision["objectResource"]
            release_key, target_name, field, parent, preferred, alternates, source_file = endpoint(iri)
            if (release_key, target_name) != (decision["objectReleaseKey"], decision["objectPublisherName"]):
                raise ValueError(f"REF-038 adjudication of {value} names a target the capture does not hold")
            basis, reasoning, target_value = decision["basis"], decision["reasoning"], target_name
        pref = _label(preferred)
        content = {
            "evidence_tier": "E4",
            "warrant": "humanReview",
            "reviewer": adjudication["reviewerIri"],
            "adjudicated_on": adjudication["decidedAt"],
            "decision_record": "docs/decisions.md#ref-038",
            "decision": "approved",
            "decision_basis": basis,
            "relation": str(A.sameEntityAs),
            "name_similarity_used": False,
            "reasoning": reasoning,
            "source_record": record(
                "regulations-gov-agencies-roster-2026-08-16",
                source_iri,
                "attributes.id",
                value,
                source_name,
                REGS_ROSTER,
                raw["links"]["self"],
            ),
            "target_record": record(release_key, iri, field, target_value, target_name, source_file),
        }
        rows.append(
            {
                "source_value_kind": "regulationsGovAgencyId",
                "source_value": value,
                "org": iri,
                "pref_label": pref,
                "abbreviations": [value],
                "aliases": sorted({_label(source_name), *map(_label, alternates)} - {pref, value, ""}),
                "parent_org": parent,
                "relation": str(A.sameEntityAs),
                "evidence_tier": "E4",
                "warrant": "humanReview",
                "basis": basis,
                "evidence_records": [
                    {
                        "record_id": "urn:ref:agency-projection-evidence:" + digest(content).removeprefix("sha256:"),
                        **content,
                    }
                ],
            }
        )
    if residue:
        raise ValueError("REF-038 adjudicates ids outside its residue: " + ", ".join(sorted(residue)))
    if (len(rows), len(unresolved)) != REF_038_COUNTS:
        raise ValueError(f"REF-038 projection counts {(len(rows), len(unresolved))} are not {REF_038_COUNTS}")
    return sorted_rows(rows), sorted_rows(unresolved)


def read_graph(path):
    data = zstd.decompress(path.read_bytes())
    dataset = rdflib.Dataset()
    dataset.parse(data=data.decode(), format="nquads")
    graph = rdflib.Graph()
    for s, p, o, _ in dataset.quads():
        graph.add((s, p, o))
    return graph, len(dataset)


def check_rdf(g, c, d, expected, details, decision_files, endpoint_records=None):
    """Compare the agency pack with the plans; ``decision_files`` maps each item to its decisions file and sha256."""
    errors = []
    snapshot = {"events": [], "bridges": [], "nonEmissionAbsences": []}

    def check(label, e, a):
        errors.extend(differences(e, a, label))

    def one(s, p):
        values = list(g.objects(s, p))
        if len(values) != 1:
            errors.append({"path": f"{s}/{p}/cardinality", "expected": 1, "actual": len(values)})
            return values[0] if values else None
        return values[0]

    def strings(s, p):
        return sorted(str(x) for x in g.objects(s, p))

    payloads = {s: json.loads(str(o)) for s, o in g.subject_objects(A.nativePayload)}
    event_nodes = set(g.subjects(RDF.type, A.OrganizationChangeEvent))
    assertion_nodes = set(g.subjects(RDF.type, RDF.Statement))
    # The physical producer class can differ from rdf:Statement; rdf:subject defines each bridge assertion.
    assertion_nodes = set(g.subjects(RDF.subject, None))
    check("RDF/event-count", len(details), len(event_nodes))
    check("RDF/bridge-count", len(expected["bridges"]), len(assertion_nodes))
    by_item = defaultdict(list)
    for record, payload in payloads.items():
        owner = payload.get("ownerDecision", {})
        item_id = owner.get("itemId")
        by_item[item_id].append((record, payload))
        raw = d["decisions"].get(item_id, {})
        owner_expected = {
            "answer": raw.get("answer"),
            "channel": raw.get("channel"),
            "contentDigest": raw.get("content_digest"),
            "decidedOn": raw.get("decided_on"),
            "decisionsFile": decision_files.get(item_id, (None, None))[0],
            "decisionsFileSha256": "sha256:" + str(decision_files.get(item_id, (None, None))[1]),
            "itemId": item_id,
        }
        if "note" in raw:
            owner_expected["note"] = raw["note"]
        check(f"{item_id}/ownerDecision", owner_expected, owner)
        common = {"decidedAt", "decision", "decisionRecord", "evidenceTier", "ownerDecision", "reviewerIri"}
        fields = common | (
            {"event", "publicRecord"}
            if "event" in payload
            else {
                "decisionBasis",
                "endpointRecord",
                "endpointRole",
                "mappingTripleDigest",
                "nameSimilarityUsed",
                "objectIri",
                "parents",
                "predicateIri",
                "publisherNames",
                "reasoning",
                "subjectIri",
            }
        )
        check(f"{item_id}/payload-fields", sorted(fields), sorted(payload))
        check(f"{item_id}/decisionRecord", "docs/decisions.md#ref-072", payload.get("decisionRecord"))
        check(f"{item_id}/reviewer", d["reviewer_iri"], payload.get("reviewerIri"))
        check(f"{item_id}/evidenceTier", "E4", payload.get("evidenceTier"))
        check(f"{item_id}/decision", "adopted", payload.get("decision"))
        check(f"{item_id}/decidedAt", raw.get("decided_on", "") + "T00:00:00+00:00", payload.get("decidedAt"))
        literal = one(record, A.nativePayload)
        native_digest = "sha256:" + hashlib.sha256(str(literal).encode()).hexdigest()
        check(f"{item_id}/sourceDigest", native_digest, str(one(record, A.sourceDigest)))
        # README section 'RDF record digests': sorted N-Triples predicate-object lines.
        lines = sorted(
            f"{p.n3()} {_quoteLiteral(o) if isinstance(o, rdflib.Literal) else o.n3()} ."
            for p, o in g.predicate_objects(record)
            if p != A.contentDigest
        )
        record_digest = "sha256:" + hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()
        bindings = list(g.subjects(A.evidenceSourceRecord, record))
        check(f"{item_id}/binding-count", 1, len(bindings))
        for binding in bindings:
            for predicate, value in (
                (R.attestor, d["reviewer_iri"]),
                (R.attestedAt, raw.get("decided_on", "") + "T00:00:00+00:00"),
                (R.decision, str(R.approved)),
                (R.assertionOrigin, str(R.humanAsserted)),
                (R.attestorKind, str(R.humanUser)),
                (R.epistemicBasis, str(R.editorialAssertion)),
                (R.evidentiaryFunction, str(R.supports)),
                (R.evidenceRole, str(R.textualEvidence)),
                (A.evidenceSourceDigest, record_digest),
            ):
                check(f"{item_id}/binding/{predicate}", value, str(one(binding, predicate)))
    seen_event_nodes = set()
    seen_bridge_nodes = set()
    for event in c["events"]:
        eid = event["event_id"]
        pairs = by_item[eid]
        check(f"{eid}/source-count", len(event["public_records"]), len(pairs))
        check(
            f"{eid}/publicRecords",
            sorted_rows(event["public_records"]),
            sorted_rows([p.get("publicRecord") for _, p in pairs]),
        )
        targets = set()
        for record, payload in pairs:
            got = copy.deepcopy(payload.get("event", {}))
            if (
                isinstance(got, dict)
                and isinstance(got.get("results"), list)
                and all(isinstance(r, dict) and "rowId" in r for r in got["results"])
            ):
                got["results"].sort(key=lambda r: r["rowId"])
            check(f"{eid}/event-native", details[eid], got)
            check(f"{eid}/sourceLocator", payload["publicRecord"]["url"], str(one(record, A.sourceLocator)))
            for binding in g.subjects(A.evidenceSourceRecord, record):
                targets.add(one(binding, R.bindsAssertion))
        check(f"{eid}/event-target-count", 1, len(targets))
        for node in targets:
            seen_event_nodes.add(node)
            check(f"{eid}/type", True, (node, RDF.type, A.OrganizationChangeEvent) in g)
            check(
                f"{eid}/originals",
                sorted(o["resource_iri"] for o in event["originals"]),
                strings(node, A.originalOrganization),
            )
            check(
                f"{eid}/results",
                sorted(r["resourceIri"] for r in details[eid]["results"]),
                strings(node, A.resultingOrganization),
            )
            literal = one(node, R.effectiveDate)
            check(f"{eid}/effectiveDate", event["effective_date"] + "T00:00:00+00:00", str(literal))
            check(f"{eid}/effectiveDate-datatype", str(rdflib.XSD.dateTime), str(getattr(literal, "datatype", None)))
            snapshot["events"].append(
                {
                    "eventId": eid,
                    "node": str(node),
                    "effectiveDate": str(literal),
                    "originals": strings(node, A.originalOrganization),
                    "results": strings(node, A.resultingOrganization),
                    "evidenceRecords": sorted(str(r) for r, _ in pairs),
                    "event": details[eid],
                }
            )
    actual_triples = set()
    for node in assertion_nodes:
        actual_triples.add((str(one(node, RDF.subject)), str(one(node, RDF.predicate)), str(one(node, RDF.object))))
    expected_triples = {(r["subject"], r["relation"], r["object"]) for r in expected["bridges"]}
    check("RDF/bridge-triples", sorted(expected_triples), sorted(actual_triples))
    candidate_by_id = {r["candidate_id"]: r for r in c["candidates"]}
    for row in expected["bridges"]:
        item_id = row["candidate_id"]
        raw_row = candidate_by_id[item_id]
        pairs = by_item[item_id]
        check(item_id + "/source-count", 2, len(pairs))
        roles = []
        targets = set()
        for record, payload in pairs:
            roles.append(payload.get("endpointRole"))
            for key, value in (
                ("decisionBasis", row["basis"]),
                ("reasoning", row["reasoning"]),
                ("subjectIri", row["subject"]),
                ("predicateIri", row["relation"]),
                ("objectIri", row["object"]),
                ("publisherNames", {"subject": row["subject_publisher_name"], "object": row["object_publisher_name"]}),
                (
                    "parents",
                    {
                        role: {
                            "publisherName": raw_row[endpoint]["parent"]["publisher_name"],
                            "resourceIri": raw_row[endpoint]["parent"]["resource_iri"],
                        }
                        for role, endpoint in [("subject", "source"), ("object", "target")]
                        if raw_row[endpoint].get("parent")
                    },
                ),
                ("nameSimilarityUsed", False),
            ):
                check(item_id + "/" + key, value, payload.get(key))
            triple = {"subject": row["subject"], "predicate": row["relation"], "object": row["object"]}
            check(item_id + "/mappingTripleDigest", digest(triple), payload.get("mappingTripleDigest"))
            role = payload.get("endpointRole")
            ep = payload.get("endpointRecord", {})
            if endpoint_records is not None:
                check(item_id + "/endpointRecord", endpoint_records.get(row.get(role)), ep)
                wanted_locator = endpoint_records.get(row.get(role), {}).get("sourceLocator")
                if wanted_locator is not None:
                    wanted_locator += "#agency-identity-resource=" + quote(row[role], safe="")
                check(item_id + "/sourceLocator", wanted_locator, str(one(record, A.sourceLocator)))
            check(item_id + "/endpoint/" + str(role) + "/resourceIri", row.get(role), ep.get("resourceIri"))
            check(
                item_id + "/endpoint/" + str(role) + "/publisherName",
                row.get(str(role) + "_publisher_name"),
                ep.get("publisherName"),
            )
            check(
                item_id + "/endpoint/" + str(role) + "/value", row.get(str(role) + "_publisher_name"), ep.get("value")
            )
            for binding in g.subjects(A.evidenceSourceRecord, record):
                targets.add(one(binding, R.bindsAssertion))
        for target in targets:
            check(
                item_id + "/bound-triple",
                [row["subject"], row["relation"], row["object"]],
                [str(one(target, p)) for p in (RDF.subject, RDF.predicate, RDF.object)],
            )
        check(item_id + "/endpointRoles", ["object", "subject"], sorted(roles))
        check(item_id + "/assertion-count", 1, len(targets))
        seen_bridge_nodes.update(targets)
        snapshot["bridges"].append(
            {
                "candidateId": item_id,
                "nodes": sorted(map(str, targets)),
                "subject": row["subject"],
                "relation": row["relation"],
                "object": row["object"],
                "evidenceRecords": sorted(str(r) for r, _ in pairs),
            }
        )
    check("RDF/event-coverage", sorted(map(str, event_nodes)), sorted(map(str, seen_event_nodes)))
    check("RDF/bridge-coverage", sorted(map(str, assertion_nodes)), sorted(map(str, seen_bridge_nodes)))
    check("RDF/item-coverage", sorted(set(details) | {r["candidate_id"] for r in expected["bridges"]}), sorted(by_item))
    check(
        "RDF/source-record-count",
        sum(len(e["public_records"]) for e in c["events"]) + 2 * len(expected["bridges"]),
        len(payloads),
    )
    for row in expected["non-emissions"]:
        present = bool(by_item.get(row["item_id"])) or bool(
            row["subject"] and (row["subject"], str(A.sameEntityAs), row["object"]) in actual_triples
        )
        if row["subject_value"] == "CISA":
            present = present or any(t[0].endswith(":CISA") or t[2].endswith(":CISA") for t in actual_triples)
        check(row["item_id"] + "/no-emitted-bridge", False, present)
        snapshot["nonEmissionAbsences"].append({"itemId": row["item_id"], "absent": not present})
    # Aliases are release metadata, never RDF statements (REF-075 D2): no record cites an alias decision.
    alias_items = {r["alias_id"] for r in expected.get("aliases", ())} | {
        r["item_id"] for r in expected["non-emissions"] if r["reason"] == "aliasRejectedByOwner"
    }
    check("RDF/aliases-off-wire", [], sorted(alias_items & set(by_item)))
    for rows in snapshot.values():
        rows.sort(key=canonical)
    return errors, snapshot


COVERED = ("candidates", "events", "non_emissions", "no_fr_bridge")
ALIAS_COVERED = ("aliases",)
OWNER_AGGREGATE = "sha256:7fe88a9167a9363f5c2bfdcd3911953b7323abe1564d40586991c9612f95f4bc"
SUCCESSION_OWNER_AGGREGATE = "sha256:4d29ffd7c936159dbff13d9b228845e50d134a567a8ff6b60a3d9e2f7f7921cc"
ALIAS_OWNER_AGGREGATE = "sha256:f27a8b66b414ed8c75153340997623b589c5fe1820d75e60ec73953d361c0b82"
ALIAS_CANDIDATES = "plans/agency-registry-alias-batch-candidates.json"
#: Each batch's candidates and decisions files, the aggregate the owner decided on, and what it covers, in release order.
BATCHES = (
    (
        "plans/agency-registry-batch-1-candidates.json",
        "plans/agency-registry-batch-1-decisions.json",
        OWNER_AGGREGATE,
        COVERED,
    ),
    (
        "plans/agency-registry-succession-batch-candidates.json",
        "plans/agency-registry-succession-batch-decisions.json",
        SUCCESSION_OWNER_AGGREGATE,
        COVERED,
    ),
    (ALIAS_CANDIDATES, "plans/agency-registry-alias-batch-decisions.json", ALIAS_OWNER_AGGREGATE, ALIAS_COVERED),
)


def digest(value):
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def decision_failures(c, d, owner_aggregate=OWNER_AGGREGATE, covers=COVERED):
    """Recompute item/member digests in one indexed pass, retaining array order.

    An alias's digest is its own row's; an alias the owner has not decided is held, so the alias
    batch's decisions need only be a subset of its aliases.
    """
    failures = []
    members = defaultdict(list)
    for row in c["candidates"]:
        if row.get("event_id"):
            members[row["event_id"]].append(row)
    computed = {}
    decidable = set()

    def clean(row):
        return {k: v for k, v in row.items() if k not in {"content_digest", "effect_note"}}

    for group in covers:
        for row in c[group]:
            key = row.get("candidate_id", row.get("event_id", row.get("value_id", row.get("alias_id"))))
            if key in computed:
                failures.append({"path": "duplicate-item/" + str(key)})
            event_members = members[row["event_id"]] if group == "events" else []
            computed[key] = (
                digest(clean(row))
                if group == "aliases"
                else digest({"entry": clean(row), "members": [clean(x) for x in event_members]})
            )
            failures.extend(differences(row["content_digest"], computed[key], "digest/" + key))
            if group != "candidates" or row["relation"] == "sameEntityAs":
                decidable.add(key)
            if group == "events":
                failures.extend(
                    differences(row["rows"], [x["candidate_id"] for x in event_members], "event-members/" + key)
                )
    decided = sorted(d["decisions"])
    wanted = sorted(decidable & set(decided)) if covers == ALIAS_COVERED else sorted(decidable)
    failures.extend(differences(wanted, decided, "decision-population"))
    for key, answer in d["decisions"].items():
        failures.extend(differences(computed.get(key), answer["content_digest"], "decision-digest/" + key))
    aggregate = digest({k: c[k] for k in covers})
    for key, observed in [
        ("candidates_digest", aggregate),
        ("digest", digest({k: v for k, v in c.items() if k != "digest"})),
    ]:
        failures.extend(differences(c[key], observed, key))
    failures.extend(differences(owner_aggregate, aggregate, "owner-approved-aggregate"))
    failures.extend(differences(list(covers), c["candidates_digest_covers"], "aggregate-coverage"))
    failures.extend(differences(c["owner_reviewer_iri"], d["reviewer_iri"], "reviewer"))
    return failures


def pinned_json(path, trusted):
    if not trusted:
        raise ValueError("required external digest absent: " + str(path))
    raw = Path(path).read_bytes()
    if "sha256:" + hashlib.sha256(raw).hexdigest() != trusted:
        raise ValueError("external digest mismatch: " + str(path))
    return json.loads(raw)


def child(root, path):
    result = (Path(root) / path).resolve()
    if not result.is_relative_to(Path(root).resolve()):
        raise ValueError("evidence path escapes its root: " + path)
    return result


def authenticate_agency_evidence(
    root,
    manifest_path,
    trusted_manifest_digest,
    receipt_path,
    trusted_receipt_digest,
    candidates,
    decisions,
    source_paths=None,
    alias_batch=None,
):
    """Authenticate the pinned review: batch 1's events, and, given ``alias_batch``, every decided alias's records."""
    manifest = pinned_json(manifest_path, trusted_manifest_digest)
    receipt = pinned_json(receipt_path, trusted_receipt_digest)
    errors = differences(manifest["candidatesDigest"], candidates["candidates_digest"], "review/aggregate")
    errors.extend(differences(manifest["reviewReceiptSha256"], trusted_receipt_digest, "review/receipt"))
    sources = {}
    for row in manifest["members"]:
        path = (
            Path(source_paths[row["path"]])
            if source_paths and row["path"] in source_paths
            else child(root, row["path"])
        )
        raw = path.read_bytes()
        errors.extend(
            differences(row["sha256"], "sha256:" + hashlib.sha256(raw).hexdigest(), "evidence/" + row["path"])
        )
        errors.extend(differences(row["byteLength"], len(raw), "evidence-size/" + row["path"]))
        if row.get("sourceUrl"):
            if row["sourceUrl"] in sources:
                raise ValueError("duplicate reviewed source URL")
            sources[row["sourceUrl"]] = row
    events = {e["event_id"]: e for e in candidates["events"]}
    members = defaultdict(list)
    for row in candidates["candidates"]:
        if row.get("event_id"):
            members[row["event_id"]].append(row)
    errors.extend(
        differences(sorted(events), sorted(r["eventId"] for r in receipt["events"]), "review/event-population")
    )
    for reviewed in receipt["events"]:
        event = events[reviewed["eventId"]]
        selected = {
            "ownerDecision": decisions["decisions"][event["event_id"]],
            "selectedDate": event["effective_date"],
            "selectedDateBasis": event["date_basis"],
            "originals": event["originals"],
            "results": [
                {"candidateId": r["candidate_id"], "target": r["target"], "functionsTaken": r.get("functions_taken")}
                for r in members[event["event_id"]]
            ],
        }
        errors.extend(differences(selected, {k: reviewed[k] for k in selected}, "review/" + event["event_id"]))
        if not reviewed["claims"]:
            raise ValueError("reviewed event has no claims")
        for claim in reviewed["claims"]:
            if not claim["evidence"] and claim["status"] != "not_claimed":
                raise ValueError("reviewed claim has no retained source")
            for evidence in claim["evidence"]:
                source = sources.get(evidence["sourceUrl"])
                if not source or not evidence.get("location"):
                    raise ValueError("reviewed claim source or location missing")
                errors.extend(differences(source["sha256"], "sha256:" + evidence["sourceSha256"], "review/source-hash"))
                errors.extend(differences(source["retainedPath"], evidence["retainedPath"], "review/source-path"))
    review = receipt.get("aliasReview")
    if alias_batch is None:
        if review is not None:
            raise ValueError("the receipt reviews aliases, but no alias batch was given to bind them to")
        return errors
    if review is None:
        raise ValueError("the alias batch has no review in the pinned receipt")
    ac, ad = alias_batch
    errors.extend(differences(manifest.get("aliasCandidatesDigest"), ac["candidates_digest"], "review/alias-aggregate"))
    aliases = {a["alias_id"]: a for a in ac["aliases"] if a["alias_id"] in ad["decisions"]}
    errors.extend(
        differences(sorted(aliases), sorted(r["aliasId"] for r in review["aliases"]), "review/alias-population")
    )
    for reviewed in review["aliases"]:
        alias = aliases[reviewed["aliasId"]]
        effect = alias["answer_effects"][ad["decisions"][alias["alias_id"]]["answer"]]
        selected = {
            "ownerDecision": ad["decisions"][alias["alias_id"]],
            "nameKey": alias["name_key"],
            "outcome": effect["outcome"],
            "frRelation": effect.get("fr_relation"),
            "fr": (alias["fr_record"] or {}).get("resource_iri"),
            "target": (alias["target"] or {}).get("resource_iri"),
        }
        label = "review/" + alias["alias_id"]
        errors.extend(differences(selected, {k: reviewed.get(k) for k in selected}, label))
        evidence = [e for claim in reviewed["claims"] for e in claim["evidence"]]
        errors.extend(
            differences(
                [[r["url"], r["sha256"], r["file"], r["passage"]] for r in alias["records"]],
                [[e["sourceUrl"], "sha256:" + e["sourceSha256"], e["retainedPath"], e["passage"]] for e in evidence],
                label + "/records",
            )
        )
        for item in evidence:
            source = sources.get(item["sourceUrl"])
            if not source:
                raise ValueError("reviewed alias record is not a pinned evidence member")
            errors.extend(differences(source["sha256"], "sha256:" + item["sourceSha256"], label + "/source-hash"))
            errors.extend(differences(source["retainedPath"], item["retainedPath"], label + "/source-path"))
    return errors


def table_path(key):
    """A view table's member path: the registry's own tables, then REF-038's projection folded in."""
    return f"tables/agency-{key}.parquet" if key.startswith("projection") else f"tables/agency-registry-{key}.parquet"


def verify_agency_artifacts(
    *,
    source_root,
    distribution,
    agency_view=None,
    agency_view_manifest_sha256=None,
    agency_audit_evidence_manifest=None,
    agency_audit_evidence_sha256=None,
    agency_review_receipt=None,
    agency_review_receipt_sha256=None,
    source_paths=None,
):
    """Compare authenticated independent expectations with the exact agency slice.

    Distribution authentication is the caller's responsibility. The separately
    trusted agency view and primary evidence cannot be inferred from that pin.
    """
    required = (
        agency_view,
        agency_view_manifest_sha256,
        agency_audit_evidence_manifest,
        agency_audit_evidence_sha256,
        agency_review_receipt,
        agency_review_receipt_sha256,
    )
    if not all(required):
        return {
            "status": "unevaluated",
            "failures": [
                {
                    "path": "required-agency-evidence",
                    "reason": "Dedicated agency view and externally pinned source-review evidence are required",
                }
            ],
        }
    trusted_inputs = {
        "agencyViewManifest": {
            "path": str(Path(agency_view) / "view-manifest.json"),
            "sha256": agency_view_manifest_sha256,
        },
        "auditEvidenceManifest": {"path": str(agency_audit_evidence_manifest), "sha256": agency_audit_evidence_sha256},
        "reviewReceipt": {"path": str(agency_review_receipt), "sha256": agency_review_receipt_sha256},
    }
    source_paths = source_paths or {}
    try:
        root = Path(source_root)
        dist = Path(distribution)
        view = Path(agency_view)
        batches, decision_files, errors = [], {}, []
        for cp_name, dp_name, owner_aggregate, covers in BATCHES:
            cp = Path(source_paths.get(cp_name, root / cp_name))
            dp = Path(source_paths.get(dp_name, root / dp_name))
            batch = (json.loads(cp.read_text()), json.loads(dp.read_text()))
            errors.extend(decision_failures(*batch, owner_aggregate, covers))
            decision_files.update({item: (dp_name, sha(dp)) for item in batch[1]["decisions"]})
            batches.append(batch)
        # The retained source-review receipt covers batch 1's events and the alias batch's records; the
        # succession batch's one event cites its own public records.
        errors.extend(
            authenticate_agency_evidence(
                root,
                agency_audit_evidence_manifest,
                agency_audit_evidence_sha256,
                agency_review_receipt,
                agency_review_receipt_sha256,
                *batches[0],
                source_paths=source_paths,
                alias_batch=batches[-1],
            )
        )
        c, d = merged_plans(batches)
        if errors:
            return {"status": "failed", "failures": errors, "trustedInputs": trusted_inputs}
        expected, details = expected_from_batches(batches)
        rosters = read_rosters(root, source_paths)
        expected["projection"], expected["projection-unresolved"] = expected_projection(
            root, rosters, c["inputs"]["roster_releases"], source_paths
        )
        expected["organizations"] = expected_organizations(
            rosters, expected["projection"], expected["current-successors"]
        )
        manifest = pinned_json(view / "view-manifest.json", agency_view_manifest_sha256)
        errors.extend(
            differences(
                {name: plan["candidates_digest"] for (name, *_), (plan, _) in zip(BATCHES, batches, strict=True)},
                manifest["release"]["candidatesDigests"],
                "view/candidate-aggregate",
            )
        )
        paths = [table_path(key) for key in expected]
        errors.extend(
            differences(sorted(paths), sorted(m["path"] for m in manifest["members"]), "view/member-population")
        )
        for member in manifest["members"]:
            raw = child(view, member["path"]).read_bytes()
            errors.extend(
                differences(
                    member["sha256"],
                    "sha256:" + hashlib.sha256(raw).hexdigest(),
                    "view/member-digest/" + member["path"],
                )
            )
            errors.extend(differences(member["byteLength"], len(raw), "view/member-size/" + member["path"]))
        if errors:
            return {"status": "failed", "failures": errors, "trustedInputs": trusted_inputs}
        actual = {key: sorted_rows(pq.read_table(view / table_path(key)).to_pylist()) for key in expected}
        errors.extend(differences(expected, actual, "agency-view"))
        record_errors, record_receipts = check_alias_records(root, batches[-1], source_paths)
        errors.extend(record_errors)
        errors.extend(
            check_alias_rosters(batches[-1], rosters, read_opm_names(root, source_paths), expected["projection"])
        )
        endpoint_errors, endpoint_receipts, _ = check_raw_endpoints(root, c, source_paths, rosters)
        errors.extend(endpoint_errors)
        distribution_manifest = json.loads((dist / "atlas-manifest.json").read_text())
        packs = [p for p in distribution_manifest["packs"] if p["path"] == f"packs/mappings/{KEY}.nq.zst"]
        if len(packs) != 1:
            raise ValueError("agency mapping pack absent or duplicated")
        pack = packs[0]
        path = child(dist, pack["path"])
        raw = path.read_bytes()
        if "sha256:" + hashlib.sha256(raw).hexdigest() != pack["transport"]["digest"]:
            raise ValueError("agency pack transport digest mismatch")
        if "sha256:" + hashlib.sha256(zstd.decompress(raw)).hexdigest() != pack["content"]["digest"]:
            raise ValueError("agency pack content digest mismatch")
        graph, count = read_graph(path)
        endpoint_records = independent_endpoint_records(c, endpoint_receipts)
        rdf_errors, snapshot = check_rdf(graph, c, d, expected, details, decision_files, endpoint_records)
        errors.extend(rdf_errors)
        return {
            "status": "failed" if errors else "passed",
            "failures": errors,
            "trustedInputs": trusted_inputs,
            "rawRosterInputs": endpoint_receipts,
            "rdfQuadCount": count,
            "rawRosterEndpointsChecked": len(endpoint_receipts),
            "aliasRecordsRead": record_receipts,
            "comparedRows": {k: len(v) for k, v in actual.items()},
            "rdf": snapshot,
            "scope": "Faithful representation of recorded owner decisions and pinned primary-source review; no legal adjudication",
        }
    except (ValueError, KeyError, OSError, AssertionError, TypeError, AttributeError) as error:
        return {
            "status": "failed",
            "failures": [{"path": "agency-comparison", "reason": str(error)}],
            "trustedInputs": trusted_inputs,
        }


def independent_endpoint_records(candidates, receipts):
    """Bind normalized endpoint evidence to independently read roster bytes."""
    by_iri = {row["resourceIri"]: row for row in receipts}
    expected = {}
    for row in candidates["candidates"]:
        for endpoint in (row["source"], row["target"]):
            iri = endpoint["resource_iri"]
            receipt = by_iri[iri]
            roster = endpoint["roster"]
            if roster == "federal-register-agencies":
                publisher, field, locator = (
                    "Federal Register",
                    "name",
                    "https://www.federalregister.gov/api/v1/agencies",
                )
            elif roster == "ecfr-agencies":
                publisher, field, locator = "eCFR", "name", "https://www.ecfr.gov/api/admin/v1/agencies.json"
            elif roster == "federal-hierarchy-organizations":
                page = int(Path(receipt["sourcePath"]).stem.rsplit("-", 1)[1])
                publisher, field, locator = (
                    "Federal Hierarchy",
                    "fhorgname",
                    f"https://api.sam.gov/prod/federalorganizations/v1/orgs?limit=200&offset={page * 200}",
                )
            else:
                raise ValueError("unsupported roster " + roster)
            expected[iri] = {
                "field": field,
                "publisher": publisher,
                "publisherName": endpoint["publisher_name"],
                "releaseDigest": candidates["inputs"]["roster_releases"][endpoint["release_key"]],
                "releaseKey": endpoint["release_key"],
                "resourceIri": iri,
                "sourceDigest": "sha256:" + receipt["sourceSha256"],
                "sourceLocator": locator,
                "value": endpoint["publisher_name"],
            }
    return expected
