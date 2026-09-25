# Chapter 5 — Knowledge-Base Processing

This chapter describes how SupportNova turns the approved documents of Lumora Home Technologies into traceable, versioned evidence: how documents are uploaded and validated, how PDF and DOCX files are parsed into numbered sections and chunks, which metadata is kept, how versions and conflicts are controlled, and how the resulting index is searched for every complaint. Chapter 9 continues from the retrieved evidence to the prompt and to the Python checks that verify every citation.

## 5.1 Purpose

The Knowledge Base is the set of approved Lumora documents — policies, rules, standard operating procedures (SOPs), guidelines, FAQs and templates — that SupportNova may use as evidence. The GenAI Complaint Intelligence Pipeline (Pipeline 1) may cite only sections of these documents, and the Python Ground-Truth Validation Pipeline (Pipeline 2) resolves every citation against the same registry of documents, versions and sections. The Knowledge Base gives evidence; the Complaint Resolution Rule Matrix gives decision criteria. The two are linked by policy references of the form `DOC-ID:section` that every rule carries (for example `RPL-POL-03:3.1` in rule RES-PRD-DOA-01). The resolution and escalation rules of the baseline Rule Matrix (`rules/*.yaml`) contain 145 distinct policy references in 18 documents. Run against these rules and the active sections of the demo database, the Rule Matrix integrity check (`backend/src/supportnova/rule_engine/integrity.py`, also run by `POST /api/v1/rules/validate`) finds no reference missing from the Knowledge Base.

Knowledge-base processing implements SRS Steps 2 to 7 (knowledge-base creation, mandatory PDF and DOCX input, document validation, parsing, chunking and policy version control), Steps 25 and 26 (policy retrieval with source traceability and applicability), functional requirements vi to x, the Hidden Policy Update and Contradictory Policy challenges of SRS section 1.8 (items 4 and 10), and the Knowledge-Base Dataset deliverable. In the demo database the Knowledge Base holds 24 documents with 29 versions, 482 sections and 484 chunks. Seeded documents and administrator uploads pass through the same ingestion function, and a change takes effect for the next complaint without a restart.

Figure 5.1 shows the lifecycle of a document, from its Markdown source in the repository to its use as evidence and its eventual revision.

![Figure 5.1 — Knowledge-base lifecycle in SupportNova](diagrams/pipelines/fig-05-01-kb-lifecycle.svg)
*Figure 5.1 — Knowledge-base lifecycle in SupportNova*

The processing code is split into the packages that the SRS source-code layout names (`document_processing/`, `knowledge_base/`, `security/`). Table 5.1 lists where each step lives.

**Table 5.1 — Knowledge-base modules**

| Module | Responsibility |
|---|---|
| `backend/src/supportnova/services/documents.py` | Ingestion (`ingest_document`), status changes, revision impact analysis, bootstrap from the manifest |
| `backend/src/supportnova/security/files.py` | File validation: extension and signature, size, empty file, executables, DOCX archive checks |
| `backend/src/supportnova/document_processing/parsers.py` | PDF, DOCX, Markdown, TXT and CSV parsing into sections; metadata detection |
| `backend/src/supportnova/document_processing/validation.py` | Metadata validation and version ordering |
| `backend/src/supportnova/document_processing/chunking.py` | Section-aware chunking with traceable chunk IDs |
| `backend/src/supportnova/document_processing/facts.py` | Numeric policy facts and section-by-section version diff |
| `backend/src/supportnova/security/injection.py` | Instruction screening of every chunk (quarantine) |
| `backend/src/supportnova/knowledge_base/` | Embeddings, BM25 index, knowledge snapshot, conflicts, hybrid retrieval |
| `backend/src/supportnova/api/v1/knowledge.py` | REST endpoints for documents, versions, impact, search, conflicts and statistics |
| `frontend/src/pages/Knowledge.tsx`, `DocumentDetail.tsx`, `components/knowledge/UploadDocumentDialog.tsx` | Knowledge base page, document page and upload dialog |

## 5.2 Supported Documents

### 5.2.1 The Lumora Knowledge Base

Lumora Home Technologies is fictional, and so are all its documents. The Knowledge Base contains 14 policies (16 versions), 2 rules documents, 3 SOPs (5 versions), 2 guidelines, 2 FAQs (3 versions) and 1 template, rendered as 13 PDF, 15 DOCX and 1 Markdown file. Each version has a status: 23 are Active, 3 Previous, 2 Superseded and 1 Draft. Table 5.2 lists every document as registered in `knowledge_base/manifest.yaml`; the section and chunk counts are those of the current version in the demo database.

**Table 5.2 — Lumora knowledge-base documents and versions**

| Document ID | Title | Type | Owner | Versions (status, format, effective period) | Sections / chunks |
|---|---|---|---|---|---|
| BIL-POL-05 | Billing and Payments Policy | policy | DEPT-BIL | 2.0 Active, PDF, from 2025-11-01 | 16 / 16 |
| CAN-POL-06 | Cancellation Policy | policy | DEPT-BIL | 1.2 Active, DOCX, from 2025-09-01 | 13 / 13 |
| CHP-POL-01 | Complaint Handling Policy | policy | DEPT-CRL | 3.0 Active, PDF, from 2026-01-15 | 33 / 33 |
| CHP-SOP-13 | Complaint Handling Standard Operating Procedure | sop | DEPT-CRL | 2.0 Active, DOCX, from 2026-01-15 | 17 / 17 |
| CMP-GDL-19 | Compliance Guidelines | guideline | DEPT-CMP | 1.1 Active, PDF, from 2025-12-01 | 17 / 17 |
| CPN-POL-11 | Compensation and Goodwill Policy | policy | DEPT-CRL | 1.3 Active, DOCX, from 2026-01-01 | 14 / 14 |
| DEL-POL-04 | Delivery and Shipping Policy | policy | DEPT-LOG | 2.0 Previous, DOCX, 2025-01-01 to 2026-01-09; 3.0 Active, PDF, from 2026-01-10 | 20 / 20 |
| ESC-SOP-12 | Escalation Procedure | sop | DEPT-MGT | 3.0 Previous, DOCX, 2025-01-01 to 2025-12-31; 3.1 Active, PDF, from 2026-01-01; 3.2 Draft, DOCX, from 2026-12-01 | 27 / 27 |
| FAQ-BIL-17 | Billing and Refunds FAQ | faq | DEPT-BIL | 1.0 Previous, DOCX, 2024-06-01 to 2026-01-31; 2.0 Active, MD, from 2026-02-01 | 10 / 10 |
| FAQ-GEN-16 | Customer FAQ | faq | DEPT-CRL | 5.0 Active, DOCX, from 2026-02-15 | 20 / 20 |
| INS-POL-24 | Professional Installation Service Policy | policy | DEPT-CRL | 1.0 Active, PDF, from 2025-09-01 | 13 / 13 |
| PRV-POL-08 | Privacy and Data Protection Policy | policy | DEPT-CMP | 4.0 Active, PDF, from 2026-03-01 | 20 / 20 |
| REF-POL-02 | Refund Policy | policy | DEPT-RET | 1.0 Superseded, DOCX, 2024-03-01 to 2025-12-31; 2.0 Active, PDF, from 2026-01-01 | 23 / 23 |
| RET-SOP-23 | Legacy Returns Handling SOP | sop | DEPT-RET | 1.4 Superseded, DOCX, 2023-05-01 to 2025-06-30 | 5 / 5 |
| RPL-POL-03 | Replacement and Returns Policy | policy | DEPT-RET | 2.1 Active, DOCX, from 2026-02-01 | 17 / 17 |
| RTE-RUL-14 | Department Routing Rules | rules | DEPT-MGT | 2.0 Active, PDF, from 2026-01-01 | 9 / 11 |
| SAF-POL-10 | Product Safety Policy | policy | DEPT-SAF | 2.0 Active, PDF, from 2025-08-15 | 18 / 18 |
| SEC-POL-09 | Account Security Policy | policy | DEPT-SEC | 2.0 Active, DOCX, from 2025-10-01 | 16 / 16 |
| SLA-RUL-15 | Service Level Rules | rules | DEPT-MGT | 2.0 Active, PDF, from 2026-01-01 | 18 / 18 |
| STF-POL-21 | Staff Conduct and Service Standards | policy | DEPT-CRL | 1.0 Active, PDF, from 2025-06-01 | 13 / 13 |
| SUB-POL-22 | Subscription Services Policy | policy | DEPT-BIL | 2.0 Active, DOCX, from 2025-10-15 | 11 / 11 |
| TEC-GDL-20 | Product Support Guidelines | guideline | DEPT-TEC | 3.0 Active, DOCX, from 2025-11-15 | 14 / 14 |
| TPL-COM-18 | Customer Communication Templates | template | DEPT-CRL | 2.0 Active, DOCX, from 2026-01-15 | 9 / 9 |
| WAR-POL-07 | Warranty Policy | policy | DEPT-WAR | 2.0 Active, PDF, from 2025-07-01 | 18 / 18 |

