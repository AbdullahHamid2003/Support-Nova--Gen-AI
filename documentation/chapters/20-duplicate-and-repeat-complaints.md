# Chapter 20 — Duplicate and Repeat Complaints

SRS Step 52 requires SupportNova to detect exact duplicates, near-duplicate complaints and repeated submissions. Step 53 requires the complaint history of each simulated customer to be kept, and Step 54 requires repeated unresolved complaints to be identified so that they "may receive higher escalation priority". The SRS 1.8(13) Repeat Complaint Challenge adds that a previously unresolved complaint may be resubmitted "using substantially different wording". Duplicate detection also appears in complaint validation (Step 10) and pre-processing (Step 11), and in functional requirements lvi to lviii. SupportNova handles these cases with deterministic Python only. No GenAI call is involved in deciding that two complaints are related, and a linked duplicate never reaches the model at all.

## 20.1 Three relationships and how the system responds

SupportNova distinguishes three relationships between a new complaint and a customer's earlier complaints. Table 20.1 summarises them.

**Table 20.1 — Relationships and responses**

| Relationship | Detected by | When | Result |
|---|---|---|---|
| Exact duplicate at intake | Same text hash, same customer, within `DUPLICATE_WINDOW_HOURS` (24 h) | `POST /api/v1/complaints` | HTTP 409 `duplicate_complaint`; no complaint is created |
| Exact or near duplicate | Same text hash, or similarity of at least `NEAR_DUPLICATE_THRESHOLD` (0.86), among the customer's complaints of the last 90 days | Pipeline preprocessing | Linked to the original and closed; no AI call |
| Repeat complaint | A related earlier complaint of the same customer | Pipeline preprocessing | Marked as a repeat; history counts feed urgency and escalation rules |

The thresholds are configuration settings (`.env.example`, `core/config.py`). The look-back window and the repeat thresholds are Rule Matrix parameters in `rules/parameters.yaml`: `repeat_window_days` = 90, `repeat_supervisor_threshold` = 2 and `repeat_manager_threshold` = 3, all from ESC-SOP-12 section 4.5, and `reopen_window_days` = 14 from CHP-POL-01 section 8.2. Figure 20.1 shows the decision sequence.

![Figure 20.1 — Duplicate and repeat decision](diagrams/pipelines/fig-20-01-duplicate-repeat-decision.svg)
*Figure 20.1 — Duplicate and repeat decision*

## 20.2 Normalisation, hashing and similarity

Two deterministic representations are computed for every complaint when it is created (`create_complaint` in `backend/src/supportnova/services/complaints.py`).

The **text hash** is the SHA-256 of a canonical form of the title and the normalised description (`security/sanitization.py`). `normalize_text` applies NFKC normalisation, removes invisible and control characters, strips HTML, unifies quotation marks and dashes and collapses whitespace. `canonical_for_hash` then lower-cases the text and replaces every run of non-alphanumeric characters with a single space. Differences in capitals, punctuation, spacing or hidden characters therefore do not change the hash. `tests/backend/unit/test_perception_security.py::test_normalisation_and_duplicate_hash` checks that "Order LATE!!  Please   help" containing a zero-width space and "order late please help" give the same hash. The hash is stored in the indexed column `complaints.text_hash`.

The **similarity vector** is a 512-dimension vector from the local feature-hashing embedder in `knowledge_base/embeddings.py` (`similarity_vectors`). The embedder uses stemmed words, word pairs and character trigrams with signed hashing, logarithmic term frequency and L2 normalisation. It is a classic information-retrieval technique, not a neural model. It needs no API key and gives identical results on every machine, so a duplicate decision can always be reproduced. The vector is stored in `complaints.embedding`, and the similarity of two complaints is the dot product of their vectors, that is, their cosine similarity.

## 20.3 Exact duplicates at intake

When a customer, or an agent on a customer's behalf, submits a complaint through the API, `create_complaint` looks for a complaint of the same customer with the same text hash created within the last `DUPLICATE_WINDOW_HOURS`. The check runs when `REJECT_EXACT_DUPLICATES` is true (the default). If such a complaint exists, the request fails with HTTP 409, error code `duplicate_complaint`, the message "This complaint was already submitted as CMP-…" and the original reference in `details.duplicate_of`, and no complaint is created. The submission form calls `POST /api/v1/complaints/validate` while the customer types and shows "Looks like a duplicate … Submitting again will not open a second case" before the complaint is sent. This precheck compares the hash with all of the customer's complaints, without the time window.

