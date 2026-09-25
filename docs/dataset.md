# SupportNova complaint dataset

The complaint dataset for **Lumora Home Technologies** - a fictional smart-home electronics company
(devices, the Cloud Vault and Care+ subscriptions, and the Pro Install service). Every customer, order,
complaint and policy is simulated; no real person or company data is used.

| Set | File | Records | IDs | Dates |
|-----|------|--------:|-----|-------|
| Dev | `data/sample_complaints/complaints.jsonl` / `.csv` | **617** | `CMP-00001` .. `CMP-00617` | 2026-05-04 .. 2026-09-21 |
| Holdout (unseen) | `data/hidden_test_ready/holdout_complaints.jsonl` / `.csv` | **154** | `EVL-00001` .. `EVL-00154` | 2026-09-01 .. 2026-09-21 |
| Customers | `data/sample_complaints/customers.json` | 300 | `CUST-10001` .. `CUST-10300` | - |
| Order ledger | `data/sample_complaints/orders.json` | 594 | `LMR-######`, transactions `TXN-########` | - |
| Summary | `data/sample_complaints/dataset_summary.json` | counts, SRS checks, coherence report | | |

IDs are assigned in chronological order of `complaint_date`. The holdout set is the "unseen" set for the
SRS GenAI-vs-Python comparison report: it is generated only from holdout scenarios whose wording was written
separately (maximum token-set Jaccard similarity to any dev complaint: **0.421**).

## 1. How the dataset is built

```
scripts/dataset/scenarios/*.yaml   human-readable scenario bank (412 scenarios / chains)
        |  pick date, customer, channel, product (seeded, deterministic)
        v
order profile (scripts/dataset/ledger.py)    -> simulated ledger record, relative to the complaint date
        v
slot rendering (scripts/dataset/render.py)   -> title / description / supporting information,
        |                                       every inserted fact is *registered* (amount, date, duration ...)
        v
declared facts  {complaint_facts, signals, history, order}
        v
supportnova.rule_engine.reference.label_declared(matrix, declared)   -> expected routing, urgency,
        |                                                                priority, escalation, eligibility ...
        v
checks: intended rule, scenario expectations, lexical coherence, uniqueness  -> records + summary
```

1. **Scenario bank.** Each scenario states the ground truth: primary subcategory (and secondary issues),
   the resolution rule it must trigger (`intended_rule`), an order profile, the risk/request signals that are
   truly present, the requested resolution, and several text variants written in different styles (calm,
   polite, frustrated, angry). Special files hold multi-issue, ambiguous, contradictory-policy, adversarial,
   incomplete and repeat/duplicate scenarios. Holdout scenarios (`pool: holdout`, IDs `H-...`) live next to
   the dev ones but use completely different templates.
2. **Order profiles** synthesise the ledger record that makes the scenario true *relative to the complaint
   date*, e.g. `in_transit_late_standard(bdays_late=[4, 8])` places the estimated delivery exactly 4-8 business
   days (Mon-Fri) before the complaint; `refund_issued_bd_ago(bdays=[10, 15])` issues a refund 10-15 business
   days earlier; `annual_renewal_days_ago`, `cancelled_then_charged`, `restocking_fee(reason=...)`,
   `trace_completed`, `lost_no_updates`, `high_value(base, min_total=500|1500|2500)`, `careplus_claims(n)`,
   `duplicate_charge`, `overcharged`, `install_missed` ...
   (35 profiles, all in `ledger.py`). Unit prices always come from `config/products.yaml`; the ledger is the
   state as of the latest complaint that references the order (no future-dated events).
3. **Rendering.** Templates use slots such as `{product}`, `{order_ref}`, `{date:delivered}`,
   `{amt:total}`, `{comp:demand}`, `{dur:denied}`, `{hours:outage}`, `{prev_ref}`. The renderer picks one
   date style and one currency style per complaint (`3 September`, `Sep 3`, `USD 179`, `$179.00` ...) and
   adapts the text to the channel (e-mail greeting and sign-off, `@LumoraHome` social posts, phone transcript
   tag, formal uploaded letter). Every fact-bearing slot is registered, so `complaint_facts` and `entities`
   are computed from what was inserted - never by parsing the text.