### 5.2.2 Coverage of the SRS document types

SRS section 1.2 lists fourteen kinds of company document that administrators must be able to upload, and SRS Step 2 lists thirteen documents the knowledge base must contain. Table 5.3 maps both lists to the Lumora documents; every item is covered. The SRS minimum of 20 policy or SOP documents is exceeded (24 documents), which `tests/backend/unit/test_documents_exports.py::test_knowledge_base_meets_srs_minimums` asserts together with the presence of PDF and DOCX files and of Active and outdated versions.

**Table 5.3 — SRS document types mapped to Lumora documents**

| SRS document type (section 1.2 / Step 2) | Lumora document(s) |
|---|---|
| Customer-service policies / complaint policy | CHP-POL-01; also STF-POL-21, CPN-POL-11, INS-POL-24 |
| Refund policies | REF-POL-02 |
| Replacement policies | RPL-POL-03 |
| Cancellation policy | CAN-POL-06 (subscriptions in SUB-POL-22) |
| Warranty policies | WAR-POL-07 |
| Billing procedures / billing policy | BIL-POL-05 |
| Delivery policies | DEL-POL-04 |
| Privacy policy | PRV-POL-08 (account security in SEC-POL-09) |
| Service Level Agreements / service-level rules | SLA-RUL-15 |
| Escalation procedures | ESC-SOP-12 |
| Complaint-handling SOPs / complaint SOP | CHP-SOP-13 (legacy RET-SOP-23, Superseded) |
| Product-support guidelines | TEC-GDL-20 |
| Department-routing rules | RTE-RUL-14 |
| Frequently Asked Questions | FAQ-GEN-16, FAQ-BIL-17 |
| Compliance guidelines | CMP-GDL-19 |
| Response templates | TPL-COM-18 |
| (Safety category, beyond the SRS list) | SAF-POL-10 |

### 5.2.3 Authoring and rendering

Every document version is written once as Markdown with YAML front matter in `knowledge_base/source/<DOC_ID>_v<VERSION>.md` and rendered by `scripts/build_knowledge_base.py` to the format named in its front matter: PDF with fpdf2, DOCX with python-docx, or Markdown copied as-is. The script checks each source against `knowledge_base/kb_spec.yaml`, which pins the section IDs and headings that the Rule Matrix cites and the facts each section must state (for example that REF-POL-02 section 4.3 gives "5 business days of inspection approval"). It then re-opens every rendered file to confirm that it contains text and that every section heading survived rendering; DOCX headings must use the Heading 1 and Heading 2 styles. The script writes `manifest.yaml` with the metadata, SHA-256 and size of each file.

The renderer reproduces the features that make real documents hard to parse. Each PDF page carries a running header such as `REF-POL-02 v2.0 - Refund Policy` and a footer `Page 1 of 3`. Tables such as the RTE-RUL-14 routing table are drawn as real tables. DOCX files store the document ID, version, status and effective date in their core properties, and a document that is not Active shows a visible notice (`PREVIOUS VERSION`, `SUPERSEDED` or `DRAFT - NOT FOR OPERATIONAL USE`), with the status also added to its running header.

### 5.2.4 Deliberate test content

Some content is deliberately inconsistent, so that the precedence rules can be demonstrated on real documents. FAQ-GEN-16 v5.0 answer 2.2 says refunds are issued within 3 business days of receiving a return, which contradicts REF-POL-02 section 4.3 (5 business days after inspection approval); this is the one conflict between Active documents (section 5.12). The outdated versions carry further conflicts: REF-POL-02 v1.0 has a 60-day refund window, FAQ-BIL-17 v1.0 says duplicate charges are reversed immediately, DEL-POL-04 v2.0 gives a USD 15 delay credit, ESC-SOP-12 v3.0 and the Draft v3.2 use other repeat and high-value thresholds, and RET-SOP-23 v1.4 lets agents grant a USD 50 goodwill credit without approval. The complaint dataset cites these documents in its contradictory-policy cases (Chapter 6).

Two further sets of documents are kept outside the loaded Knowledge Base. `knowledge_base/security_samples/MAL-DOC-99_v1.0.docx` is a labelled security fixture that imitates a policy addendum and embeds instructions aimed at automated systems (section 5.4.4). `data/hidden_test_ready/documents/` holds a hidden-pack rehearsal: REF-POL-02 v2.1 (PDF, effective 2026-09-15), a revised Refund Policy, and ENV-POL-25 v1.0 (DOCX), a new E-Waste Take-Back and Recycling Policy for a new category.

### 5.2.5 Supported file formats

`parse_document` in `parsers.py` accepts PDF and DOCX, the formats the SRS makes mandatory, and Markdown, TXT and CSV, the optional ones. PDF and DOCX parsing is Implemented and Tested on the real documents (`test_parse_sections_from_real_documents[pdf]` and `[docx]`). Markdown is used by FAQ-BIL-17 v2.0 and by the end-to-end test `tests/e2e/test_full_chain.py::test_document_upload_and_policy_versioning_journey`. TXT and CSV parsing is Implemented, but no Lumora document uses these formats and no automated test covers them.

## 5.3 Document Upload

### 5.3.1 Upload dialog

