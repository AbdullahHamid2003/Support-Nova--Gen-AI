# Appendix I — Dataset Structure

This appendix is the field-by-field reference for the SupportNova complaint dataset described in Chapter 6. It is based on the record schema `schemas/dataset/complaint_record.schema.json` (JSON Schema draft 2020-12), the writers in `scripts/dataset/outputs.py`, the reader `backend/src/supportnova/services/datasets.py` and `docs/dataset.md`. Every value in the examples is fictional.

## I.1 Files and Formats

**Table I.1 — Dataset files and formats**

| File | Content | Records | Format details |
|---|---|---:|---|
| `data/sample_complaints/complaints.jsonl` | Development set, `CMP-00001` to `CMP-00617` | 617 | UTF-8, one JSON object per line, in chronological ID order |
| `data/sample_complaints/complaints.csv` | Development set, flattened | 617 | UTF-8, header row plus one row per record, 71 columns, minimal quoting |
| `data/hidden_test_ready/holdout_complaints.jsonl` | Holdout set, `EVL-00001` to `EVL-00154` | 154 | As the development JSONL |
| `data/hidden_test_ready/holdout_complaints.csv` | Holdout set, flattened | 154 | As the development CSV |
| `data/sample_complaints/customers.json` | Simulated customers `CUST-10001` to `CUST-10300` | 300 | UTF-8 JSON array, indented |
| `data/sample_complaints/orders.json` | Simulated order ledger | 594 | UTF-8 JSON array, indented |
| `data/sample_complaints/dataset_summary.json` | Counts, distributions, SRS checks and coherence report | 1 | UTF-8 JSON object |
| `schemas/dataset/complaint_record.schema.json` | Schema of one complaint record | — | JSON Schema draft 2020-12 |

All files are produced by `scripts/generate_dataset.py` (default seed 20260923) and checked by `scripts/validate_dataset.py`. The JSONL and CSV files of a split contain the same records; the validator checks that their row counts agree.

## I.2 Top-Level Fields of a Complaint Record

The schema requires all 25 top-level fields, uses `null` for a value that does not apply and forbids additional properties. Table I.2 lists them. The examples come from CMP-00249 unless another record is named.

**Table I.2 — Top-level fields**

| Field | Type | Meaning | Example |
|---|---|---|---|
| `complaint_id` | string, `^(CMP\|EVL)-[0-9]{5}$` | Record ID; `CMP` for development, `EVL` for holdout; assigned in date order | `CMP-00249` |
| `title` | string | Complaint title as written by the customer | `Broken on arrival and a rude agent` |
| `description` | string | Complaint text, including any channel wrapper (greeting, transcript tag, post handle) | `My Halo speaker came with a cracked top panel on 29 June, …` |
| `customer_ref` | string, `^CUST-[0-9]{5}$` | Customer in `customers.json` | `CUST-10088` |
| `customer_name` | string | Full name of the fictional customer | `Valeria Holloway` |
| `customer_type` | enum | `individual`, `care_plus`, `business`, `vip` | `individual` |
| `product_service` | string | Product or service as the customer wrote it; empty when not stated | `Halo speaker` |
| `product_sku` | string or null, `^(LUM\|SVC)-[A-Z0-9-]+$` | Ground-truth SKU identifiable from the complaint or the referenced order | `LUM-SPK-500` |
| `order_reference` | string or null | Order reference as supplied, normally `LMR-######`; invalid or malformed values are deliberate and tagged | `LMR-513923` |
| `transaction_reference` | string or null, `^TXN-[0-9]{8}$` | Transaction reference as supplied | `TXN-59348090` (CMP-00234) |
| `channel` | enum | `web_form`, `email`, `chat`, `phone`, `mobile_app`, `social_media`, `uploaded` | `chat` |
| `complaint_date` | string, ISO 8601 UTC (`…Z`) | Submission time; sets the policy date for the case | `2026-06-30T13:09:15Z` |
| `previous_complaint_reference` | string or null, `^(CMP\|EVL)-[0-9]{5}$` | Earlier complaint the customer cites | `CMP-00023` (CMP-00062) |
| `preferred_contact_method` | enum | `email`, `phone`, `sms`, `chat` | `sms` |
| `requested_resolution` | enum | `refund`, `replacement`, `repair`, `compensation`, `explanation`, `cancellation`, `other`, `none` | `replacement` |
| `supporting_information` | string | Additional text supplied with the complaint; empty when none | `Order reference: LMR-713529` (CMP-00027) |
| `attachments` | array of `{file_name, content_type}` | Attachment metadata; an `image/*` type means photo evidence | `[{"file_name": "complaint_letter_brennan.pdf", "content_type": "application/pdf"}]` (CMP-00012) |
| `requested_tone` | enum | `professional`, `empathetic`, `concise`, `formal` | `formal` |
| `seed_status` | enum | Lifecycle state used to seed complaint history: `New`, `In Progress`, `Escalated`, `Awaiting Customer`, `Resolved`, `Closed` | `New` |
| `declared` | object | Ground-truth facts used for labelling (section I.3) | — |
| `expected` | object | Expected labels (section I.4) | — |
| `difficulty_type` | enum | Main challenge of the record (section I.5) | `multi_issue` |
| `tags` | array of string | Every applicable property, e.g. `safety`, `calm_critical`, `injection:fake_system_message`, `lexical_trap:fire_event`, `outdated_policy:RET-SOP-23 v1.4` | `["blocking_missing_info", "missing_info", "multi_issue"]` |
| `scenario_id` | string, `^[A-Z0-9][A-Z0-9-]+$` | Source scenario in the scenario bank; holdout scenarios start with `H-` | `MI-DOA-RUD` |
| `split` | enum | `dev` or `holdout` | `dev` |

