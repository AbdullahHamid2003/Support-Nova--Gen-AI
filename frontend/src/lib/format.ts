import { differenceInMinutes, format, formatDistanceToNowStrict, isValid, parseISO } from 'date-fns'

export function toDate(value: string | Date | null | undefined): Date | null {
  if (!value) return null
  const d = typeof value === 'string' ? parseISO(value) : value
  return isValid(d) ? d : null
}

export function fmtDate(value: string | Date | null | undefined, pattern = 'd MMM yyyy'): string {
  const d = toDate(value)
  return d ? format(d, pattern) : '—'
}

export function fmtDateTime(value: string | Date | null | undefined): string {
  return fmtDate(value, 'd MMM yyyy, HH:mm')
}

export function fmtRelative(value: string | Date | null | undefined): string {
  const d = toDate(value)
  return d ? `${formatDistanceToNowStrict(d)} ago` : '—'
}

/** "in 5h 12m" / "overdue by 2d 3h" for SLA deadlines. */
export function fmtDue(value: string | null | undefined): { text: string; overdue: boolean } {
  const d = toDate(value)
  if (!d) return { text: '—', overdue: false }
  const mins = differenceInMinutes(d, new Date())
  const abs = Math.abs(mins)
  const days = Math.floor(abs / 1440)
  const hours = Math.floor((abs % 1440) / 60)
  const minutes = abs % 60
  const span = days ? `${days}d ${hours}h` : hours ? `${hours}h ${minutes}m` : `${minutes}m`
  return mins >= 0 ? { text: `due in ${span}`, overdue: false } : { text: `overdue by ${span}`, overdue: true }
}

export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`
}

const STAGE_LABELS: Record<string, string> = {
  queued: 'Queued', preprocessing: 'Screening', retrieval: 'Policy search', ai_analysis: 'AI analysis', validation: 'Rule check',
  response_generation: 'Response drafting', response_validation: 'Response check', finalizing: 'Routing & SLA', completed: 'Completed', failed: 'Failed',
}

/** Display name for a processing-stage code ("ai_analysis" -> "AI analysis"). */
export function fmtStage(stage: string | null | undefined): string {
  if (!stage) return '—'
  return STAGE_LABELS[stage] ?? stage.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}

export function fmtBytes(n: number | null | undefined): string {
  if (!n) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