Administrators open **Knowledge base → Upload document**, or **Upload new version** on a document page, which pre-fills the document ID. The dialog (`UploadDocumentDialog.tsx`) accepts a dropped or browsed file and first checks the extension (PDF, DOCX, TXT, Markdown or CSV) and the size limit published by `GET /api/v1/config/public`. It then sends the file to `POST /api/v1/documents/preview`, which parses it without storing anything and returns the detected title, page count, metadata and section outline. The dialog pre-fills the document ID, version, status, effective and expiry dates, owner department and topics from that metadata, marks each pre-filled field with "Pre-filled from the file - check it.", and shows the section outline with page numbers beside the form.

The form repeats the server's rules on the client — document ID pattern `ABC-POL-12`, numeric version, required effective date, expiry date not before the effective date — and explains the consequences for version control before anything is saved. When the ID matches an existing document it shows "New version of REF-POL-02" and states that the current Active version will become Previous. It disables **Upload** when the version already exists, and warns when a newer Active version exists. Nothing is stored until the user chooses **Upload**, which sends the file and the reviewed metadata to `POST /api/v1/documents`. The confirmation message reports the number of sections and chunks, any quarantined chunks, validation warnings and whether a revision impact analysis is ready.

### 5.3.2 API

All knowledge-base endpoints are served under `/api/v1` by `api/v1/knowledge.py` (Table 5.4). Uploading, previewing and changing a status require the `knowledge:manage` permission, which only the Administrator role holds. Reading requires `knowledge:read`, held by the Support Agent, Reviewer, Support Manager and Administrator roles; customers have no access to the Knowledge Base.

**Table 5.4 — Knowledge-base endpoints**

| Method and path | Permission | Purpose |
|---|---|---|
| `POST /documents/preview` | knowledge:manage | Parse without saving; detected metadata and section outline |
| `POST /documents` | knowledge:manage | Upload a file with metadata (multipart form) |
| `GET /documents` | knowledge:read | Documents with versions, statuses and quarantine counts |
| `GET /documents/{doc_id}` | knowledge:read | One document and its versions |
| `GET /documents/{doc_id}/versions/{version}` | knowledge:read | Sections, chunks, facts, findings and impact of one version |
| `POST /documents/{doc_id}/versions/{version}/status` | knowledge:manage | Change the status of a version (audited) |
| `GET /documents/{doc_id}/versions/{version}/download` | knowledge:read | Original stored file |
| `GET /documents/{doc_id}/impact` | knowledge:read | Revision impact analyses of the document |
| `GET /knowledge/search` | knowledge:read | Evidence search (retrieval playground) |
| `GET /knowledge/conflicts` | knowledge:read | Precedence-resolved conflicts and precedence rules |
| `GET /knowledge/stats` | knowledge:read | Counts by status and format, chunks, quarantined chunks, revision |

### 5.3.3 Seeding and dry-run scanning

On the first start, when the `documents` table is empty, `services/seed.py` calls `bootstrap_knowledge_base`. It reads `knowledge_base/manifest.yaml`, sorts the entries by document and version, and passes each file with its manifest metadata to the same `ingest_document` function that serves administrator uploads. Uploading in version order lets the normal version control run, and the statuses written in the manifest are then restored exactly (for example DEL-POL-04 v2.0 stays Previous instead of being moved on to Superseded). Files whose SHA-256 is already stored are skipped, so the bootstrap can be repeated safely.

The Adversarial Lab offers a dry run: `POST /api/v1/lab/document-scan` (`services/lab.py::document_scan`) parses a document, screens each section for instructions and reports which sections would be quarantined, without adding the document to the Knowledge Base.

## 5.4 File Validation

An upload passes a fixed sequence of checks, and nothing is written to the database or to storage until the file checks, the parse and the metadata checks have all passed. A failure returns HTTP 422 (`ValidationFailed` or `DocumentProcessingError`) or 409 (`Conflict`) with a readable message, and field-level errors are shown next to the matching form fields. Table 5.5 lists the checks in execution order.

**Table 5.5 — Validation checks on upload**

| Check | Rule applied | On failure | Evidence |
|---|---|---|---|
| File name | Directories and unsafe characters stripped, at most 120 characters (`safe_filename`) | Name sanitised | `test_upload_validation_rejects_executables_and_mismatches` |
| Empty file | Zero bytes rejected | 422 | `test_upload_size_edge` |
| File size | At most `MAX_UPLOAD_MB` (default 15 MB) | 422 | `test_upload_size_edge` (exactly at and one byte over the limit) |
| Executables | 22 blocked extensions and executable signatures (`MZ`, ELF, Mach-O, `#!`) | 422 | `test_executable_upload_rejected` |
| File type | Extension in pdf, docx, txt, md, csv; PDF must start with `%PDF-` | 422 | `test_upload_validation_rejects_executables_and_mismatches` |
| DOCX integrity | Valid ZIP; at most 2,000 entries and 120 MB uncompressed; `word/document.xml` and `[Content_Types].xml` present; no macros or embedded binaries | 422 | Implemented (no dedicated test) |
| Text files | No NUL bytes; decodable as UTF-8 or cp1252 | 422 | Implemented (no dedicated test) |
| Duplicate document | SHA-256 of the file already stored | 409 | Implemented (no dedicated test) |
| Parsing compatibility | Corrupted, password-protected or text-less PDF; unreadable or empty DOCX, Markdown or CSV | 422 | `test_corrupted_document_is_rejected_cleanly` |
| Document ID | Required; pattern `^[A-Z]{2,5}-[A-Z]{2,5}-\d{2,3}$` | 422, field error | Implemented |
| Title | Required | 422, field error | Implemented |
| Document category | One of policy, rules, sop, guideline, faq, template; inferred from the ID when blank; must match the type already registered | 422, field error | Implemented |
| Version | Numeric, up to three parts (`2.0`, `3.1`); unique per document | 422 or 409 | `test_metadata_validation_and_version_order` |
| Status | Active, Previous, Superseded or Draft | 422, field error | `test_metadata_validation_and_version_order` |
| Effective and expiry dates | Effective date required and valid; expiry date valid and not before the effective date | 422, field error | Implemented |
| Date plausibility | Active with a future effective date, or with a past expiry date | Warning stored with the version | Implemented |
| Version order | An older version cannot be uploaded as Active when a newer Active version exists | 422 | Implemented |
| Readable content | At least one section with text | 422 | Implemented |
| Embedded instructions | Every chunk screened; suspicious chunks quarantined | Chunk excluded from evidence | `test_malicious_document_sections_flagged`, `test_malicious_document_upload_is_quarantined` |

### 5.4.1 Type, integrity and size

`validate_upload` in `backend/src/supportnova/security/files.py` checks the type in two ways. The extension must be on the allow-list, and the content must agree with it: a PDF must start with `%PDF-`, a DOCX must be a valid Office archive, and TXT, Markdown and CSV files must contain text rather than binary data. A file named `policy.pdf` that begins with the Windows executable signature `MZ` is therefore rejected even though its extension is allowed (`tests/backend/api/test_security_api.py::test_executable_upload_rejected`). The DOCX archive check also guards against decompression bombs (at most 2,000 entries and 120 MB uncompressed) and rejects documents that contain a VBA macro project or embedded `.bin`, `.exe` or `.dll` parts. The size limit comes from the `MAX_UPLOAD_MB` setting, 15 MB by default in `core/config.py` and `.env.example`, and the boundary is tested at exactly the limit and one byte over (`tests/backend/api/test_boundaries.py::test_upload_size_edge`).

