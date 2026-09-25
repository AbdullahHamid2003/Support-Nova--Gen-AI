import type { ComplaintSummary } from '@/lib/types'

export interface ReviewItem {
  id: number
  status: string
  reason_codes: string[]
  reasons: { code: string; rule_id?: string; name: string; message?: string; detail?: string }[]
  priority: string | null
  assigned_to_id: number | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  final_decision: string | null
  complaint: ComplaintSummary | null
  actions: { action: string; comment: string; actor: string; at: string; payload: Record<string, unknown> }[]
}

export const REASON_LABELS: Record<string, string> = {
  ai_python_category_mismatch: 'AI and rules disagree on the category',
  critical_validation_failure: 'A critical check failed',
  low_verification_score: 'Verification score too low',
  missing_policy_support: 'No policy supports the decision',
  ambiguous_complaint: 'Unclear complaint',
  escalation_unclear: 'Escalation level unclear',
  policy_contradiction: 'Conflicting policy information',
  sensitive_case: 'Sensitive case needs human approval',
  invalid_ai_output: 'No usable AI answer',
  prompt_injection_detected: 'Attempt to manipulate the AI',
  unsupported_promise: 'Response makes unsupported promises',
  hallucination_detected: 'Unsupported claims',
  unknown_category: 'Unknown category',
  reference_mismatch: 'Order not found for this customer',
  pipeline_error: 'Processing error',
}
