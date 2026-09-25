# Chapter 10 — Complaint Resolution Rule Matrix

The Complaint Resolution Rule Matrix (Rule Matrix) is the deterministic ground truth of SupportNova. It encodes, as data rather than code, the complaint-handling logic contained in the approved policies of Lumora Home Technologies: for every complaint subcategory it states which department owns the case, how urgent and how important it is, which escalation is mandatory, which actions are required, recommended or prohibited, whether a refund, replacement or compensation may be offered, which follow-up is due and which timelines a customer may be told. The Python Ground-Truth Validation Pipeline (Pipeline 2) evaluates these rules for every complaint; the GenAI Complaint Intelligence Pipeline (Pipeline 1) never creates, edits or approves them. The Rule Matrix is therefore the third element of the principle that governs the whole system: **GenAI proposes. Python validates. Ground truth decides.**

This chapter describes how a rule is structured, the condition language in which rule conditions are written, the rule types and their counts, how the rules are derived from the approved documents, how conflicts between rules are resolved, how the matrix protects its own integrity, how the Python pipeline consumes it and how it is changed at runtime without a code change.

## 10.1 Role of the Rule Matrix in SupportNova

SRS Step 8 requires a structured rule matrix that represents the approved complaint-handling logic and that is not generated at runtime by the same GenAI model that resolves complaints. SupportNova meets this requirement by keeping the matrix as version-controlled YAML files under `rules/` (14 files) and `config/` (organisation, taxonomy, departments, products and the action catalogue). The loader `backend/src/supportnova/rule_engine/loader.py` reads the 19 files into one *bundle*, and `build_matrix()` turns the bundle into an immutable, typed `RuleMatrix` object defined in `backend/src/supportnova/rule_engine/models.py`. **Implemented.**

The YAML files are the baseline; the live, editable copy is held in the database. On first start `seed_from_yaml()` in `backend/src/supportnova/services/rules.py` writes every rule into the table `rules`: 276 rule rows of ten rule types and 14 configuration rows (for example the priority matrix, the validation policy, the signals and the 59 parameters). The taxonomy, departments and products are stored in their own tables (11 categories, 35 subcategories, 10 departments, 15 products). At runtime `RuleService.matrix()` rebuilds the `RuleMatrix` from the database whenever the system setting `rules_revision` changes and otherwise serves it from memory; in the demonstration database the revision counter stands at 16, one seed plus fifteen audited changes. Both the YAML baseline and the database copy produce the same kind of bundle, so the baseline can be restored at any time (Section 10.9). **Implemented.**

The Knowledge Base and the Rule Matrix are related but distinct. The Knowledge Base holds the approved documents (24 documents, 29 versions) and supplies evidence and citations; the Rule Matrix holds the decision criteria derived from those documents. The two are joined by the policy references carried by every rule and by the source section recorded for every parameter (Section 10.5). Figure 10.1 shows the matrix, its sources and its consumers.

![Figure 10.1 — Rule Matrix sources, live copy and consumers](diagrams/pipelines/fig-10-01-rule-matrix-architecture.svg)
*Figure 10.1 — Rule Matrix sources, live copy and consumers*

Pipeline 1 receives only vocabulary from the matrix: the prompt builder `reference_values()` in `backend/src/supportnova/genai_pipeline/context.py` passes the taxonomy codes, department codes, action codes, escalation level names, the priority matrix and the follow-up types, together with the text of the approved routing and service-level policies (RTE-RUL-14 sections 3 to 5 and SLA-RUL-15 sections 5 and 6) taken from the Knowledge Base (Chapter 22). The resolution, escalation and urgency-floor rules and the decision that the Python pipeline computes from them are never sent to the model, and the analysis is complete before Pipeline 2 starts. No code path allows Pipeline 1 to write to the `rules` table; rule changes require an authenticated user with the `rules:manage` permission, which only the administrator role holds (`backend/src/supportnova/security/rbac.py`).

In the colour convention used for every figure in Chapters 10 to 15, green boxes are deterministic Python steps, purple boxes are GenAI steps, blue cylinders are data stores, orange boxes are people and red boxes are rejections or defects.

## 10.2 Anatomy of a Resolution Rule

A resolution rule describes one way of handling one subcategory. Every subcategory has between two and five resolution rules: one unconditional default rule and up to four conditional rules that describe more specific situations. The fields of a rule and their relation to the fields required by SRS Deliverable 5 are listed in Table 10.1.

**Table 10.1 — Fields of a resolution rule and the SRS Deliverable 5 matrix fields**

| Deliverable 5 field | Representation in SupportNova | Source of the value |
|---|---|---|
| Rule ID | `rule_id`, pattern `RES-<subcategory>-NN` | `rules/complaint_rules/resolution_rules.yaml` |
| Category | Derived from the subcategory | `config/taxonomy.yaml` (11 categories) |
| Subcategory | `subcategory` | 35 subcategory codes |
| Conditions | `when` (Section 10.3) and `precedence` (Section 10.6) | resolution rule |
| Department | Primary and supporting departments of the subcategory's routing rule; optional `department` and `supporting_departments` on the rule | `rules/routing_rules/routing_rules.yaml` (Chapter 13) |
| Urgency | `urgency` (base value that urgency floors may raise) | resolution rule, `priority_rules.yaml` (Chapter 14) |
| Priority | `impact`; priority = `priority_matrix[urgency][impact]` | `priority_rules.yaml`, SLA-RUL-15:4 |
| Policy | `policy_refs` in the form `DOC-ID:section` | Knowledge Base section identifiers |
| Escalation | `escalation` (level inherent to the rule); global escalation rules add mandatory levels | `rules/escalation_rules/escalation_rules.yaml` |
| Required actions | `required_actions`, which may contain `any_of` groups | `config/actions.yaml` (66 action codes) |
| Prohibited actions | `prohibited_actions` | action codes and the 12 prohibited behaviours |
| Follow-up | `follow_up` with `required`, `type` and `due_hours` | one of the 6 follow-up types |
| Eligibility (additional) | `eligibility.refund`, `.replacement`, `.compensation` | resolution rule, `rules/parameters.yaml` |
| Timelines (additional) | `timelines`, the parameter keys a response may quote | `rules/parameters.yaml` |