### 5.4.2 Duplicates and parsing compatibility

The SHA-256 of the file identifies duplicates. `ingest_document` rejects a file whose hash is already stored with 409 "This exact document has already been uploaded (duplicate file)", and a unique index on `document_versions.sha256` enforces the same rule in the database. A different file with an existing document ID and version is also rejected with 409, because the pair (document, version) is unique.

Parsing compatibility is established by parsing. A PDF that PyMuPDF cannot open, a password-protected PDF and a PDF without extractable text (a scanned image, since no OCR is performed) are rejected with a message that names the reason, as are DOCX files that python-docx cannot open and documents that contain no text. `test_corrupted_document_is_rejected_cleanly` checks that a truncated PDF raises a clean application error rather than an unhandled exception.

### 5.4.3 Metadata requirements

Metadata comes from two sources that are merged before validation: the values detected in the document (section 5.8) and the values in the upload form. A non-empty form value overrides a detected one, and the parsed title fills in a missing title. `validate_metadata` in `document_processing/validation.py` then applies the rules in Table 5.5 and reports all failures at once as field-level details. The document category is taken from the form or inferred from the middle part of the ID (POL → policy, RUL → rules, SOP → sop, GDL → guideline, FAQ → faq, TPL or COM → template), and it must match the type under which the document ID is already registered. Two situations produce warnings instead of errors, because the version may still be stored: an Active version whose effective date is in the future ("the document will not be used as primary evidence until then") and an Active version whose expiry date has passed ("will be treated as Outdated"). Warnings are saved in `document_versions.extra.warnings` and shown after the upload. `test_metadata_validation_and_version_order` checks that an invalid version and status are reported as field errors, that a valid record for REF-POL-02 v2.1 is accepted, and that versions sort numerically (2.10 > 2.9 > 2.0).

### 5.4.4 Security checks and quarantine

Uploaded documents are untrusted input in the same way as complaints (SRS Step 50). Each chunk produced by the chunker (section 5.7) is scanned by `security/injection.py::scan`, which applies 28 regular-expression patterns in 13 finding types — instruction overrides, fake system or administrator messages, role hijacking, output manipulation, concealment from humans, data exfiltration, directives to approve outcomes and others — and decodes base64 payloads to scan their content. A chunk with a high-severity finding, or a combined risk of 0.5 or more, is stored with `is_quarantined = true` and a reason such as "Instruction-like content detected: directive_to_system". A quarantined chunk is kept for audit and shown on the document page but is never eligible as evidence (section 5.10). All findings are stored in `document_versions.security_findings`, and the audit entry `document.uploaded` records how many chunks were quarantined.

The security fixture MAL-DOC-99 v1.0 shows the effect. Its DOCX has twelve sections. Sections 4.1, 4.2, 5 and 6.2 are flagged, including section 6.2, whose instruction is written in near-invisible white 1-point text: python-docx reads the text regardless of its formatting. The remaining eight sections stay usable (`test_malicious_document_sections_flagged`). Through the API, the Adversarial Lab scan of the same file reports quarantined sections (`tests/backend/integration/test_defects_and_live_changes.py::test_malicious_document_upload_is_quarantined`).

The screener also produces findings on legitimate documents, and this is recorded as a limitation. In the loaded Knowledge Base, 4 of 484 chunks are quarantined. One is RET-SOP-23 v1.4 section 3 ("issue a USD 50 goodwill credit without approval"), deliberately outdated text in a Superseded document. The other three are section 3.1, "No Escalation", of all three ESC-SOP-12 versions, whose sentence "No additional approval is needed" matches the pattern for instructions to skip checks. This is a false positive in the Active Escalation Procedure: the definition of the No Escalation level cannot be cited as evidence. No Rule Matrix rule cites `ESC-SOP-12:3.1`, so no rule-required evidence is lost. A fifth finding, a medium-severity "already approved" in CHP-POL-01 section 6.4 (risk 0.3), is recorded but does not quarantine the chunk; the Knowledge base page shows it as "1 flagged".

## 5.5 PDF and DOCX Parsing

Every parser returns a `ParsedDocument`: the title, format, page count, ordered sections, full text, detected metadata and, for Markdown, the front matter. Parsing is deterministic Python; no GenAI model is involved. Table 5.6 summarises how each format signals structure.

**Table 5.6 — Parser behaviour by format**

| Format | Library | Heading signal | Tables | Metadata sources | Page numbers |
|---|---|---|---|---|---|
| PDF | PyMuPDF 1.28.2 | Bold spans or font at least 1.5 pt above body size | `find_tables`, one line per row | Text of the document | Yes |
| DOCX | python-docx 1.2.0 | Heading styles or all-bold paragraphs | One line per row, merged cells collapsed | Text; core properties (subject, comments) | No |
| Markdown | PyYAML for front matter | `##` and `###` headings | Kept as text lines | Front matter; text | No |
| TXT | — | Numbering alone | — | Text | No |
| CSV | Python `csv` | One section per row | Row values as `column: value` | — | No |

### 5.5.1 PDF parsing

`parse_pdf` opens the file with PyMuPDF and reads each page as text spans (`page.get_text("dict")`), which keep the font size and weight that plain text extraction loses. Each line gets the page number, the largest span size rounded to 0.1 pt, a bold flag (font flag 16 or "bold" in the font name, true only when every span is bold) and whether it lies in the top or bottom 10 % of the page (`HEADER_FOOTER_BAND = 0.1`). The body font size is the size that covers the most characters. The first line on page 1 that is at least 4 pt larger than the body becomes the title, and a line is a heading candidate when it is bold or at least 1.5 pt larger than the body. In the Lumora PDFs body text is 10 pt, section headings are bold 13 pt and subsection headings bold 11 pt, so both heading levels are recognised.

### 5.5.2 Running headers, footers and tables

Two parts of a PDF page are not body text: running headers and footers, and tables whose cells PyMuPDF reports as separate lines. Only a line that lies inside the top or bottom band and repeats on at least 60 % of the pages (and on at least two pages) counts as a running header or footer and is removed. Page-number footers such as `Page 2 of 3`, `2 / 3` or `- 2 -` are removed wherever they occur. Tables are found with `page.find_tables()`: any line whose centre falls inside a table's bounding box is replaced by the table's rows, emitted once, with the cells joined as `cell | cell | cell` and empty cells written as `-`. Table detection is best effort, and a page on which it fails is read as plain lines.

These rules come from a defect found during live testing. The earlier logic treated text that repeated across pages as a running header or footer, so repeated body text — such as a department name that recurs in a table — was removed, and the RTE-RUL-14 routing table lost its department cells. The damage mattered because the parsed routing table is also the text that the analysis prompt receives as reference data (Chapter 9). The fix restricted header and footer removal to the page bands and emitted tables row by row. The regression test `tests/backend/unit/test_documents_exports.py::test_pdf_keeps_repeated_body_text_and_reads_tables_by_row` builds a three-page PDF with a running header, `Page N of 3` footers, a body sentence repeated on every page and a routing-table row. It asserts that the header and footers are gone, that the body sentence survives three times, that the row is read as `RTE-004 | BIL-DUP Duplicate Charge | Billing Operations (DEPT-BIL)`, and that sections 1, 2 and 3 are found.