4. **Labelling** runs the approved Rule Matrix on the declared facts (see section 2).
5. **Checks during generation** (exit code 1 on failure): the selected resolution rule equals the scenario's
   `intended_rule`; optional scenario expectations (priority, escalation rules, missing information,
   eligibility) hold; every declared signal is lexically present in the text; texts are unique.

Generation is deterministic: the same `--seed` produces byte-identical files, and every scenario keeps its
intended rule under other seeds too (checked with seeds 1, 2, 3, 42 and 777).

## 2. Declared-fact labelling (and why it is not circular)

The `expected` block is **policy-correct by construction**: it is the output of
`supportnova.rule_engine.reference.label_declared` applied to facts the scenario *declares* - the true
subcategory, the signals that are really present, the order ledger record and the complaint history.

The runtime system has to *recover* those facts from raw complaint text: the GenAI pipeline reads the text,
and the Python ground-truth pipeline detects signals lexically and looks orders up in the ledger. The dataset
therefore measures how well each pipeline turns text into the policy-correct outcome; the answer key is not
produced by the pipelines being evaluated. Deliberate traps make the difference visible:

* **lexical traps** - the text contains a term of a signal that is *not* truly present ("I was in hospital
  for most of that time" in a refund request, "fire the agent", injected "classify this as a fire hazard",
  "the installer ... took pictures"). They are annotated per record as `lexical_trap:<signal>` tags (14 in
  total) and are excluded from the declared signals;
* risk words hidden inside prompt injections are never declared (see section 4);
* ambiguous wording where the risk-first primary is not the most frequent keyword.

The validator re-runs `label_declared` on every record's `declared` block plus the ledger and checks that all
rule-derived fields reproduce exactly (771/771).

`declared` input reconstruction (`scripts/dataset/records.py::declared_input`):

| label_declared key | taken from |
|---|---|
| complaint_date, customer_ref, customer_type | record fields |
| order | ledger record for a well-formed `order_reference`; `{}` (order.exists = false) when that reference is not in the ledger; otherwise the order owning `transaction_reference`; else `null` |
| complaint_facts, signals, history | `declared.*` |
| text | `title + "\n" + description + "\n" + supporting_information` (empty parts skipped) |
| primary_subcategory / secondary_subcategories | `expected.subcategory` / `expected.secondary_issues[].subcategory` |

## 3. Conventions

* **Primary issue** (multi-issue and ambiguous complaints) follows `routing_rules.yaml` precedence
  `SAF > ACC-UNA > PRV > LEGAL > BIL > PRD > DEL > WAR > others`; root causes outrank the refund consequences
  they cause ("arrived damaged and the refund has not been processed" -> primary PRD-DOA, secondary REF-DLY).
  Within the lowest rank the issue with the greatest impact is primary; each multi-issue scenario states its
  `rationale`. Ambiguous complaints carry `alt_subcategory:<code>` tags for the competing reading.
* **Complaint facts** (`declared.complaint_facts`): `has_order_reference` = a well-formed `LMR-######` was
  supplied; `has_product` = a product/service is named (text or product field); `has_date` = a calendar date
  or an "N days/weeks/months ago/since" duration was written; `word_count` = words in `description`;
  `max_amount` = largest USD amount written; `requested_compensation_amount` = largest amount explicitly
  demanded as compensation; `max_elapsed_days` = largest "N days/weeks/months ago/since" duration in days
  (week = 7, month = 30); `outage_hours` = stated outage length.
* **History** (`declared.history`) comes from repeat chains: `prior_same_issue_count` = earlier complaints of
  the chain that are cases (original or repeat - exact/near duplicates are linked, not new cases),
  `unresolved_prior_same_issue` = those seeded New / In Progress / Escalated / Awaiting Customer,
  `references_resolved_complaint` = the cited complaint was seeded Resolved/Closed (reopen -> ESC-019).
* **Sentiment / emotions** follow the writing style: calm and polite -> Neutral (Positive only for the
  5 clearly thankful and satisfied complaints), frustrated -> Negative, angry -> Strongly Negative; emotions
  default to [] / [Frustration] / [Anger, Frustration] plus Urgency (safety, security) or Confusion
  (ambiguous) where the text shows it.