The category and the department are not repeated inside each resolution rule. The category follows from the taxonomy, and the department comes from the routing rule of the subcategory, so that a department change is made once for all rules of a subcategory. The loader supports a `department` override on a resolution rule, but none of the 116 rules uses it; 16 rules add supporting departments. The export endpoint `GET /api/v1/rules/export` resolves these indirections and writes the Deliverable 5 columns (Rule ID, Category, Subcategory, Conditions, Department, Supporting, Urgency, Impact, Priority, Policy, Escalation, Required actions, Prohibited actions, Follow-up, Status) as CSV, Excel, PDF or YAML; the exported deliverable is `reports/rule_matrix/complaint_resolution_rule_matrix.{csv,xlsx,pdf,yaml}` with 155 rows (116 resolution and 39 escalation rules). **Implemented.**

The following rule, quoted verbatim from `rules/complaint_rules/resolution_rules.yaml`, handles a smart-lock incident. It is the rule that decided the real case CMP-00616 examined in Chapter 11.

```yaml
  - rule_id: RES-ACC-UNA-03
    name: Smart-lock security incident
    subcategory: ACC-UNA
    precedence: 40
    when: {signal: lock_security}
    urgency: Critical
    impact: High
    supporting_departments: [DEPT-MGT]
    required_actions: [VERIFY_IDENTITY, ADVISE_PHYSICAL_KEY, REVIEW_ACCOUNT_ACTIVITY, REVOKE_SESSIONS, ESCALATE_CRITICAL_MANAGEMENT]
    prohibited_actions: [REQUEST_SENSITIVE_CREDENTIALS, DISMISS_SAFETY_CONCERN]
    eligibility: {refund: not_applicable, replacement: not_applicable, compensation: not_applicable}
    escalation: Critical Management Escalation
    follow_up: {required: true, type: Escalation acknowledgement, due_hours: 1}
    timelines: [security_response_hours]
    policy_refs: ["SEC-POL-09:5.1", "SEC-POL-09:5.2", "SEC-POL-09:5.3"]
```

Eligibility uses four values: `eligible`, `not_eligible`, `requires_verification` and `not_applicable`. Compensation can also be a mapping that fixes the type of compensation and either an amount or a ceiling, and amounts are always parameter references rather than literal numbers. The delivery-delay rule below grants the store credit defined by `delay_credit_usd` (USD 10, DEL-POL-04:5.2):

```yaml
  - rule_id: RES-DEL-DLY-02
    name: Standard order delayed more than 3 business days - delay credit
    subcategory: DEL-DLY
    precedence: 20
    when: {fact: eligibility.delay_qualifies, op: eq, value: true}
    urgency: High
    impact: Medium
    required_actions: [VERIFY_SHIPMENT_STATUS, CONTACT_CARRIER, OFFER_STORE_CREDIT]
    prohibited_actions: [UNSUPPORTED_DELIVERY_DEADLINE, GUARANTEE_COMPENSATION]
    eligibility: {refund: not_applicable, replacement: not_applicable, compensation: {status: eligible, type: store_credit, amount_usd: "$param:delay_credit_usd"}}
    escalation: No Escalation
    follow_up: {required: true, type: Resolution confirmation, due_hours: 72}
    timelines: []
    policy_refs: ["DEL-POL-04:5.1", "DEL-POL-04:5.2", "CPN-POL-11:6"]
```

Action codes come from the catalogue `config/actions.yaml`, which defines 66 actions in 13 groups (verification 13, information 3, logistics 9, billing 9, compensation 3, technical 6, warranty 2, security 4, privacy 4, safety 4, service 3, escalation 5, follow-up 1) and 12 prohibited behaviours. Each prohibited behaviour, for example `PROMISE_REFUND_BEFORE_VERIFICATION` or `DISMISS_SAFETY_CONCERN`, carries a severity, the policy sections that forbid it and regular-expression patterns with which the Python pipeline detects it in generated text (Chapters 11 and 15). A rule may list either kind of code under `prohibited_actions`: RES-PRD-DOA-03 prohibits the action `SHIP_REPLACEMENT` as well as the behaviour `GRANT_POLICY_EXCEPTION`.

## 10.3 The Three-Valued Condition Language

Rule conditions are written in a small declarative language implemented in `backend/src/supportnova/rule_engine/conditions.py`. A condition is a YAML mapping; nothing in the matrix is executed as code, and the module never uses `eval`. The grammar, quoted from the module's documentation string, is:

```text
    {}                                         -> True
    {all: [c1, c2]} / {any: [..]} / {not: c}   -> combinators
    {signal: name} / {any_signal: [..]} / {all_signals: [..]}
    {subcategory_in: [..]} / {category_in: [..]}
    {text_matches: "<regex>"}
    {escalation_level_at_least: "<level name>"}
    {secondary_issues: true}
    {fact: "order.business_days_late", op: gt, value: 3 | "$param:key" | [..]}
      op in: eq ne in not_in gt gte lt lte exists not_exists contains between
```