### 5.5.3 DOCX parsing

`parse_docx` walks the document body in order, so paragraphs and tables stay interleaved as in the original. Empty paragraphs are skipped, a paragraph in the Title style becomes the title, and a paragraph in a Heading style, or one whose runs are all bold, is a heading candidate. List paragraphs are prefixed with `- ` so that the chunker keeps list items apart. Each table row becomes one line with its cells joined by ` | `; repeated adjacent cells, which python-docx returns for horizontally merged cells, are collapsed. Running headers and footers are not a problem in DOCX, because they belong to the section header and footer parts, which the body walk does not read. Metadata is detected in the text and read from the core properties: the build script writes `version=…;status=…;effective=…` into the comments property and the document ID into the subject, and `parse_docx` accepts the subject only if it matches the document-ID pattern.

### 5.5.4 Markdown, TXT and CSV parsing

`parse_text` decodes UTF-8 (falling back to cp1252), parses the YAML front matter with `yaml.safe_load` (no code execution) and takes the document ID, title, type, version, status, dates, owner, topics and supersedes from it. The front-matter title, or else the first `#` heading, becomes the title, and headings of level two and below (`##`, `###`) are heading candidates. A plain-text file without Markdown headings is split on its numbering alone. `parse_csv` turns each data row into a section whose heading is the first column and whose text lists the remaining columns as `column: value` pairs.

## 5.6 Section Extraction

Section extraction turns the parsed lines into numbered sections, because the section number is the unit that rules, citations and validators refer to. A line starts a new section when it matches `NUMBERED_HEADING` — one to four levels of numbering followed by a heading that starts with a capital letter or digit, such as `4.3 Refund Issue Time` — and the format marks it as a heading (section 5.5). A line that ends with `.`, `,`, `;` or `:` is never a heading, which stops numbered sentences in the body from being mistaken for headings. The level is the number of numeric parts (`4` is level 1, `4.3` level 2). Text is added to the current section until the next heading. For PDFs the page on which the section starts and the page on which its last line appears are recorded. The text before the first heading — the title block and the metadata line `Document ID: REF-POL-02 | Version: 2.0 | …` — is used for metadata detection and is not stored as a section.

Documents without numbered headings are handled by a fallback that splits at heading-styled lines of up to 100 characters, numbers the sections 1 to n and places any leading text in a section `1 Introduction`. This keeps unseen documents from the hidden evaluation pack usable even when they do not follow the Lumora numbering convention.

Section numbering is stable by design. `kb_spec.yaml` states that the section IDs "are cited by the Rule Matrix … and must not change", the build verifies them, and `test_parse_sections_from_real_documents[pdf]` and `[docx]` check that every parsed section of an Active PDF and DOCX document has an ID and a heading and that the document ID is detected. The demo database holds 482 sections in `document_sections`, each with its section ID, heading, level, page span, text and position.

## 5.7 Chunking

A chunk is the unit that retrieval ranks and the GenAI model reads. `chunk_sections` in `document_processing/chunking.py` never lets a chunk cross a section boundary, so a chunk always belongs to exactly one section. Within a section the text is split into paragraphs at blank lines and before list items. Paragraphs are packed into a chunk until the next would take it past `max_words = 180`, and a single paragraph longer than 180 words is split at sentence boundaries. Every chunk keeps the section ID, heading, page span and position, and its size is stored in `token_count`, which counts words rather than model tokens.

Each chunk is identified by a chunk UID built from its origin: `<DOC_ID>@<version>#<section>-c<n>`. The chunk `REF-POL-02@2.0#4.3-c1`, for example, is the first chunk of section 4.3, Refund Issue Time, of Refund Policy version 2.0. The UID is unique in the database (unique index on `document_chunks.chunk_uid`), readable by people and resolvable by code, so any piece of evidence can be traced to the exact document version, section and stored file without a lookup table. The same UID appears in the retrieval record of every analysis and in the `policy_references` rows written for retrieved evidence (section 5.11).

The 482 sections produce 484 chunks: a median of 49 words, a mean of 50.1 and a range of 7 to 538 words. Only one chunk exceeds the 180-word target: `RTE-RUL-14@2.0#3-c2`, the routing table, at 538 words. Its rows have no sentence punctuation, so the sentence splitter cannot divide them. The limit is therefore a target rather than a guarantee. For the routing table this has no effect on the analysis, because the routing policy reaches the prompt as reference data (Chapter 9).

## 5.8 Metadata

SupportNova keeps metadata at four levels — document, version, section and chunk — and every level carries the fields that SRS Steps 5 and 6 require. Table 5.7 maps the SRS items to the stored fields; Appendix J gives the complete field list with an example.

**Table 5.7 — Metadata required by the SRS and where it is stored**

| SRS item | Stored field(s) | Level | Notes |
|---|---|---|---|
| Document ID | `documents.doc_id` | Document | Unique, e.g. REF-POL-02 |
| Document title | `documents.title` | Document | From the form or the parsed title |
| Document category | `documents.doc_type` | Document | Sets the precedence rank |
| Owner | `documents.owner_department` | Document | Department code, e.g. DEPT-RET |
| Version | `document_versions.version` | Version | Unique per document |
| Status | `document_versions.status` | Version | Active, Previous, Superseded, Draft |
| Effective date | `document_versions.effective_date` | Version | Required |
| Expiry date | `document_versions.expiry_date` | Version | Optional |
| Source reference | `storage_path`, `sha256`, `file_name` | Version | Original file, downloadable |
| Section | `document_sections.section_id`, `level` | Section | Numbering preserved |
| Heading | `document_sections.heading`, `document_chunks.heading` | Section, chunk | |
| Page number where available | `page_start`, `page_end` | Section, chunk | PDF only; null for DOCX and Markdown |
| Chunk ID | `document_chunks.chunk_uid` | Chunk | `DOC@version#section-cN` |

Metadata detection (`parsers.py::detect_metadata`) looks in the first 3,000 characters of the text for `Document ID`, `Version`, `Status`, `Effective date`, `Expiry date` and `Owner`. The Lumora documents state these on one line under the title, so the preview can pre-fill the upload form. The detected values are also kept in `document_versions.extra.detected_metadata`, so the values found in the file can be compared later with those entered on upload.

Each version also stores extracted policy facts (`facts.py::extract_facts`) in `document_versions.facts`. These are the durations ("30 calendar days"), money amounts and percentages stated in each section, plus keyed facts defined in `rules/precedence/precedence_rules.yaml` — refund issue time, refund window, delay credit, agent compensation limit and duplicate-charge reversal. REF-POL-02 v2.0 has 16 extracted facts, shown on its **Extracted facts** tab. Facts serve two purposes: detecting conflicts between Active documents (section 5.12) and finding the numbers that change between versions (section 5.9.3).

