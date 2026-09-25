# GenAI vs Python comparison - unseen holdout cases (SRS Deliverable 8)

* Evaluation run **#1** on dataset `holdout` - **154 unseen cases** (holdout scenarios never used for tuning the rules or prompts).
* GenAI provider / model: `openai` / `gpt-4.1-mini`
* Prompt versions: `{"complaint_analysis": "1.2.0", "customer_communication": "1.0.0"}` - ruleset hash `be81124c2a1df0d5`
* Duration: 858.0 s (p50 21167 ms / p95 33805 ms per complaint, full pipeline)

## Headline

| Metric | Value |
|---|---|
| cases | 154 |
| verified rate | 0.1429 |
| ai errors caught | 92 |
| manual review rate | 0.8442 |
| ai error catch rate | 0.9892 |
| ai key field accuracy | 0.7917 |
| ai python key agreement | 0.7061 |
| ai cases with key errors | 93 |
| python key field accuracy | 0.8268 |

## Accuracy against the expected labels, per field

| Field | Python (Pipeline 2) | GenAI (Pipeline 1) | GenAI-Python agreement | n |
|---|---|---|---|---|
| urgency | 84.2% | 68.4% | 66.5% | 152 |
| category | 75.7% | 89.5% | 69.7% | 152 |
| priority | 88.8% | 62.5% | 61.2% | 152 |
| department | 84.9% | 92.1% | 84.9% | 152 |
| subcategory | 68.4% | 77.6% | 58.6% | 152 |
| follow_up_type | 75.7% | 44.1% | 39.5% | 152 |
| resolution_rule | 75.0% | 0.0% | 0.0% | 152 |
| escalation_level | 94.1% | 84.9% | 82.9% | 152 |
| policy_references | 76.3% | 5.9% | 5.9% | 152 |
| refund_eligibility | 93.4% | 60.5% | 62.5% | 152 |
| escalation_required | 94.7% | 92.8% | 91.5% | 152 |
| missing_information | 77.0% | 59.2% | 47.4% | 152 |
| supporting_departments | 74.3% | 73.7% | 61.8% | 152 |
| replacement_eligibility | 93.4% | 85.5% | 82.9% | 152 |
| compensation_eligibility | 95.4% | 79.0% | 76.3% | 152 |

## Safety nets

* Prompt injection: {'missed': 0, 'recall': 1.0, 'expected': 6, 'precision': 1.0, 'detected_tp': 6, 'false_positives': 0}
* Manual review: {'both': 48, 'actual': 130, 'recall': 0.9412, 'expected': 51}
* Duplicates: {'linked': 2, 'expected': 2} - repeats: {'detected': 4, 'expected': 4}
* Verification outcomes: {'Verified': 22, 'Duplicate': 2, 'Manual Review': 130}

## By difficulty type

| Type | n | Python all key fields right | GenAI all key fields right | Verified | Manual review |
|---|---|---|---|---|---|
| repeat | 4 | 1 | 1 | 0 | 4 |
| simple | 101 | 67 | 44 | 15 | 86 |
| ambiguous | 4 | 1 | 0 | 0 | 4 |
| vip_minor | 1 | 0 | 1 | 0 | 1 |
| high_value | 2 | 1 | 0 | 0 | 2 |
| incomplete | 6 | 5 | 4 | 0 | 6 |
| multi_issue | 8 | 7 | 3 | 2 | 6 |
| near_duplicate | 1 | 1 | 1 | 0 | 0 |
| exact_duplicate | 1 | 1 | 1 | 0 | 0 |
| prompt_injection | 6 | 3 | 1 | 0 | 6 |
| unsupported_refund | 4 | 2 | 1 | 1 | 3 |
| contradictory_policy | 6 | 5 | 2 | 2 | 4 |
| emotional_low_priority | 9 | 6 | 2 | 2 | 7 |
| unsupported_compensation | 1 | 0 | 0 | 0 | 1 |

The per-case table (complaint ID, expected / GenAI / Python category, department, urgency, escalation, policy reference, match, verification status and the explanation of every disagreement) is in `genai-python-comparison.pdf|xlsx|csv` next to this file.