Facts are addressed by dotted paths in eight namespaces: `complaint` (text-derived facts such as `has_order_reference` or `requested_compensation_amount`), `order` (facts from the simulated order ledger), `customer`, `eligibility` (derived windows such as `within_refund_window`), `history` (repeat facts), `case`, `classification` and `sla`. Signals are named risk and intent indicators detected in the complaint text by `rules/complaint_rules/signals.yaml` (35 signals, with negation cues such as "no" or "never" suppressing a match within three tokens). A value written as `$param:<key>` is resolved from `rules/parameters.yaml` at evaluation time, so a threshold is changed in one place.

The essential property of the language is three-valued logic. Every condition evaluates to `True`, `False` or `None`, where `None` means *unknown*: a fact that the condition needs has not been established, for example because the customer gave no order reference. `all` returns `False` as soon as one part is false and `None` if any part is unknown; `any` returns `True` as soon as one part is true and `None` if any part is unknown; `not` keeps an unknown result unknown. The decision engine uses this to avoid guessing. A rule whose condition is unknown is recorded as *pending verification*, and every eligibility dimension on which a pending rule disagrees with the selected rule becomes `requires_verification` (Section 10.8). Table 10.2 shows the behaviour asserted by the unit test `tests/backend/unit/test_rule_engine.py::test_three_valued_conditions`.

**Table 10.2 — Three-valued evaluation, as tested by test_three_valued_conditions**

| Condition | Facts and signals supplied | Result |
|---|---|---|
| `order.days_since_delivery lte 30` | 10 days since delivery | `True` |
| `order.days_since_delivery lte 30` | 45 days since delivery | `False` |
| `order.days_since_delivery lte 30` | no delivery date known | `None` (requires verification) |
| `all` of the above condition and `signal: overheating` | 10 days, overheating detected | `True` |
| `any` of `signal: fire_event` and the above condition | no fire signal, no delivery date | `None` |
| `not` of `signal: fire_event` | no fire signal | `True` |
| `order.days_since_delivery lte $param:refund_window_days` | 25 days, parameter value 30 | `True` |

Across all rule conditions in the matrix the most frequent constructs are fact comparisons with `eq` (76), signal tests (58), `all` combinators (33), regular-expression tests with `text_matches` (15), `any` combinators (13), `gte` comparisons (12) and `subcategory_in` tests (12). The function `describe()` renders any condition in readable form, for example `(eligibility.within_doa_window = True) AND (complaint.has_photo_evidence = True)`; this rendering appears in the Rule Matrix page, the Rule simulator, the decision trace and the exported matrix. The functions `referenced_facts()` and `referenced_signals()` list what a condition depends on, which the integrity validator uses to detect references to undefined signals (Section 10.7). **Implemented, Tested.**

## 10.4 Rule Types and Counts

The matrix contains ten types of rule rows. Table 10.3 lists them with the counts measured by loading the baseline with the project's own loader; the same counts are stored in the database table `rules`.

**Table 10.3 — Rule types in the Complaint Resolution Rule Matrix**

| Rule type | File | Rows | Identifiers | Role | Status |
|---|---|---|---|---|---|
| Resolution | `complaint_rules/resolution_rules.yaml` | 116 | RES-PRD-DOA-01 … RES-STF-MIN-03 | Handling, eligibility, actions and follow-up per subcategory | Configured |
| Escalation | `escalation_rules/escalation_rules.yaml` | 39 | ESC-001 … ESC-039 | Mandatory escalation conditions, levels and departments | Configured |
| Routing | `routing_rules/routing_rules.yaml` | 35 | RTE-001 … RTE-035 | Primary and supporting department per subcategory | Configured |
| Conditional routing | `routing_rules/routing_rules.yaml` | 6 | RTE-101 … RTE-106 | Supporting departments added by signals or escalation level | Configured |
| Urgency floor | `complaint_rules/priority_rules.yaml` | 15 | URG-001 … URG-015 | Minimum urgency and impact for risk signals and facts | Configured |
| Category | `complaint_rules/category_rules.yaml` | 35 | CAT-PRD-DOA … CAT-STF-MIN | Weighted terms for the deterministic classifier | Configured |
| Missing information | `complaint_rules/missing_info_rules.yaml` | 8 | MIS-001 … MIS-008 | Required information and clarification topics | Configured |
| Follow-up | `complaint_rules/followup_rules.yaml` | 4 | FUP-001 … FUP-004 | Global follow-up rules that override or add to rule follow-ups | Configured |
| SLA | `sla_rules/sla_rules.yaml` | 4 | SLA-P0 … SLA-P3 | First-response and resolution targets per priority | Configured |
| Review | `complaint_rules/review_rules.yaml` | 14 | REV-001 … REV-014 | Manual-review triggers | Configured |
| **Total rule rows** | | **276** | | | |

The 14 configuration rows complete the matrix: `escalation_config` (the six escalation levels and the six required fields of escalation notes), `routing_precedence`, `priority_config` (levels, the priority matrix and the principles URG-100 to URG-102), `category_settings`, `missing_info_config`, `followup_config`, `sla_config`, `signals` (35 signals and the sentiment lexicon), `parameters` (59 parameters), `response_rules`, `precedence_rules`, `validation_policy` (52 checks and the scoring policy), `actions` (66 actions and 12 prohibited behaviours) and `organization`.

