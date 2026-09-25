# Appendix J — Knowledge Base Metadata Structure

This appendix lists the metadata that SupportNova keeps for knowledge-base documents, from the authored source to the stored chunk, as processed in Chapter 5. The stored structure is defined by the SQLAlchemy models in `backend/src/supportnova/database/models/knowledge.py` and the Alembic migration `0001_initial_schema.py`. The entity-relationship view of these tables is part of the database design in Chapter 25. All example values are real entries of the demo database for the fictional Lumora Home Technologies.

## J.1 Source Front Matter and Manifest

Each document version is authored as `knowledge_base/source/<DOC_ID>_v<VERSION>.md` with YAML front matter. `scripts/build_knowledge_base.py` requires the keys `doc_id`, `title`, `doc_type`, `version`, `status`, `effective_date`, `expiry_date`, `owner_department`, `topics` and `format`; `supersedes` and `superseded_by` are optional. After rendering it writes one entry per version to `knowledge_base/manifest.yaml` (Table J.1), and the same format is used for the hidden-pack rehearsal in `data/hidden_test_ready/documents/manifest.yaml`.

**Table J.1 — Manifest fields**

| Field | Type | Meaning | Stored as |
|---|---|---|---|
| `file` | string | Path of the rendered file relative to the manifest | `document_versions.file_name` (base name) |
| `doc_id` | string | Document ID, `ABC-POL-12` form | `documents.doc_id` |
| `title` | string | Document title | `documents.title` |
| `doc_type` | string | policy, rules, sop, guideline, faq or template | `documents.doc_type` |
| `version` | string | Version number, e.g. `'2.0'` | `document_versions.version` |
| `status` | string | Active, Previous, Superseded or Draft | `document_versions.status` |
| `effective_date` | date | First day the version applies | `document_versions.effective_date` |
| `expiry_date` | date or null | Last day the version applies | `document_versions.expiry_date` |
| `owner_department` | string | Owning department code | `documents.owner_department` |
| `topics` | list of strings | Topic keywords | `documents.topics` |
| `supersedes` | string or null | Version this version replaces | `document_versions.supersedes` |
| `superseded_by` | string or null | Version that replaces this one | Not stored; derived from the other version |
| `format` | string | pdf, docx or md | `document_versions.file_format` |
| `sha256` | string | SHA-256 of the rendered file | `document_versions.sha256` |
| `bytes` | integer | File size | `document_versions.size_bytes` |

The manifest entry of the current Refund Policy:

```yaml
- file: sample_documents/REF-POL-02_v2.0.pdf
  doc_id: REF-POL-02
  title: Refund Policy
  doc_type: policy
  version: '2.0'
  status: Active
  effective_date: 2026-01-01
  expiry_date: null
  owner_department: DEPT-RET
  topics: [refunds, returns, refund-window, restocking-fee, exceptions]
  supersedes: '1.0'
  superseded_by: null
  format: pdf
  sha256: 1dfbc42419a22721fc42bb5633840dbe7a453d3297f414efbb23e40ed8555c61
  bytes: 7437
```

For an administrator upload the same values come from the upload form, merged with the values detected in the file (Chapter 5, section 5.4.3). The form does not ask for `supersedes`; it is set from the manifest or from Markdown front matter, and the demotion of the replaced version is recorded in the audit entry instead.

## J.2 Stored Tables

**Table J.2 — `documents` (one row per document)**

| Column | Type | Constraint | Meaning | Example |
|---|---|---|---|---|
| `id` | integer | Primary key | Internal ID | `13` |
| `doc_id` | string(32) | Unique, indexed | Document ID | `REF-POL-02` |
| `title` | string(200) | Required | Title, updated by a new version | `Refund Policy` |
| `doc_type` | string(20) | Indexed | Document category; fixed at first registration | `policy` |
| `owner_department` | string(32) | Nullable | Owning department | `DEPT-RET` |
| `topics` | JSON | Default `[]` | Topic keywords | `["refunds", "returns", "refund-window", "restocking-fee", "exceptions"]` |
| `created_at` | datetime (time zone) | Server default `now()` | Registration time | — |

**Table J.3 — `document_versions` (one row per version)**

