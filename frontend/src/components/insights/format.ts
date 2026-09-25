/* Formatting helpers and label maps shared by the insight & quality pages
   (analytics, reports, evaluation, adversarial lab, audit). */

/** "critical_validation_failure" -> "Critical validation failure". */
export function humanize(code: string | null | undefined): string {
  if (!code) return ''
  const text = code.replace(/[_.]+/g, ' ').replace(/\s+/g, ' ').trim()
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** 3 -> "+300%", -0.25 -> "−25%". */
export function signedPercent(change: number | null | undefined): string {
  if (change === null || change === undefined || Number.isNaN(change)) return '—'
  const v = Math.round(change * 100)
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v)}%`
}

/** Difference between two rates in percentage points: 0.7785 vs 0.5022 -> "+27.6 pts". */
export function pointsDelta(a: number | null | undefined, b: number | null | undefined): string {
  if (a === null || a === undefined || b === null || b === undefined) return '—'
  const d = (a - b) * 100
  return `${d > 0 ? '+' : d < 0 ? '−' : ''}${Math.abs(d).toFixed(1)} pts`
}

/** Safe ratio; null when the denominator is zero. */
export function ratio(n: number, d: number): number | null {
  return d ? n / d : null
}

/** Colour token for a 0–1 rate where higher is better (or lower is better with `invert`). */
export function rateColor(value: number, { good = 0.9, fair = 0.7, invert = false }: { good?: number; fair?: number; invert?: boolean } = {}): string {
  if (invert) return value <= 1 - good ? 'var(--success)' : value <= 1 - fair ? 'var(--warning)' : 'var(--destructive)'
  return value >= good ? 'var(--success)' : value >= fair ? 'var(--warning)' : 'var(--destructive)'
}

export function isActiveRun(status: string | null | undefined): boolean {
  return status === 'queued' || status === 'running'
}

/** Short, copy-friendly form of a SHA-256 hash: "99c6bd24…3f65". */
export function shortHash(hash: string | null | undefined, head = 8, tail = 4): string {
  if (!hash) return '—'
  return hash.length <= head + tail + 1 ? hash : `${hash.slice(0, head)}…${hash.slice(-tail)}`
}

/** Labels for the fields compared between GenAI (Pipeline 1), Python (Pipeline 2) and expected labels. */
export const FIELD_LABELS: Record<string, string> = {
  category: 'Category',
  subcategory: 'Subcategory',
  department: 'Department',
  supporting_departments: 'Supporting departments',
  sentiment: 'Sentiment',
  urgency: 'Urgency',
  impact: 'Impact',
  priority: 'Priority',
  entities: 'Entities',
  policy_references: 'Policy references',
  resolution: 'Resolution steps',
  resolution_rule: 'Resolution rule',
  refund_eligibility: 'Refund eligibility',
  replacement_eligibility: 'Replacement eligibility',
  compensation_eligibility: 'Compensation eligibility',
  escalation_required: 'Escalation required',
  escalation_level: 'Escalation level',
  follow_up_required: 'Follow-up required',
  follow_up_type: 'Follow-up type',
  missing_information: 'Missing information',
}

export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? humanize(field)
}

/** Validation dimensions used by the Python ground-truth checks. */
const DIMENSION_LABELS: Record<string, string> = { schema: 'AI answer', follow_up: 'Follow-up', grounding: 'Facts' }
export function dimensionLabel(dimension: string): string {
  return DIMENSION_LABELS[dimension] ?? humanize(dimension)
}

/** Manual-review triggers (rules/complaint_rules/review_rules.yaml). */
export const REVIEW_REASONS: Record<string, { rule: string; name: string }> = {
  ai_python_category_mismatch: { rule: 'REV-001', name: 'AI and rules disagree on the category' },
  critical_validation_failure: { rule: 'REV-002', name: 'A critical check failed' },
  low_verification_score: { rule: 'REV-003', name: 'Verification score too low' },
  missing_policy_support: { rule: 'REV-004', name: 'No policy supports the decision' },
  ambiguous_complaint: { rule: 'REV-005', name: 'Unclear complaint' },
  escalation_unclear: { rule: 'REV-006', name: 'Escalation level unclear' },
  policy_contradiction: { rule: 'REV-007', name: 'Conflicting policy information' },
  sensitive_case: { rule: 'REV-008', name: 'Sensitive case needs human approval' },
  invalid_ai_output: { rule: 'REV-009', name: 'No usable AI answer' },
  prompt_injection_detected: { rule: 'REV-010', name: 'Attempt to manipulate the AI' },
  unsupported_promise: { rule: 'REV-011', name: 'Response makes unsupported promises' },
  hallucination_detected: { rule: 'REV-012', name: 'Unsupported claims' },
  unknown_category: { rule: 'REV-013', name: 'Unknown category' },
  reference_mismatch: { rule: 'REV-014', name: 'Order not found for this customer' },
  pipeline_error: { rule: '—', name: 'Processing failed' },
}

export function reviewReasonLabel(code: string): string {
  return REVIEW_REASONS[code]?.name ?? humanize(code)
}

/** What each server-side RBAC permission (security/rbac.py) allows. */
export const PERMISSION_LABELS: Record<string, string> = {
  'analytics:read': 'View analytics, trends and dashboards',
  'analytics:read_own': 'View own workload statistics',
  'audit:read': 'Read the full audit log and verify its integrity',
  'audit:read_complaint': 'Read the audit trail for complaints, reviews, reports and evaluations',
  'complaint:clarify_own': 'Answer clarification requests on own complaints',
  'complaint:create': 'Submit complaints',
  'complaint:read_all': 'Read every complaint',
  'complaint:read_own': 'Read own complaints (customer view)',
  'complaint:reprocess': 'Re-run the analysis on a complaint',
  'complaint:respond': 'Send validated responses to customers',
  'complaint:update': 'Change status, assignment and notes',
  'escalation:create': 'Escalate a complaint manually',
  'evaluation:read': 'View evaluation runs and results',
  'evaluation:run': 'Start and cancel evaluation runs',
  'knowledge:manage': 'Upload and update knowledge base documents',
  'knowledge:read': 'Read policies and search the knowledge base',
  'lab:use': 'Use the Adversarial Lab',
  'prompts:manage': 'Create and activate prompt versions',
  'reports:export': 'Build and export reports',
  'review:act': 'Approve, reject, modify or reclassify in manual review',
  'review:read': 'View the manual-review queue',
  'rules:manage': 'Edit the Rule Matrix',
  'rules:read': 'Read the Rule Matrix',
  'settings:manage': 'View system configuration',
  'taxonomy:manage': 'Add categories, subcategories and departments',
  'users:manage': 'Create and edit users',
  'users:read': 'View users and roles',
}

/** Resource part of a permission ("complaint:read_all" -> "complaint"). */
export function permissionGroup(permission: string): string {
  return permission.split(':')[0] ?? permission
}