In the development set, 595 records have `seed_status` New, 11 In Progress, 4 Resolved, 4 Escalated and 3 Awaiting Customer. The non-New states belong to the originals of repeat chains, so that repeat detection finds unresolved or reopened history.

## I.3 The `declared` Block

The `declared` block holds the facts that are truly present in the complaint. The reference labeller `supportnova.rule_engine.reference.label_declared` turns them into the expected labels. The runtime pipelines never see this block.

**Table I.3 — Fields of the `declared` block**

| Field | Type | Meaning | Example |
|---|---|---|---|
| `signals` | array of unique strings, `^[a-z_]+$` | Risk and request signals truly present, named as in `rules/complaint_rules/signals.yaml` (33 of the 35 signals occur) | `["replacement_request"]` |
| `complaint_facts.has_order_reference` | boolean | A well-formed `LMR-######` was supplied | `true` |
| `complaint_facts.has_transaction_reference` | boolean | A transaction reference was supplied | `false` |
| `complaint_facts.has_product` | boolean | A product or service is named in the text or the product field | `true` |
| `complaint_facts.product_sku` | string or null | SKU of the named product | `LUM-SPK-500` |
| `complaint_facts.has_photo_evidence` | boolean | An image attachment was supplied | `false` |
| `complaint_facts.has_date` | boolean | A calendar date or an "N days/weeks/months ago" duration was written | `true` |
| `complaint_facts.word_count` | integer ≥ 0 | Words in `description` | `37` |
| `complaint_facts.max_amount` | number or null | Largest USD amount written | `500.0` (CMP-00358) |
| `complaint_facts.requested_compensation_amount` | number or null | Largest amount explicitly demanded as compensation | `500.0` (CMP-00358) |
| `complaint_facts.max_elapsed_days` | integer or null | Largest "N days/weeks/months ago/since" duration in days (week 7, month 30) | `16` (CMP-00009) |
| `complaint_facts.outage_hours` | number or null | Stated outage length | `36.0` (CMP-00046) |
| `complaint_facts.requested_resolution` | enum | Copy of the requested resolution | `replacement` |
| `complaint_facts.channel` | enum | Copy of the channel | `chat` |
| `history.prior_same_issue_count` | integer ≥ 0 | Earlier complaints of the same chain that are cases (duplicates are linked, not counted) | `1` (CMP-00018) |
| `history.unresolved_prior_same_issue` | integer ≥ 0 | Those earlier cases that are New, In Progress, Escalated or Awaiting Customer | `1` (CMP-00018) |
| `history.references_resolved_complaint` | boolean | The cited complaint was Resolved or Closed (reopening) | `false` |