Bulk imports of the demonstration dataset and evaluation runs skip the intake check, because every record must be kept and scored. For them, and for web complaints that repeat an older complaint outside the 24-hour window, duplicates are handled in preprocessing.

## 20.4 Linked duplicates and repeats in preprocessing

During preprocessing the pipeline calls `analyse_history` in `backend/src/supportnova/services/history.py` for every complaint that belongs to a known customer. The function reads that customer's complaints dated within `repeat_window_days` before the new complaint, up to the 50 most recent. The history scope keeps test data apart from operational data. An operational complaint never sees evaluation or Adversarial Lab records. An evaluation case sees the operational history, read-only, plus earlier cases of its own run. A lab case sees operational and lab records. For each earlier complaint, most recent first, the function applies the following tests in order.

1. **Exact duplicate:** the text hash is the same.
2. **Near duplicate:** the similarity is at least 0.86.
3. **Related complaint:** the new complaint's previous-complaint reference names it, both complaints share an order reference, both have the same primary subcategory, or both are in the same category with a similarity of at least `REPEAT_SIMILARITY_THRESHOLD` (0.30).

When any earlier complaint in the history matches test 1 or 2, the new complaint is linked as a duplicate of the most recent match, and an exact duplicate is preferred over a near duplicate. The pipeline marks it `is_duplicate`, stores `duplicate_of_id`, writes a history event on both complaints and an audit entry `complaint.duplicate_linked`, and closes it. The stored history message for CMP-00018 reads "Linked as near-duplicate (similarity 0.913) of CMP-00012; no second case opened (CHP-POL-01 s7.1)." The pipeline then stops before retrieval, so no GenAI call is made and no second SLA, escalation or response is created for the same problem. Linking only happens for new submissions, imports, evaluation and lab runs. When a complaint is re-analysed after reopening, clarification, reclassification, regeneration or an agent's re-run, linking is switched off.

When earlier complaints match only test 3, the new complaint is a **repeat**. `analyse_history` computes three history facts: the number of related earlier complaints (`prior_same_issue_count`), how many of them are still unresolved (`unresolved_prior_same_issue`) and whether the complaint reopens a resolved one (`references_resolved_complaint`). The last fact is true when the previous-complaint reference names a Resolved or Closed complaint, or when the text contains repeat language (the `repeat_indicator` signal, for example "still not fixed" or "already complained") and a related complaint was resolved within the 14-day reopen window. The complaint is marked `is_repeat`, with `repeat_of_id` pointing to the most recent related complaint. The pipeline's history event records the link, for example "repeat of CMP-00190 (1 unresolved)" for CMP-00215.

The history also reaches the model and the agent. The verified facts in the analysis prompt list up to six earlier complaints of the last 90 days with reference, date, subcategory, status and order. The case page shows a "Customer history" card with the similarity of each earlier complaint and links to the related complaint, and the complaint list can be filtered on `repeat` and `duplicate`. When a customer gives a previous-complaint reference at submission, `validate_submission` checks that the complaint exists and belongs to the same customer. A customer therefore cannot attach another customer's complaint to their own.

## 20.5 Effect on priority and escalation

The three history facts are ordinary facts of the rule engine, so the Rule Matrix decides what a repeat means. Table 20.2 lists the rules that use them.

**Table 20.2 — Rules that use complaint history**

| Rule | Condition | Effect |
|---|---|---|
| URG-011 | Unresolved earlier complaints on the same issue ≥ 2 | Urgency at least High, impact Medium (priority P2 or higher) |
| ESC-017 | Unresolved earlier complaints ≥ 2 | Supervisor Review |
| ESC-018 | Unresolved earlier complaints ≥ 3 | Department Manager |
| ESC-019 | The complaint reopens a resolved complaint | Supervisor Review (failed resolution) |
| RES-SVC-SUP-02 | Repeat language, or at least one earlier complaint on the issue | Support failure: review interaction records, link the previous complaint |
| RES-SVC-INS-02 | At least one earlier complaint, or a failed re-visit described in the text | Installation fee refund review with Supervisor Review |

A complaint with two or more unresolved earlier complaints on the same issue therefore receives at least High urgency, the SLA of its raised priority (Chapter 19) and an escalation. This is the "higher escalation priority" of SRS Step 54. The thresholds are parameters, so changing the repeat threshold from two to three is a data change. In the stored decisions of the demo database, ESC-017 fired 9 times, ESC-018 once and ESC-019 4 times (Chapter 18).

## 20.6 Measured results

