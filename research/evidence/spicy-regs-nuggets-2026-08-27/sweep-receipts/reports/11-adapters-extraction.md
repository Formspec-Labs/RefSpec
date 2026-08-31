## NUGGETS AT RISK

1. **Office extraction with explicit loss accounting and containment — absent from all survivors.**

   `docling.py` parses DOCX, PPTX, and XLSX through pinned, model-free Docling releases ([docling.py:144](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/docling.py:144), [docling.py:190](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/docling.py:190)). It preserves:

   - Body, headers/footers, background, invisible content, speaker notes, and Word comments as five separately labeled layers ([docling.py:303](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/docling.py:303)).
   - Table grids, every cell, row/column-header flags, spans, captions, and ambiguity-marked tabular serialization ([docling.py:280](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/docling.py:280), [docling.py:2308](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/docling.py:2308)).
   - Formula fallback through `orig`, parent and caption references, tree depth, per-layer heading paths, PPTX/XLSX page rectangles, and explicit omissions for content that produced no usable text ([docling.py:66](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/docling.py:66), [docling.py:2256](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/docling.py:2256)).
   - A closed, fixed-text refusal vocabulary covering malformed provider objects, unresolved references, overlapping cells, bad geometry, unknown layers, and every mapping bound ([docling.py:525](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/docling.py:525)).
   - A child-process gate with stripped credentials, wall timeout, process-group termination, input/result caps, and an honest list of unenforced CPU, memory, disk, network, and filesystem limits ([source.py:2961](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/source.py:2961), [source.py:3377](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/source.py:3377)).

   **Survivor checked:** DocSpec’s registry handles text, HTML, XML, JSON, PDF, and images, then refuses every other media type ([extraction.py:408](/Users/mikewolfd/Work/DocSpec/src/docspec/processing/extraction.py:408)). It has no Office element, table, comment, note, caption, or omission mapping. RefSpec, Rulespec, and SpicySearch contain no Office extractor.

2. **Provider-independent structured-LLM safety layer — absent from all survivors.**

   These are not simple transports:

   | Adapter | Behavior that would disappear |
   |---|---|
   | Anthropic | Pre-call JSON Schema validity and enforceability analysis; provider-native exact token count; prompt budget; distinct refusal, output-budget, incomplete-response, schema-violation, nonretryable, and retry-exhausted outcomes ([anthropic.py:347](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/anthropic.py:347), [anthropic.py:653](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/anthropic.py:653)). |
   | OpenAI | Schema-inclusive `tiktoken` budget, local Draft 2020-12 validation, application-owned exponential retries, `insufficient_quota` nonretry classification, and per-attempt/token telemetry ([openai.py:258](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/openai.py:258), [openai.py:430](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/openai.py:430), [openai.py:523](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/openai.py:523)). |
   | OpenAI-compatible | Strict-schema versus prompted modes; broker routing that requires schema support; controlled fallback when `response_format` itself is rejected; explicitly estimated token counts; local validation after either mode ([openai_compatible.py:20](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/openai_compatible.py:20), [openai_compatible.py:468](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/openai_compatible.py:468)). |
   | Codex CLI | Ephemeral read-only execution, ignored user rules/configuration, disabled tools/features, stripped API credentials, allowlisted event vocabulary, unique final-message/usage checks, and local schema validation ([codex_cli.py:10](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/codex_cli.py:10), [codex_cli.py:156](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/codex_cli.py:156)). It does **not** enforce a prompt budget or output-token limit and has no retry loop; its receipt says so ([codex_cli.py:286](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/codex_cli.py:286)). |

   **Survivor checked:** DocSpec only defines an injected `Processor` interface ([processor.py:15](/Users/mikewolfd/Work/DocSpec/src/docspec/ports/processor.py:15)) and validates a generic secret-free provider receipt ([processors.py:496](/Users/mikewolfd/Work/DocSpec/src/docspec/domain/processors.py:496)). It implements none of the provider calls, refusal classifications, schema enforcement, token budgeting, or retry decisions. RefSpec’s `structuredOutputSchema` is declarative vocabulary, not execution ([vocabulary.py:2700](/Users/mikewolfd/Work/RefSpec/src/refspec/vocabulary.py:2700)). Rulespec and SpicySearch have no counterpart.