## I.4 The `expected` Block

The `expected` block holds 31 labels. All rule-derived fields reproduce exactly when `label_declared` is run on the declared facts and the ledger record; the validator confirms this for all 771 records.

**Table I.4 — Fields of the `expected` block**

| Field | Type | Meaning | Example (CMP-00249 unless noted) |
|---|---|---|---|
| `primary_issue` | string | Human-readable label of the primary issue | `Damaged delivery and a rude agent` |
| `secondary_issues` | array of `{label, category, subcategory}` | Additional issues in the complaint | `[{"label": "Agent was rude", "category": "STF", "subcategory": "STF-RUD"}]` |
| `category` | string, `^[A-Z]{3}$` | Category of the primary issue | `PRD` |
| `subcategory` | string, `^[A-Z]{3}-[A-Z]{3}$` | Subcategory of the primary issue | `PRD-DOA` |
| `sentiment` | enum | `Positive`, `Neutral`, `Negative`, `Strongly Negative`, from the writing style | `Strongly Negative` |
| `emotion_indicators` | array of enum | `Frustration`, `Anger`, `Disappointment`, `Confusion`, `Urgency` | `["Frustration", "Anger"]` |
| `urgency` | enum | `Low`, `Medium`, `High`, `Critical`; base rule plus urgency floors | `Medium` |
| `impact` | enum | `Low`, `Medium`, `High` | `Medium` |
| `priority` | enum | `P0` to `P3`, from the priority matrix | `P2` |
| `entities` | array of `{type, value}` | Entities of type `order_id`, `transaction_id`, `product`, `service`, `date`, `amount`, `location`, `complaint_reference`; values are exact substrings of the text | `[{"type": "product", "value": "Halo speaker"}, …]` |
| `department` | string, `^DEPT-[A-Z]{3}$` | Primary department | `DEPT-RET` |
| `supporting_departments` | array of unique department codes | Standing, conditional and escalation departments | `["DEPT-LOG", "DEPT-CRL"]` |
| `policy_references` | array of unique strings, `DOC-ID:section` | Sections cited by the selected rule and the fired escalation rules | `["RPL-POL-03:3.1"]` |
| `resolution_rule` | string, `^RES-[A-Z]{3}-[A-Z]{3}-[0-9]{2}$` | Selected resolution rule | `RES-PRD-DOA-01` |
| `required_actions` | array of action codes or `{any_of: [...]}` groups | Required actions of the rule, including the escalation action | `["VERIFY_ORDER", "REQUEST_PHOTO_EVIDENCE"]` |
| `refund_eligibility` | enum | `eligible`, `not_eligible`, `requires_verification`, `not_applicable` | `requires_verification` |
| `replacement_eligibility` | enum | As above | `requires_verification` |
| `compensation_eligibility` | enum | As above | `not_applicable` |
| `compensation_amount_usd` | number or null | Amount of an eligible compensation | `10.0` (CMP-00009) |
| `escalation_required` | boolean | Any escalation fires | `false` |
| `escalation_level` | enum | One of the six levels, from `No Escalation` to `Critical Management Escalation`; the highest fired level | `No Escalation` |
| `escalation_rules` | array, `ESC-###` or a `RES-*` ID | Fired escalation rules; a resolution-rule ID where the escalation is inherent in the rule | `["ESC-002", "ESC-007"]` (CMP-00396) |
| `follow_up_required` | boolean | A follow-up is required | `true` |
| `follow_up_type` | string or null | One of the six follow-up types | `Request for additional information` |
| `missing_information` | array of unique field names | Missing-information fields: `order_reference`, `photo_evidence`, `transaction_reference`, `transaction_date`, `product`, `problem_description`, `order_reference_unverified`, `order_ownership` | `["photo_evidence"]` |
| `blocking_missing_information` | boolean | The case cannot be resolved without the information | `true` |
| `is_duplicate_of` | ID or null | Source of an exact duplicate | `CMP-00030` (CMP-00036) |
| `is_near_duplicate_of` | ID or null | Source of a near-duplicate | `CMP-00012` (CMP-00018) |
| `is_repeat_of` | ID or null | Root of the repeat chain | `CMP-00023` (CMP-00062) |
| `prompt_injection` | boolean | The text contains a manipulation attempt | `false` |
| `manual_review_expected` | boolean | The case should go to manual review (injection, ambiguous or contradictory policy, SAF or PRV category, sensitive signals, blocking missing information) | `true` |

