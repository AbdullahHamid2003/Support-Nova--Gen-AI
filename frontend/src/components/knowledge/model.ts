/* Knowledge-base API shapes and small pure helpers shared by the knowledge pages
   (and the Rule Matrix, which links policy references back to their documents). */

export const DOC_TYPES = ['policy', 'rules', 'sop', 'guideline', 'faq', 'template'] as const
export const DOC_STATUSES = ['Active', 'Draft', 'Previous', 'Superseded'] as const
export const DOC_FORMATS = ['pdf', 'docx', 'txt', 'md', 'csv'] as const

export const DOC_TYPE_LABEL: Record<string, string> = {
  policy: 'Policy',
  rules: 'Rules',
  sop: 'SOP',
  guideline: 'Guideline',
  faq: 'FAQ',
  template: 'Template',
}

/** Mirrors the server-side metadata validation (document_processing/validation.py). */
export const DOC_ID_PATTERN = /^[A-Z]{2,5}-[A-Z]{2,5}-\d{2,3}$/
export const VERSION_PATTERN = /^\d{1,3}(\.\d{1,3}){0,2}$/

export interface InjectionFinding {
  type: string
  severity: string
  text: string
  start: number
  end: number
  description: string
}

export interface SecurityFinding {
  chunk_uid: string
  section_id: string
  types: string[]
  findings: InjectionFinding[]
  risk_score: number
  is_suspicious: boolean
}

export interface ValueChange {
  kind: string
  unit: string
  old: number | string
  new: number | string
}

export interface ChangedSection {
  section_id: string
  change: 'added' | 'removed' | 'modified' | string
  heading: string
  similarity?: number
  value_changes?: ValueChange[]
}

export interface AffectedParameter {
  key: string
  current_value: number | string
  source: string
  suggested_value: number | string | null
  out_of_sync: boolean
}

export interface AffectedComplaint {
  complaint_ref: string
  status: string
  sections: string[]
  response_requires_revision: boolean
}

export interface ImpactAnalysis {
  version?: string
  doc_id: string
  old_version: string
  new_version: string
  analysed_at: string
  previous_policy_obsolete?: boolean
  changed_sections: ChangedSection[]
  affected_resolution_rules: string[]
  affected_escalation_rules: string[]
  escalation_rules_changed?: boolean
  affected_parameters: AffectedParameter[]
  affected_complaints: AffectedComplaint[]
  responses_requiring_revision: number
}

export interface DocVersion {
  id: number
  version: string
  status: string
  effective_date: string | null
  expiry_date: string | null
  file_name: string
  file_format: string
  size_bytes: number
  sha256: string
  page_count: number | null
  section_count: number
  chunk_count: number
  parse_status: string
  uploaded_at: string
  supersedes: string | null
  security_findings: SecurityFinding[] | null
  warnings: string[]
  impact: ImpactAnalysis | null
  primary_eligible: boolean
  effective_state: string
}

export interface DocSummary {
  doc_id: string
  title: string
  doc_type: string
  owner_department: string | null
  topics: string[]
  active_version: string | null
  active_format: string | null
  version_count: number
  statuses: string[]
  quarantined_chunks: number
  versions: DocVersion[]
}

export interface DocDetail {
  doc_id: string
  title: string
  doc_type: string
  owner_department: string | null
  topics: string[]
  versions: DocVersion[]
}

export interface DocSection {
  section_id: string
  heading: string
  level: number
  page_start: number | null
  page_end: number | null
  text: string
}

export interface DocChunk {
  chunk_uid: string
  section_id: string
  heading: string
  page_start: number | null
  token_count: number
  is_quarantined: boolean
  quarantine_reason: string | null
  embedding_model: string
  text: string
}

export interface DocFact {
  key: string | null
  kind: string
  unit: string
  value: number | string
  snippet: string
  section_id: string
}

export interface VersionDetail extends DocVersion {
  doc_id: string
  title: string
  facts: DocFact[] | null
  sections: DocSection[]
  chunks: DocChunk[]
}

export interface UploadResult extends DocVersion {
  doc_id: string
}

export interface PreviewResult {
  file_name: string
  format: string
  size_bytes: number
  title: string | null
  page_count: number | null
  detected_metadata: Record<string, unknown>
  sections: { section_id: string; heading: string; level: number; page_start: number | null; chars: number }[]
}

export interface KnowledgeStats {
  documents: number
  versions: number
  by_status: Record<string, number>
  by_format: Record<string, number>
  chunks: number
  quarantined_chunks: number
  revision: number
}

export interface ConflictStatement {
  doc_id: string
  title: string
  doc_type: string
  version: string
  section_id: string
  chunk_uid: string
  value: string | number
  snippet: string
  precedence_rank: number
  effective_date: string | null
}