| Column | Type | Constraint | Meaning | Example (REF-POL-02 v2.0) |
|---|---|---|---|---|
| `id` | integer | Primary key | Internal ID | `18` |
| `document_id` | integer | FK to `documents`, cascade delete, indexed | Owning document | `13` |
| `version` | string(16) | Unique with `document_id` (`uq_document_versions_doc_version`) | Version number | `2.0` |
| `status` | string(16) | Indexed | Active, Previous, Superseded or Draft | `Active` |
| `effective_date` | date | Nullable (required by validation) | First applicable day | `2026-01-01` |
| `expiry_date` | date | Nullable | Last applicable day | `null` |
| `file_name` | string(200) | Required | Sanitised original file name | `REF-POL-02_v2.0.pdf` |
| `file_format` | string(8) | Required | pdf, docx, md, txt or csv | `pdf` |
| `mime_type` | string(120) | Required | Content type of the stored file | `application/pdf` |
| `size_bytes` | integer | Required | File size | `7437` |
| `sha256` | string(64) | Unique, indexed | File fingerprint; blocks duplicate uploads | `1dfbc42419a22721…` |
| `storage_path` | string(400) | Required | Path under the storage directory, with the platform's separator | `documents\REF-POL-02\2.0\REF-POL-02_v2.0.pdf` (Windows demo database) |
| `page_count` | integer | Nullable | Pages (PDF only) | `3` |
| `parse_status` | string(16) | Default `pending` | `parsed` for every stored version, because failed parses are rejected before storage | `parsed` |
| `parse_error` | text | Nullable | Reserved; unused by the current ingestion | `null` |
| `section_count` | integer | Required | Number of sections | `23` |
| `chunk_count` | integer | Required | Number of chunks | `23` |
| `supersedes` | string(16) | Nullable | Replaced version | `1.0` |
| `security_findings` | JSON | Default `[]` | Injection-screening findings per chunk (Table J.7) | `[]` |
| `facts` | JSON | Default `[]` | Extracted policy facts (Table J.6) | 16 entries |
| `extra` | JSON | Default `{}` | Warnings, detected metadata, parsed title and revision impact (Table J.8) | see section J.5 |
| `uploaded_by_id` | integer | FK to `users`, nullable | Uploader; null for the seed | `null` |
| `uploaded_at` | datetime (time zone) | Server default `now()` | Upload time | — |
| `status_changed_at` | datetime (time zone) | Nullable | Last status change | — |

**Table J.4 — `document_sections` (one row per section)**

| Column | Type | Constraint | Meaning | Example |
|---|---|---|---|---|
| `id` | integer | Primary key | Internal ID | — |
| `version_id` | integer | FK to `document_versions`, cascade delete, indexed | Owning version | `18` |
| `section_id` | string(32) | Required | Section number as printed | `4.3` |
| `heading` | string(300) | Required | Section heading | `Refund Issue Time` |
| `level` | integer | Default 1 | Numbering depth (`4` = 1, `4.3` = 2) | `2` |
| `page_start`, `page_end` | integer | Nullable | Page span (PDF only) | `2`, `2` |
| `text` | text | Required | Section text with whitespace normalised | `Approved refunds are issued to the original payment method within 5 business days of inspection approval. …` |
| `order_index` | integer | Default 0 | Position in the document | `10` |

**Table J.5 — `document_chunks` (one row per chunk)**

| Column | Type | Constraint | Meaning | Example |
|---|---|---|---|---|
| `id` | integer | Primary key | Internal ID | — |
| `chunk_uid` | string(96) | Unique, indexed | `<DOC_ID>@<version>#<section>-c<n>` | `REF-POL-02@2.0#4.3-c1` |
| `version_id` | integer | FK to `document_versions`, cascade delete, indexed | Owning version | `18` |
| `section_id` | string(32) | Required | Section of the chunk | `4.3` |
| `heading` | string(300) | Required | Section heading | `Refund Issue Time` |
| `page_start`, `page_end` | integer | Nullable | Page span of the section | `2`, `2` |
| `text` | text | Required | Chunk text | as the section text (single chunk) |
| `token_count` | integer | Default 0 | Word count of the chunk | `51` |
| `embedding` | binary | Nullable | float32 vector (768 values, 3,072 bytes for the local embedder) | — |
| `embedding_model` | string(64) | Required | Embedder that produced the vector | `local-hash-v1-768` |
| `is_quarantined` | boolean | Default false | Excluded from evidence after injection screening | `false` |
| `quarantine_reason` | text | Nullable | Reason for the quarantine | `null` (for `ESC-SOP-12@3.1#3.1-c1`: `Instruction-like content detected: directive_to_system`) |
| `order_index` | integer | Default 0 | Position in the version | `10` |