Duplicate and repeat detection was measured on two data sets whose records carry labels for the expected relationship (`is_duplicate_of`, `is_near_duplicate_of`, `is_repeat_of`). Table 20.3 shows the results. Both the number of relationships detected and whether the link points to the labelled complaint were checked.

**Table 20.3 — Measured duplicate and repeat detection**

| Data set | Relationship | Labelled | Detected | Linked to the labelled complaint |
|---|---|---|---|---|
| Holdout, 154 unseen cases (evaluation run #1) | Exact duplicate | 1 | 1 | 1 |
| | Near duplicate | 1 | 1 | 1 |
| | Repeat | 4 | 4 | 3 |
| Development set, 617 complaints (demo database) | Exact duplicate | 9 | 9 | 9 |
| | Near duplicate | 11 | 9 linked, 2 flagged as repeats | 8 |
| | Repeat | 17 | 17 | 10 |

On the holdout set, the evaluation summary reports duplicates "linked 2 of 2" and repeats "detected 4 of 4" (`reports/genai_python_comparison/summary.md`). The case-level check behind Table 20.3 confirms that the exact duplicate EVL-00059 was linked to EVL-00043 and the near duplicate EVL-00068 to EVL-00058 (similarity 0.911). Three of the four repeats point to the labelled earlier complaint. The fourth, EVL-00154, points to CMP-00602 instead of the labelled CMP-00581; both are earlier complaints of the same customer, and the system picks the most recent. Two further holdout cases without a repeat label, EVL-00016 and EVL-00125, were also flagged as repeats.

On the development set, all nine exact duplicates were linked to their labelled originals. Of the eleven near duplicates, eight were linked to the labelled original. CMP-00411 was linked to CMP-00406, which is itself an exact duplicate of the labelled original CMP-00403. The rewording of CMP-00242 and CMP-00440 brought their similarity to 0.819 and 0.841, below the 0.86 threshold, so both were flagged as repeats of the labelled originals instead of being closed as duplicates. The near-duplicate links in the database have similarities between 0.872 and 0.95. All seventeen labelled repeats were flagged. Ten point to the labelled complaint and seven to a more recent complaint of the same chain; for example, CMP-00604 points to CMP-00584, which is itself a repeat of the labelled CMP-00534. Five further complaints were flagged as repeats without a label. In total the demo database holds 20 linked duplicates (18 from the dataset, 2 from the holdout run), each with its audit entry.

## 20.7 Tests

- `tests/backend/integration/test_difficult_cases.py::test_exact_duplicate_rejected_and_near_duplicate_linked`: a second, identical submission for the same customer is refused with HTTP 409 and `details.duplicate_of` equal to the first complaint. A reworded version ("constantly" replaced by "all the time") is linked as a duplicate and Closed.
- `tests/backend/integration/test_difficult_cases.py::test_repeated_complaint_detected`: a second complaint about the same app crash, with the first complaint as its previous reference, is marked as a repeat and lists the first complaint as related.
- `tests/backend/unit/test_perception_security.py::test_normalisation_and_duplicate_hash`: formatting differences do not change the hash.

The integration tests use the offline GenAI test double. Duplicate and repeat detection involves no model, so the tests exercise the same code that produced the measured results.

## 20.8 Limitations

- **Customer identity.** Detection works only for complaints linked to a known customer profile. A complaint submitted by staff without a customer reference is not checked, and the same person under two profiles is not recognised.
- **Exact hashing.** The hash is exact after normalisation, so a single changed word defeats the intake check. The near-duplicate link then catches the resubmission, as long as the similarity stays at 0.86 or above.
- **Fixed thresholds.** The two similarity thresholds were set for this dataset. Stronger rewording turns a near duplicate into a repeat (CMP-00242, CMP-00440). The 0.30 threshold, combined with the same-category test, also flags some unrelated complaints of the same customer as repeats (five in the development set, two in the holdout set).
- **Most recent link.** `repeat_of` points to the most recent related complaint, not to the first complaint of a chain.
- **No analysis of duplicates.** A linked duplicate is closed without its own analysis. A small addition to an otherwise identical text, such as a new symptom, is visible only through the link on the original case.
- **Shared lab customer.** All Adversarial Lab scenarios use one fictional lab customer (CUST-99001), so later lab runs see earlier lab complaints as history. This is why the delivery scenario LAB-DEF-05 (case LAB-00017) was also escalated to Supervisor Review by ESC-017: earlier lab complaints of the same customer on the same issue were still unresolved.