Several identifier prefixes are shared between rules and validation checks: routing rule RTE-001 (PRD-DOA to DEPT-RET) is not the same thing as check RTE-001 (primary department matches the routing rules), escalation rule ESC-001 (fire, smoke or explosion) is not check ESC-001 (required escalation identified), and the missing-information rules MIS-001 to MIS-008 and follow-up rules FUP-001 to FUP-004 share prefixes with checks MIS-001, MIS-002, FUP-001 and FUP-002. This report always states whether a rule or a check is meant.

The SRS Hint requires at least 100 structured complaint-resolution rules and at least 30 mandatory escalation rules or conditions. The matrix contains 116 and 39, which the unit test `tests/backend/unit/test_rule_engine.py::test_rule_matrix_meets_srs_minimums` asserts together with the minimum numbers of categories, subcategories and departments. **Tested.** The resolution rules cover all 35 subcategories: 3 subcategories have two rules (ACC-UPD, TEC-APP, PRV-DSR), 21 have three, 8 have four and 3 have five (PRD-MAL, DEL-DLY, REF-REQ); 35 rules are unconditional defaults and 81 are conditional. 32 rules carry an escalation level of their own (9 Supervisor Review, 8 Critical Management Escalation, 7 Compliance Review, 6 Specialist Team and 2 Department Manager; for example RES-WAR-DEN-01 requires Supervisor Review for every warranty-denial appeal), 22 list recommended actions and two use `any_of` groups (RES-PRD-DOA-02 and RES-DEL-LST-02).

The escalation rules are evaluated for every complaint independently of the resolution rule, so that a mandatory escalation cannot be lost when the complaint is classified under an unexpected subcategory. Table 10.4 groups them by trigger. The quoted rule shows the compact flow-mapping style in which escalation, routing and floor rules are written:

```yaml
  - {rule_id: ESC-010, name: Smart-lock unexplained unlock, trigger: security, when: {signal: lock_security}, level: Critical Management Escalation, departments: [DEPT-SEC, DEPT-MGT], policy_refs: ["ESC-SOP-12:4.2", "SEC-POL-09:5.3"], reason: "Physical home security compromised (unexplained smart-lock event)."}
```

**Table 10.4 — Escalation rules by trigger**

| Trigger | Rules | Examples |
|---|---|---|
| Safety | 8 | ESC-001 fire, smoke or explosion; ESC-004 injury; ESC-005 child involved in a safety incident |
| Policy exception | 5 | ESC-028 refund outside the window; ESC-029 and ESC-030 compensation above approval limits |
| Privacy | 4 | ESC-012 data or footage exposed; ESC-014 overdue data-rights request |
| High value | 4 | ESC-020 USD 500 or more; ESC-021 USD 1,500 or more; ESC-023 high-value lost order |
| Security | 3 | ESC-009 unauthorized access; ESC-010 smart-lock unlock; ESC-011 fraudulent payment |
| Repeat | 3 | ESC-017 two prior unresolved; ESC-018 three or more; ESC-019 reopened complaint |
| Staff | 3 | ESC-032 harassment or discrimination; ESC-033 technician damage or theft |
| Critical impact | 2 | ESC-025 critical impact; ESC-026 vulnerable person with critical impact |
| Reputational | 2 | ESC-035 media threat; ESC-036 chargeback threat |
| Legal, service failure, replacement failure, warranty appeal | 1 each | ESC-016, ESC-024, ESC-037, ESC-038 |
| SLA | 1 | ESC-039 SLA breach on P0 or P1, marked `runtime_only` and enforced by the SLA monitor (`backend/src/supportnova/services/sla.py`) |

By level, 13 escalation rules require Supervisor Review, 7 Department Manager, 7 Specialist Team, 6 Compliance Review and 6 Critical Management Escalation. Escalation behaviour is described in Chapter 18; this chapter concerns only its representation in the matrix.

## 10.5 Derivation from Approved Documents

Every rule is traceable to the approved documents from which it was derived. All 116 resolution rules and all 39 escalation rules carry `policy_refs`, and the rule rows together cite 177 distinct `DOC-ID:section` references in 20 documents, from the Refund Policy REF-POL-02 to the Escalation Procedure ESC-SOP-12. The integrity validator enforces the reference format with the pattern `^[A-Z]{3}-[A-Z]{3}-\d{2}:\d+(\.\d+)*$`.

Numeric thresholds are never written into rules. They live in `rules/parameters.yaml`, where each of the 59 parameters records its value, unit, description and the policy section that defines it; the parameters cite 50 distinct sections in 16 documents. The first entries of the file read:

```yaml
parameters:
  # ---- Refunds (REF-POL-02 v2.0) --------------------------------------------
  refund_window_days:            {value: 30,  unit: calendar_days, source: "REF-POL-02:3.1", description: Standard refund window from delivery date.}
  care_plus_refund_window_days:  {value: 45,  unit: calendar_days, source: "REF-POL-02:3.2", description: Extended refund window for Care+ members.}
  defect_refund_window_days:     {value: 30,  unit: calendar_days, source: "REF-POL-02:3.3", description: Defective products - refund or replacement window before the warranty process applies.}
```

Four mechanisms keep the documents and the rules consistent.