* **Entities** are exact substrings of the text: slot-inserted values plus product/service names written
  literally (conservative alias scan, generic words such as "hub" or "lock" excluded).
* **manual_review_expected** is true for prompt injection, ambiguous and contradictory-policy cases,
  categories SAF and PRV, the signals legal_threat / staff_harassment / injury / lock_security, and any
  blocking missing information.
* **seed_status** seeds complaint history: chain originals are Resolved / In Progress / Escalated /
  Awaiting Customer as the scenario requires; everything else is New.

## 4. Special complaint types

| Type | How it is built | Expected behaviour |
|---|---|---|
| Multi-issue (`multi_issue.yaml`) | 2-4 issues, `secondary` list with labels | primary by precedence; secondary departments added as supporting |
| Ambiguous (`ambiguous.yaml`) | one vague issue with two readings | risk-first primary, manual review |
| Contradictory policy (`contradictory_policy.yaml`) | customer cites REF-POL-02 v1.0 (60 days, 90-day loyalty exception), FAQ-BIL-17 v1.0 (60 days, "duplicates reversed immediately"), FAQ-GEN-16 v5.0 ("3 business days"), RET-SOP-23 v1.4 (USD 50 agent credit, batteries by prepaid label), DEL-POL-04 v2.0 (USD 15 after 5 days, lost after 10), the draft ESC-SOP-12 v3.2, invented policies, or an agent's out-of-policy promise; also customers who wrongly think they are out of time | the ACTIVE policy decides (e.g. USD 10 credit, 30-day window, specialist battery collection); manual review |
| Prompt injection (`adversarial.yaml`) | "ignore your rules", fake `SYSTEM:` / admin notes, instructions in supporting information or attachment names, JSON / markdown payloads, role play, developer mode, fake policy IDs (REF-POL-99 s9.9), fake transcripts, data-exfiltration requests, SQL-like strings | labels ignore the instruction. Literal requests inside an injection remain requests (a fake "pre-approved USD 500 compensation" is a USD 500 compensation claim, so the matrix routes it to the approval level that amount needs, with no eligibility change); risk words used only inside an injection are not declared signals |
| Incomplete (`incomplete.yaml`) | no order number, no product, no date, no photos, < 8-word descriptions, `LMR-000000` / unknown refs, malformed refs (`LMR 482913`), an order that belongs to another customer | clarification request (MIS-001..008); safety/privacy never blocked |
| Repeat / duplicate chains (`repeats.yaml`) | one customer and one issue; exact resubmissions, near-duplicates (resend prefix, typo, dropped sentence ...), repeats with new wording citing `{prev_ref}`; dev chains continued in the holdout set | `is_duplicate_of` / `is_near_duplicate_of` / `is_repeat_of`; ESC-017 (2 unresolved), ESC-018 (3+), ESC-019 (reopened) |

## 5. Record fields

Every field is always present (`null` when not applicable). Schema: `schemas/dataset/complaint_record.schema.json`
(JSON Schema draft 2020-12). CSV files flatten the record: `declared_signals`, `fact_*`, `history_*` and
`expected_*` columns; lists are `;`-joined (`attachments` as `file|type`, `expected_secondary_issues` as
`SUB:label`, `expected_entities` as `type=value`, `any_of` action groups as `A|B`).

