/* Reports & exports (SRS Steps 66-67, Deliverables 8-10). Every report is built live by the API from
   one format-neutral model, so the browser preview, CSV, Excel and PDF always carry the same numbers. */
import { useQuery } from '@tanstack/react-query'
import {
  Building2, ClipboardCheck, Eye, FileBarChart, FileText, Filter, GitCompareArrows, Lightbulb, RotateCcw, Scale, ShieldAlert, Siren, Timer, X,
} from 'lucide-react'
import * as React from 'react'

import { ErrorState, LoadingBlock, PageHeader } from '@/components/app/common'
import { DownloadButtons, Metric } from '@/components/insights/common'
import type { EvaluationRunList } from '@/components/insights/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle, Tooltip } from '@/components/ui/overlays'
import {
  Badge, Card, CardContent, CardFooter, CardHeader, CardTitle, Input, Label, NativeSelect,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/primitives'
import { api } from '@/lib/api'
import { useAuth, usePublicConfig } from '@/lib/auth'
import { fmtDate } from '@/lib/format'
import { cn } from '@/lib/utils'

// ------------------------------------------------------------------ response shapes
interface Catalog { items: { key: string; name: string }[]; formats: string[] }
interface ReportTableJson { title: string; columns: string[]; rows: unknown[][] }
interface ReportSectionJson {
  heading: string
  paragraphs: string[]
  bullets: string[]
  metrics: { label: string; value: unknown }[]
  tables: ReportTableJson[]
}
interface ReportJson { title: string; subtitle: string; meta: Record<string, unknown>; sections: ReportSectionJson[]; notes: string[] }

interface Filters { date_from: string; date_to: string; department: string; category: string }
const NO_FILTERS: Filters = { date_from: '', date_to: '', department: '', category: '' }
type Scope = 'filtered' | 'partial' | 'global'

// ------------------------------------------------------------------ catalogue descriptions
const REPORT_INFO: Record<string, { icon: React.ElementType; name?: string; summary: string; contents: string[]; scope: Scope; scopeNote?: string }> = {
  'complaint-analysis': {
    icon: FileBarChart,
    summary: 'Volume, classification and outcome of every complaint.',
    contents: ['Totals: open, resolved, escalated, verified, in review', 'Repeats, duplicates and injection attempts', 'Average resolution time and verification score', 'Breakdowns by category, subcategory, product, urgency, priority, sentiment, channel and status', 'The latest 500 complaints'],
    scope: 'filtered',
  },
  'department-performance': {
    icon: Building2,
    summary: 'Workload, SLA and quality per department and agent.',
    contents: ['Volume as primary and supporting department', 'Open and resolved', 'Escalations, SLA breaches and breach rate', 'Manual review load', 'Average resolution time and verification score', 'Agent workload: assigned, resolved, breached'],
    scope: 'filtered',
  },
  escalations: {
    icon: Siren,
    summary: 'Every escalation and the rule that required it.',
    contents: ['Totals, open and resolved', 'Escalations the AI missed and the rules added', 'Escalations triggered by the SLA', 'Breakdown by level, rule and source', 'List of escalations with reasons and departments'],
    scope: 'filtered',
  },
  'sla-status': {
    icon: Timer,
    summary: 'SLA status and the open cases that need attention now.',
    contents: ['On track, at risk, breached and met', 'First-response compliance', 'First-response and resolution targets by priority', 'Open complaints at risk or breached, by due time'],
    scope: 'filtered',
  },
  'policy-usage': {
    icon: FileText,
    summary: 'Which policies decisions rely on, and document versions.',
    contents: ['Most-used sections: cited by AI, required by rules, retrieved', 'Outdated versions used only as context', 'Quarantined content', 'Document versions'],
    scope: 'partial',
    scopeNote: 'Only the outdated-versions table uses the filters.',
  },
  'resolution-compliance': {
    icon: Scale,
    summary: 'Whether AI resolutions and promises follow the Rule Matrix.',
    contents: ['Pass rate across 15 compliance checks', 'Unsupported promises caught', 'Prohibited actions caught', 'Refund, replacement and compensation corrections', 'Each failure, corrected or sent to review'],
    scope: 'filtered',
  },
  'genai-python-comparison': {
    icon: GitCompareArrows,
    name: 'AI vs rules comparison',
    summary: 'AI vs rules for each case, and why they differ.',
    contents: ['Category, department, urgency and escalation: AI vs rules', 'Policy reference, match and verification status', 'Why each difference happened', 'Agreement by field'],
    scope: 'filtered',
    scopeNote: 'Uses the filters, or the evaluation run picked below.',
  },
  'manual-reviews': {
    icon: ClipboardCheck,
    summary: 'Cases sent to reviewers, why, and what they decided.',
    contents: ['Pending, in review and completed', 'Average reviewer turnaround', 'Review reasons', 'Outcomes and reviewer actions', 'List of reviews'],
    scope: 'filtered',
  },
  'complaint-intelligence': {
    icon: Lightbulb,
    name: 'Complaint insights',
    summary: 'Executive summary of complaint patterns and risks.',
    contents: ['Key totals and the category, priority and sentiment mix', 'Department routing', 'Escalation and SLA risk', 'Repeat customers', 'Top policy sections', 'Fields where AI and rules disagree most', 'Trend alerts'],
    scope: 'filtered',
    scopeNote: 'Trend alerts ignore the filters and use the last 14 days.',
  },
  security: {
    icon: ShieldAlert,
    summary: 'Attacks, malicious documents, AI defects and access control.',
    contents: ['Complaints with injection attempts', 'Adversarial Lab runs and results', 'Deliberate AI defect results', 'Quarantined knowledge base content', 'Failed sign-ins, lockouts and denied access', 'Security controls in place'],
    scope: 'global',
    scopeNote: 'Covers the whole system; filters do not apply.',
  },
}

const SCOPE_BADGE: Record<Scope, { label: string; variant: 'validate' | 'info' | 'muted' }> = {
  filtered: { label: 'Uses filters', variant: 'validate' },
  partial: { label: 'Partly filtered', variant: 'info' },
  global: { label: 'Whole system', variant: 'muted' },
}

const COMPARISON = 'genai-python-comparison'

// ------------------------------------------------------------------ page
export default function ReportsPage() {
  const { can } = useAuth()
  const config = usePublicConfig()
  const cfg = config.data
  const catalog = useQuery({ queryKey: ['reports', 'catalog'], queryFn: () => api.get<Catalog>('/reports'), staleTime: 10 * 60_000 })
  const runs = useQuery({
    queryKey: ['evaluation', 'runs'],
    queryFn: () => api.get<EvaluationRunList>('/evaluation/runs'),
    enabled: can('evaluation:read'),
  })
  const [filters, setFilters] = React.useState<Filters>(NO_FILTERS)
  const [runId, setRunId] = React.useState('')
  const [preview, setPreview] = React.useState<string | null>(null)

  const rangeInvalid = !!filters.date_from && !!filters.date_to && filters.date_from > filters.date_to
  const activeFilters = Object.values(filters).filter(Boolean).length
  const deptName = cfg?.departments.find((d) => d.code === filters.department)?.name ?? filters.department
  const catName = cfg?.categories.find((c) => c.code === filters.category)?.name ?? filters.category
  const scopeParts = [
    filters.date_from || filters.date_to ? `${filters.date_from ? fmtDate(filters.date_from) : '…'} to ${filters.date_to ? fmtDate(filters.date_to) : '…'}` : null,
    filters.department ? `department ${deptName}` : null,
    filters.category ? `category ${catName}` : null,
  ].filter(Boolean)
  const scopeText = scopeParts.length ? scopeParts.join(', ') : 'all complaints'

  const queryFor = (key: string) => {
    const q: Record<string, string | number | undefined> = {
      date_from: filters.date_from || undefined,
      date_to: filters.date_to || undefined,
      department: filters.department || undefined,
      category: filters.category || undefined,
    }
    if (key === COMPARISON && runId) q.run_id = Number(runId)
    return q
  }
  const set = (k: keyof Filters, v: string) => setFilters((f) => ({ ...f, [k]: v }))
  const reports = catalog.data?.items ?? []
  const previewName = preview ? REPORT_INFO[preview]?.name ?? reports.find((r) => r.key === preview)?.name ?? preview : ''

  return (
    <>
      <PageHeader
        eyebrow="Insight & quality"
        title="Reports & exports"
        description="Preview any report, then export it as CSV, Excel or PDF."
      />

      <Card className="gap-3 py-4">
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Filter className="text-muted-foreground size-4" aria-hidden /> Report scope
            {activeFilters ? <Badge variant="primary">{activeFilters} active</Badge> : null}
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-[repeat(4,minmax(0,1fr))_auto] lg:items-end">
            <div className="space-y-1.5">
              <Label htmlFor="rf-from">From date</Label>
              <Input id="rf-from" type="date" value={filters.date_from} max={filters.date_to || undefined} onChange={(e) => set('date_from', e.target.value)} aria-invalid={rangeInvalid} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rf-to">To date</Label>
              <Input id="rf-to" type="date" value={filters.date_to} min={filters.date_from || undefined} onChange={(e) => set('date_to', e.target.value)} aria-invalid={rangeInvalid} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rf-dept">Department</Label>
              <NativeSelect id="rf-dept" value={filters.department} onChange={(e) => set('department', e.target.value)}>
                <option value="">All departments</option>
                {(cfg?.departments ?? []).map((d) => <option key={d.code} value={d.code}>{d.name}</option>)}
              </NativeSelect>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rf-cat">Category</Label>
              <NativeSelect id="rf-cat" value={filters.category} onChange={(e) => set('category', e.target.value)}>
                <option value="">All categories</option>
                {(cfg?.categories ?? []).map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
              </NativeSelect>
            </div>
            <Button variant="ghost" onClick={() => setFilters(NO_FILTERS)} disabled={!activeFilters}>
              <RotateCcw /> Reset
            </Button>
          </div>
          {rangeInvalid ? (
            <p className="text-destructive text-xs" role="alert">The “from” date must be on or before the “to” date.</p>
          ) : (
            <p className="text-muted-foreground text-xs">
              Scope: <span className="text-foreground font-medium">{scopeText}</span>. Dates refer to when the complaint was submitted.
            </p>
          )}
        </CardContent>
      </Card>

      {catalog.isLoading ? (
        <LoadingBlock rows={6} className="mt-6" />
      ) : catalog.error ? (
        <div className="mt-6"><ErrorState error={catalog.error} onRetry={() => catalog.refetch()} /></div>
      ) : (
        <div className="mt-6 grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
          {reports.map((r) => {
            const info = REPORT_INFO[r.key] ?? { icon: FileText, summary: 'Built from current complaint data.', contents: [], scope: 'filtered' as Scope }
            const name = info.name ?? r.name
            const Icon = info.icon
            const scope = SCOPE_BADGE[info.scope]
            const runSelected = r.key === COMPARISON && !!runId
            return (
              <Card key={r.key} className="flex flex-col">
                <CardHeader>
                  <div className="flex items-start gap-3">
                    <div className="bg-primary/10 text-primary flex size-10 shrink-0 items-center justify-center rounded-lg">
                      <Icon className="size-5" aria-hidden />
                    </div>
                    <div className="min-w-0 space-y-1.5">
                      <CardTitle className="leading-snug">{name}</CardTitle>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Tooltip content={runSelected ? 'Covers the selected evaluation run, not the filters.' : info.scopeNote ?? 'Date, department and category filters apply.'}>
                          <Badge variant={runSelected ? 'info' : scope.variant} tabIndex={0}>{runSelected ? `Evaluation run #${runId}` : scope.label}</Badge>
                        </Tooltip>
                      </div>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="flex-1 space-y-3">
                  <p className="text-muted-foreground text-sm">{info.summary}</p>
                  {info.contents.length ? (
                    <div>
                      <div className="text-muted-foreground mb-1.5 text-[11px] font-semibold uppercase tracking-wide">Contains</div>
                      <ul className="space-y-1 text-sm">
                        {info.contents.map((c) => (
                          <li key={c} className="flex gap-2">
                            <span className="bg-primary/60 mt-2 size-1 shrink-0 rounded-full" aria-hidden />
                            <span>{c}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {r.key === COMPARISON && can('evaluation:read') ? (
                    <div className="space-y-1.5 rounded-lg border border-dashed p-3">
                      <Label htmlFor="rf-run">Compare</Label>
                      <NativeSelect id="rf-run" value={runId} onChange={(e) => setRunId(e.target.value)}>
                        <option value="">Complaints (uses the filters)</option>
                        {(runs.data?.items ?? []).map((run) => (
                          <option key={run.id} value={String(run.id)}>
                            Run #{run.id} · {run.label} · {run.n_done}/{run.n_cases} cases · {run.status}
                          </option>
                        ))}
                      </NativeSelect>
                      <p className="text-muted-foreground text-xs">A run adds the expected label for each test case.</p>
                    </div>
                  ) : null}
                </CardContent>
                <CardFooter className="flex-wrap justify-between gap-2 border-t pt-4">
                  <Button size="sm" onClick={() => setPreview(r.key)} disabled={rangeInvalid}>
                    <Eye /> Preview
                  </Button>
                  <DownloadButtons path={`/reports/${r.key}`} query={queryFor(r.key)} label={`${name} report`} disabled={rangeInvalid} />
                </CardFooter>
              </Card>
            )
          })}
        </div>
      )}

      <Dialog open={preview !== null} onOpenChange={(open) => { if (!open) setPreview(null) }}>
        {preview ? <ReportPreview reportKey={preview} name={previewName} query={queryFor(preview)} /> : null}
      </Dialog>
    </>
  )
}

// ------------------------------------------------------------------ preview
function ReportPreview({ reportKey, name, query }: { reportKey: string; name: string; query: Record<string, string | number | undefined> }) {
  const report = useQuery({
    queryKey: ['report', reportKey, query],
    queryFn: () => api.get<ReportJson>(`/reports/${reportKey}`, { ...query, format: 'json' }),
  })
  const r = report.data
  return (
    <DialogContent className="max-w-6xl gap-0 p-0" showClose={false}>
      <div className="bg-popover sticky top-0 z-10 rounded-t-xl border-b px-6 pt-5 pb-4">
        <div className="flex items-start justify-between gap-4">
          <DialogHeader className="pr-0">
            <DialogTitle>{REPORT_INFO[reportKey]?.name ? `${name} report` : r?.title ?? `${name} report`}</DialogTitle>
            <DialogDescription>{r?.subtitle || 'Exports contain the same numbers as this preview.'}</DialogDescription>
          </DialogHeader>
          <DialogClose asChild>
            <Button variant="ghost" size="icon-sm" aria-label="Close preview">
              <X />
            </Button>
          </DialogClose>
        </div>
        <DownloadButtons path={`/reports/${reportKey}`} query={query} label={`${name} report`} className="mt-3" />
      </div>
      <div className="px-6 py-5">
        {report.isLoading ? (
          <LoadingBlock rows={8} />
        ) : report.error ? (
          <ErrorState error={report.error} onRetry={() => report.refetch()} title="Could not build this report" />
        ) : r ? (
          <ReportView report={r} />
        ) : null}
      </div>
    </DialogContent>
  )
}

function cellText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(value)
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (Array.isArray(value)) return value.length ? value.map(cellText).join(', ') : '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function ReportView({ report }: { report: ReportJson }) {
  const meta = Object.entries(report.meta ?? {})
  return (
    <div className="space-y-6">
      {meta.length ? (
        <dl className="bg-muted/30 grid gap-x-6 gap-y-2 rounded-lg border p-3 sm:grid-cols-2">
          {meta.map(([k, v]) => (
            <div key={k} className="min-w-0">
              <dt className="text-muted-foreground text-xs font-medium">{k}</dt>
              <dd className="text-sm">{cellText(v)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {report.sections.map((s, i) => (
        <ReportSectionView key={`${s.heading}-${i}`} section={s} />
      ))}
      {report.notes?.length ? (
        <ul className="text-muted-foreground space-y-1 border-t pt-3 text-xs">
          {report.notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      ) : null}
    </div>
  )
}

function ReportSectionView({ section: s }: { section: ReportSectionJson }) {
  return (
    <section className="space-y-3">
      <h3 className="border-b pb-1.5 text-sm font-semibold">{s.heading}</h3>
      {s.metrics.length ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
          {s.metrics.map((m) => <Metric key={m.label} label={m.label} value={cellText(m.value)} />)}
        </div>
      ) : null}
      {s.paragraphs.map((p, i) => (
        <p key={i} className="text-sm leading-relaxed whitespace-pre-line">{p}</p>
      ))}
      {s.bullets.length ? (
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {s.bullets.map((b, i) => <li key={i}>{b}</li>)}
        </ul>
      ) : null}
      {s.tables.map((t, i) => (
        <ReportTableView key={`${t.title}-${i}`} table={t} />
      ))}
    </section>
  )
}

const PAGE = 25

function ReportTableView({ table }: { table: ReportTableJson }) {
  const [limit, setLimit] = React.useState(PAGE)
  const rows = table.rows ?? []
  const numeric = table.columns.map((_, ci) => rows.length > 0 && rows.every((r) => r[ci] === null || r[ci] === undefined || typeof r[ci] === 'number'))
  const shown = rows.slice(0, limit)
  return (
    <div className="space-y-2">
      {table.title ? <h4 className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">{table.title}</h4> : null}
      {rows.length === 0 ? (
        <p className="text-muted-foreground rounded-lg border border-dashed px-3 py-4 text-center text-sm">No rows for this scope.</p>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                {table.columns.map((c, ci) => (
                  <TableHead key={`${c}-${ci}`} className={cn(numeric[ci] && 'text-right')}>{c}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((row, ri) => (
                <TableRow key={ri}>
                  {table.columns.map((_, ci) => (
                    <TableCell key={ci} className={cn('max-w-[26rem] py-2 align-top text-[13px] whitespace-normal', numeric[ci] && 'text-right tabular-nums')}>
                      {cellText(row[ci])}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {rows.length > PAGE ? (
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
          <span className="text-muted-foreground">
            Showing {Math.min(limit, rows.length).toLocaleString()} of {rows.length.toLocaleString()} rows — the CSV and Excel exports contain every row.
          </span>
          <div className="flex gap-1.5">
            {limit < rows.length ? (
              <>
                <Button variant="outline" size="sm" onClick={() => setLimit((l) => l + PAGE * 4)}>Show 100 more</Button>
                <Button variant="ghost" size="sm" onClick={() => setLimit(rows.length)}>Show all</Button>
              </>
            ) : (
              <Button variant="ghost" size="sm" onClick={() => setLimit(PAGE)}>Show fewer</Button>
            )}
          </div>
        </div>
      ) : null}
    </div>
  )
}
