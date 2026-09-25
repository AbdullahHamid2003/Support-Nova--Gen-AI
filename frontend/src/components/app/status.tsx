/* Semantic badges used everywhere so a status always looks the same. */
import { AlertTriangle, BadgeCheck, CheckCircle2, CircleDashed, CircleX, Clock, Flame, MinusCircle, ShieldAlert, UserCheck } from 'lucide-react'
import type * as React from 'react'

import { Badge } from '@/components/ui/primitives'
import { Tooltip } from '@/components/ui/overlays'
import { cn } from '@/lib/utils'

type Variant = 'default' | 'secondary' | 'outline' | 'success' | 'warning' | 'destructive' | 'info' | 'primary' | 'validate' | 'muted'

const STATUS: Record<string, Variant> = {
  New: 'info', Processing: 'primary', Analyzed: 'primary', Assigned: 'secondary', 'In Progress': 'info',
  'Awaiting Customer': 'warning', Escalated: 'destructive', Resolved: 'success', Closed: 'muted', Reopened: 'warning',
}
export function StatusBadge({ status, className }: { status?: string | null; className?: string }) {
  if (!status) return null
  return <Badge variant={STATUS[status] ?? 'outline'} className={className}>{status}</Badge>
}

const VERIFICATION: Record<string, { v: Variant; icon: React.ElementType; tip: string }> = {
  Verified: { v: 'success', icon: BadgeCheck, tip: 'Passed the rule check. No review needed.' },
  'Human Verified': { v: 'validate', icon: UserCheck, tip: 'Approved by a reviewer.' },
  'Manual Review': { v: 'warning', icon: ShieldAlert, tip: 'The rule check flagged an issue. A reviewer must decide.' },
  Pending: { v: 'muted', icon: CircleDashed, tip: 'Not analysed yet.' },
  Duplicate: { v: 'muted', icon: MinusCircle, tip: 'Linked to an earlier complaint as a duplicate.' },
}
export function VerificationBadge({ status, score, className }: { status?: string | null; score?: number | null; className?: string }) {
  if (!status) return null
  const cfg = VERIFICATION[status] ?? { v: 'outline' as Variant, icon: CircleDashed, tip: status }
  const Icon = cfg.icon
  return (
    <Tooltip content={cfg.tip}>
      <Badge variant={cfg.v} className={className}>
        <Icon aria-hidden />
        {status}
        {score !== null && score !== undefined && status !== 'Pending' ? <span className="opacity-75 tabular-nums">· {Math.round(score)}</span> : null}
      </Badge>
    </Tooltip>
  )
}

const PRIORITY: Record<string, { v: Variant; label: string }> = {
  P0: { v: 'destructive', label: 'P0 · Critical' }, P1: { v: 'warning', label: 'P1 · High' }, P2: { v: 'info', label: 'P2 · Medium' }, P3: { v: 'muted', label: 'P3 · Low' },
}
export function PriorityBadge({ priority, compact }: { priority?: string | null; compact?: boolean }) {
  if (!priority) return <span className="text-muted-foreground">—</span>
  const cfg = PRIORITY[priority] ?? { v: 'outline' as Variant, label: priority }
  return <Badge variant={cfg.v} className="font-semibold tabular-nums">{compact ? priority : cfg.label}</Badge>
}

const URGENCY: Record<string, Variant> = { Critical: 'destructive', High: 'warning', Medium: 'info', Low: 'muted' }
export function UrgencyBadge({ urgency }: { urgency?: string | null }) {
  if (!urgency) return <span className="text-muted-foreground">—</span>
  return (
    <Badge variant={URGENCY[urgency] ?? 'outline'}>
      {urgency === 'Critical' ? <Flame aria-hidden /> : null}
      {urgency}
    </Badge>
  )
}

const SLA: Record<string, Variant> = { 'On Track': 'success', 'At Risk': 'warning', Breached: 'destructive', Met: 'validate' }
export function SlaBadge({ state }: { state?: string | null }) {
  if (!state) return <span className="text-muted-foreground">—</span>
  return (
    <Badge variant={SLA[state] ?? 'outline'}>
      <Clock aria-hidden />
      {state}
    </Badge>
  )
}

const SENTIMENT: Record<string, string> = {
  'Strongly Negative': 'text-destructive', Negative: 'text-[oklch(0.55_0.15_40)] dark:text-warning', Neutral: 'text-muted-foreground', Positive: 'text-success', Mixed: 'text-info',
}
export function SentimentText({ sentiment }: { sentiment?: string | null }) {
  if (!sentiment) return <span className="text-muted-foreground">—</span>
  return <span className={cn('text-sm font-medium', SENTIMENT[sentiment])}>{sentiment}</span>
}

export function EscalationBadge({ level, required }: { level?: string | null; required?: boolean }) {
  if (!level || level === 'No Escalation' || required === false) return <span className="text-muted-foreground text-sm">None</span>
  const critical = level.startsWith('Critical')
  return (
    <Badge variant={critical ? 'destructive' : 'warning'}>
      <AlertTriangle aria-hidden />
      {level}
    </Badge>
  )
}

export function CheckIcon({ status, className }: { status: string; className?: string }) {
  if (status === 'pass') return <CheckCircle2 className={cn('text-success size-4', className)} aria-label="pass" />
  if (status === 'warn') return <AlertTriangle className={cn('text-warning size-4', className)} aria-label="warning" />
  if (status === 'fail') return <CircleX className={cn('text-destructive size-4', className)} aria-label="fail" />
  return <MinusCircle className={cn('text-muted-foreground size-4', className)} aria-label="not applicable" />
}

export function MatchBadge({ match }: { match: string }) {
  if (match === 'match') return <Badge variant="success"><CheckCircle2 aria-hidden />Match</Badge>
  if (match === 'partial') return <Badge variant="warning"><AlertTriangle aria-hidden />Partial</Badge>
  return <Badge variant="destructive"><CircleX aria-hidden />Mismatch</Badge>
}

export function SeverityBadge({ severity }: { severity: string }) {
  const v: Variant = severity === 'critical' ? 'destructive' : severity === 'major' ? 'warning' : severity === 'minor' ? 'info' : 'muted'
  return <Badge variant={v} className="uppercase tracking-wide text-[10px]">{severity}</Badge>
}