1. **Build-time cross-check of the documents.** The Knowledge Base sources are rendered to PDF, DOCX and Markdown by `scripts/build_knowledge_base.py`, which validates each Active version against `knowledge_base/kb_spec.yaml`. The specification contains 353 must-state statements in 259 sections of the 24 documents; for REF-POL-02 section 3.1 it requires the sentence "Products may be returned for a refund within 30 calendar days of the delivery date.", the same value that `refund_window_days` takes from REF-POL-02:3.1. The special check `_check_routing_table()` requires section 3 of the Department Routing Rules RTE-RUL-14 to reproduce `routing_rules.yaml` row by row, with the header "Rule ID | Category | Subcategory | Primary department | Supporting departments", so the published routing policy and the routing rules cannot drift apart. **Implemented.**
2. **Runtime check against the active Knowledge Base.** `POST /api/v1/rules/validate` passes the section index of the Active document versions to the integrity validator, which reports a warning for any policy reference that does not resolve. Run read-only against the demonstration database (386 active section keys), the current matrix produces 0 errors and 0 warnings. **Implemented.**
3. **Impact analysis when a policy is revised.** When a new document version becomes Active, `impact_analysis()` in `backend/src/supportnova/services/documents.py` lists the changed sections, the resolution and escalation rules that cite them and the parameters whose source section changed. When the old parameter value was replaced by a new number, the parameter is flagged `out_of_sync` with a `suggested_value`; the administrator then changes the parameter, and the change is audited. The rules are never altered automatically. The integration test `tests/backend/integration/test_defects_and_live_changes.py::test_revised_policy_upload_versioning_and_impact` uploads the hidden-pack document `REF-POL-02_v2.1.pdf` and asserts that sections 3.1, 3.2 and 4.3 are reported as changed and that `refund_window_days` is flagged with the suggested value 21. **Tested.**
4. **Rule-guided retrieval.** The retriever in `backend/src/supportnova/knowledge_base/retriever.py` adds the sections cited by the resolution and routing rules of the candidate subcategories to the evidence search, so the policy text given to Pipeline 1 is steered by the same references that the rules use (Chapter 9). **Implemented.**

The dataset's expected labels are produced by the same matrix. The reference labeler `backend/src/supportnova/rule_engine/reference.py` applies the Rule Matrix to the facts *declared* by the dataset author for each scenario (primary subcategory, signals really present, order record, history), whereas the runtime pipeline has to *detect* those facts from the complaint text. The evaluation of Chapter 12 therefore measures how well each pipeline recovers the policy-correct outcome from text and is not circular. The unit test `tests/backend/unit/test_rule_engine.py::test_reference_labels_reproduce_dataset` re-labels the first 150 dataset records and asserts that the result equals the stored labels. **Tested.**

## 10.6 Precedence

Three kinds of precedence decide which rule applies when several could.

### 10.6.1 Rule Selection within a Subcategory

When the `RuleMatrix` is built, the active rules of each subcategory are sorted by descending `precedence` and then by rule identifier. `DecisionEngine.select_rule()` evaluates them in that order and selects the first rule whose condition is `True`; every rule met earlier whose condition is unknown is recorded as pending. Because each subcategory has an unconditional default rule with precedence 10, some rule is always selected. The precedence values express specificity: the more specific a situation, the higher its precedence. Across the 116 rules the values are 10 (35 rules), 20 (29), 25 (2), 30 (33), 35 (2), 40 (14) and 50 (1). Table 10.5 shows the chain for damaged-on-arrival complaints.

**Table 10.5 — Precedence chain for subcategory PRD-DOA (Damaged on Arrival)**

| Order | Rule | Precedence | Condition | Refund / replacement | Key actions |
|---|---|---|---|---|---|
| 1 | RES-PRD-DOA-04 | 50 | `order.is_hazardous = True` | requires verification | ADVISE_STOP_USING, ARRANGE_SPECIALIST_COLLECTION; ISSUE_RETURN_LABEL prohibited |
| 2 | RES-PRD-DOA-02 | 30 | within 7-day DOA window AND photo evidence | eligible / eligible | SHIP_REPLACEMENT or PROCESS_REFUND, ISSUE_RETURN_LABEL |
| 3 | RES-PRD-DOA-03 | 20 | outside the 7-day window | not eligible / not eligible | VERIFY_ORDER; SHIP_REPLACEMENT prohibited |
| 4 | RES-PRD-DOA-01 | 10 | always (default) | requires verification | VERIFY_ORDER, REQUEST_PHOTO_EVIDENCE |

A damaged lithium-battery product is therefore handled by the hazardous-goods rule even when the report also falls inside the seven-day window; that rule, which cites RPL-POL-03:6.1 and SAF-POL-10:5.2, prohibits the prepaid return label and the postal return of the battery and requires a specialist collection instead.

### 10.6.2 Risk-First Primary Issue

When a complaint contains several issues, the deterministic classifier in `backend/src/supportnova/complaint_processing/perception.py` applies the routing precedence of RTE-RUL-14 section 5, configured as `order: [SAF, ACC-UNA, PRV, LEGAL, BIL, PRD, DEL, WAR]` in the `routing_precedence` row. A candidate from a higher-ranked group becomes the primary issue if its score reaches `precedence_min_score` (4.0), even when another candidate scores higher; the displaced issue is kept as a secondary issue. The unit test `tests/backend/unit/test_perception_security.py::test_risk_precedence_beats_higher_scoring_issue` asserts that a late delivery that "overheated and started smoking" is classified as SAF with a DEL secondary issue. The `LEGAL` entry of the order is not matched by the classifier, whose candidates carry only category and subcategory codes; legal threats are handled instead by urgency floor URG-008, escalation rule ESC-016 and conditional routing rule RTE-102 (Chapter 14). **Implemented, Tested.**

### 10.6.3 Combining Floors and Escalations

Urgency floors can only raise urgency and impact, never lower them: the engine keeps the higher of the current value and the floor value (`_max_level` in `backend/src/supportnova/rule_engine/decision.py`). When several escalation rules fire, the highest-ranked level applies and the departments of every fired rule are informed, as ESC-SOP-12 section 7 requires. A rule-inherent escalation is added only when no global rule has already fired at the same level. These combinations are monotonic, so adding a rule can make a decision stricter but never weaker.

