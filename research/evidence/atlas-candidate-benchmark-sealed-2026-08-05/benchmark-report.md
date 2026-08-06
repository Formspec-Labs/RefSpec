# OAEI Conference provider embedding benchmark

## Verified scope

- Concepts: 802 across seven ontologies.
- Gold mappings: 305 across 21 reference alignments.
- Common embedding dimension: 768.
- Synchronous multi-input chunk size: 50.
- Corpus digest: `sha256:3e4474e490673b2c25c28b27bdf5a6b0dafb74e711d2ab00c1df7554958f86e4`.
- Gold digest: `sha256:43d476e4414a95998f26659ee6cc2853239f38a7e5222879675fdc7ca6ebc0ef`.

## Recall

Each cell is bidirectional union recall: a gold pair counts when either ontology retrieves the other within top-k.

| Arm | @1 | @2 | @3 | @5 | @10 | @20 | @50 | @100 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| google-gemini-embedding-001-retrieval | 88.85% | 94.75% | 96.39% | 98.03% | 98.36% | 98.36% | 100.00% | 100.00% |
| google-gemini-embedding-001-semantic-similarity | 88.52% | 93.11% | 95.08% | 96.72% | 97.70% | 98.69% | 99.34% | 100.00% |
| google-gemini-embedding-2-retrieval-instruction | 90.49% | 94.75% | 95.74% | 98.03% | 98.03% | 99.34% | 100.00% | 100.00% |
| openai-text-embedding-3-large | 84.59% | 93.11% | 94.75% | 95.41% | 97.05% | 98.69% | 100.00% | 100.00% |
| openai-text-embedding-3-small | 83.28% | 89.51% | 93.44% | 94.43% | 95.41% | 97.38% | 99.67% | 100.00% |
| cross-arm union | 95.74% | 97.05% | 98.03% | 98.36% | 98.36% | 100.00% | 100.00% | 100.00% |

## Usage and cost

| Arm | Model | Mode | Requests | Input tokens | List-price cost |
| --- | --- | --- | ---: | ---: | ---: |
| google-gemini-embedding-001-retrieval | `gemini-embedding-001` | retrieval | 34 | 124,910 | $0.018736 |
| google-gemini-embedding-001-semantic-similarity | `gemini-embedding-001` | semantic-similarity | 17 | 62,455 | $0.009368 |
| google-gemini-embedding-2-retrieval-instruction | `gemini-embedding-2` | asymmetric retrieval with official prompt instructions | 34 | 72,567 | $0.014513 |
| openai-text-embedding-3-large | `text-embedding-3-large` | symmetric structured concept text | 17 | 28,527 | $0.003709 |
| openai-text-embedding-3-small | `text-embedding-3-small` | symmetric structured concept text | 17 | 28,527 | $0.000571 |

Total standard list-price cost: **$0.046897**.
Conservative retry reservation: **$0.067205** against a **$0.25** hard ceiling.

## Asynchronous Batch API smoke check

One OpenAI Batch API line embedded the first two pinned concept texts together
with `text-embedding-3-small` at 768 dimensions. The batch completed with one
successful request, zero failed requests, a `[2, 768]` vector shape, 62 reported
input tokens, and a list-price Batch cost of **$0.000000620**. The synchronous
benchmark plus this check cost **$0.046897820** at published list prices.

The first upload used a one-hour file lifetime. Batch validation accepted the
job and then reported that an input file must remain available for at least the
24-hour completion window; it processed zero requests. The successful retry
used a 48-hour input-file lifetime. This gives the implementation a concrete
preflight rule for future Batch submissions.

- Successful Batch result: `/private/tmp/refspec-candidate-benchmark.ANhNrc/evidence/openai-text-embedding-3-small-async-batch-smoke/result.json` (`sha256:cf146d009904d06d3f6cf8ff57d8c0f019528d6d8acf82b0f3f605a5023200b2`)
- Successful output JSONL: `/private/tmp/refspec-candidate-benchmark.ANhNrc/evidence/openai-text-embedding-3-small-async-batch-smoke/output.jsonl` (`sha256:76d774ec3884c1720955c524f742c4c9e2e7e29998c15104041d9d930c5002c7`)
- Validation evidence: `/private/tmp/refspec-candidate-benchmark.ANhNrc/evidence/openai-text-embedding-3-small-async-batch-smoke-attempt-1-invalid-expiration`

## Evidence

Every arm directory contains exact redacted request JSON, exact raw response JSON, exchange digests, compressed vectors, full gold ranks, and a result record. No API key is present in these artifacts.

- Benchmark result: `/private/tmp/refspec-candidate-benchmark.ANhNrc/benchmark-result.json` (`sha256:4cf714671d7a72435ec06183c518eef5ced72cf25effb5ca7351686e115db0aa`)
- Corpus: `/private/tmp/refspec-candidate-benchmark.ANhNrc/corpus.json` (`sha256:3e4474e490673b2c25c28b27bdf5a6b0dafb74e711d2ab00c1df7554958f86e4`)
- Gold: `/private/tmp/refspec-candidate-benchmark.ANhNrc/gold.json` (`sha256:43d476e4414a95998f26659ee6cc2853239f38a7e5222879675fdc7ca6ebc0ef`)
- Evidence root: `/private/tmp/refspec-candidate-benchmark.ANhNrc/evidence`

## Official references checked

- openai-small-model: https://developers.openai.com/api/docs/models/text-embedding-3-small
- openai-large-model: https://developers.openai.com/api/docs/models/text-embedding-3-large
- openai-batch: https://platform.openai.com/docs/api-reference/batch/object
- google-embeddings-guide: https://ai.google.dev/gemini-api/docs/embeddings
- google-embeddings-api: https://ai.google.dev/api/embeddings
- google-embedding-2-model: https://ai.google.dev/gemini-api/docs/models/gemini-embedding-2
- google-pricing: https://ai.google.dev/gemini-api/docs/pricing