3. **SPLADE retrieval and cross-encoder reranking — absent from all survivors.**

   Lost adapter behavior includes:

   - SPLADE pin `tomaarsen/splade-modernbert-base-miriad@c640…`, 50,368 dimensions, 8,192-token limit, batch size 8, and distinct query/document encoders ([sentence_transformers.py:39](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/sentence_transformers.py:39), [sentence_transformers.py:431](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/sentence_transformers.py:431)).
   - Portable validated sparse vectors with sorted unique indices, finite values, exact dimensions, dense/COO-tensor conversion, raw weights, and per-input active-dimension/token telemetry ([sentence_transformers.py:164](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/sentence_transformers.py:164), [sentence_transformers.py:498](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/sentence_transformers.py:498)).
   - Reranker pin `BAAI/bge-reranker-v2-m3@953d…`, 4,096-token pairs, batch size 16, exact untruncated pair-token auditing, complete finite score validation, restoration to input order, and MPS cache clearing ([sentence_transformers.py:47](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/sentence_transformers.py:47), [sentence_transformers.py:557](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/sentence_transformers.py:557)).

   Drift rejection and checkpointing are adjacent retrieval-layer capabilities, not methods in the adapter itself:

   - Sparse rows bind exact text digests, model revision, tokenizer, call facts, and vector representation; incompatible resume data is rejected ([retrieval.py:777](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/retrieval.py:777), [retrieval.py:3540](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/retrieval.py:3540)).
   - Reranking hashes the exact query, candidate order, candidate text, model limit, and batch size, then refuses candidate-list or text drift before a provider call ([retrieval.py:4102](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/retrieval.py:4102), [retrieval.py:4153](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/retrieval.py:4153)).
   - Its append-only checkpoint records unknown/failed/completed transitions, resumes stored score rows after interruption, and rebuilds ranks provider-free ([retrieval.py:4405](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/retrieval.py:4405), [retrieval.py:4441](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/retrieval.py:4441), [retrieval.py:4606](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/retrieval.py:4606)).

   **Survivor checked:** SpicySearch retains only the pinned dense BGE arm ([semantic_vector.py:60](/Users/mikewolfd/Work/spicysearch/src/spicysearch/backends/semantic_vector.py:60), [semantic_vector.py:147](/Users/mikewolfd/Work/spicysearch/src/spicysearch/backends/semantic_vector.py:147)). Source-wide searches confirm no SPLADE encoder, cross-encoder reranker, corresponding drift checks, or rerank checkpoint in DocSpec, RefSpec, Rulespec, or SpicySearch.

4. **Measured thin-parse refusal — absent from DocSpec and the other survivors.**

   `source.py` records parser-and-format-specific floors derived from measured populations: HTML visible-text retention, XML visible-text retention, and PDF extracted-character density for both pypdf and PyMuPDF ([source.py:997](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/source.py:997)). It deliberately refuses:

   - retention below the floor;
   - an unmeasurable parse;
   - any parser/format pair with no measured floor.

   Named per-document exemptions are explicit and recorded ([source.py:1262](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/source.py:1262), [source.py:1324](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/source.py:1324)). Office parsing consequently has no admissible floor until an Office population is measured ([source.py:1010](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/source.py:1010)). The live boundary currently invokes the mechanism for native markup and PDF extraction ([document_file_pipeline.py:280](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/document_file_pipeline.py:280)).

   **Survivor checked:** DocSpec reports HTML visible-character counts but does not compare them with extraction output or refuse thin parses ([extraction.py:224](/Users/mikewolfd/Work/DocSpec/src/docspec/processing/extraction.py:224)). Its `RetentionPolicy` controls which stored artifacts remain; it is unrelated to extraction completeness. No survivor has a measured extraction-retention floor.