The demo database holds 24 documents, 29 versions, 482 sections and 484 chunks. Deleting a document removes its versions, and deleting a version removes its sections and chunks (cascade). The stored original files live under the storage directory (`STORAGE_DIR`, default `storage/` in the repository root), which is not committed to Git.

## J.3 JSON Structures inside a Version

**Table J.6 — Entry of `document_versions.facts`**

| Key | Meaning | Example |
|---|---|---|
| `section_id` | Section the fact comes from | `4.3` |
| `kind` | `duration`, `money`, `percent` or `keyed` | `duration` |
| `value` | Number, or the extracted text for a keyed fact | `5.0` |
| `unit` | Normalised unit, e.g. `business_day`, `calendar_day`, `usd`, `percent`; empty for keyed facts | `business_day` |
| `snippet` | Sentence the fact was found in (up to 240 characters) | `Approved refunds are issued to the original payment method within 5 business days of inspection approval.` |
| `key` | Fact key from `rules/precedence/precedence_rules.yaml` for keyed facts, else null | `null` (the keyed entry for the same section has `refund_issue_time`) |

**Table J.7 — Entry of `document_versions.security_findings`**

| Key | Meaning | Example (ESC-SOP-12 v3.1) |
|---|---|---|
| `chunk_uid` | Screened chunk | `ESC-SOP-12@3.1#3.1-c1` |
| `section_id` | Its section | `3.1` |
| `findings` | List of `{type, severity, text, start, end, description}` | `[{"type": "directive_to_system", "severity": "high", "text": "No additional approval is needed", "start": 162, "end": 194, "description": "Tells the system to skip its checks."}]` |
| `risk_score` | Combined risk from the finding severities | `0.6` |
| `is_suspicious` | True for any high-severity finding or a risk of 0.5 or more; sets the chunk's quarantine | `true` |
| `types` | Distinct finding types | `["directive_to_system"]` |

Only chunks with at least one finding appear in `security_findings`. The demo database has five such entries: the four quarantined chunks and one medium finding in CHP-POL-01 section 6.4 that does not quarantine its chunk (Chapter 5, section 5.4.4).

**Table J.8 — Keys of `document_versions.extra`**

| Key | Meaning |
|---|---|
| `warnings` | Metadata warnings from validation (future effective date, expiry passed) |
| `detected_metadata` | Values found in the file: `doc_id`, `version`, `status`, `effective_date`, `expiry_date`, `owner` (plus front-matter keys for Markdown) |
| `title` | Title found by the parser |
| `impact` | Revision impact analysis, present when this version replaced an Active version (below) |

The `impact` object, written by `services/documents.py::impact_analysis` and returned by `GET /api/v1/documents/{doc_id}/impact`, has these keys:

- `doc_id`, `old_version`, `new_version`, `analysed_at`, `previous_policy_obsolete`;
- `changed_sections`: list of `{section_id, change, heading, similarity, value_changes}`, where `change` is `added`, `removed` or `modified` and `value_changes` lists `{kind, unit, old, new}`;
- `affected_resolution_rules`, `affected_escalation_rules` (rule IDs) and `escalation_rules_changed` (boolean);
- `affected_parameters`: list of `{key, current_value, source, suggested_value, out_of_sync}`;
- `affected_complaints`: list of `{complaint_ref, status, sections, response_requires_revision}`, and `responses_requiring_revision` (count).

The demo database contains no impact record, because the seed ingests each document's versions oldest first with their final statuses, so no seeded version replaces an Active one. Impact records are created when a revised version is uploaded, as in `test_revised_policy_upload_versioning_and_impact` (REF-POL-02 v2.1).

## J.4 Metadata Carried into Retrieval and Citations