### 10.6.4 Document Precedence

Precedence between documents, as opposed to rules, is configured in `rules/precedence/precedence_rules.yaml`: document types rank policy and rules first, then SOP, guideline, FAQ and template (PRC-002), a later effective date prevails within the same type and topic (PRC-003), and outdated versions are never primary evidence (PRC-004). These rules govern retrieval and conflict detection in the Knowledge Base (Chapter 9) and the policy checks POL-002 and POL-006 of Chapter 11.

## 10.7 Integrity Validation

A matrix that references an unknown department or a missing parameter would fail at runtime or, worse, silently decide wrongly. The function `validate_matrix()` in `backend/src/supportnova/rule_engine/integrity.py` therefore checks the whole matrix before any version of it is used. Table 10.6 summarises what it reports.

**Table 10.6 — Integrity checks performed by validate_matrix()**

| Area | Reported as error | Reported as warning |
|---|---|---|
| Resolution rules | Duplicate rule ID; unknown subcategory, department, action code, prohibited action, timeline parameter or follow-up type; invalid urgency, impact or escalation level | Rule without required actions |
| Conditions (all rule types) | Malformed condition; unknown parameter; undefined signal; unknown subcategory or category | Fact outside the eight known namespaces |
| Coverage | Active subcategory without resolution rules, without a default rule or without a routing rule | Subcategory without a classification rule |
| Routing and escalation | Unknown department; routing rule for an unknown subcategory; duplicate escalation ID; invalid level | — |
| Policy references | Malformed `DOC-ID:section` reference | Reference not found in the active Knowledge Base (when an index is supplied) |
| Priority and SLA | Missing or invalid priority for any urgency and impact pair; missing SLA rule for P0 to P3; non-positive or inconsistent SLA targets | — |
| Parameters and classifier | Signal or product boost referring to an undefined signal or SKU | Parameter source that is not a policy reference |

The validator is called in five places: `POST /api/v1/rules/validate` (with the Knowledge Base index), every rule, configuration or parameter change before it is saved, the reset to the YAML baseline, the creation of a new subcategory, and the unit test `tests/backend/unit/test_rule_engine.py::test_rule_matrix_integrity`. A result with any error blocks the change (Section 10.9). For the current matrix the result is 0 errors and 0 warnings, both for the YAML baseline and for the live database copy, and the Rule Matrix page shows the badge "Integrity valid" (Figure 10.3). **Implemented, Tested.**

The validator does not reject unexpected keys. In the compact flow-mapping style, an unquoted comma inside a `name` ends the value, so four display names are shortened when the YAML is parsed: ESC-001 ("Fire"), ESC-021 ("High-value dispute (USD 1"), ESC-032 ("Staff harassment") and URG-001 ("Fire"), each with a stray key holding the rest of the text. The conditions, levels and departments of these rules are unaffected and the full wording survives in the `reason` field, but the shortened names appear in the Rule Matrix page. The fix is to quote the names; an unknown-key warning in the validator would catch the pattern in future.

## 10.8 How the Python Pipeline Consumes the Rules

The class `DecisionEngine` in `backend/src/supportnova/rule_engine/decision.py` evaluates the matrix for one complaint. Its method `decide(ctx, primary, secondary)` receives an evaluation context (facts, signals and normalised text built by the fact builder, Chapter 11), the reference subcategory and any secondary subcategories, and computes the outcome in a fixed order:

1. **Resolution rule.** Select the highest-precedence rule whose condition is true and record the pending rules (Section 10.6.1).
2. **Urgency, impact and priority.** Start from the rule's urgency and impact, apply every urgency floor whose condition is true, and look up the priority in the priority matrix (Chapter 14).
3. **Primary department.** Take the rule's department override if present, otherwise the routing rule's primary department (Chapter 13).
4. **Escalation.** Evaluate every active escalation rule except `runtime_only` ones, substitute `$primary_department`, keep the highest rank and add the rule-inherent escalation if needed.
5. **Supporting departments.** Collect them from the routing rule, the resolution rule, the primary departments of secondary issues, conditional routing and the fired escalation rules, excluding the primary department.
6. **Actions.** Take the rule's required, recommended and prohibited actions, add the action code of the escalation level (for example `ESCALATE_CRITICAL_MANAGEMENT`) when it is not already required, and add the required actions of the secondary issues' rules as recommendations.
7. **Eligibility.** Take the rule's refund, replacement and compensation values; set a dimension to `requires_verification` where a pending rule disagrees; resolve compensation amounts and ceilings from the parameters.
8. **Missing information.** Evaluate the eight missing-information rules; blocking gaps never block safety or privacy complaints or ACC-UNA (`never_block_categories`, `never_block_subcategories`).
9. **Follow-up.** Apply FUP-001 when information is blocking (24 hours), otherwise FUP-002 when an escalation is required (due at the SLA first-response target), otherwise the rule's own follow-up.
10. **Policy references, timelines and SLA.** Merge the rule's references with those of the fired escalation rules, expand the rule's timeline parameters with their values, units and sources, and attach the SLA targets of the priority.

The result is a `Decision` object in which every value carries the rule identifiers that produced it, and a `trace` of plain sentences such as "Resolution rule RES-ACC-UNA-03 selected (signal:lock_security)." and "Escalation ESC-010 fired: Physical home security compromised (unexplained smart-lock event). -> Critical Management Escalation.". The trace is shown in the case view and in the Rule simulator. The unit test `tests/backend/unit/test_rule_engine.py::test_decision_engine_trace_is_explainable` asserts that a DEL-DLY decision carries a department, a RES-DEL-DLY rule and a non-empty trace. **Implemented, Tested.**