## 5.9 Version Control

### 5.9.1 Statuses and effective dates

Every version has one of the four statuses that SRS Step 7 names. Whether a version may be used as evidence also depends on the complaint's date, so SupportNova derives an effective state from the stored status and the dates (`knowledge_base/store.py`, `VersionInfo.effective_status` and `ChunkEntry.primary_eligible`). A chunk is primary evidence only when its version is Active, already effective and not expired on the complaint date, and the chunk is not quarantined — precedence rule PRC-001. Every other version is at most outdated context and is never the primary basis of a decision (PRC-004, implementing CHP-POL-01 section 10.4 and the SRS rule that outdated policies must not be the primary basis of a resolution). Table 5.8 summarises the statuses; Figure 5.2 shows the transitions.

**Table 5.8 — Version statuses and their use**

| Status or state | Meaning | Use as evidence | Demo count |
|---|---|---|---|
| Active, in effect | Approved and within its effective and expiry dates on the complaint date | Primary evidence (PRC-001) | 23 versions |
| Active, pending | Approved, effective date after the complaint date | Not used until effective | 0 |
| Active, expired | Approved, expiry date before the complaint date | Outdated context only | 0 |
| Previous | Replaced by a newer Active version | Outdated context only (PRC-004) | 3 (DEL-POL-04 2.0, ESC-SOP-12 3.0, FAQ-BIL-17 1.0) |
| Superseded | Formally replaced | Outdated context only (PRC-004) | 2 (REF-POL-02 1.0, RET-SOP-23 1.4) |
| Draft | Not approved | Never evidence; searchable for review | 1 (ESC-SOP-12 3.2) |

![Figure 5.2 — Version-control states of a document version](diagrams/pipelines/fig-05-02-version-control-states.svg)
*Figure 5.2 — Version-control states of a document version*

### 5.9.2 Transitions on upload and status change

When a version is uploaded as Active, `ingest_document` moves the current Active version of the same document to Previous and any Previous version to Superseded, sets `status_changed_at`, and lists the transitions in the audit entry (`details.demoted`). Uploading an older version number as Active while a newer Active version exists is refused, so the newest approved version is always the one in force; historic versions can still be uploaded as Previous or Superseded, as the seed does. `version_key` compares versions numerically, so 2.10 is newer than 2.9. An administrator can also change a status with `POST /api/v1/documents/{doc_id}/versions/{version}/status` or the **Version status** panel on the document page. Activating a version there moves the other Active version to Previous and runs the impact analysis. Every status change is audited as `document.status_changed`. After each upload or status change the knowledge revision counter (`kb_revision` in `system_settings`) is incremented, and the next retrieval rebuilds the index (section 5.10.1).

The end-to-end test `test_document_upload_and_policy_versioning_journey` uploads TST-POL-90 v1.0 and then v1.1 as Active. It checks that v1.0 becomes Previous, that the revision impact names the changed section, and that evidence search returns v1.1 and never v1.0.

### 5.9.3 Revision impact analysis

SRS section 1.8(4) asks the application to tell whether current resolutions are affected by a revised policy, whether the previous policy is obsolete, whether escalation rules have changed and whether generated responses need revision. `impact_analysis` in `services/documents.py` answers these questions whenever a new version replaces an Active one:

- **Changed sections.** `facts.py::diff_versions` compares the two versions section by section and reports each section as added, removed or modified. A section is modified when its text similarity is below 0.995 or when any extracted number differs, so a change from 30 to 21 days is detected however similar the rest of the text is. Numeric changes are listed as pairs of old and new values.
- **Affected rules.** Resolution and escalation rules whose policy references point to a changed section are listed, and `escalation_rules_changed` is set when any escalation rule is affected.
- **Out-of-sync parameters.** Rule Matrix parameters whose `source` cites a changed section are listed. When the old number in that section equals the parameter's current value, the new number is proposed as the suggested value and the parameter is flagged `out_of_sync`.
- **Affected complaints.** Open complaints (not Closed; submitted through the web, the API or the dataset) whose analyses cited a changed section of the old version are listed, and every one that is not yet Resolved is marked as needing a revised response.
- **Obsolescence.** `previous_policy_obsolete` is true, because the old version is no longer primary evidence.

The result is stored in `document_versions.extra.impact`, returned by `GET /api/v1/documents/{doc_id}/impact` and shown on the document's **Revision impact** tab.

The hidden-pack revision REF-POL-02 v2.1 illustrates the analysis (Table 5.9). The integration test `test_revised_policy_upload_versioning_and_impact` previews and uploads the file, checks that v2.1 becomes Active and v2.0 Previous or Superseded, that sections 3.1, 3.2 and 4.3 are reported as changed, that `refund_window_days` is out of sync with the suggested value 21, and that evidence search returns only v2.1 for REF-POL-02. The remaining rows of Table 5.9 were reproduced for this report by running the same parser, diff and parameter logic on the two files, without the database.

**Table 5.9 — Revision impact of REF-POL-02 v2.0 → v2.1**

| Changed section | Change detected | Rule Matrix consequence |
|---|---|---|
| 3.1 Standard Refund Window | 30 → 21 calendar days | `refund_window_days` 30, suggested 21, out of sync (asserted by the test) |
| 3.2 Care+ Members | 45 → 60 calendar days | `care_plus_refund_window_days` 45, suggested 60, out of sync |
| 3.4 Non-Refundable Items | Text modified, no number changed | — |
| 4.3 Refund Issue Time | 5 → 3 business days | `refund_issue_business_days` 5, suggested 3, out of sync |
| 5.1 Late Refunds | 5 → 3 business days (reference to 4.3) | `refund_delay_status_update_business_days` listed, value 1 unaffected |
| Rules citing the changed sections | 8 resolution rules (RES-REF-REQ-01 to 05, RES-REF-DLY-01 to 03); no escalation rule | Listed for review |

The analysis does not change the Rule Matrix. The Knowledge Base supplies evidence and the Rule Matrix supplies criteria, so the new refund window takes effect in decisions only when an administrator updates the parameter (`PUT /api/v1/rule-parameters/refund_window_days`), which is versioned and audited (Chapter 10). `test_changing_a_rule_parameter_changes_the_decision` shows the effect: a refund request 25 days after delivery changes from eligible (or requires verification) to not eligible when the window is set to 21 days.

### 5.9.4 Limitation: activation before the effective date

Demotion does not wait for the effective date. When a version with a future effective date is uploaded as Active, the previous Active version becomes Previous immediately, while the new version is still Pending. Complaints dated between the upload and the new effective date then have no primary version of that document, and retrieval returns no evidence from it. The upload shows a warning, but the gap is real. Keeping the previous version primary until the new version's effective date is not implemented and is recorded here as a Future Enhancement.

## 5.10 Retrieval Architecture

### 5.10.1 Knowledge snapshot