Prohibited and recommended actions are not fields of the record. They belong to the selected resolution rule: `resolution_rule` names the rule in `rules/complaint_rules/resolution_rules.yaml`, whose `prohibited_actions` and `recommended_actions` apply to the case.

## I.5 Enumerated Values

**Table I.5 — Enumerations used in the records**

| Field | Values |
|---|---|
| `customer_type` | individual, care_plus, business, vip |
| `channel` | web_form, email, chat, phone, mobile_app, social_media, uploaded |
| `preferred_contact_method` | email, phone, sms, chat |
| `requested_resolution` | refund, replacement, repair, compensation, explanation, cancellation, other, none |
| `requested_tone` | professional, empathetic, concise, formal |
| `seed_status` | New, In Progress, Escalated, Awaiting Customer, Resolved, Closed |
| `sentiment` | Positive, Neutral, Negative, Strongly Negative |
| `emotion_indicators` | Frustration, Anger, Disappointment, Confusion, Urgency |
| `urgency` / `impact` / `priority` | Low, Medium, High, Critical / Low, Medium, High / P0, P1, P2, P3 |
| eligibility fields | eligible, not_eligible, requires_verification, not_applicable |
| `escalation_level` | No Escalation, Supervisor Review, Department Manager, Specialist Team, Compliance Review, Critical Management Escalation |
| `follow_up_type` | Request for additional information, Resolution confirmation, Refund-status update, Replacement-status update, Escalation acknowledgement, Closure confirmation |
| `difficulty_type` | simple, multi_issue, ambiguous, contradictory_policy, prompt_injection, incomplete, repeat, near_duplicate, exact_duplicate, emotional_low_priority, calm_critical, policy_exception, unsupported_refund, unsupported_compensation, high_value, vip_minor, sensitive (`calm_critical` and `sensitive` are allowed but unused as main types) |
| `split` | dev, holdout |

## I.6 CSV Flattening

The CSV files contain the same records as the JSONL files in one row each (`scripts/dataset/outputs.py::flatten`). `services/datasets.py::unflatten` reverses the flattening when a CSV file is uploaded for evaluation. Table I.6 gives the rules.

**Table I.6 — CSV flattening rules**

| Record part | CSV representation | Example |
|---|---|---|
| Top-level scalars | Column of the same name; `null` as empty; booleans `true` / `false` | `order_reference` = `LMR-513923` |
| `attachments` | `file_name\|content_type`, items joined by `;` | `complaint_letter_brennan.pdf\|application/pdf` |
| `tags` | Joined by `;` | `blocking_missing_info;missing_info;multi_issue` |
| `declared.signals` | Column `declared_signals`, joined by `;` | `replacement_request` |
| `declared.complaint_facts.*` | Columns `fact_<name>` | `fact_word_count` = `37` |
| `declared.history.*` | Columns `history_<name>` | `history_prior_same_issue_count` = `0` |
| `expected.*` | Columns `expected_<name>` | `expected_subcategory` = `PRD-DOA` |
| `expected.secondary_issues` | `SUBCATEGORY:label`, joined by `;` (the category is implied by the subcategory) | `STF-RUD:Agent was rude` |
| `expected.entities` | `type=value`, joined by `;` | `product=Halo speaker;date=29 June;order_id=LMR-513923` |
| `expected.required_actions` | Codes joined by `;`; an `any_of` group joined by `\|` | `VERIFY_SHIPMENT_STATUS;RESHIP_ORDER\|PROCESS_REFUND` (CMP-00066) |
| Other lists in `expected` | Joined by `;` | `expected_supporting_departments` = `DEPT-LOG;DEPT-CRL` |