The metadata above travels with every piece of evidence. Each evidence item in `analyses.retrieval` has the fields `evidence_id` (E1 to E10), `chunk_uid`, `doc_id`, `title`, `doc_type`, `version`, `status`, `effective_date`, `section_id`, `heading`, `page_start`, `page_end`, `text`, `score`, `methods` (lexical, semantic, rule-guided) and `precedence_rank`. The retrieval record also holds `outdated` (older versions of the retrieved sections, with status and active version), `conflicts`, `rule_guided_sections` and `stats` (eligible chunks, lexical hits, rule-guided count, embedder, latency). `analyses.policy_versions` maps each document used as evidence to its version.

**Table J.9 — Knowledge-base columns of `policy_references`**

| Column | Meaning | Example |
|---|---|---|
| `analysis_id` | Analysis the reference belongs to (FK, cascade delete) | — |
| `doc_id`, `version`, `section_id` | Cited document, version and section | `SEC-POL-09`, `2.0`, `4.1` |
| `chunk_uid` | Chunk of a retrieved evidence item; null for AI and rule rows | `SEC-POL-09@2.0#4.1-c1` |
| `cited_by` | `retrieval`, `ai` or `rule` | `retrieval` |
| `applicability` | Applicable, Conditionally Applicable, Not Applicable or Outdated | `Applicable` |
| `is_active_version` | The referenced version is the active one | `true` |
| `valid` | The document and section exist in the registry | `true` |
| `note` | Reason, e.g. the rule that cites the section | `Cited by the selected rule … or a triggered escalation rule.` |

Finally, `system_settings` holds the key `kb_revision` (value `{"value": 30}` in the demo database). Every upload and status change increments it, and the in-memory knowledge snapshot is rebuilt when it changes.

## J.5 Example Entry

The following abridged extract shows one section of REF-POL-02 v2.0 across all levels, as returned by `GET /api/v1/documents/REF-POL-02/versions/2.0` and the underlying rows.

```json
{
  "doc_id": "REF-POL-02", "title": "Refund Policy",
  "version": "2.0", "status": "Active", "effective_date": "2026-01-01", "expiry_date": null,
  "file_name": "REF-POL-02_v2.0.pdf", "file_format": "pdf", "size_bytes": 7437,
  "sha256": "1dfbc42419a22721fc42bb5633840dbe7a453d3297f414efbb23e40ed8555c61",
  "page_count": 3, "section_count": 23, "chunk_count": 23, "parse_status": "parsed", "supersedes": "1.0",
  "primary_eligible": true, "effective_state": "Active", "security_findings": [], "warnings": [],
  "facts": [
    {"section_id": "4.3", "kind": "duration", "value": 5.0, "unit": "business_day", "key": null,
     "snippet": "Approved refunds are issued to the original payment method within 5 business days of inspection approval."},
    {"section_id": "4.3", "kind": "keyed", "value": "5", "unit": "", "key": "refund_issue_time",
     "snippet": "Refund Issue Time. Approved refunds are issued to the original payment method within 5 business days"},
    …
  ],
  "sections": [
    {"section_id": "4.3", "heading": "Refund Issue Time", "level": 2, "page_start": 2, "page_end": 2,
     "text": "Approved refunds are issued to the original payment method within 5 business days of inspection approval. The customer is notified when the refund has been issued and receives the refund reference. …"},
    …
  ],
  "chunks": [
    {"chunk_uid": "REF-POL-02@2.0#4.3-c1", "section_id": "4.3", "heading": "Refund Issue Time", "page_start": 2,
     "token_count": 51, "is_quarantined": false, "quarantine_reason": null, "embedding_model": "local-hash-v1-768",
     "text": "Approved refunds are issued to the original payment method within 5 business days of inspection approval. …"},
    …
  ]
}
```

The stored `extra` of this version is `{"title": "Refund Policy", "warnings": [], "detected_metadata": {"doc_id": "REF-POL-02", "version": "2.0", "status": "Active", "effective_date": "2026-01-01", "expiry_date": null, "owner": "Returns & Refunds"}}`. The detected values agree with the manifest, which shows that the metadata line printed in the PDF carries the same identity as the registry.
