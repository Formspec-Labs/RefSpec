"""Command-line interface for building, verifying, querying, and tagging with Atlas Vocabulary Packs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from refspec.atlas.vocabulary_pack import AtlasVocabularyPack
from refspec.atlas.vocabulary_pack_build import build_vocabulary_pack
from refspec.atlas.vocabulary_protocols import (
    DEFAULT_CALIBRATION_EVT_SIGMA,
    DEFAULT_CURATED_SCHEME_WEIGHTS,
    REGULATORY_BENCHMARK_SCHEME_PRESET,
    AuthorityReranker,
    LookupPolicy,
    RelationPolicy,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="refspec-build-vocabulary-pack",
        description="Build, verify, query, or extract concepts with sealed read-only Atlas Vocabulary Packs.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="Compile a verified Atlas 3.1 Parquet view into a SQLite pack")
    p_build.add_argument("--view-root", type=Path, required=True)
    p_build.add_argument("--manifest-digest", required=True)
    p_build.add_argument("--output", type=Path, required=True)
    p_build.add_argument("--scheme", action="append", dest="schemes", required=True)
    p_build.add_argument("--language", action="append", dest="languages")
    p_build.add_argument("--no-mappings", action="store_true")
    p_build.add_argument("--no-derived", action="store_true")
    p_build.add_argument("--no-quarantine-cycles", action="store_true")
    p_build.add_argument("--verify-all", action="store_true")

    p_vec = sub.add_parser("build-vectors", help="Compile a Tier-1 .vpack semantic sidecar for a pack")
    p_vec.add_argument("--pack", type=Path, required=True)
    p_vec.add_argument("--embeddings-dir", type=Path, required=True)
    p_vec.add_argument("--output", type=Path, required=True)
    p_vec.add_argument("--model-id", default="BAAI/bge-m3")
    p_vec.add_argument("--mode", choices=("auto", "flat_f16", "ivf_i8", "binary_i8"), default="auto")
    p_vec.add_argument("--clusters", type=int, default=1024)
    p_vec.add_argument(
        "--recommended-min-cosine",
        type=float,
        default=None,
        help="Optional calibrated cosine abstention floor persisted in the .vpack header",
    )
    p_vec.add_argument(
        "--calibration-mode",
        choices=("auto", "none", "centered_covariance"),
        default="auto",
        help="OOD calibration mode for the compiled sidecar (default: auto)",
    )
    p_vec.add_argument(
        "--calibration-evt-sigma",
        type=float,
        default=DEFAULT_CALIBRATION_EVT_SIGMA,
        help="Extreme-value sigma multiplier for unsupervised recommendedMinCosine calibration",
    )

    p_cal = sub.add_parser(
        "calibrate-vectors",
        help="Attach unsupervised centered-covariance EVT OOD calibration to an existing .vpack sidecar",
    )
    p_cal.add_argument("--sidecar", type=Path, required=True)
    p_cal.add_argument("--output", type=Path, required=True)
    p_cal.add_argument(
        "--calibration-evt-sigma",
        type=float,
        default=DEFAULT_CALIBRATION_EVT_SIGMA,
        help="Extreme-value sigma multiplier for unsupervised recommendedMinCosine calibration",
    )
    p_cal.add_argument(
        "--recommended-min-cosine",
        type=float,
        default=None,
        help="Optional explicit abstention floor override persisted in the calibrated .vpack header",
    )

    p_verify = sub.add_parser("verify", help="Verify a compiled pack (and optional sidecar) and print stats")
    p_verify.add_argument("--pack", type=Path, required=True)
    p_verify.add_argument("--pack-digest")
    p_verify.add_argument("--manifest-digest")
    p_verify.add_argument("--sidecar", type=Path)
    p_verify.add_argument("--sidecar-digest")

    p_query = sub.add_parser("query", help="Run a smoke lookup against a compiled pack")
    p_query.add_argument("--pack", type=Path, required=True)
    p_query.add_argument("--text", required=True)
    p_query.add_argument("--limit", type=int, default=10)
    p_query.add_argument("--group-identical", action="store_true")
    p_query.add_argument("--context", action="store_true")
    p_query.add_argument("--authority-rerank", action="store_true")

    p_extract = sub.add_parser("extract", help="Extract verbatim Atlas concepts from text")
    p_extract.add_argument("--pack", type=Path, required=True)
    p_extract.add_argument("--text", required=True)
    p_extract.add_argument("--limit", type=int, default=20)
    p_extract.add_argument("--max-ngram", type=int, default=5)
    p_extract.add_argument(
        "--max-unigram-doc-freq",
        "--max-unigram-df",
        dest="max_unigram_doc_freq",
        type=int,
        default=None,
        help="Suppress single-token matches with vocab_terms.doc_freq above this threshold (0 disables cap)",
    )
    p_extract.add_argument(
        "--scheme-preset",
        choices=("none", "regulatory-benchmark"),
        default="none",
        help="Optional scheme-weight tiebreak preset (default: none / neutral canonical rid order)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "build":
        manifest = build_vocabulary_pack(
            args.view_root,
            args.output,
            trusted_manifest_digest=args.manifest_digest,
            schemes=args.schemes,
            languages=args.languages or ("en",),
            include_mappings=not args.no_mappings,
            include_derived=not args.no_derived,
            quarantine_broader_cycles=not args.no_quarantine_cycles,
            verify_all_view_members=args.verify_all,
        )
        print(json.dumps(manifest.to_dict(), indent=2))
        return 0

    if args.command == "build-vectors":
        from refspec.atlas.vocabulary_vectors import build_semantic_sidecar

        vmanifest = build_semantic_sidecar(
            args.pack,
            args.embeddings_dir,
            args.output,
            model_id=args.model_id,
            mode=args.mode,
            n_clusters=args.clusters,
            recommended_min_cosine=args.recommended_min_cosine,
            calibration_mode=args.calibration_mode,
            calibration_evt_sigma=args.calibration_evt_sigma,
        )
        print(json.dumps(vmanifest.to_dict(), indent=2))
        return 0

    if args.command == "calibrate-vectors":
        from refspec.atlas.vocabulary_vectors import calibrate_semantic_sidecar

        vmanifest = calibrate_semantic_sidecar(
            args.sidecar,
            args.output,
            calibration_evt_sigma=args.calibration_evt_sigma,
            recommended_min_cosine=args.recommended_min_cosine,
        )
        print(json.dumps(vmanifest.to_dict(), indent=2))
        return 0

    if args.command == "verify":
        sidecar: Any = None
        if args.sidecar is not None:
            from refspec.atlas.vocabulary_vectors import AtlasSemanticSidecar

            sidecar = AtlasSemanticSidecar.open(args.sidecar, trusted_sidecar_digest=args.sidecar_digest)
        try:
            with AtlasVocabularyPack.open(
                args.pack,
                trusted_pack_digest=args.pack_digest,
                trusted_manifest_digest=args.manifest_digest,
                semantic_index=sidecar,
            ) as pack:
                print(json.dumps(pack.stats(), indent=2))
        finally:
            if sidecar is not None:
                sidecar.close()
        return 0

    if args.command == "query":
        reranker = AuthorityReranker() if args.authority_rerank else None
        with AtlasVocabularyPack.open(
            args.pack,
            lookup_policy=LookupPolicy(
                group_identical_labels=args.group_identical,
                include_context=args.context,
            ),
            candidate_reranker=reranker,
            relation_policy=RelationPolicy(),
        ) as pack:
            payload: dict[str, Any] = pack.lookup_with_meta_sync(args.text, limit=args.limit)
            print(json.dumps(payload, indent=2))
        return 0

    if args.command == "extract":
        with AtlasVocabularyPack.open(args.pack) as pack:
            extract_kwargs: dict[str, Any] = {
                "limit": args.limit,
                "max_ngram": args.max_ngram,
                "scheme_weights": (
                    REGULATORY_BENCHMARK_SCHEME_PRESET
                    if args.scheme_preset == "regulatory-benchmark"
                    else DEFAULT_CURATED_SCHEME_WEIGHTS
                ),
            }
            if args.max_unigram_doc_freq is not None:
                extract_kwargs["max_unigram_doc_freq"] = (
                    None if args.max_unigram_doc_freq == 0 else args.max_unigram_doc_freq
                )
            hits = pack.extract_concepts_sync(args.text, **extract_kwargs)
            print(json.dumps(hits, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
