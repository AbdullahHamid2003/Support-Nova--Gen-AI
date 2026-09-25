# Chapter 35 — Performance and Scalability

The SRS sets two quantitative non-functional requirements that this chapter addresses. Performance (NFR 1): the application should analyse, validate and generate an initial complaint recommendation within 20 seconds under normal API and network conditions. Scalability (NFR 2): it should support at least 10,000 complaints, 100 complaint categories or subcategories and 1,000 knowledge-base documents without a complete redesign. This chapter reports what was measured, explains where the time goes, describes the mechanisms that keep the deterministic parts fast (indexes, in-memory retrieval, caching, pagination, asynchronous and batch processing), and states plainly what has not been tested. In short, the deterministic Python work takes milliseconds, and almost all of the elapsed time is the two calls to the GenAI API. The validated recommendation is ready within 20 seconds for most complaints, but the complete pipeline, which also drafts the customer response, meets 20 seconds for only about a third of them. No load test has been run.

## 35.1 How performance is measured

Performance is measured from the running system, not estimated. `backend/src/supportnova/services/pipeline.py` times each stage of every analysis and stores the result in the `analyses` table: `stage_timings` holds the milliseconds for `preprocessing`, `retrieval`, `ai_analysis`, `validation`, `response_generation`, `response_validation` and `total`, and `total_latency_ms` holds the complete pipeline time. The two GenAI stages include every retry. Each individual GenAI attempt is also stored in `ai_runs` with its own `latency_ms` and token counts. Evaluation runs compute p50, p95 and maximum latency over their cases (`evaluation_runs.metrics.latency_ms`).

The main measurement set is the demo import of 24 September 2026: 617 dataset complaints imported and processed with OpenAI gpt-4.1-mini, prompts `complaint_analysis` 1.2.0 and `customer_communication` 1.0.0, four complaints in parallel (`BATCH_WORKERS=4`), on the development machine with the local PostgreSQL 17 cluster. 599 of the 617 complaints were analysed; the other 18 were linked as duplicates of earlier complaints and closed without an analysis. The second set is holdout evaluation run #1 on 154 unseen complaints. Figure 35.1 shows the resulting time budget.

![Figure 35.1 — Measured latency of each pipeline stage (599 analysed dataset complaints)](diagrams/pipelines/fig-35-01-latency-breakdown.svg)
*Figure 35.1 — Measured latency of each pipeline stage (599 analysed dataset complaints)*

## 35.2 Measured latency

**Table 35.1 — Stage timings of the 599 analysed dataset complaints**

| Stage | Performed by | Average | p50 | p95 |
|---|---|---|---|---|
| Preprocessing (normalisation, screening, redaction, perception, history, duplicates) | Python | 21.4 ms | 20 ms | 29 ms |
| Retrieval (hybrid search, precedence conflicts) | Python | 3.6 ms | 3 ms | 5 ms |
| GenAI analysis call, including retries | GenAI | 17.2 s | 16.2 s | 24.9 s |
| Python validation, phase A | Python | 2.2 ms | 2 ms | 4 ms |
| GenAI response call, including retries | GenAI | 5.9 s | 5.2 s | 9.8 s |
| Response validation, phase B | Python | 2.4 ms | 2 ms | 4.1 ms |
| Total, including persistence | — | 23.1 s | 21.7 s | 33.9 s |

The two GenAI calls account for 99.7% of the average total (23,069.5 of 23,134.8 ms). The four deterministic Python stages together take about 30 ms, and saving the results takes about 36 ms more on average; the finalising stage is not timed separately, so this is the remainder. Validating a GenAI answer against the Rule Matrix with its 52 checks is therefore not a performance concern. The time is spent waiting for the model.

**Table 35.2 — End-to-end pipeline latency per run**

| Run | Analysed complaints | p50 | p95 | Within 20 s | Remarks |
|---|---|---|---|---|---|
| Demo import (dataset) | 599 | 21.7 s | 33.9 s | 32.4% | 4 in parallel; minimum 11.3 s, maximum 81.7 s |
| Holdout evaluation run #1 | 152 of 154 | 21.2 s | 33.8 s | 38.8% | maximum 44.6 s; whole run 858 s |
| Adversarial Lab | 18 | 21.3 s | 28.1 s | 33.3% | includes deliberate defects and one forced retry |
| Web submissions | 5 | 18.3 s | 23.7 s | 80.0% | submitted one at a time; too few to generalise |

The p50 and p95 of run #1 are the run's own recorded metrics. Its share within 20 s is computed from the stored `total_latency_ms` of its 152 analysed cases.

**Table 35.3 — Latency of the individual GenAI calls (valid attempts)**

