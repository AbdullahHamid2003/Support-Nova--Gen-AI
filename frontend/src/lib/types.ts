/* API response shapes (subset actually used by the UI). */

export type Role = 'customer' | 'agent' | 'reviewer' | 'manager' | 'admin'

export interface User {
  id: number
  email: string
  full_name: string
  role: Role
  department: string | null
  customer_ref: string | null
}

export interface Session {
  user: User
  permissions: string[]
  csrf_token?: string
}

export interface Option {
  code: string
  name: string
  description?: string
}

export interface PublicConfig {
  organization: { name?: string; short_name?: string; tagline?: string; [k: string]: unknown }
  channels: Option[]
  customer_types: Option[]
  preferred_contact_methods: Option[]
  requested_resolutions: Option[]
  response_tones: Option[]
  reference_formats: Record<string, string>
  categories: { code: string; name: string; subcategories: Option[] }[]
  departments: Option[]
  products: { sku: string; name: string; type: string }[]
  escalation_levels: string[]
  statuses: string[]
  verification_statuses: string[]
  /** configured is false only when the server has no AI API key */
  ai: { provider: string; model: string; configured: boolean }
  limits: { max_attachment_mb: number; max_upload_mb: number }
}

export interface ComplaintSummary {
  complaint_ref: string
  title: string
  status: string
  channel: string
  created_at: string
  updated_at: string
  complaint_date: string
  department: string | null
  category: string | null
  subcategory: string | null
  processing_stage: string
  resolved_at: string | null
  customer_ref?: string | null
  customer_name?: string | null
  customer_type?: string
  category_code?: string | null
  subcategory_code?: string | null
  department_code?: string | null
  urgency?: string | null
  priority?: string | null
  sentiment?: string | null
  escalation_level?: string | null
  escalation_required?: boolean
  verification_status?: string
  verification_score?: number | null
  needs_review?: boolean
  sla_state?: string | null
  is_duplicate?: boolean
  is_repeat?: boolean
  injection_detected?: boolean
  ai_python_agreement?: boolean | null
  assigned_agent?: string | null
  source?: string
  product_sku?: string | null
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Check {
  code: string
  name: string
  dimension: string
  severity: 'critical' | 'major' | 'minor' | 'info'
  status: 'pass' | 'warn' | 'fail' | 'not_applicable'
  message: string
  expected: unknown
  actual: unknown
  rule_refs: string[]
  policy_refs: string[]
}

export interface ComparisonRow {
  field: string
  ai: unknown
  python: unknown
  match: 'match' | 'partial' | 'mismatch'
  explanation: string
}

export interface EvidenceItem {
  evidence_id: string
  chunk_uid: string
  doc_id: string
  title: string
  doc_type: string
  version: string
  status: string
  effective_date: string | null
  section_id: string
  heading: string
  page_start: number | null
  page_end: number | null
  text: string
  score: number
  methods: string[]
  precedence_rank: number
}

export interface Timeline {
  param: string
  value: number
  unit: string
  source: string
  text: string
}

export interface ValidatedDecision {
  classification: {
    category: string | null
    subcategory: string | null
    category_name: string | null
    subcategory_name: string | null
    secondary: string[]
    source: string
    ai_category: string | null
    ai_subcategory: string | null
    python_candidates: { subcategory: string; category: string; score: number; matched: string[] }[]
  }
  department: string | null
  supporting_departments: string[]
  urgency: string
  impact: string
  priority: string
  urgency_sources: string[]
  sla: Record<string, unknown>
  escalation: {
    required: boolean
    level: string
    fired: { rule_id: string; level: string; reason: string; departments?: string[]; policy_refs?: string[] }[]
    departments: string[]
    notes: Record<string, unknown> | null
  }
  eligibility: {
    refund: string
    replacement: string
    compensation: string
    compensation_type: string | null
    compensation_amount_usd: number | null
    compensation_max_usd: number | null
    pending_rule_ids: string[]
    notes: string[]
  }
  required_actions: (string | { any_of: string[] })[]
  recommended_actions: string[]
  prohibited_actions: string[]
  resolution_steps: { action_code: string; description: string; policy_ref: string | null; source: string }[]
  excluded_ai_steps?: { action_code: string; description: string; reason: string }[]
  customer_steps: string[]
  follow_up: { required?: boolean; type?: string; due_hours?: number; source_rule?: string }
  missing_information: { rule_id: string; field: string; label: string; blocking: boolean; question: string }[]
  clarification_questions: string[]
  policy_refs: string[]
  timelines: Timeline[]
  selected_rule: { rule_id: string | null; name: string | null; condition: string | null }
  pending_rules: string[]
  trace: { step: string; detail: string; [k: string]: unknown }[]
  applicability: { evidence_id: string | null; ref: string; doc_id: string; version: string; section_id: string; heading: string; applicability: string; reason: string }[]
  summary: string
  key_facts: string[]
  /** set when sentences repeating flagged embedded instructions were left out of the summary */
  summary_note?: string | null
  safety: boolean
  agent_guidance: { ai_recommendation: string[]; validated: string[]; human: string[] }
}

export interface ResponseDraft {
  id: number
  version_no: number
  kind: string
  tone: string
  subject: string
  body: string
  status: string
  source: string
  validation: { issues?: { code: string; severity: string; text: string; message: string }[]; [k: string]: unknown }
  created_at: string
  sent_at: string | null
  sent_via: string | null
}

export interface ComplaintDetail extends ComplaintSummary {
  description: string
  supporting_info: string
  product_text: string
  order_ref: string | null
  transaction_ref: string | null
  previous_complaint_ref: string | null
  preferred_contact: string
  requested_resolution: string
  requested_tone: string
  attachments: { file_name: string; content_type: string; size_bytes: number }[]
  preprocessing?: {
    normalized_text?: string
    injection?: { findings: { type: string; severity: string; text: string; start: number; end: number; description: string }[]; risk_score: number; is_suspicious: boolean; types: string[] }
    signals?: unknown
    entities?: { type: string; value: string; start?: number; end?: number }[]
    classification?: { primary: string | null; confidence: string; ambiguous: boolean; candidates: { subcategory: string; category: string; score: number; matched: string[] }[]; secondary: string[] }
    sentiment?: { label: string; score: number; emotions?: string[] }
    facts?: Record<string, Record<string, unknown>>
    history?: Record<string, unknown>
    order_found?: boolean | null
  }
  analysis?: {
    id: number
    version_no: number
    status: string
    provider: string
    model: string
    fault_injection: string | null
    prompt_versions: Record<string, string>
    policy_versions: Record<string, string>
    ruleset_hash: string
    output: Record<string, unknown> | null
    communication: Record<string, unknown> | null
    retrieval: { query: string; evidence: EvidenceItem[]; outdated: Record<string, unknown>[]; conflicts: Record<string, unknown>[]; rule_guided_sections: string[]; stats: Record<string, unknown> }
    stage_timings: Record<string, number>
    error: string | null
    created_at: string
    completed_at: string | null
    total_latency_ms: number | null
    ai_attempts: number
  } | null
  validation?: {
    id: number
    overall_status: string
    score: number
    decision: string
    dimension_scores: Record<string, number>
    review_reasons: { code: string; rule_id?: string; name: string; message?: string; detail?: string }[]
    counts: Record<string, number>
    comparison: { rows: ComparisonRow[]; agreement: number; ai_available: boolean; python_classification_confidence: string; reference_subcategory: string | null; selected_rule: string | null; condition: string }
    validated_decision: ValidatedDecision
    python_expected: Record<string, unknown>
    ruleset_hash: string
    checks: Check[]
  } | null
  resolution?: { ai_steps: unknown[]; validated_steps: unknown[]; eligibility: Record<string, unknown>; status: string } | null
  responses: ResponseDraft[]
  escalations?: { id: number; level: string; rank: number; reason: string; source: string; rule_ids: string[]; departments: string[]; notes: Record<string, unknown>; status: string; created_at: string }[]
  follow_ups: { id?: number; type: string; message?: string; due_at: string; status: string; source_rule?: string }[]
  sla?: { priority: string; rule_id: string; started_at: string; first_response_due_at: string; resolution_due_at: string; first_response_at: string | null; resolved_at: string | null; response_state: string; resolution_state: string } | null
  review?: { id: number; status: string; reasons: { code: string; name: string; message?: string }[]; final_decision: string | null; assigned_to: number | null; created_at: string; actions: { action: string; comment: string; actor: string; at: string; payload: Record<string, unknown> }[] } | null
  related?: { complaint_ref: string; relation: string; status: string; title: string }[]
  // customer view
  latest_update?: { message: string; status?: string; at: string } | null
  updates?: { message: string; status?: string; at: string }[]
  resolution_status?: string
}

export interface TimelineEvent {
  id: number
  event_type: string
  message: string
  actor: string
  from_status: string | null
  to_status: string | null
  data: Record<string, unknown>
  at: string
}

export interface AuditEntry {
  id: number
  at: string
  actor: string
  role: string | null
  action: string
  entity_type: string
  entity_id: string
  summary: string
  details: Record<string, unknown>
  ip_address: string | null
  request_id: string | null
  hash: string
  prev_hash: string
}

export interface DistributionItem {
  key: string | null
  label: string
  count: number
  share: number
}