The column order is: the 23 top-level fields other than `declared` and `expected`, then `declared_signals`, the 13 `fact_*` columns, the 3 `history_*` columns and the 31 `expected_*` columns, 71 columns in total.

## I.7 Customers and Order Ledger

**Table I.7 — Fields of `customers.json`**

| Field | Meaning | Example |
|---|---|---|
| `customer_ref` | Customer ID | `CUST-10001` |
| `first_name`, `last_name`, `full_name` | Fictional name | `Wesley`, `Jovanovic`, `Wesley Jovanovic` |
| `email` | Address at `example.com` | `wesley.jovanovic@example.com` |
| `city` | Fictional city | `Birchmont` |
| `customer_type` | individual, care_plus, business or vip (exact 60/20/10/10 split) | `individual` |
| `company` | Company name for business customers, else null | `null` |
| `preferred_contact_method` | email, phone, sms or chat | `chat` |
| `customer_since` | Date the customer relationship started | `2024-11-16` |
| `care_plus_member` | Active Care+ plan | `false` |

**Table I.8 — Fields of `orders.json` (order ledger)**

| Field | Meaning | Example (LMR-513923, the order of CMP-00249) |
|---|---|---|
| `order_ref`, `customer_ref` | Order and owning customer | `LMR-513923`, `CUST-10088` |
| `items` | `[{sku, qty, unit_price}]`, prices from `config/products.yaml` | `[{"sku": "LUM-SPK-500", "qty": 1, "unit_price": 99.0}]` |
| `order_total`, `shipping_method`, `shipping_fee` | Totals and shipping | `99.0`, `standard`, `0.0` |
| `order_date`, `estimated_delivery_date`, `dispatched_date`, `delivered_date` | Order timeline | `2026-06-23`, `2026-06-29`, `2026-06-24`, `2026-06-29` |
| `status`, `tracking_last_update` | Order status and last tracking event | `delivered`, `2026-06-29` |
| `transactions` | `[{txn_ref, type, amount, date}]`, type `charge` or `refund` | `[{"txn_ref": "TXN-31753283", "type": "charge", "amount": 99.0, "date": "2026-06-23"}]` |
| `care_plus`, `replacement_count`, `careplus_claims_12m` | Protection plan and history | `false`, `0`, `0` |
| `return`, `cancellation`, `subscription`, `trace` | Optional sub-records (return and refund dates, cancellation, `{plan, renewal_date, auto_renew}`, carrier trace) | `null` |

The ledger has 594 orders: 434 referenced by complaints and 160 background orders. It records the state as of the latest complaint that refers to each order, so no event is dated after that complaint.

## I.8 Dataset Summary

`dataset_summary.json` is written with the dataset and is the source of the counts in Chapter 6. Its top-level keys are listed in Table I.9.

**Table I.9 — Keys of `dataset_summary.json`**

| Key | Content |
|---|---|
| `splits` | Record counts per split (`dev` 617, `holdout` 154) |
| `dev`, `holdout` | Per split: `counts` (all difficulty and SRS counters), and distributions `by_category`, `by_subcategory`, `by_difficulty_type`, `by_channel`, `by_customer_type`, `by_sentiment`, `by_priority`, `by_escalation_level`, `by_department`, `by_requested_tone`, `by_requested_resolution`, `by_resolution_rule`, `by_escalation_rule`, `by_tag` |
| `resolution_rule_coverage` | 116 of 116 rules covered; 14 covered only by the development set |
| `srs_minimum_checks` | Each check with requirement, actual value, pass flag and split |
| `all_checks_passed` | `true` |
| `seed` | `20260923` |
| `generation` | 412 scenarios, 771 complaints, writing styles (calm 292, frustrated 243, angry 121, polite 115), 3,009 distinct tokens in the descriptions, 594 ledger orders |
| `coherence` | Signal-coherence method and results, with the 14 deliberate lexical traps listed per record |
| `intended_rule_or_expectation_failures`, `render_errors` | Empty lists |