| Call | Valid attempts | Average | p50 | p95 | Average tokens in / out |
|---|---|---|---|---|---|
| Complaint analysis (`complaint_analysis` 1.2.0) | 780 | 16.5 s | 16.0 s | 23.9 s | 9,598 / 1,405 |
| Customer response (`customer_communication` 1.0.0) | 780 | 5.6 s | 5.2 s | 8.6 s | 1,684 / 322 |

The analysis call is slow because it is large. Its system prompt carries the taxonomy, departments, action catalogue, escalation levels, the urgency and priority guide and the routing policy, and the user prompt carries up to ten evidence sections, precedence conflicts, the verified order and history facts and the complaint. The model returns a 37-field JSON object. Prompt version 1.1.0 already asked the model for brief free text in order to "cut response time towards the SRS 20-second target" (its changelog in `prompts/complaint_analysis/1.1.0.yaml`). The response call is smaller because it only receives the validated decision, the evidence the decision relies on and the complaint.

## 35.3 Dependence on the GenAI API and the network

The SRS target applies "under normal API and network conditions", and the measurements show how much the tail depends on them. Every GenAI attempt has a 60-second timeout (`AI_TIMEOUT_SECONDS`) and up to two retries (`AI_MAX_RETRIES`). The retry runner in `genai_pipeline/runner.py` waits 2 s after a rate limit or connection error and 0.5 s after other retryable errors, doubling the wait with each attempt up to 8 s (Chapter 36). In the demo database, 31 of the 1,591 attempts failed: 26 connection errors (for example "getaddrinfo failed", a DNS failure on the development machine), 4 timeouts and 1 invalid answer injected on purpose by the Lab. Every one succeeded on the second attempt, and no stage needed a third.

**Table 35.4 — Effect of a failed attempt on the dataset pipeline latency**

| Dataset analyses | Count | p50 | p95 | Maximum | Within 20 s |
|---|---|---|---|---|---|
| Without a failed attempt | 569 | 21.4 s | 30.5 s | 77.3 s | 34.1% |
| With one failed attempt | 30 | 34.4 s | 80.2 s | 81.7 s | 0.0% |

The three slowest dataset complaints (CMP-00344 at 81.7 s, CMP-00044 at 81.2 s and CMP-00193 at 79.0 s) each lost the full 60-second timeout on the first analysis attempt and then succeeded on the retry in 13.5 to 17.3 s. The retries preserve correctness, since no analysis failed, at the cost of latency. A shorter timeout would shorten the tail, but it would also cut off legitimately long answers: one analysis without any failure took 77.3 s.

## 35.4 Assessment against the 20-second target

The SRS asks for an "initial complaint recommendation" within 20 seconds. In SupportNova the validated recommendation, meaning the GenAI analysis checked and corrected by Pipeline 2, exists in memory once validation phase A has finished. Summing the stored stage timings up to that point (preprocessing, retrieval, AI analysis and validation) gives, for the 599 dataset complaints, an average of 17.2 s, a p50 of 16.2 s and a p95 of 24.9 s, with **80.8% within 20 s**; for the 152 analysed cases of run #1 the share is 84.9% (p50 15.6 s, p95 25.0 s). The pipeline, however, saves the recommendation together with the customer-response draft, so staff see it only when the whole pipeline has finished: p50 21.7 s, with **32.4% within 20 s**.

The target is therefore met for the recommendation itself in about four of five cases and missed for the complete visible result: the full-pipeline p50 exceeds 20 s by 1.7 s. This is reported as a measured shortfall (**Tested**, target not met for the full pipeline). Two changes would address it, neither of them built. The first is to save and show the validated recommendation before the response call starts, so the user sees the recommendation at about 17 s and the draft a few seconds later (**Planned**). The second is to use a faster model or a smaller analysis output, which is a configuration and prompt change (`AI_MODEL`, a new prompt version) whose accuracy effect would have to be measured with a new holdout run first (**Planned**).

## 35.5 Database performance

The database is PostgreSQL 17 with 35 tables created by the Alembic migrations `0001_initial` and `0002_drop_mock_flags`. The demo database has 120 indexes in the `public` schema, primary keys included. The `complaints` table, which every list, dashboard and report reads, has 17 secondary B-tree indexes on the columns that are filtered and grouped, including the composites `ix_complaints_department_status`, `ix_complaints_status_created`, `ix_complaints_category_created` and `ix_complaints_customer_created`, and the single-column indexes on `text_hash` (exact-duplicate lookup), `order_ref`, `sla_state`, `needs_review`, `verification_status`, `priority` and `escalation_required`. Migration 0001 also creates a GIN trigram index `ix_complaints_title_trgm` on `lower(title)` when the `pg_trgm` extension is available (it is present in the demo database), for case-insensitive search.

