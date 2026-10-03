"""Read-only independent agency artifact check; no refspec/producer imports or fetching.

Run with the repository's Python (rdflib, pyarrow, backports.zstd). The expected
rows come directly from the candidate JSON and recorded owner answers. The generic fidelity verifier calls this bounded agency comparison.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

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
    return {
        "bridges": sorted_rows(bridges),
        "events": sorted_rows(events),
        "non-emissions": sorted_rows(non),
        "current-successors": current_successors(events),
    }, event_details


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


def check_raw_endpoints(repo, c, source_paths=None):
    """Read source JSON fields directly, without producer roster readers."""
    source_paths = source_paths or {}
    names = [
        "tests/fixtures/federal_register_native_controls/fr-agencies-2026-08-15.json",
        "tests/fixtures/cfr_list_of_subjects/ecfr-agencies-2026-08-15.json",
        *(f"tests/fixtures/federal_hierarchy_complete/fh-orgs-all-page-{i}.json" for i in range(5)),
    ]
    paths = {name: Path(source_paths.get(name, repo / name)) for name in names}
    logical_paths = {path: name for name, path in paths.items()}
    fr_path, ecfr_path, *fh_paths = paths.values()
    fr = {r["id"]: r for r in json.loads(fr_path.read_text())}
    ecfr = {}

    def visit(rows, parent=None):
        for row in rows:
            ecfr[row["slug"]] = (row, parent)
            visit(row.get("children", []), row["slug"])

    visit(json.loads(ecfr_path.read_text())["agencies"])
    fh = {r["fhorgid"]: (r, p) for p in fh_paths for r in json.loads(p.read_text())["orglist"]}
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
    file_digests = {p: sha(p) for p in [fr_path, ecfr_path, *fh_paths]}
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


def read_graph(path):
    data = zstd.decompress(path.read_bytes())
    dataset = rdflib.Dataset()
    dataset.parse(data=data.decode(), format="nquads")
    graph = rdflib.Graph()
    for s, p, o, _ in dataset.quads():
        graph.add((s, p, o))
    return graph, len(dataset)


def check_rdf(g, c, d, expected, details, decision_sha, endpoint_records=None):
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
            "decisionsFile": "plans/agency-registry-batch-1-decisions.json",
            "decisionsFileSha256": "sha256:" + decision_sha,
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
    for rows in snapshot.values():
        rows.sort(key=canonical)
    return errors, snapshot


COVERED = ("candidates", "events", "non_emissions", "no_fr_bridge")
OWNER_AGGREGATE = "sha256:7fe88a9167a9363f5c2bfdcd3911953b7323abe1564d40586991c9612f95f4bc"


def digest(value):
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def decision_failures(c, d):
    """Recompute item/member digests in one indexed pass, retaining array order."""
    failures = []
    members = defaultdict(list)
    for row in c["candidates"]:
        if row.get("event_id"):
            members[row["event_id"]].append(row)
    computed = {}
    decidable = set()

    def clean(row):
        return {k: v for k, v in row.items() if k not in {"content_digest", "effect_note"}}

    for group in COVERED:
        for row in c[group]:
            key = row.get("candidate_id", row.get("event_id", row.get("value_id")))
            if key in computed:
                failures.append({"path": "duplicate-item/" + str(key)})
            event_members = members[row["event_id"]] if group == "events" else []
            computed[key] = digest({"entry": clean(row), "members": [clean(x) for x in event_members]})
            failures.extend(differences(row["content_digest"], computed[key], "digest/" + key))
            if group != "candidates" or row["relation"] == "sameEntityAs":
                decidable.add(key)
            if group == "events":
                failures.extend(
                    differences(row["rows"], [x["candidate_id"] for x in event_members], "event-members/" + key)
                )
    failures.extend(differences(sorted(decidable), sorted(d["decisions"]), "decision-population"))
    for key, answer in d["decisions"].items():
        failures.extend(differences(computed.get(key), answer["content_digest"], "decision-digest/" + key))
    aggregate = digest({k: c[k] for k in COVERED})
    for key, observed in [
        ("candidates_digest", aggregate),
        ("digest", digest({k: v for k, v in c.items() if k != "digest"})),
    ]:
        failures.extend(differences(c[key], observed, key))
    failures.extend(differences(OWNER_AGGREGATE, aggregate, "owner-approved-aggregate"))
    failures.extend(differences(list(COVERED), c["candidates_digest_covers"], "aggregate-coverage"))
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
):
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
    return errors


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
        cp_name = "plans/agency-registry-batch-1-candidates.json"
        dp_name = "plans/agency-registry-batch-1-decisions.json"
        cp = Path(source_paths.get(cp_name, root / cp_name))
        dp = Path(source_paths.get(dp_name, root / dp_name))
        c = json.loads(cp.read_text())
        d = json.loads(dp.read_text())
        errors = decision_failures(c, d)
        errors.extend(
            authenticate_agency_evidence(
                root,
                agency_audit_evidence_manifest,
                agency_audit_evidence_sha256,
                agency_review_receipt,
                agency_review_receipt_sha256,
                c,
                d,
                source_paths=source_paths,
            )
        )
        if errors:
            return {"status": "failed", "failures": errors, "trustedInputs": trusted_inputs}
        expected, details = expected_from_plans(c, d)
        manifest = pinned_json(view / "view-manifest.json", agency_view_manifest_sha256)
        errors.extend(
            differences(c["candidates_digest"], manifest["release"]["candidatesDigest"], "view/candidate-aggregate")
        )
        paths = [f"tables/agency-registry-{key}.parquet" for key in expected]
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
        actual = {
            key: sorted_rows(pq.read_table(view / "tables" / f"agency-registry-{key}.parquet").to_pylist())
            for key in expected
        }
        errors.extend(differences(expected, actual, "agency-view"))
        endpoint_errors, endpoint_receipts, _ = check_raw_endpoints(root, c, source_paths)
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
        rdf_errors, snapshot = check_rdf(graph, c, d, expected, details, sha(dp), endpoint_records)
        errors.extend(rdf_errors)
        return {
            "status": "failed" if errors else "passed",
            "failures": errors,
            "trustedInputs": trusted_inputs,
            "rawRosterInputs": endpoint_receipts,
            "rdfQuadCount": count,
            "rawRosterEndpointsChecked": len(endpoint_receipts),
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