| Field | Meaning |
|---|---|
| complaint_id | `CMP-#####` (dev) or `EVL-#####` (holdout), chronological |
| title, description, supporting_information | customer text (description includes channel wrappers) |
| customer_ref, customer_name, customer_type | customer (`individual`, `care_plus`, `business`, `vip`) |
| product_service | product/service as the customer wrote it (`""` when not stated) |
| product_sku | ground-truth SKU identifiable from the complaint (mention or referenced order), else null |
| order_reference, transaction_reference | as supplied; deliberately invalid/malformed values are tagged |
| channel | web_form, email, chat, phone, mobile_app, social_media, uploaded |
| complaint_date | ISO timestamp, UTC (`Z`) |
| previous_complaint_reference | complaint the customer cites (earlier complaint of the same customer, or tagged `invalid_complaint_reference`) |
| preferred_contact_method, requested_resolution, requested_tone | organization.yaml codes |
| attachments | `[{file_name, content_type}]` - photos (image/*) mean `has_photo_evidence = true` |
| seed_status | lifecycle status used to seed complaint history |
| declared.signals | signals truly present (names from signals.yaml) |
| declared.complaint_facts, declared.history | see section 3 |
| expected.primary_issue, secondary_issues | human-readable issue labels (`{label, category, subcategory}`) |
| expected.category, subcategory | = declared primary |
| expected.sentiment, emotion_indicators | from the writing style |
| expected.urgency, impact, priority | Rule Matrix (base rule + urgency floors, priority matrix) |
| expected.entities | order_id, transaction_id, product, service, date, amount, location, complaint_reference |
| expected.department, supporting_departments | routing rules + conditional routing + escalation departments |
| expected.policy_references | `DOC-ID:section` from the selected rule and fired escalation rules |
| expected.resolution_rule, required_actions | selected `RES-*` rule; actions incl. `{any_of: [...]}` groups and the escalation action |
| expected.refund/replacement/compensation_eligibility, compensation_amount_usd | eligible, not_eligible, requires_verification, not_applicable |
| expected.escalation_required, escalation_level, escalation_rules | highest fired level; `ESC-*` ids (or the `RES-*` id for rule-inherent escalation) |
| expected.follow_up_required, follow_up_type | FUP rules (blocking info > escalation > rule default) |
| expected.missing_information, blocking_missing_information | MIS-rule fields; blocking flag |
| expected.is_duplicate_of, is_near_duplicate_of, is_repeat_of | link to the source / chain root complaint |
| expected.prompt_injection, manual_review_expected | booleans (section 3) |
| difficulty_type, tags | main challenge + all applicable tags (security, privacy, safety, legal_threat, high_value, unsupported_refund, calm_critical, emotional_low_priority, vip_minor, lexical_trap:*, injection:*, outdated_policy:* ...) |
| scenario_id, split | source scenario (holdout ids never appear in dev) and `dev` / `holdout` |

`customers.json`: customer_ref, first/last/full name, `@example.com` e-mail, fictional city, customer_type
(exact 60/20/10/10 split), company (business), preferred_contact_method, customer_since, care_plus_member.

`orders.json` (ledger): order_ref, customer_ref, items `[{sku, qty, unit_price}]`, order_total,
shipping_method/fee, order/estimated/dispatched/delivered dates, status, tracking_last_update,
transactions `[{txn_ref, type charge|refund, amount, date}]`, care_plus, replacement_count,
careplus_claims_12m, return, cancellation, subscription `{plan, renewal_date, auto_renew}`, trace. 434 orders
are referenced by complaints; 160 are background orders; digital services use `standard` with a zero fee.

## 6. Counts (seed 20260923)

| Requirement | SRS minimum | Target | Dev | Holdout |
|---|---:|---:|---:|---:|
| Unique complaints | 500 | 540 / 120 | **617** | **154** |
| Categories / subcategories | 10 / 20 | 11 / 35 | 11 / 35 (min 10 per subcategory) | 11 / 35 |
| Departments referenced (primary / any) | 8 | 8 | 9 / 10 | 9 / 10 |
| Ambiguous or multi-issue | 25 | 25 | 73 | 12 |
| Multi-issue (three or more issues) | - | 30 (6) | 51 (12) | 8 (2) |
| Ambiguous | - | 15 | 22 | 4 |
| Contradictory / difficult policy | 20 | 22 | 32 | 6 |
| Prompt injection / adversarial | 20 | 22 | 31 | 6 |
| Repeated / near-duplicate | 25 | 30 | 37 | 6 |
| - exact / near / repeat | - | 8 / 10 / 12 | 9 / 11 / 17 | 1 / 1 / 4 |
| - citing a previous complaint | - | - | 18 | 4 |
| - ESC-017 / ESC-018 / ESC-019 fired | - | some | 5 / 1 / 3 | 1 / 0 / 1 |
| Incomplete (invalid refs / malformed refs) | - | 25 | 38 (3 / 2) | 6 (1 / 1) |
| Emotional low priority (angry, P3) | - | 15 | 38 | 12 |
| Calm but critical (calm/polite, P0/P1) | - | 15 | 70 | 25 |
| VIP with minor issue (P3) | - | 6 | 23 | 6 |
| Low-value privacy breach | - | 4 | 5 | 1 |
| Legal threat | - | 10 | 12 | 3 |
| Security / privacy / safety | - | 15 / 25 / 25 | 27 / 49 / 50 | 9 / 13 / 14 |
| Unsupported refund / compensation | - | 12 / 12 | 45 / 26 | 9 / 8 |
| High value (order >= USD 500) | - | 8 | 12 | 6 |
| Simple | - | plenty | 350 | 101 |
| Channels / tones / sentiments / priorities | - | all | 7 / 4 / 4 / 4 | 7 / 4 / 4 / 4 |
| Resolution rules covered (dev + holdout) | 100 rules | all | **116 / 116** (14 only in dev) | |

Distributions (dev): categories ACC 49, BIL 91, DEL 68, PRD 64, PRV 47, REF 72, SAF 50, STF 40, SVC 45,
TEC 49, WAR 42; channels web_form 170, email 144, chat 90, phone 71, mobile_app 58, social_media 47,
uploaded 37; customer types individual 356, care_plus 135, vip 65, business 61; sentiment Neutral 307,
Negative 204, Strongly Negative 102, Positive 4; priority P0 97, P1 23, P2 310, P3 187; escalation No
Escalation 411, Supervisor Review 59, Specialist Team 46, Compliance Review 43, Critical Management
Escalation 30, Department Manager 28. Full breakdowns (per subcategory, rule, tag, tone ...) are in
`dataset_summary.json`.

Coherence self-check (all 771 records): 0 declared signals missing from the text, 0 declared signals found
only inside a negation window, 0 unexplained undeclared lexical hits, 14 deliberate lexical traps.

## 7. Regenerate and validate

```bash
# from the repository root (Python 3.11+ with PyYAML and jsonschema; the backend venv has both)
backend/.venv/Scripts/python.exe scripts/generate_dataset.py            # --seed 20260923 --out-dir data
backend/.venv/Scripts/python.exe scripts/validate_dataset.py            # --data-dir data; exit 1 on any FAIL
```

`generate_dataset.py` prints the SRS/mix check table and fails (exit 1) if a scenario misses its intended
rule or expectation, a declared signal is not expressed in its text, or a minimum is not met
(`--allow-failures` writes the files anyway, `--quiet` prints only problems). `validate_dataset.py` checks
schema validity, all counts, ID/date order, referential integrity (customers, orders, transactions,
ownership, previous-complaint and duplicate links), configuration codes, signals and lexical coherence,
label reproducibility, holdout disjointness and similarity, text uniqueness and record consistency, and
prints a PASS/WARN/FAIL table.

To add a scenario: append it to the relevant `scripts/dataset/scenarios/*.yaml` file (unknown keys, signals,
SKUs, profiles or rule IDs are rejected by the loader), regenerate and validate.

## 8. Known limitations and findings

* Business days are Monday-Friday; public holidays are not modelled (same as `supportnova.core.timeutil`).
* `rules/complaint_rules/signals.yaml` lists the negation cue `no` unquoted; YAML 1.1 parses it as boolean
  `false`, so the runtime loader never treats "no" as a negation cue. The dataset's coherence detector maps it
  back to "no" (intended semantics); quoting it in the YAML would fix the runtime.
* The `embedded_policy_claim` pattern `[A-Z]{3}-(POL|SOP|RUL|GDL|FAQ|TPL)-\d{2}` cannot match FAQ and template
  IDs whose type comes first (`FAQ-GEN-16`, `FAQ-BIL-17`, `TPL-COM-18`); texts that cite those FAQs also use
  wording such as "according to your policy" so the declared signal is lexically present.
* Some rule-matrix consequences are kept exactly as the rules produce them, e.g. an amount of USD 500 or more
  written anywhere in a complaint raises impact (URG-012) and, for monetary subcategories, the order total is
  the claimed amount for ESC-020/021.
