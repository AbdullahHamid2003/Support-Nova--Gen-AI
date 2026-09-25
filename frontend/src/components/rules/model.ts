/* Rule Matrix API shapes and pure helpers (shared by the Rule Matrix page and its dialogs). */
import type { QueryClient } from '@tanstack/react-query'

import { ApiError } from '@/lib/api'

export interface RuleRow {
  rule_id: string
  rule_type: string
  name: string
  subcategory: string | null
  is_active: boolean
  version: number
  updated_at: string | null
  body: Record<string, unknown>
  condition: string | null
}

export interface RulesList {
  items: RuleRow[]
  total: number
  counts: Record<string, number>
  ruleset_hash: string
}

export interface ActionDef {
  code: string
  name: string
  group: string
  description: string
}

export interface ProhibitedDef {
  code: string
  name: string
  severity: string
}

export interface SignalDef {
  name: string
  label: string
  terms: string[]
}

export interface EscalationLevel {
  rank: number
  name: string
  action_code: string | null
}

export interface RuleParameter {
  key: string
  value: number | string
  unit: string
  source: string
  description: string
}

export interface SlaTarget {
  rule_id: string
  priority: string
  first_response_hours: number
  resolution_hours: number
  policy_refs: string[]
}

export interface RulesMeta {
  actions: ActionDef[]
  prohibited_actions: ProhibitedDef[]
  signals: SignalDef[]
  escalation_levels: EscalationLevel[]
  follow_up_types: string[]
  priority_matrix: Record<string, Record<string, string>>
  rule_types: string[]
  config_ids: string[]
  parameters: Record<string, RuleParameter>
  sla: Record<string, SlaTarget>
}

export interface IntegrityIssue {
  severity: string
  rule_id: string
  message: string
}

export interface IntegrityReport {
  valid: boolean
  errors: number
  warnings: number
  issues: IntegrityIssue[]
  ruleset_hash?: string
  counts?: Record<string, number>
}

export interface TaxonomySubcategory {
  code: string
  name: string
  description: string
  is_active: boolean
  rules: number
  department: string | null
  has_classifier: boolean
}

export interface TaxonomyCategory {
  code: string
  name: string
  description: string
  is_active: boolean
  subcategories: TaxonomySubcategory[]
}

export interface TaxonomyDepartment {
  code: string
  name: string
  description: string
  is_active: boolean
}

export interface Taxonomy {
  categories: TaxonomyCategory[]
  departments: TaxonomyDepartment[]
}

export const RULE_TYPES: { key: string; label: string; description: string }[] = [
  { key: 'resolution', label: 'Resolution', description: 'Actions, eligibility and timelines for each subcategory.' },
  { key: 'escalation', label: 'Escalation', description: 'When to escalate. The AI can never lower the level.' },
  { key: 'routing', label: 'Routing', description: 'The departments that handle each subcategory (RTE-RUL-14).' },
  { key: 'conditional_routing', label: 'Conditional routing', description: 'Extra departments added when a risk signal is found.' },
  { key: 'urgency_floor', label: 'Urgency floors', description: 'Minimum urgency and impact when a risk signal is found.' },
  { key: 'category', label: 'Classification', description: 'Keywords used to classify each complaint.' },
  { key: 'missing_info', label: 'Missing info', description: 'Missing details and whether they block resolution.' },
  { key: 'followup', label: 'Follow-up', description: 'Which follow-up is scheduled, and when.' },
  { key: 'sla', label: 'SLA', description: 'Response and resolution targets per priority (SLA-RUL-15).' },
  { key: 'review', label: 'Review triggers', description: 'When a reviewer must approve before anything is sent.' },
]

export const RULE_TYPE_LABEL: Record<string, string> = Object.fromEntries(RULE_TYPES.map((t) => [t.key, t.label]))

export const CONFIG_INFO: Record<string, { label: string; description: string }> = {
  escalation_config: { label: 'Escalation levels', description: 'The escalation ladder and what every escalation note must include.' },
  routing_precedence: { label: 'Routing precedence', description: 'Which subcategory family wins when a complaint touches several departments.' },
  priority_config: { label: 'Priority settings', description: 'Urgency and impact levels and the priority matrix. Sentiment and customer type never raise priority.' },
  category_settings: { label: 'Classification settings', description: 'Minimum score, ambiguity margin and secondary-issue thresholds.' },
  missing_info_config: { label: 'Missing-info exemptions', description: 'Categories and subcategories where missing information never blocks handling (safety, privacy, account takeover).' },
  followup_config: { label: 'Follow-up types', description: 'The follow-up types rules may schedule.' },
  sla_config: { label: 'SLA states', description: 'SLA states and the parameter that sets the At-Risk threshold.' },
  signals: { label: 'Risk signals', description: 'Risk words (fire, injury, fraud, legal threat…) that set urgency, escalation and classification.' },
  parameters: { label: 'Policy parameters', description: 'Numeric policy values (windows, limits, timelines) with the policy section each one comes from.' },
  response_rules: { label: 'Response rules', description: 'Tone rules and wording checks applied to customer responses.' },
  precedence_rules: { label: 'Knowledge precedence', description: 'Document-type ranking and the rules that settle policy conflicts.' },
  validation_policy: { label: 'Validation policy', description: 'Validation checks, their severity and dimension, and the verification threshold.' },
  actions: { label: 'Action catalogue', description: 'Allowed and prohibited actions that rules and responses refer to.' },
  organization: { label: 'Organisation profile', description: 'Channels, customer types, reference formats and organisation details.' },
}

export const URGENCY_LEVELS = ['Critical', 'High', 'Medium', 'Low'] as const
export const IMPACT_LEVELS = ['High', 'Medium', 'Low'] as const

export function asString(v: unknown): string {
  if (v === null || v === undefined) return ''
  return typeof v === 'string' ? v : typeof v === 'number' || typeof v === 'boolean' ? String(v) : JSON.stringify(v)
}

export function asStrings(v: unknown): string[] {
  return Array.isArray(v) ? v.map((x) => asString(x)) : []
}

export function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}
}

export function computePriority(matrix: Record<string, Record<string, string>> | undefined, urgency: string, impact: string): string | null {
  if (!urgency || !impact) return null
  return matrix?.[urgency]?.[impact] ?? null
}

/** Integrity issues returned by the server when a change would make the Rule Matrix invalid. */
export function integrityIssues(err: unknown): IntegrityIssue[] {
  if (!(err instanceof ApiError) || !Array.isArray(err.details)) return []
  return (err.details as Record<string, unknown>[])
    .filter((d) => d && typeof d === 'object' && typeof d.message === 'string' && ('rule_id' in d || 'severity' in d))
    .map((d) => ({ severity: asString(d.severity) || 'error', rule_id: asString(d.rule_id), message: asString(d.message) }))
}

const UNIT: Record<string, string> = {
  calendar_days: 'calendar days',
  business_days: 'business days',
  hours: 'hours',
  months: 'months',
  usd: 'USD',
  percent: '%',
  count: '',
}

export function unitLabel(unit: string): string {
  return UNIT[unit] ?? unit.replace(/_/g, ' ')
}

export function formatParam(value: number | string, unit: string): string {
  if (unit === 'usd') return `USD ${value}`
  if (unit === 'percent') return `${value}%`
  const u = unitLabel(unit)
  return u ? `${value} ${u}` : String(value)
}

export function invalidateRules(qc: QueryClient) {
  qc.invalidateQueries({ queryKey: ['rules'] })
  qc.invalidateQueries({ queryKey: ['taxonomy'] })
}