## I.9 Holdout Format

The holdout files use exactly the same record schema and CSV layout as the development files. They differ only in their values: `complaint_id` uses the `EVL` prefix, `split` is `holdout`, `scenario_id` starts with `H-`, and `complaint_date` lies between 2026-09-01 and 2026-09-21. Four holdout records refer to development complaints through `previous_complaint_reference` and `expected.is_repeat_of` (EVL-00031, EVL-00091, EVL-00114 and EVL-00154), so the complaint history must include the development set when they are processed. In the application the holdout set is the built-in dataset `holdout` of **Evaluation → Start an evaluation run**. Each case becomes a complaint with the reference `R<run>-<case>`, for example `R1-EVL-00016`, and a previous reference to another case of the same run is mapped to that case's complaint reference.

## I.10 Hidden-Dataset Input Format

An external or hidden dataset can be uploaded as a JSON array, a JSON object with a `complaints` or `records` array, JSON Lines or CSV (`POST /api/v1/evaluation/runs/upload`), or placed in `data/hidden_test_ready/`, where it is listed as `file:<name>`. Only the complaint description is essential; every other field is optional and unknown columns are ignored. Table I.10 lists the fields the evaluation runner reads (`services/datasets.py::to_submission` and `services/evaluation.py`).

**Table I.10 — Accepted input fields for a hidden dataset**

| Field (accepted aliases) | Required | Default when missing | Use |
|---|---|---|---|
| `description` | Yes | — (a file in which no record has one is rejected) | Complaint text |
| `title` | No | First 80 characters of the description | Complaint title |
| `complaint_id` (`id`) | No | `ROW-00001`, `ROW-00002`, … | Case ID and complaint reference `R<run>-<id>` |
| `supporting_information` (`supporting_info`) | No | Empty | Additional text |
| `customer_ref`, `customer_name` | No | No customer linked | Links a customer; an unknown reference creates a customer record for the run |
| `customer_type` | No | `individual` | Customer type |
| `channel` | No | `web_form` | Channel |
| `product_service` (`product`) | No | Empty | Product text |
| `order_reference` (`order_ref`) | No | None | Order lookup in the ledger |
| `transaction_reference` (`transaction_ref`) | No | None | Transaction reference |
| `previous_complaint_reference` | No | None | Repeat and history linking |
| `preferred_contact_method` (`preferred_contact`) | No | `email` | Contact preference |
| `requested_resolution` | No | `none` | Requested resolution |
| `requested_tone` | No | `professional` | Response tone |
| `complaint_date` | No | Time of the run | Case date and policy date |
| `attachments` | No | None | Attachment metadata |
| `seed_status` | No | None | Applied after processing as history for later cases (not a label) |
| `expected` object or `expected_*` columns | No | Accuracy not measured | Scoring only; never read by the pipeline |

A run is limited to 5,000 records and to a file of at most `MAX_UPLOAD_MB`. The smallest accepted CSV is the one used by `tests/backend/integration/test_defects_and_live_changes.py::test_hidden_dataset_upload_with_minimal_columns` (abridged):

```text
complaint_id,title,description
HID-1,Late parcel,My parcel is two weeks late and tracking has not moved since last Monday.
HID-2,Recycling question,Can I send my old hub back through a take-back or recycling scheme please?
HID-3,Charged twice,I was charged twice for the same order and need the duplicate charge reversed.
```

The schema also defines an `evaluation_cases` table (`database/models/workflow.py`), but the current code does not use it: evaluation reads the dataset files directly, and the demo database holds no rows in that table.