Retrieval runs in the application process over an in-memory `KnowledgeSnapshot` (`knowledge_base/store.py`). The snapshot holds one entry per parsed chunk with the metadata of its document and version, a registry of all versions with their section headings and texts, a BM25 index, a matrix of chunk vectors and the precedence-resolved conflicts. It is built on first use and rebuilt when `kb_revision` changes (the Knowledge base page in Figure 5.4 shows revision 30), so uploads and status changes apply to the next complaint without a restart. No external vector database is needed: vectors are stored with the chunks in PostgreSQL, and `VECTOR_DATABASE_URL` is optional and unused by default.

### 5.10.2 Embeddings

`EMBEDDING_PROVIDER` selects the embedder (`knowledge_base/embeddings.py`). The default, `local`, is a deterministic feature-hashing embedder with 768 dimensions (`local-hash-v1-768`). It hashes stemmed unigrams (weight 1.0), bigrams (0.8) and character trigrams (0.25) with signed BLAKE2b hashing, applies logarithmic term frequency and normalises to unit length. It needs no model download or key and gives the same vectors on every machine, but it is a classic information-retrieval technique, not a neural model: it captures shared vocabulary and word forms, not meaning. All 484 chunks in the demo database are embedded with it, and all recorded runs used it. The `openai` (default model `text-embedding-3-small`) and `gemini` (`text-embedding-004`) adapters are used when the provider and a key are configured; they are Implemented but excluded from test coverage and not used in any recorded run. Each vector is stored as float32 bytes together with the model name, and a model change causes the chunks to be re-embedded when the snapshot is next built.

### 5.10.3 Hybrid, rule-guided ranking

`retrieve` in `knowledge_base/retriever.py` ranks chunks in five steps:

1. **Eligibility filter.** Only chunks that are primary evidence on the complaint date are candidates: Active, in effect and not quarantined. In every recorded analysis this left 387 of the 484 chunks.
2. **Lexical ranking.** Okapi BM25 (k1 = 1.4, b = 0.72) over the chunk text, the heading counted twice and the document title; the best 30 chunks with a positive score are kept.
3. **Semantic ranking.** Cosine similarity between the query vector and the chunk vectors; the best 30 chunks with a similarity above 0.05 are kept.
4. **Rule-guided expansion.** The deterministic classifier proposes up to three candidate subcategories. For each, `rule_sections` collects the sections cited by the subcategory's resolution rules, most-cited first, and by its routing rule, except the routing-table reference `RTE-RUL-14:3` that every routing rule carries. The active chunks of those sections form a third ranked list.
5. **Fusion and selection.** The three lists are combined by reciprocal-rank fusion (k = 60, weight 1.4 for the rule-guided list), ties are broken by document-type precedence, at most four chunks are taken from one document, and the top `RETRIEVAL_TOP_K` chunks (10) become the evidence items E1 to E10.

The query is the complaint title, the normalised description and the product text. Older versions of the retrieved sections are returned separately as outdated context, never as evidence, and precedence-resolved conflicts that involve a retrieved chunk are attached (section 5.12). Table 5.10 collects the parameters.

**Table 5.10 — Retrieval parameters**

| Parameter | Value | Source |
|---|---|---|
| Evidence items per complaint | 10 | `RETRIEVAL_TOP_K` |
| Lexical and semantic candidate lists | 30 each | `retriever.py` |
| BM25 k1 / b | 1.4 / 0.72 | `bm25.py` |
| Semantic similarity floor | 0.05 | `retriever.py` |
| Rule-guided subcategories | Top 3 candidates | `retriever.py` |
| Fusion constant / rule-guided weight | 60 / 1.4 | `RRF_K`, `retriever.py` |
| Maximum chunks per document | 4 | `per_doc_cap` |
| Embedder | `local-hash-v1-768` (768 dimensions) | `EMBEDDING_PROVIDER=local` |
| Evidence search default / maximum | 8 / 20 | `GET /knowledge/search` |

### 5.10.4 Measured behaviour

The retrieval record of each analysis includes statistics that can be aggregated. Over the 780 completed analyses in the demo database, every analysis received exactly 10 evidence items. The lexical list contributed to 7,120 of the 7,800 items, the semantic list to 6,696 and the rule-guided list to 3,209. The median retrieval time was 2.1 ms (95th percentile 3.5 ms), negligible next to the GenAI calls. Outdated context was attached in 592 analyses (75.9 %) and a precedence-resolved conflict in 140 (17.9 %). How well these items cover the sections the rules rely on, and how the model uses them, is analysed in Chapter 9. **Evidence search** on the Knowledge base page runs the same `retrieve` function for a typed complaint, so an evaluator can see exactly which evidence the pipeline would receive.

## 5.11 Policy Traceability

A policy citation in SupportNova can be followed back to the stored file in four steps. The evidence item shown to the model (E1 to E10) carries its chunk UID. The chunk UID names the document, version and section, and belongs to a `document_versions` row. That row holds the storage path, file name and SHA-256 of the original file. The file itself is served by `GET /api/v1/documents/{doc_id}/versions/{version}/download`, which also confirms that the resolved path lies inside the storage directory. Because the Lumora section numbers are pinned by `kb_spec.yaml`, the section in a citation (`REF-POL-02:4.3`) is the same number a person sees in the PDF.

Each analysis stores its complete retrieval record — query, evidence with chunk UIDs, scores and contributing methods, outdated context, conflicts, the rule-guided sections and statistics — in `analyses.retrieval`, together with the version of every document used as evidence in `analyses.policy_versions`, which is the policy-version logging of SRS Step 49. Citations are stored as rows of `policy_references` with the source that produced them:

- `retrieval` — the Python applicability label (Applicable, Conditionally Applicable, Not Applicable or Outdated) for every evidence item, with its chunk UID, and for every outdated section; 9,296 rows in the demo database.
- `ai` — every citation made by the GenAI model, resolved against the registry to record whether the document and section exist and which version is active; 2,280 rows.
- `rule` — every section required by the selected resolution rule and the fired escalation rules; 1,939 rows.

Traceability is also checked when the rules and the dataset are built. The Rule Matrix integrity check warns about policy references that are not in the active Knowledge Base (none at present), and `scripts/validate_dataset.py` confirms that every policy section cited by an expected label exists in `kb_spec.yaml` (check `codes.policy_sections`, Chapter 6). The checks that verify each GenAI citation at run time — SCH-004, POL-001 to POL-006 and HAL-004 — are described in Chapter 9.

## 5.12 Knowledge Conflict Handling

Conflicting statements are resolved by the documented precedence rules of CHP-POL-01 section 10, configured in `rules/precedence/precedence_rules.yaml` and listed in Table 5.11. Document types are ranked Policy = Rules (1) > SOP (2) > Guideline (3) > FAQ (4) > Template (5), and between documents of the same rank the most recent effective date prevails.

**Table 5.11 — Precedence rules**

| Rule | Name | Rule text (abridged) | Policy basis |
|---|---|---|---|
| PRC-001 | Active documents only | Only Active documents within their effective and expiry dates can be primary evidence | CHP-POL-01:10.1 |
| PRC-002 | Precedence by document type | Policy = Rules > SOP > Guideline > FAQ > Template | CHP-POL-01:10.2 |
| PRC-003 | Precedence by effective date | Same type and topic: the most recent effective date prevails | CHP-POL-01:10.3 |
| PRC-004 | Outdated documents | Previous, Superseded, Draft, expired or not-yet-effective documents are never primary | CHP-POL-01:10.4 |
| PRC-005 | Conflict handling | Conflicts are resolved by PRC-002 or PRC-003 and reported to the document owner | CHP-POL-01:10.5 |

