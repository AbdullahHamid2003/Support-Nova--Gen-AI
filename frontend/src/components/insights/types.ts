/* Response shapes shared by the evaluation, evaluation-run and reports pages
   (backend: services/evaluation.py run_json / compute_metrics). */

export interface EvaluationHeadline {
  cases: number
  python_key_field_accuracy: number | null
  ai_key_field_accuracy: number | null
  ai_python_key_agreement: number | null
  verified_rate: number | null
  manual_review_rate: number | null
  ai_errors_caught: number
  ai_cases_with_key_errors: number
  ai_error_catch_rate: number | null
}

export interface FieldMetric {
  n: number
  ai_ok: number | null
  python_ok: number | null
  ai_vs_python: number | null
}

export interface DifficultyMetric {
  n: number
  python_key_match: number
  ai_key_match: number
  verified: number
  review: number
}

export interface EvaluationMetrics {
  headline?: EvaluationHeadline
  fields?: Record<string, FieldMetric>
  verification?: Record<string, number>
  prompt_injection?: { expected: number; detected_tp: number; missed: number; false_positives: number; recall: number | null; precision: number | null }
  manual_review?: { expected: number; actual: number; both: number; recall: number | null }
  duplicates?: { expected: number; linked: number }
  repeats?: { expected: number; detected: number }
  by_difficulty?: Record<string, DifficultyMetric>
  latency_ms?: { p50: number | null; p95: number | null; max: number | null }
  rejected_at_intake?: number
  settings?: { ai_max_retries?: number }
}

export interface EvaluationRun {
  id: number
  status: string
  split: string
  label: string
  provider: string
  model: string
  fault_injection: string | null
  prompt_versions: Record<string, string> | null
  ruleset_hash: string | null
  n_cases: number
  n_done: number
  metrics: EvaluationMetrics | null
  error: string | null
  duration_seconds: number | null
  created_at: string | null
  completed_at: string | null
}

export interface EvaluationRunList {
  items: EvaluationRun[]
}
