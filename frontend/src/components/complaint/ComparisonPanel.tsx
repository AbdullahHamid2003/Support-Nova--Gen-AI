import { Bot, GitCompareArrows, Scale, ShieldAlert } from 'lucide-react'
import * as React from 'react'

import { ScoreGauge } from '@/components/app/charts'
import { SectionTitle } from '@/components/app/common'
import { CheckIcon, MatchBadge, SeverityBadge } from '@/components/app/status'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription, AlertTitle, Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/primitives'
import { dimensionLabel } from '@/components/insights/format'
import { REASON_LABELS } from '@/lib/reviews'
import type { ComplaintDetail } from '@/lib/types'
import { cn, display, titleCase } from '@/lib/utils'

const DIM_ORDER = ['schema', 'classification', 'routing', 'priority', 'policy', 'resolution', 'eligibility', 'escalation', 'follow_up', 'communication', 'grounding', 'security']

function Value({ v }: { v: unknown }) {
  if (Array.isArray(v)) return v.length ? <div className="flex flex-wrap gap-1">{v.map((x) => <Badge key={String(x)} variant="outline" className="font-mono text-[10.5px]">{String(x)}</Badge>)}</div> : <span className="text-muted-foreground">none</span>
  if (typeof v === 'boolean') return <span>{v ? 'Yes' : 'No'}</span>
  return <span className="break-words">{display(v)}</span>
}

export function ComparisonPanel({ complaint }: { complaint: ComplaintDetail }) {
  const v = complaint.validation
  const [filter, setFilter] = React.useState<'problems' | 'all'>('problems')
  if (!v) return <p className="text-muted-foreground text-sm">The rule check has not run yet.</p>
  const rows = v.comparison.rows
  const checks = [...v.checks].sort((a, b) => DIM_ORDER.indexOf(a.dimension) - DIM_ORDER.indexOf(b.dimension))
  const shown = filter === 'problems' ? checks.filter((c) => c.status === 'fail' || c.status === 'warn') : checks
  const counts = v.counts ?? {}
  const threshold = 80
  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-[auto_1fr]">
        <Card className="items-center">
          <CardContent className="flex flex-col items-center gap-3">
            <ScoreGauge score={v.score} threshold={threshold} />
            <Badge variant={v.decision === 'Verified' ? 'success' : 'warning'} className="text-sm">{v.decision}</Badge>
            <div className="text-muted-foreground text-center text-xs">
              {counts.pass ?? 0} passed · {counts.warn ?? 0} warnings · {counts.fail ?? 0} failed
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Score by area</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-x-6 gap-y-2.5 sm:grid-cols-2">
            {DIM_ORDER.filter((d) => v.dimension_scores[d] !== undefined).map((d) => {
              const s = v.dimension_scores[d]
              return (
                <div key={d} className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-medium">{dimensionLabel(d)}</span>
                    <span className="tabular-nums">{Math.round(s)}</span>
                  </div>
                  <div className="bg-muted h-1.5 overflow-hidden rounded-full">
                    <div className={cn('h-full rounded-full', s >= 90 ? 'bg-success' : s >= 70 ? 'bg-warning' : 'bg-destructive')} style={{ width: `${Math.max(3, s)}%` }} />
                  </div>
                </div>
              )
            })}
          </CardContent>
        </Card>
      </div>

      {v.review_reasons.length ? (
        <Alert variant="warning">
          <ShieldAlert />
          <AlertTitle>Why this needs review</AlertTitle>
          <AlertDescription>
            <ul className="mt-1 list-disc space-y-0.5 pl-4">
              {v.review_reasons.map((r) => <li key={r.code}><span className="font-medium">{r.name || REASON_LABELS[r.code] || r.code}</span>{r.message || r.detail ? ` - ${r.message ?? r.detail}` : ''}</li>)}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}

      <Card className="py-0">
        <CardHeader className="pt-5">
          <CardTitle className="flex flex-wrap items-center gap-2"><GitCompareArrows className="size-4" /> AI proposal vs rules decision</CardTitle>
          <CardDescription>
            Agreement {Math.round(v.comparison.agreement * 100)}%. Where they differ, the rules value is used.
          </CardDescription>
        </CardHeader>
        <CardContent className="px-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Field</TableHead>
                <TableHead><span className="flex items-center gap-1"><Bot className="size-3.5" /> AI</span></TableHead>
                <TableHead><span className="flex items-center gap-1"><Scale className="size-3.5" /> Rules</span></TableHead>
                <TableHead>Result</TableHead>
                <TableHead className="hidden lg:table-cell">Basis</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.field} className={r.match === 'mismatch' ? 'bg-destructive/[0.035]' : ''}>
                  <TableCell className="font-medium whitespace-nowrap">{titleCase(r.field)}</TableCell>
                  <TableCell className="max-w-[16rem] text-sm"><Value v={r.ai} /></TableCell>
                  <TableCell className="max-w-[16rem] text-sm font-medium"><Value v={r.python} /></TableCell>
                  <TableCell><MatchBadge match={r.match} /></TableCell>
                  <TableCell className="text-muted-foreground hidden max-w-[18rem] text-xs lg:table-cell">{r.explanation || '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <div>
        <SectionTitle
          icon={Scale}
          action={
            <div className="flex gap-1">
              <Button size="sm" variant={filter === 'problems' ? 'secondary' : 'ghost'} onClick={() => setFilter('problems')}>Failures & warnings</Button>
              <Button size="sm" variant={filter === 'all' ? 'secondary' : 'ghost'} onClick={() => setFilter('all')}>All {checks.length} checks</Button>
            </div>
          }
        >
          Rule checks
        </SectionTitle>
        <div className="space-y-2">
          {shown.length === 0 ? <p className="text-muted-foreground text-sm">Every check passed.</p> : null}
          {shown.map((c) => (
            <details key={c.code} className={cn('group rounded-lg border bg-card', c.status === 'fail' && 'border-destructive/30', c.status === 'warn' && 'border-warning/40')}>
              <summary className="flex cursor-pointer list-none items-start gap-3 px-3 py-2.5">
                <CheckIcon status={c.status} className="mt-0.5 shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-mono text-xs font-semibold">{c.code}</span>
                    <span className="font-medium">{c.name}</span>
                    <SeverityBadge severity={c.severity} />
                    <Badge variant="muted" className="text-[10px]">{titleCase(c.dimension)}</Badge>
                  </div>
                  <p className="text-muted-foreground mt-0.5 text-[13px]">{c.message}</p>
                </div>
              </summary>
              <div className="grid gap-3 border-t px-3 py-2.5 text-xs sm:grid-cols-2">
                <div><div className="text-muted-foreground mb-0.5 font-medium">Expected (rules)</div><Value v={c.expected} /></div>
                <div><div className="text-muted-foreground mb-0.5 font-medium">Actual (AI)</div><Value v={c.actual} /></div>
                {c.rule_refs.length ? <div><div className="text-muted-foreground mb-0.5 font-medium">Rules</div><Value v={c.rule_refs} /></div> : null}
                {c.policy_refs.length ? <div><div className="text-muted-foreground mb-0.5 font-medium">Policy</div><Value v={c.policy_refs} /></div> : null}
              </div>
            </details>
          ))}
        </div>
      </div>
    </div>
  )
}