Conflicts between outdated and Active versions are settled by eligibility alone: an outdated version is never evidence, so a 60-day window in REF-POL-02 v1.0 cannot compete with the 30-day window in v2.0. Conflicts between Active documents are found by `detect_conflicts` in `knowledge_base/store.py` when the snapshot is built. For each fact key in `precedence_rules.yaml` (refund issue time, refund window, delay credit, agent compensation limit, duplicate-charge reversal) it extracts the value from every eligible chunk, keeps one statement per document and, when the values differ, orders the statements by precedence rank and then by effective date. The first statement prevails, and the others are recorded as overridden, citing PRC-002 when the ranks differ or PRC-003 otherwise. Replaying this detection over the demo database finds all five fact keys stated in Active documents. Four raise no conflict: the duplicate-charge reversal (BIL-POL-05 section 4.1) and the agent compensation limit (CPN-POL-11 section 5.1) are each stated in one document, the delay credit is USD 10 in both DEL-POL-04 section 5.2 and FAQ-GEN-16 section 1.2, and the refund window is 30 days in both REF-POL-02 section 3.1 and FAQ-GEN-16 section 2.1. One conflicts: refund issue time is 3 business days in FAQ-GEN-16 v5.0 section 2.2 and 5 business days in REF-POL-02 v2.0 section 4.3 (and in FAQ-BIL-17 v2.0 section 2.1). REF-POL-02 prevails under PRC-002, and the Knowledge base page lists this one conflict on its **Policy conflicts** tab (Figure 5.4), served by `GET /api/v1/knowledge/conflicts`.

The resolved conflict is then used in three places. When a retrieved chunk takes part in the conflict, the conflict is attached to the retrieval result, which happened in 140 of the 780 recorded analyses. The GenAI prompt receives it in `<policy_conflicts>` as a sentence such as "REF-POL-02 v2.0 section 4.3 (policy) prevails over FAQ-GEN-16 section 2.2 (faq) under PRC-002 (CHP-POL-01 s10). Use the prevailing source." Pipeline 2 then checks the answer: POL-006 (Higher-ranking policy followed in conflicts) fails when the AI cites an overridden statement, and the manual-review trigger REV-007 (policy contradiction) fires when POL-006 fails, when the customer quotes the overridden value or document, or when the AI cited it. The measured effect of these checks is reported in Chapter 9. `tests/backend/integration/test_difficult_cases.py::test_contradictory_policy_resolved_by_precedence` submits a complaint that quotes the FAQ's three business days and checks that the case carries the conflict or FAQ evidence, or goes to manual review.

## 5.13 Full Processing Pipeline

Figure 5.3 puts the steps of this chapter together, in execution order, from an uploaded PDF or DOCX file to the evidence block of the GenAI prompt. The stages the SRS names — upload, validation, parsing, section extraction, chunking, metadata, version control, embedding and index, approved knowledge base, semantic retrieval, relevant evidence and GenAI context — are all present. Their order differs in one respect: the document metadata is validated immediately after parsing, before anything is stored, and the chunk-level metadata is attached while chunking.

![Figure 5.3 — Knowledge-base processing pipeline from upload to GenAI context](diagrams/pipelines/fig-05-03-kb-processing-pipeline.svg)
*Figure 5.3 — Knowledge-base processing pipeline from upload to GenAI context*

In detail, `ingest_document` validates the file (section 5.4.1), rejects duplicates (5.4.2), parses the document (5.5), merges and validates the metadata (5.4.3), stores the original file under `storage/documents/<DOC_ID>/<version>/`, extracts the policy facts (5.8), writes the version row and its sections (5.6), chunks the sections (5.7), embeds and screens each chunk (5.10.2 and 5.4.4), applies version control and the impact analysis (5.9), writes the audit entry and increments `kb_revision`. For each complaint the retriever then filters the eligible chunks, ranks them (5.10.3) and returns ten evidence items, which the context builder turns into the `<evidence>` block of the analysis prompt (Chapter 9).

The processed Knowledge Base appears in two pages of the application. The Knowledge base page (Figure 5.4) shows 24 documents, 23 Active versions (3 Previous, 2 Superseded, 1 Draft), 484 indexed chunks by format and the 4 quarantined chunks, with tabs for the documents, the one policy conflict and evidence search. The document page (Figure 5.5) shows the version history of REF-POL-02 — v1.0 Superseded and "Context only", v2.0 Active and "Primary evidence" — with the 23 sections and their page numbers, the chunks, the 16 extracted facts, the revision impact, the version metadata with the file fingerprint, the status control and the injection-screening result.

![Figure 5.4 — Knowledge base page with document, version, chunk and quarantine counts](../screenshots/15-knowledge-base.png)
*Figure 5.4 — Knowledge base page with document, version, chunk and quarantine counts*

![Figure 5.5 — Document page of REF-POL-02 with version history and parsed sections](../screenshots/16-policy-document-versions.png)
*Figure 5.5 — Document page of REF-POL-02 with version history and parsed sections*

Table 5.12 summarises the status of the SRS knowledge-base requirements.

**Table 5.12 — Status of the SRS knowledge-base requirements**

| SRS requirement | Status | Evidence |
|---|---|---|
| Step 2 — knowledge-base documents | Implemented | 24 documents, 29 versions (`knowledge_base/manifest.yaml`); `test_knowledge_base_meets_srs_minimums` |
| Step 3 — PDF and DOCX mandatory, TXT/MD/CSV optional | Implemented, Tested (PDF, DOCX, MD) | `parsers.py`; `test_parse_sections_from_real_documents`; TXT and CSV untested |
| Step 4 — document validation | Implemented, Tested | `security/files.py`, `validation.py`; tests in Table 5.5 |
| Step 5 — parsing with ID, title, section, heading, page, version, date | Implemented, Tested | `test_pdf_keeps_repeated_body_text_and_reads_tables_by_row` |
| Step 6 — chunking with chunk ID, document, section, heading, page, version | Implemented, Tested | `chunking.py`; chunk UIDs asserted in `test_parse_sections_from_real_documents` |
| Step 7 — Active / Previous / Superseded / Draft; outdated never primary | Implemented, Tested | `test_revised_policy_upload_versioning_and_impact`, e2e versioning journey |
| Step 25 — retrieval with source traceability | Implemented, Tested | `retriever.py`; chunk UIDs in `analyses.retrieval` and `policy_references` |
| Step 26 — applicability labels | Implemented | Python assessment described in Chapter 9 |
| 1.8(4) — hidden policy update | Implemented, Tested | Impact analysis; REF-POL-02 v2.1 test |
| 1.8(10) — contradictory policy | Implemented, Configured | Precedence rules PRC-001 to PRC-005; `test_contradictory_policy_resolved_by_precedence` |
| New policy in the hidden pack | Implemented, not tested | ENV-POL-25 v1.0 prepared in `data/hidden_test_ready/documents/`; no automated test uploads it |