Two storage decisions keep reads cheap. First, the final intelligence of every case is **denormalised** onto the complaint row (`category_code`, `subcategory_code`, `department_code`, `urgency`, `priority`, `sentiment`, `escalation_level`, `sla_state`, `verification_status` and others), so dashboards and filters work on indexed scalar columns and never read JSON. `services/analytics.py` computes the distributions with SQL `GROUP BY` on these columns. Second, the nested artefacts that are only read for one case at a time are stored in **JSONB**: 52 JSONB columns, for example `analyses.output`, `analyses.retrieval`, `validation_results.validated_decision` and `validation_results.comparison`. A case page therefore loads its full intelligence with a handful of primary-key reads instead of joins over many child tables. The engine uses a connection pool of 10 connections plus up to 20 overflow connections, with `pool_pre_ping` and a recycle time of 1,800 s (`database/base.py`).

The measured database work inside the pipeline is small. The preprocessing stage, which includes the order-ledger lookup, the customer's complaint history and the duplicate checks, averages 21 ms. Dashboard and report query times have not been measured. Some aggregations run in Python over rows loaded from the database: `department_performance` loads one row per operational complaint, and `validation_stats` loads the comparison JSON of the latest validation result of every complaint. At 622 operational complaints this is unproblematic. At 10,000 it is the first place where a load test would be expected to show cost, and moving these aggregations into SQL is the corresponding improvement (**Planned**).

## 35.6 Retrieval performance

Retrieval runs inside the application process over data held in PostgreSQL. Each chunk's text and embedding are stored in `document_chunks` (the embedding as float32 bytes, together with the model name `local-hash-v1-768`). `KnowledgeService` in `knowledge_base/store.py` loads all chunks into an in-memory snapshot: the chunk entries, a BM25 index, a vector matrix, the document-version registry and the precedence-resolved conflicts between Active documents. A query in `knowledge_base/retriever.py` scores the eligible chunks (Active, within their effective dates, not quarantined) lexically with BM25 and semantically with a matrix product against the query vector, adds the policy sections the Rule Matrix cites for the candidate subcategories, fuses the three rankings by reciprocal rank (constant 60, rule-guided weight 1.4), caps each document at 4 chunks and returns the top 10 (`RETRIEVAL_TOP_K`).

The default embedder is a deterministic feature-hashing model (stemmed unigrams, bigrams and character trigrams, 768 dimensions), so retrieval needs no network call and no API key, and it gives the same result on every machine. Measured over the 780 analyses in the demo database, the retrieval function reported an average of 2.3 ms, a p50 of 2.1 ms and a p95 of 3.5 ms (`analyses.retrieval.stats.latency_ms`), with up to 387 eligible chunks out of 484 stored. The pipeline's retrieval stage, which also checks the snapshot revision, averaged 3.6 ms. No external vector database is used; `VECTOR_DATABASE_URL` exists in the configuration but is optional, and provider embeddings (`EMBEDDING_PROVIDER=openai` or `gemini`) are optional too.

## 35.7 Pagination and bounded result sets

Every list endpoint is paginated, and every export and report has a fixed upper bound, so no single request can return an unbounded result.

**Table 35.5 — Pagination and result limits**

| Endpoint or output | Default | Limit | Source |
|---|---|---|---|
| `GET /api/v1/complaints` | 25 per page | `page_size` 1 to 200, `page` at least 1 (tested, Chapter 33) | `api/v1/complaints.py` |
| `GET /api/v1/reviews` | 25 per page | `page_size` 1 to 200 | `api/v1/reviews.py` |
| `GET /api/v1/audit` | 50 per page | `page_size` 1 to 500 | `api/v1/system.py` |
| `GET /api/v1/evaluation/runs/{id}/results` | 50 per page | `page_size` 1 to 500 | `api/v1/quality.py` |
| `GET /api/v1/complaints-export` | — | 10,000 rows (CSV, Excel), 500 rows (PDF) | `api/v1/complaints.py` |
| `GET /api/v1/audit/export` | — | 20,000 rows | `api/v1/system.py` |
| Complaint analysis report register | — | latest 500 complaints (the full list via the complaint export) | `reporting/builders.py` |
| Escalation, manual review and compliance-failure registers | — | latest 400 rows | `reporting/builders.py` |
| Agent dashboard queue | — | 60 complaints | `services/analytics.py` |

## 35.8 Caching

The caches below are implemented and were verified in the code. Each is keyed by a revision counter or by configuration, so a change becomes effective immediately without a restart, which the live-modification tests in Chapter 33 depend on.

**Table 35.6 — Caches implemented in SupportNova**