export interface PolicyConflict {
  fact_key: string
  statements: ConflictStatement[]
  prevailing: ConflictStatement
  overridden: ConflictStatement[]
  resolution_rule: string
  explanation: string
}

export interface PrecedenceRule {
  rule_id: string
  name: string
  description: string
  policy_refs: string[]
}

export interface ConflictsResponse {
  items: PolicyConflict[]
  precedence: PrecedenceRule[]
  doc_type_rank: Record<string, number>
}

export interface Evidence {
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

export interface OutdatedEvidence {
  doc_id: string
  version: string
  status: string
  section_id: string
  heading: string
  text: string
  active_version: string | null
  note: string
}

export interface SearchResult {
  query: string
  evidence: Evidence[]
  outdated: OutdatedEvidence[]
  conflicts: PolicyConflict[]
  rule_guided_sections: string[]
  stats: { eligible_chunks?: number; lexical_hits?: number; rule_guided?: number; embedder?: string; latency_ms?: number; [k: string]: unknown }
  candidate_subcategories: (string | null)[]
}

// ------------------------------------------------------------------ helpers
export function versionKey(version: string): number[] {
  return version.split('.').map((p) => (/^\d+$/.test(p) ? Number(p) : 0))
}

export function compareVersions(a: string, b: string): number {
  const ka = versionKey(a)
  const kb = versionKey(b)
  for (let i = 0; i < Math.max(ka.length, kb.length); i++) {
    const d = (ka[i] ?? 0) - (kb[i] ?? 0)
    if (d !== 0) return d
  }
  return 0
}

export function sortVersions<T extends { version: string }>(versions: T[]): T[] {
  return [...versions].sort((a, b) => compareVersions(a.version, b.version))
}

/** Same inference the server applies when no document type is given (ABC-POL-12 -> policy). */
export function inferDocType(docId: string): string | undefined {
  const parts = docId.toUpperCase().split('-')
  if (parts.length < 3) return undefined
  return ({ POL: 'policy', RUL: 'rules', SOP: 'sop', GDL: 'guideline', FAQ: 'faq', TPL: 'template', COM: 'template' } as Record<string, string>)[parts[1]]
}

/** "REF-POL-02:3.1" -> { docId: "REF-POL-02", section: "3.1" }. */
export function parsePolicyRef(ref: string): { docId: string; section: string | null } {
  const [docId, section] = ref.split(':')
  return { docId: docId.trim().toUpperCase(), section: section ? section.trim() : null }
}

export function documentHref(docId: string, opts: { version?: string | null; section?: string | null } = {}): string {
  const sp = new URLSearchParams()
  if (opts.version) sp.set('v', opts.version)
  if (opts.section) sp.set('section', opts.section)
  const s = sp.toString()
  return `/knowledge/${encodeURIComponent(docId)}${s ? `?${s}` : ''}`
}

export function quarantinedCount(findings: SecurityFinding[] | null | undefined): number {
  return (findings ?? []).filter((f) => f.is_suspicious).length
}

export function flaggedCount(findings: SecurityFinding[] | null | undefined): number {
  return (findings ?? []).filter((f) => !f.is_suspicious).length
}

const UNIT_LABEL: Record<string, string> = {
  day: 'days',
  days: 'days',
  calendar_day: 'calendar days',
  calendar_days: 'calendar days',
  business_day: 'business days',
  business_days: 'business days',
  hour: 'hours',
  hours: 'hours',
  month: 'months',
  months: 'months',
  percent: '%',
  pct: '%',
  count: '',
}

/** 50 usd -> "USD 50"; 10 business_day -> "10 business days". */
export function formatQuantity(value: number | string | null | undefined, unit: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const u = (unit ?? '').toLowerCase()
  if (u === 'usd') return `USD ${value}`
  if (u === 'percent' || u === 'pct') return `${value}%`
  const label = UNIT_LABEL[u] ?? u.replace(/_/g, ' ')
  return label ? `${value} ${label}` : String(value)
}

export interface TextSpan {
  start: number
  end: number
  label: string
  tone: 'destructive' | 'warning'
}

/** Resolve the flagged injection spans of a chunk (offsets are chunk-relative; fall back to a text search). */
export function findingSpans(text: string, finding: SecurityFinding | undefined): TextSpan[] {
  if (!finding) return []
  const spans: TextSpan[] = []
  for (const f of finding.findings ?? []) {
    let start = f.start
    let end = f.end
    if (!(start >= 0 && end <= text.length && text.slice(start, end) === f.text)) {
      const idx = f.text ? text.toLowerCase().indexOf(f.text.toLowerCase()) : -1
      if (idx < 0) continue
      start = idx
      end = idx + f.text.length
    }
    spans.push({ start, end, label: `${f.type.replace(/_/g, ' ')} (${f.severity}): ${f.description}`, tone: finding.is_suspicious ? 'destructive' : 'warning' })
  }
  return spans.sort((a, b) => a.start - b.start)
}