Every matrix carries a `ruleset_hash`, the first 16 hexadecimal characters of the SHA-256 digest of its canonical bundle, and every analysis, validation result and evaluation run stores the hash of the matrix it used. The YAML baseline hashes to `62789e435529c023`. The database copy hashes differently because its bundle is assembled from the stored rows, each with its active flag and in identifier order: it was `be81124c2a1df0d5` for the holdout evaluation run and for the case CMP-00616, and it is `2ce6e64257758104` after the audited wording change of 25 September 2026 (Section 10.9). Rebuilding the database bundle with the "before" images stored in the audit log for that change reproduces `be81124c2a1df0d5` exactly, which shows that any stored decision can be traced to the precise rule set that produced it.

## 10.9 Live Modification

SRS section 1.8 (14) requires teams to add categories, routing rules and departments, change priority logic, escalation thresholds and SLAs, and add validation rules during the evaluation. In SupportNova these changes are data changes made through the application; each is validated before it is saved, versioned and audited, and it applies to the next decision without a restart. Figure 10.2 shows the workflow implemented by `RuleService` in `backend/src/supportnova/services/rules.py`.

![Figure 10.2 — Validated, versioned and audited change of the Rule Matrix](diagrams/pipelines/fig-10-02-rule-change-workflow.svg)
*Figure 10.2 — Validated, versioned and audited change of the Rule Matrix*

For every change the service first builds a *candidate* matrix: the live bundle is read from the database, the change is applied to that copy, `build_matrix()` constructs a `RuleMatrix` from it and `validate_matrix()` checks it. If the candidate has an integrity error the change is rejected with HTTP 422 and the issues are returned; nothing is stored. If the candidate is valid, the row is saved with its version number increased by one, an audit entry records the body before and after the change together with any integrity warnings, the `rules_revision` setting is increased and the cached matrix is discarded, so the next complaint is decided by the changed rules. The audit log is append-only and hash-chained (`backend/src/supportnova/audit/service.py`). Table 10.7 lists the supported operations.

**Table 10.7 — Rule Matrix change operations**

| Operation | API (prefix `/api/v1`) | Permission | Safeguard | Audit action | Evidence | Status |
|---|---|---|---|---|---|---|
| Edit or create a rule | `PUT /rules/{rule_type}/{rule_id}` | `rules:manage` | Candidate matrix; 422 on error | `rule.created`, `rule.updated` | `test_rule_edit_preview_validates_without_saving` | Implemented, Tested |
| Activate or deactivate a rule | `POST /rules/{rule_type}/{rule_id}/active` | `rules:manage` | Candidate matrix | `rule.updated` | `test_disabling_an_escalation_rule_changes_validation` | Implemented, Tested for escalation rules; effective only for resolution and escalation rules (see below) |
| Change a parameter | `PUT /rule-parameters/{key}` with value and reason | `rules:manage` | Candidate matrix | `rule.config_updated`, `rule.parameter_changed` | `test_changing_a_rule_parameter_changes_the_decision` | Implemented, Tested |
| Edit a configuration row, for example the priority matrix | `PUT /rules/config/{config_id}` | `rules:manage` | Candidate matrix | `rule.config_updated` | Recorded change of 25 September 2026 | Implemented |
| Preview an edit without saving | `POST /rules/validate` with a rule body | `rules:read` | Candidate only; no write, no revision, no audit | none | `test_rule_edit_preview_validates_without_saving` | Implemented, Tested |
| Simulate a complaint | `POST /rules/simulate` | `rules:read` | Python pipeline only; nothing stored | none | `test_changing_a_rule_parameter_changes_the_decision`, `test_new_category_without_code_changes` | Implemented, Tested |
| Add a category, subcategory or department | `POST /taxonomy/categories`, `/taxonomy/subcategories`, `/taxonomy/departments` | `taxonomy:manage` | A subcategory is created with its routing, default resolution and classification rules in one validated transaction | `taxonomy.category_created`, `taxonomy.subcategory_created`, `taxonomy.department_created` | `test_new_category_without_code_changes` | Implemented, Tested |
| Reset to the YAML baseline | `POST /rules/reset-to-baseline?confirm=true` | `rules:manage` | Reseed and integrity report | `rules.reset_to_baseline` with previous and new hash | — | Implemented |
| Export the matrix | `GET /rules/export` (CSV, Excel, PDF or YAML) | `rules:read` | Read only | none | `reports/rule_matrix/` | Implemented |

The integration tests in `tests/backend/integration/test_defects_and_live_changes.py` exercise these operations through the real API. `test_changing_a_rule_parameter_changes_the_decision` simulates a return request for a Halo speaker delivered 25 days earlier, changes `refund_window_days` from 30 to 21 and asserts that the refund eligibility changes to `not_eligible`, then restores the value. `test_rule_edit_preview_validates_without_saving` sends escalation rule ESC-010 with the invalid level "Galactic Escalation" to the preview and asserts that the report is invalid while the ruleset hash, the rule version and the number of audit entries are unchanged; saving the same body is then refused with HTTP 422. `test_disabling_an_escalation_rule_changes_validation` deactivates the first escalation rule that fires for a complaint containing a legal threat and asserts that it no longer fires. `test_new_category_without_code_changes` creates the category ENV and the subcategory ENV-RCY with a routing rule and keywords, and asserts that the Rule simulator classifies a recycling question as ENV-RCY and routes it. These tests run against a dedicated test database and answer GenAI calls with the offline test double in `tests/support/offline_llm.py`; the rule operations themselves involve no GenAI. **Tested.**