| Cache | What is cached | When it is rebuilt | Source |
|---|---|---|---|
| Rule Matrix | The built `RuleMatrix` object for the live rules | When the `rules_revision` counter in `system_settings` changes; every accepted rule edit increments it | `services/rules.py` (`RuleService.matrix`) |
| Knowledge snapshot | Chunk entries, BM25 index, vector matrix, version registry, precedence conflicts | When the `kb_revision` counter changes; every upload or version-status change increments it and invalidates the snapshot | `knowledge_base/store.py` (`KnowledgeService.snapshot`) |
| GenAI provider | The configured adapter instance | When the provider, the model or the presence of a key changes | `genai_pipeline/providers/__init__.py` |
| Settings | The parsed configuration | For the lifetime of the process (`lru_cache`) | `core/config.py` |
| Vendor prompt cache | The Anthropic system prompt, marked `cache_control: ephemeral` | Vendor side, when the Anthropic adapter is selected | `providers/anthropic_provider.py` (tested) |
| Browser query cache | React Query results per query key; the dashboard refreshes every 30 s; the report catalogue is reused for 10 minutes | On the interval or when the data is refetched | `frontend/src/pages/Dashboard.tsx`, `Reports.tsx` |

The RuleService and KnowledgeService caches are rebuilt under a lock with a double check, so concurrent requests build a new snapshot only once. There is no shared cache between processes. `REDIS_URL` is declared in `core/config.py` but nothing in the application uses it; a shared queue and cache for several server instances is a **Future Enhancement**.

## 35.9 Asynchronous and batch processing

A submission never waits for the model. `POST /api/v1/complaints` validates and stores the complaint and returns HTTP 202 with the complaint reference. The pipeline then runs in a bounded thread pool, `services/worker.py`, with `BACKGROUND_WORKERS` = 2 by default. The worker keeps a map of in-flight complaints, so the same complaint is never processed twice at the same time. The UI polls `GET /api/v1/complaints/{ref}/pipeline`, which returns the current stage and, for staff, the stage timings; the pipeline tracker on the case page shows the progress. On startup, `requeue_stuck` resubmits any complaint left in `queued` or `processing` by a crash. A separate monitor thread refreshes the SLA states every `SLA_MONITOR_INTERVAL_SECONDS` (60 s by default) and applies the SLA-breach escalation rule ESC-039.

Bulk work, meaning the dataset import and evaluation runs, uses `services/batch.py`. Records are grouped by customer, and different customers are processed in parallel with `BATCH_WORKERS` threads (4 by default). Each customer's complaints are processed in date order, because history, repeat detection and previous-complaint references depend on that customer's earlier complaints; `test_batch.py` proves that the order is kept. The demo import processed **617 complaints in 3,485 s (58.1 minutes)**, as recorded in its `dataset.imported` audit entry, which is about 10.6 complaints per minute with 4 workers. Evaluation run #1 processed 154 cases in 858 s. Throughput grows with `BATCH_WORKERS` up to the vendor's rate limits; the troubleshooting section of `README.md` advises lowering it when AI runs show `rate_limited` errors.

## 35.10 Scalability targets

**Table 35.7 — SRS scalability targets and the current state**

| Target (SRS NFR 2) | Current demo data | How the design supports it | Status |
|---|---|---|---|
| 10,000 complaints | 800 complaints (622 operational) | Indexed, denormalised complaint columns; paginated lists; bounded exports; per-customer history queries; background processing | Implemented, not load-tested (Planned) |
| 100 categories or subcategories | 11 categories and 35 subcategories (46) | The taxonomy is data: `POST /taxonomy/categories` and `/subcategories` with keywords and routing, no code change (`test_new_category_without_code_changes`) | Implemented and Tested at the current size; 100 not tested (Planned) |
| 1,000 knowledge-base documents | 24 documents, 29 versions, 484 chunks | Documents, versions, sections and chunks are rows; retrieval scores only eligible chunks; the snapshot is rebuilt only on change | Implemented, not load-tested (Planned) |

At the current average of about 17 chunks per document version (484 chunks in 29 versions), 1,000 documents would give roughly 17,000 chunks. Their vectors would need about 52 MB of memory (768 float32 values, 3,072 bytes, per chunk). This is a calculation, not a measurement, and it shows that the in-memory index would still fit a single server. BM25 and vector scoring are linear in the number of eligible chunks. Retrieval at 387 eligible chunks takes 2 to 4 ms, but the time at 17,000 chunks has not been measured.

## 35.11 What has not been tested

No load, stress or soak test has been run, and no concurrent-user measurement exists. The scalability targets of 10,000 complaints, 100 categories and subcategories and 1,000 documents are supported by the design described above but not demonstrated; they are **Planned**, together with measuring dashboard and report query times at that scale. The 99% availability target (NFR 5) has not been measured, because the application has not been operated under monitoring; `GET /api/v1/health` reports whether the database is reachable and whether the AI is configured, which is what an uptime monitor would poll (**Planned**). All latency figures in this chapter come from one development machine, with four parallel workers for batch work and one vendor, OpenAI gpt-4.1-mini. A different model, network or degree of parallelism will give different numbers, and the Evaluation page reports p50 and p95 for every new run so they can be re-measured.