5. **Provider-free extraction replay plus answer-leak controls — absent as a combined capability.**

   `extraction.py`:

   - Recursively refuses retrieval scores and ranks, plus task-specific hidden fields, before they reach the model ([extraction.py:72](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/extraction.py:72), [extraction.py:285](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/extraction.py:285)).
   - Stores exact payload, schema, secret-free request, response, and call record for every unit ([extraction.py:691](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/extraction.py:691)).
   - Recomputes candidates, rejections, provider tables, metrics, and checks without calling a provider ([extraction.py:415](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/extraction.py:415), [extraction.py:836](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/extraction.py:836)).
   - Scans the run directory for answer/oracle/gold filenames and separately records answer-derived metric fields rather than falsely claiming the run contains no answer information ([extraction.py:573](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/extraction.py:573)).
   - Prevents rebuilds from upgrading failed or unknown checks into passes, even when later supplied with answers or review material ([extraction.py:883](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/extraction.py:883)).

   **Survivor checked:** DocSpec verifies immutable checkpoints and extraction receipts before reuse ([execution.py:182](/Users/mikewolfd/Work/DocSpec/src/docspec/application/execution.py:182), [execution.py:286](/Users/mikewolfd/Work/DocSpec/src/docspec/application/execution.py:286)). That covers generic resume integrity, but not stored LLM request/response replay, answer-key access reporting, retrieval-aid refusal, or the no-upgrade rebuild rule. SpicySearch has answer-key evaluation code, but no equivalent isolation mechanism.

6. **Source evidence taxonomy and complete refusal accounting — only partly reproduced by DocSpec.**

   `source.py` adds:

   - Exact immutable source-state identity, codepoint coordinates, region digest round trips, and coverage/exclusion accounting for every source codepoint ([source.py:12](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/source.py:12), [source.py:2431](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/source.py:2431)).
   - Native-first dispatch; parser output is always `parser-derived`, never `source-exact` ([source.py:30](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/source.py:30)).
   - Layer policy: `body` is evidence-eligible; `furniture` and `notes` are durable context-only; `background` and `invisible` are held and excluded from fragments ([source.py:150](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/source.py:150), [source.py:2056](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/source.py:2056)).
   - Coordinate grades `parser-page-geometry` and `none`; DOCX generally has no page coordinates, while PPTX/XLSX elements can carry parser page geometry ([docling.py:170](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/adapters/docling.py:170)).
   - Record-level refusal codes for unknown identity/access, unsupported or deferred formats, parser disabled/unavailable/failed, and multiple renditions, plus process outcomes such as timeout, signal, malformed result, and oversize input/output ([source.py:220](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/source.py:220), [source.py:1883](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/docpipeline/source.py:1883)).

   **Survivor checked:** DocSpec does provide exact blob identity, evidence coordinates/mappings, reversible PDF page mappings, extraction receipts, and source-byte verification ([content.py:384](/Users/mikewolfd/Work/DocSpec/src/docspec/domain/content.py:384), [extraction.py:295](/Users/mikewolfd/Work/DocSpec/src/docspec/processing/extraction.py:295), [extraction.py:497](/Users/mikewolfd/Work/DocSpec/src/docspec/processing/extraction.py:497)). It does **not** provide the content-layer taxonomy, page-coordinate grades, complete source-region coverage ledger, parser-attempt ledger, or these refusal codes.

## ALREADY PROVIDED

- **DocSpec:** exact captured-byte identity, immutable extraction receipts, reversible evidence mappings, PDF page mappings, generic injected extractor/processor interfaces, and verified checkpoint reuse.
- **SpicySearch:** the same pinned dense `BAAI/bge-base-en-v1.5` model and revision, with normalized batched embeddings.
- **RefSpec and Rulespec:** declarative schema and evidence vocabulary only. Neither implements the runtime parsing, LLM-provider, sparse retrieval, reranking, or extraction-replay behaviors above.

No files or Git state were changed.