The active flag has a limitation that the tests do not cover. Every rule row stores `is_active`, and the Rule Matrix page offers an active switch for every rule type, but only two types honour it: an inactive resolution rule is left out of rule selection, and an inactive escalation rule is skipped by the decision engine. For routing, conditional routing, urgency-floor, category, missing-information, follow-up, SLA and review rules, `build_matrix()` loads inactive rows like active ones, and `finalize()` reads the separate `enabled` field of a review rule rather than its active flag. Building a matrix with URG-001, RTE-101, MIS-001, FUP-001 and REV-008 marked inactive confirms that all five remain in force. Until the loader filters inactive rows of every type, these rules are switched off by editing or removing them, and a review trigger by setting `enabled: false` in its body.

The demonstration database contains a real audited change. On 25 September 2026 the demo administrator, a fictional seeded user, updated the `validation_policy` configuration row to version 2 and the review rules REV-001 to REV-014 to version 2, producing 15 audit entries (14 `rule.updated`, 1 `rule.config_updated`). A comparison of the stored before and after images shows that only display text changed: check, trigger and dimension names were reworded (for example "GenAI and Python disagree on category" became "AI and rules disagree on the category"), and the name of check HAL-001, which the YAML parser had split at a comma, was repaired. The dimension of each check, the severities, the severity weights and the threshold of 80 are identical in both versions.

The user interface for these operations is the Rule Matrix page under Policies and rules (Figure 10.3). Its summary cards show the rules in force (276 of 276) with the ruleset hash, the 116 resolution rules covering 35 subcategories, the 39 escalation rules with five escalation levels above No Escalation, and the 59 policy parameters, each traced to a policy section. The tabs Rules, Rule simulator, Parameters, Signals, Configuration and Taxonomy give access to every rule type with its rendered condition, outcome, version and an active switch. The JSON editor offers Validate and Save. Its Validate button runs the integrity check of the live matrix and states that unsaved changes are not included and are checked on save; the unsaved-edit preview is therefore available through the API, where it is tested, but not yet from the editor button. A rejected save shows the integrity issues with the message "The live Rule Matrix is unchanged." A parameter change asks for a reason, which the audit log records with the old and new value. Agents, reviewers, managers and administrators can read the matrix; only administrators can change it.

![Figure 10.3 — Rule Matrix page with the resolution rules and the integrity badge](../screenshots/17-rule-matrix.png)
*Figure 10.3 — Rule Matrix page with the resolution rules and the integrity badge*

The Rule simulator runs only the deterministic Python pipeline, signals, classification, Rule Matrix and order ledger, on any text entered by the user; it calls no GenAI provider and stores nothing, so the effect of a rule change can be seen immediately. Figure 10.4 shows the example "Calm wording, real hazard": a customer writes that there is "no rush at all" about a smart plug that gave off sparks and a small electric shock. The simulator detects the `electrical_hazard` signal, classifies the complaint as SAF-ELC with high confidence, selects RES-SAF-ELC-01, sets P0 with Critical urgency and High impact, fires escalation rules ESC-003 and ESC-007 at Specialist Team level, and notes that sentiment and customer type never change priority (URG-100, URG-101).

![Figure 10.4 — Rule simulator deciding a calmly worded electrical hazard without GenAI](../screenshots/18-rule-simulator.png)
*Figure 10.4 — Rule simulator deciding a calmly worded electrical hazard without GenAI*

## 10.10 Requirement Coverage

Table 10.8 relates the SRS requirements for the Rule Matrix to the implementation.

**Table 10.8 — SRS requirements for the Complaint Resolution Rule Matrix**

| SRS requirement | How SupportNova meets it | Status |
|---|---|---|
| Step 8: structured matrix of approved complaint-handling logic, not generated at runtime by the GenAI model | YAML baseline in `rules/` and `config/`, live copy in table `rules`, no GenAI write path | Implemented, Configured |
| 1.6 (xi): structured ground-truth rules maintained | 276 rule rows, 14 configuration rows, versioned and audited edits | Implemented, Tested |
| Deliverable 5: Rule ID, category, subcategory, conditions, department, urgency, priority, policy, escalation, required and prohibited actions, follow-up | Rule fields and export columns (Table 10.1), `reports/rule_matrix/` | Implemented |
| Hint: at least 100 resolution rules and 30 mandatory escalation rules | 116 and 39, asserted by `test_rule_matrix_meets_srs_minimums` | Configured, Tested |
| 1.8 (5): new category processed by configuration | Taxonomy endpoints create routing, resolution and classification rules | Implemented, Tested |
| 1.8 (14): add a routing rule, change priority logic, add a department, change an escalation threshold, modify an SLA | Rule, configuration and parameter edits (Table 10.7) | Implemented; parameter and escalation changes Tested |
| 1.8 (14): add a new validation rule | New rules of existing kinds (escalation, prohibited-behaviour patterns, signals, missing information) are data; a new kind of validation check requires code in `backend/src/supportnova/python_validation/engine.py` | Partially Configured |
| 1.8 (15): diagnose and correct defects in escalation rules and policy mapping | Integrity validation, simulator, decision trace and ruleset hash | Implemented, Tested |

The Rule Matrix thus supplies the criteria; Chapter 11 describes how the Python Ground-Truth Validation Pipeline applies them to every GenAI answer.
