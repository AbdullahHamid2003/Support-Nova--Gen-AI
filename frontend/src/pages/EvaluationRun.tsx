/* One evaluation run (SRS Deliverable 8): headline metrics, GenAI vs Python accuracy against the
   expected labels per field, detection metrics and the case-by-case comparison. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle, ArrowLeft, BadgeCheck, CheckCircle2, ChevronDown, ChevronRight, CircleX, ClipboardCheck, ExternalLink, GitCompareArrows,
  Inbox, ShieldCheck, Sparkles, Square,
} from 'lucide-react'
import * as React from 'react'
import { Link, useParams } from 'react-router'
import { toast } from 'sonner'

import { DonutChart, GroupedBarChart, Legendary } from '@/components/app/charts'
import { EmptyState, ErrorState, KeyValue, LoadingBlock, PageHeader, Pagination, Spinner, StatCard } from '@/components/app/common'
import { MatchBadge, VerificationBadge } from '@/components/app/status'
import { DownloadButtons, InfoTip, Metric, RateBar, RunStatusBadge, Segmented } from '@/components/insights/common'
import { faultTitle, FAULT_PROFILE_INFO } from '@/components/insights/fault-profiles'
import { fieldLabel, humanize, isActiveRun, pointsDelta } from '@/components/insights/format'
import type { DifficultyMetric, EvaluationRun, FieldMetric } from '@/components/insights/types'
import { Button } from '@/components/ui/button'
import {
  Alert, AlertDescription, AlertTitle, Badge, Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle, Checkbox, Label, NativeSelect,
  Progress, Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/primitives'
import { ApiError, api, errorMessage } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { fmtDateTime, fmtMs } from '@/lib/format'
import { cn, num, pct } from '@/lib/utils'

// ------------------------------------------------------------------ shapes & helpers
type MatchState = 'match' | 'partial' | 'mismatch'
interface FieldComparison { ai?: unknown; python?: unknown; expected?: unknown; ai_ok?: MatchState | null; python_ok?: MatchState | null; ai_vs_python?: MatchState | null }
interface CaseSpecial {
  prompt_injection?: { detected?: boolean; expected?: boolean; ai_flagged?: boolean | null }
  manual_review?: { expected: boolean; actual: boolean }
  duplicate_of?: string | null
  duplicate_expected?: string | null
  repeat_of?: string | null
  repeat_expected?: string | null
  latency_ms?: number
  intake_error?: string | null
  pipeline_ok?: boolean
}
interface ResultItem {
  case_id: string
  difficulty_type: string
  verification_status: string
  verification_score: number | null
  explanation: string
  expected: Record<string, unknown>
  ai: Record<string, unknown>
  python: Record<string, unknown>
  comparison: Record<string, unknown>
  complaint_ref: string
}
interface ResultsPage { total: number; page: number; page_size: number; items: ResultItem[] }

const KEY_FIELDS = ['category', 'subcategory', 'department', 'urgency', 'priority', 'escalation_level']
const ALL_FIELDS = [
  ...KEY_FIELDS, 'supporting_departments', 'escalation_required', 'refund_eligibility', 'replacement_eligibility', 'compensation_eligibility',
  'follow_up_type', 'resolution_rule', 'policy_references', 'missing_information',
]
const PAGE_SIZE = 25

function cmp(item: ResultItem, field: string): FieldComparison | undefined {
  const v = item.comparison?.[field]
  return v && typeof v === 'object' ? (v as FieldComparison) : undefined
}
function special(item: ResultItem): CaseSpecial {
  const v = item.comparison?._special
  return v && typeof v === 'object' ? (v as CaseSpecial) : {}
}
function valueText(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  if (Array.isArray(v)) return v.length ? v.map(valueText).join(', ') : 'none'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}
/** Worst of several match states (mismatch > partial > match). */
function worst(...states: (MatchState | null | undefined)[]): MatchState | null {
  const s = states.filter((x): x is MatchState => !!x)
  if (!s.length) return null
  return s.includes('mismatch') ? 'mismatch' : s.includes('partial') ? 'partial' : 'match'
}
function rowMatch(item: ResultItem): MatchState | null {
  return worst(...KEY_FIELDS.map((f) => cmp(item, f)?.ai_vs_python))
}

const OK_TEXT: Record<MatchState, string> = { match: 'text-success', partial: 'text-[oklch(0.5_0.13_60)] dark:text-warning', mismatch: 'text-destructive' }

function OkIcon({ ok }: { ok?: MatchState | null }) {
  if (ok === 'match') return <CheckCircle2 className="text-success size-3 shrink-0" aria-label="matches the expected label" />
  if (ok === 'mismatch') return <CircleX className="text-destructive size-3 shrink-0" aria-label="differs from the expected label" />
  if (ok === 'partial') return <AlertTriangle className="text-warning size-3 shrink-0" aria-label="partially matches the expected label" />
  return null
}

function Val({ value, ok, className }: { value: unknown; ok?: MatchState | null; className?: string }) {
  return <span className={cn('font-mono text-xs break-words', ok ? OK_TEXT[ok] : 'text-foreground', className)}>{valueText(value)}</span>
}

// ------------------------------------------------------------------ page
export default function EvaluationRunPage() {
  const { runId = '' } = useParams<{ runId: string }>()
  const id = Number(runId)
  const valid = Number.isInteger(id) && id > 0
  const { can } = useAuth()
  const qc = useQueryClient()
  const run = useQuery({
    queryKey: ['evaluation', 'run', id],
    queryFn: () => api.get<EvaluationRun>(`/evaluation/runs/${id}`),
    enabled: valid,
    refetchInterval: (q) => (isActiveRun(q.state.data?.status) ? 2000 : false),
  })
  const cancel = useMutation({
    mutationFn: () => api.post<{ id: number; cancelling: boolean }>(`/evaluation/runs/${id}/cancel`),
    onSuccess: () => {
      toast.success('Cancelling the run', { description: 'Metrics will cover the cases already processed.' })
      qc.invalidateQueries({ queryKey: ['evaluation'] })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  if (!valid) return <EmptyState title="Evaluation run not found" description="The run number in the address is not valid." action={<BackButton />} />
  if (run.isLoading) return <LoadingBlock rows={8} />
  if (run.error) {
    const notFound = run.error instanceof ApiError && run.error.status === 404
    return notFound ? (
      <EmptyState title={`Evaluation run #${id} not found`} description="Check the run number and try again." action={<BackButton />} />
    ) : (
      <ErrorState error={run.error} onRetry={() => run.refetch()} />
    )
  }
  const r = run.data!
  const active = isActiveRun(r.status)
  const m = r.metrics ?? {}
  const h = m.headline
  const progress = r.n_cases ? Math.round((r.n_done / r.n_cases) * 100) : 0

  return (
    <>
      <PageHeader
        eyebrow={
          <Link to="/evaluation" className="inline-flex items-center gap-1 hover:underline">
            <ArrowLeft className="size-3.5" aria-hidden /> Model evaluation · run #{r.id}
          </Link>
        }
        title={r.label || `Evaluation run #${r.id}`}
        description={
          <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
            <RunStatusBadge status={r.status} />
            <span>{num(r.n_cases)} cases from the “{r.split}” dataset</span>
            <span aria-hidden>·</span>
            <span className="font-mono text-xs">{r.provider} / {r.model}</span>
            {r.fault_injection ? <Badge variant="warning">Defect: {faultTitle(r.fault_injection)}</Badge> : null}
          </span>
        }
        actions={
          <>
            {active && can('evaluation:run') ? (
              <Button variant="destructive" size="sm" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
                {cancel.isPending ? <Spinner /> : <Square />} Cancel run
              </Button>
            ) : null}
            {can('reports:export') ? (
              <DownloadButtons path={`/evaluation/runs/${r.id}/report`} formats={['pdf', 'xlsx', 'csv']} label="Evaluation report" disabled={active} />
            ) : null}
          </>
        }
      />

      <div className="space-y-6">
        {r.fault_injection ? (
          <Alert variant="info">
            <AlertTriangle />
            <AlertTitle>Deliberate defect injected: {faultTitle(r.fault_injection)}</AlertTitle>
            <AlertDescription>
              <p>{FAULT_PROFILE_INFO[r.fault_injection]?.plain ?? r.fault_injection} Expect lower AI accuracy; the rule check should catch it.</p>
            </AlertDescription>
          </Alert>
        ) : null}
        {r.status === 'failed' ? (
          <Alert variant="destructive">
            <CircleX />
            <AlertTitle>The run failed</AlertTitle>
            <AlertDescription><p>{r.error ?? 'Unknown error.'}</p></AlertDescription>
          </Alert>
        ) : r.status === 'interrupted' ? (
          <Alert variant="warning">
            <AlertTriangle />
            <AlertTitle>The run was interrupted</AlertTitle>
            <AlertDescription><p>The server stopped while this run was in progress ({num(r.n_done)} of {num(r.n_cases)} cases). Start a new run for complete metrics.</p></AlertDescription>
          </Alert>
        ) : r.status === 'cancelled' ? (
          <Alert>
            <Square />
            <AlertTitle>Cancelled after {num(r.n_done)} of {num(r.n_cases)} cases</AlertTitle>
            <AlertDescription><p>The metrics below cover the processed cases only.</p></AlertDescription>
          </Alert>
        ) : null}

        {active ? (
          <Card className="border-info/40 bg-info/5 gap-3 py-4" role="status" aria-live="polite">
            <CardContent className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className="flex items-center gap-2 font-medium"><Spinner className="text-info" /> {r.status === 'queued' ? 'Queued — starting shortly' : 'Processing cases'}</span>
                <span className="tabular-nums">{num(r.n_done)} / {num(r.n_cases)} ({progress}%)</span>
              </div>
              <Progress value={progress} indicatorClassName="bg-info" aria-label="Run progress" />
              <p className="text-muted-foreground text-xs">Metrics appear when the run finishes. Processed cases are listed below.</p>
            </CardContent>
          </Card>
        ) : null}

        {h ? (
          <>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
              <StatCard label="Rules accuracy" value={pct(h.python_key_field_accuracy, 1)} icon={ShieldCheck} tone="validate" hint="key fields vs expected" />
              <StatCard label="AI accuracy" value={pct(h.ai_key_field_accuracy, 1)} icon={Sparkles} tone="primary" hint={`Rules ${pointsDelta(h.python_key_field_accuracy, h.ai_key_field_accuracy)}`} />
              <StatCard label="AI matches rules" value={pct(h.ai_python_key_agreement, 1)} icon={GitCompareArrows} hint="key fields" />
              <StatCard label="AI errors caught" value={`${num(h.ai_errors_caught)} / ${num(h.ai_cases_with_key_errors)}`} icon={BadgeCheck} tone="success" hint={`${pct(h.ai_error_catch_rate, 1)} caught by the rules`} />
              <StatCard label="Verified automatically" value={pct(h.verified_rate, 1)} icon={BadgeCheck} tone="success" hint="no human needed" />
              <StatCard label="Sent to manual review" value={pct(h.manual_review_rate, 1)} icon={ClipboardCheck} tone="warning" hint="a human decides" />
            </div>
            <p className="text-muted-foreground -mt-2 text-xs">
              <strong className="text-foreground">Key fields</strong> are category, subcategory, department, urgency, priority and escalation level.
              An AI error is <strong className="text-foreground">caught</strong> when the rules fix it or send the case to review.
              {h.python_key_field_accuracy === null ? ' This dataset has no expected labels, so only AI vs rules agreement is measured.' : ''}
            </p>
          </>
        ) : !active ? (
          <EmptyState icon={Inbox} title="No metrics for this run" description="Metrics appear when a run completes." />
        ) : null}

        {m.fields ? <FieldAccuracyCard fields={m.fields} /> : null}

        {h ? (
          <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
            <VerificationCard verification={m.verification ?? {}} />
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-1.5 text-sm">
                  Prompt-injection detection
                  <InfoTip>Recall = attempts caught. Precision = flags that were real.</InfoTip>
                </CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-2">
                <Metric label="Recall" value={pct(m.prompt_injection?.recall, 1)} tone="success" />
                <Metric label="Precision" value={pct(m.prompt_injection?.precision, 1)} tone="success" />
                <Metric label="Expected" value={num(m.prompt_injection?.expected)} />
                <Metric label="Detected" value={num(m.prompt_injection?.detected_tp)} />
                <Metric label="Missed" value={num(m.prompt_injection?.missed)} tone={m.prompt_injection?.missed ? 'destructive' : 'default'} />
                <Metric label="False alarms" value={num(m.prompt_injection?.false_positives)} tone={m.prompt_injection?.false_positives ? 'warning' : 'default'} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-1.5 text-sm">
                  Manual-review routing
                  <InfoTip>Recall = share of cases needing a human that went to review.</InfoTip>
                </CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-2">
                <Metric label="Recall" value={pct(m.manual_review?.recall, 1)} tone="success" className="col-span-2" />
                <Metric label="Expected" value={num(m.manual_review?.expected)} />
                <Metric label="Routed" value={num(m.manual_review?.actual)} />
                <Metric label="Both" value={num(m.manual_review?.both)} hint="expected and routed" className="col-span-2" />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-1.5 text-sm">
                  History & speed
                  <InfoTip>Times are the full processing time per case.</InfoTip>
                </CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-2">
                <Metric label="Duplicates linked" value={`${num(m.duplicates?.linked)} / ${num(m.duplicates?.expected)}`} hint="linked / expected" />
                <Metric label="Repeats detected" value={`${num(m.repeats?.detected)} / ${num(m.repeats?.expected)}`} hint="detected / expected" />
                <Metric label="Median time" value={fmtMs(m.latency_ms?.p50)} />
                <Metric label="95th percentile" value={fmtMs(m.latency_ms?.p95)} hint={m.latency_ms?.max !== undefined && m.latency_ms?.max !== null ? `max ${fmtMs(m.latency_ms.max)}` : undefined} />
              </CardContent>
            </Card>
          </div>
        ) : null}

        {m.by_difficulty && Object.keys(m.by_difficulty).length ? <DifficultyCard byDifficulty={m.by_difficulty} /> : null}

        <ResultsCard run={r} difficulties={Object.keys(m.by_difficulty ?? {}).sort()} />

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Run configuration</CardTitle>
          </CardHeader>
          <CardContent>
            <KeyValue
              columns={3}
              items={[
                ['Dataset', r.split],
                ['Cases', `${num(r.n_done)} processed of ${num(r.n_cases)}`],
                ['AI model', `${r.provider} / ${r.model}`],
                ['Deliberate defect', r.fault_injection ? `${faultTitle(r.fault_injection)} (${r.fault_injection})` : 'none'],
                ['Prompt versions', r.prompt_versions ? Object.entries(r.prompt_versions).map(([k, v]) => `${humanize(k)} ${v}`).join(' · ') : '—'],
                ['Rule Matrix version', <span key="hash" className="font-mono text-xs">{r.ruleset_hash ?? '—'}</span>],
                ['Max AI retries', m.settings?.ai_max_retries ?? '—'],
                ['Rejected at intake', m.rejected_at_intake ?? '—'],
                ['Started', fmtDateTime(r.created_at)],
                ['Completed', fmtDateTime(r.completed_at)],
                ['Duration', r.duration_seconds !== null ? `${num(r.duration_seconds, 1)} s` : '—'],
              ]}
            />
          </CardContent>
        </Card>
      </div>
    </>
  )
}

function BackButton() {
  return (
    <Button asChild variant="outline" size="sm" className="mt-2">
      <Link to="/evaluation"><ArrowLeft /> Back to evaluation</Link>
    </Button>
  )
}

// ------------------------------------------------------------------ per-field accuracy
function FieldAccuracyCard({ fields }: { fields: Record<string, FieldMetric> }) {
  const [scope, setScope] = React.useState<'key' | 'all'>('key')
  const order = (scope === 'key' ? KEY_FIELDS : ALL_FIELDS).filter((f) => fields[f])
  const extra = Object.keys(fields).filter((f) => scope === 'all' && !ALL_FIELDS.includes(f))
  const names = [...order, ...extra]
  const hasExpected = names.some((f) => fields[f].python_ok !== null || fields[f].ai_ok !== null)
  const data = names.map((f) => ({ field: fieldLabel(f), ai: fields[f].ai_ok ?? 0, python: fields[f].python_ok ?? 0 }))
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          Accuracy by field: AI vs rules
          <InfoTip>List fields, such as policy references, must match exactly.</InfoTip>
        </CardTitle>
        <CardDescription>Share of cases matching the expected label</CardDescription>
        <CardAction>
          <Segmented label="Fields shown" value={scope} onChange={setScope} options={[{ value: 'key', label: 'Key fields' }, { value: 'all', label: `All ${Object.keys(fields).length}` }]} />
        </CardAction>
      </CardHeader>
      <CardContent>
        {!hasExpected ? (
          <EmptyState icon={GitCompareArrows} title="No expected labels in this dataset" description="The table below still shows AI vs rules agreement." />
        ) : (
          <GroupedBarChart
            data={data}
            xKey="field"
            layout="vertical"
            height={names.length * 40 + 60}
            valueFormatter={(v) => pct(v, 0)}
            bars={[
              { key: 'ai', label: 'AI', color: 'var(--chart-1)' },
              { key: 'python', label: 'Rules', color: 'var(--validate)' },
            ]}
          />
        )}
        <div className="mt-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Field</TableHead>
                <TableHead className="text-right">Cases</TableHead>
                <TableHead>AI accuracy</TableHead>
                <TableHead>Rules accuracy</TableHead>
                <TableHead className="text-right">Rules lead</TableHead>
                <TableHead>AI vs rules agreement</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {names.map((f) => {
                const x = fields[f]
                return (
                  <TableRow key={f}>
                    <TableCell className="py-1.5 font-medium">{fieldLabel(f)}</TableCell>
                    <TableCell className="py-1.5 text-right tabular-nums">{num(x.n)}</TableCell>
                    <TableCell className="py-1.5"><RateBar value={x.ai_ok} color="var(--chart-1)" label="AI accuracy" /></TableCell>
                    <TableCell className="py-1.5"><RateBar value={x.python_ok} color="var(--validate)" label="Rules accuracy" /></TableCell>
                    <TableCell className={cn('py-1.5 text-right text-xs font-medium tabular-nums', (x.python_ok ?? 0) >= (x.ai_ok ?? 0) ? 'text-validate' : 'text-destructive')}>
                      {pointsDelta(x.python_ok, x.ai_ok)}
                    </TableCell>
                    <TableCell className="py-1.5"><RateBar value={x.ai_vs_python} color="var(--chart-8)" label="Agreement" /></TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

const VERIFICATION_COLORS: Record<string, string> = {
  Verified: 'var(--success)', 'Human Verified': 'var(--validate)', 'Manual Review': 'var(--warning)', Duplicate: 'var(--chart-8)', Rejected: 'var(--destructive)', Pending: 'var(--muted-foreground)',
}

function VerificationCard({ verification }: { verification: Record<string, number> }) {
  const data = Object.entries(verification).sort((a, b) => b[1] - a[1]).map(([k, v], i) => ({ label: k, value: v, color: VERIFICATION_COLORS[k] ?? `var(--chart-${(i % 8) + 1})` }))
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5 text-sm">
          Verification outcome
          <InfoTip>Final decision per case. Rejected = failed intake checks.</InfoTip>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {data.length ? (
          <>
            <DonutChart data={data} height={150} centerLabel="cases" />
            <Legendary items={data.map((d) => ({ label: d.label, value: d.value, color: d.color }))} />
          </>
        ) : (
          <p className="text-muted-foreground text-sm">No outcomes yet.</p>
        )}
      </CardContent>
    </Card>
  )
}

function DifficultyCard({ byDifficulty }: { byDifficulty: Record<string, DifficultyMetric> }) {
  const rows = Object.entries(byDifficulty).sort((a, b) => b[1].n - a[1].n)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          Results by difficulty type
          <InfoTip>Hard cases are expected to go to manual review.</InfoTip>
        </CardTitle>
        <CardDescription>How each kind of case was handled</CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Difficulty type</TableHead>
              <TableHead className="text-right">Cases</TableHead>
              <TableHead>Rules: all key fields right</TableHead>
              <TableHead>AI: all key fields right</TableHead>
              <TableHead className="text-right">Verified</TableHead>
              <TableHead className="text-right">Manual review</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map(([type, d]) => (
              <TableRow key={type}>
                <TableCell className="font-medium">{humanize(type)}</TableCell>
                <TableCell className="text-right tabular-nums">{num(d.n)}</TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <RateBar value={d.n ? d.python_key_match / d.n : null} color="var(--validate)" className="flex-1" label="Rules" />
                    <span className="text-muted-foreground w-10 text-right text-xs tabular-nums">{d.python_key_match}/{d.n}</span>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <RateBar value={d.n ? d.ai_key_match / d.n : null} color="var(--chart-1)" className="flex-1" label="AI" />
                    <span className="text-muted-foreground w-10 text-right text-xs tabular-nums">{d.ai_key_match}/{d.n}</span>
                  </div>
                </TableCell>
                <TableCell className="text-right tabular-nums">{num(d.verified)}</TableCell>
                <TableCell className="text-right tabular-nums">{num(d.review)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------------ case-by-case results (Deliverable 8)
function ResultsCard({ run, difficulties }: { run: EvaluationRun; difficulties: string[] }) {
  const [difficulty, setDifficulty] = React.useState('')
  const [mismatchesOnly, setMismatchesOnly] = React.useState(false)
  const [page, setPage] = React.useState(1)
  const [open, setOpen] = React.useState<Set<string>>(() => new Set())
  const active = isActiveRun(run.status)
  const results = useQuery({
    queryKey: ['evaluation', 'results', run.id, { difficulty, mismatchesOnly, page }],
    queryFn: () => api.get<ResultsPage>(`/evaluation/runs/${run.id}/results`, { difficulty: difficulty || undefined, mismatches_only: mismatchesOnly || undefined, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
    refetchInterval: active ? 3000 : false,
  })
  const toggle = (caseId: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(caseId)) next.delete(caseId)
      else next.add(caseId)
      return next
    })
  const data = results.data
  return (
    <Card className="py-0">
      <CardHeader className="pt-5">
        <CardTitle className="flex items-center gap-1.5">
          Case-by-case comparison
          <InfoTip>EXP = expected label. Expand a row for all fields.</InfoTip>
        </CardTitle>
        <CardDescription>Open a case to see how it was processed.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 px-0 pb-4">
        <div className="flex flex-wrap items-center gap-3 px-5">
          {difficulties.length ? (
            <div className="flex items-center gap-1.5">
              <Label htmlFor="res-difficulty" className="text-muted-foreground text-xs font-normal">Difficulty</Label>
              <NativeSelect id="res-difficulty" className="h-8 w-auto text-xs" value={difficulty} onChange={(e) => { setDifficulty(e.target.value); setPage(1) }}>
                <option value="">All types</option>
                {difficulties.map((d) => <option key={d} value={d}>{humanize(d)}</option>)}
              </NativeSelect>
            </div>
          ) : null}
          <label className="flex items-center gap-1.5 text-xs">
            <Checkbox checked={mismatchesOnly} onCheckedChange={(c) => { setMismatchesOnly(c === true); setPage(1) }} /> Only cases where AI and rules disagree
          </label>
          <div className="text-muted-foreground ml-auto flex items-center gap-3 text-xs">
            <span className="flex items-center gap-1"><CheckCircle2 className="text-success size-3" aria-hidden /> matches expected</span>
            <span className="flex items-center gap-1"><CircleX className="text-destructive size-3" aria-hidden /> differs</span>
            {results.isFetching ? <Spinner /> : null}
          </div>
        </div>
        {results.isLoading ? (
          <div className="px-5"><LoadingBlock rows={6} /></div>
        ) : results.error ? (
          <div className="px-5"><ErrorState error={results.error} onRetry={() => results.refetch()} /></div>
        ) : !data || data.items.length === 0 ? (
          <div className="px-5">
            <EmptyState icon={Inbox} title={active ? 'No cases processed yet' : 'No cases match'} description={mismatchesOnly || difficulty ? 'Try removing a filter.' : undefined} />
          </div>
        ) : (
          <>
            <Table className={cn(results.isPlaceholderData && 'opacity-60')}>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8 pl-4"><span className="sr-only">Details</span></TableHead>
                  <TableHead>Case</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead>Department</TableHead>
                  <TableHead>Urgency</TableHead>
                  <TableHead>Escalation</TableHead>
                  <TableHead>AI vs rules</TableHead>
                  <TableHead>Verification</TableHead>
                  <TableHead className="min-w-56 pr-5">Explanation</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((item) => (
                  <ResultRows key={item.case_id} item={item} open={open.has(item.case_id)} onToggle={() => toggle(item.case_id)} />
                ))}
              </TableBody>
            </Table>
            <div className="px-5">
              <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

/** Expected, GenAI and Python classification stacked in one cell (subcategory codes carry their category prefix). */
function CategoryCell({ item }: { item: ResultItem }) {
  const cat = cmp(item, 'category')
  const sub = cmp(item, 'subcategory')
  const exp = item.expected ?? {}
  if (!cat && !sub && !exp.subcategory && !exp.category) return <span className="text-muted-foreground text-xs">—</span>
  const line = (label: string, value: unknown, ok?: MatchState | null) => (
    <div className="flex items-start gap-1">
      <span className="text-muted-foreground w-7 shrink-0 text-[10px] font-semibold leading-4">{label}</span>
      {ok === undefined ? <span className="w-3.5 shrink-0" /> : <span className="mt-0.5"><OkIcon ok={ok} /></span>}
      <Val value={value} ok={ok} />
    </div>
  )
  return (
    <div className="space-y-0.5">
      {line('EXP', exp.subcategory ?? exp.category ?? 'no label')}
      {line('AI', sub?.ai ?? cat?.ai, worst(cat?.ai_ok, sub?.ai_ok))}
      {line('RULE', sub?.python ?? cat?.python, worst(cat?.python_ok, sub?.python_ok))}
    </div>
  )
}

function PairCell({ item, field }: { item: ResultItem; field: string }) {
  const c = cmp(item, field)
  if (!c) return <span className="text-muted-foreground text-xs">—</span>
  return (
    <div className="max-w-[13rem] space-y-0.5" title={c.expected !== undefined ? `Expected: ${valueText(c.expected)}` : undefined}>
      <div className="flex items-start gap-1">
        <span className="text-muted-foreground w-7 shrink-0 text-[10px] font-semibold leading-4">AI</span>
        <span className="mt-0.5"><OkIcon ok={c.ai_ok} /></span>
        <Val value={c.ai} ok={c.ai_ok} />
      </div>
      <div className="flex items-start gap-1">
        <span className="text-muted-foreground w-7 shrink-0 text-[10px] font-semibold leading-4">RULE</span>
        <span className="mt-0.5"><OkIcon ok={c.python_ok} /></span>
        <Val value={c.python} ok={c.python_ok} />
      </div>
    </div>
  )
}

function ResultRows({ item, open, onToggle }: { item: ResultItem; open: boolean; onToggle: () => void }) {
  const match = rowMatch(item)
  const sp = special(item)
  const detailId = `case-detail-${item.case_id}`
  return (
    <>
      <TableRow data-state={open ? 'selected' : undefined} className="align-top">
        <TableCell className="pl-4">
          <Button variant="ghost" size="icon-sm" onClick={onToggle} aria-expanded={open} aria-controls={detailId} aria-label={`${open ? 'Hide' : 'Show'} all fields for case ${item.case_id}`}>
            {open ? <ChevronDown /> : <ChevronRight />}
          </Button>
        </TableCell>
        <TableCell>
          <Link to={`/complaints/${item.complaint_ref}`} className="text-primary inline-flex items-center gap-1 font-mono text-xs font-semibold hover:underline" title={`Open complaint ${item.complaint_ref}`}>
            {item.case_id} <ExternalLink className="size-3" aria-hidden />
          </Link>
          {item.difficulty_type ? <div className="mt-1"><Badge variant="outline" className="px-1.5 py-0 text-[10px]">{humanize(item.difficulty_type)}</Badge></div> : null}
        </TableCell>
        <TableCell><CategoryCell item={item} /></TableCell>
        <TableCell><PairCell item={item} field="department" /></TableCell>
        <TableCell><PairCell item={item} field="urgency" /></TableCell>
        <TableCell><PairCell item={item} field="escalation_level" /></TableCell>
        <TableCell>{match ? <MatchBadge match={match} /> : <span className="text-muted-foreground text-xs">n/a</span>}</TableCell>
        <TableCell><VerificationBadge status={item.verification_status} score={item.verification_score} /></TableCell>
        <TableCell className="pr-5">
          <p className="line-clamp-4 max-w-[22rem] text-xs leading-snug">{item.explanation}</p>
        </TableCell>
      </TableRow>
      {open ? (
        <TableRow className="bg-muted/25 hover:bg-muted/25">
          <TableCell colSpan={9} className="p-0">
            <div id={detailId} className="space-y-4 px-5 py-4">
              {sp.intake_error ? (
                <Alert variant="destructive">
                  <CircleX />
                  <AlertTitle>Rejected at intake</AlertTitle>
                  <AlertDescription><p>{sp.intake_error}</p></AlertDescription>
                </Alert>
              ) : null}
              <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
                <Metric
                  label="Injection"
                  value={sp.prompt_injection?.detected ? 'Detected' : 'None'}
                  tone={sp.prompt_injection?.expected === undefined ? 'default' : sp.prompt_injection.detected === sp.prompt_injection.expected ? 'success' : 'destructive'}
                  hint={sp.prompt_injection?.expected !== undefined ? `expected: ${sp.prompt_injection.expected ? 'yes' : 'no'} · AI flagged: ${valueText(sp.prompt_injection?.ai_flagged)}` : undefined}
                />
                <Metric
                  label="Manual review"
                  value={sp.manual_review ? (sp.manual_review.actual ? 'Routed' : 'Not routed') : '—'}
                  tone={!sp.manual_review ? 'default' : sp.manual_review.actual === sp.manual_review.expected ? 'success' : sp.manual_review.actual ? 'warning' : 'destructive'}
                  hint={sp.manual_review ? `expected: ${sp.manual_review.expected ? 'yes' : 'no'}` : undefined}
                />
                <Metric label="Duplicate of" value={sp.duplicate_of ?? '—'} hint={`expected: ${valueText(sp.duplicate_expected)}`} tone={sp.duplicate_expected ? (sp.duplicate_of ? 'success' : 'destructive') : 'default'} />
                <Metric label="Repeat of" value={sp.repeat_of ?? '—'} hint={`expected: ${valueText(sp.repeat_expected)}`} tone={sp.repeat_expected ? (sp.repeat_of ? 'success' : 'destructive') : 'default'} />
                <Metric label="Processing time" value={fmtMs(sp.latency_ms)} hint={sp.pipeline_ok === false ? 'a processing problem occurred' : 'end to end'} />
                <Metric label="Score" value={item.verification_score ?? '—'} hint={item.verification_status} />
              </div>
              {Object.keys(item.comparison ?? {}).some((k) => k !== '_special') ? (
                <div className="bg-card rounded-lg border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Field</TableHead>
                        <TableHead>Expected</TableHead>
                        <TableHead>AI</TableHead>
                        <TableHead>Rules</TableHead>
                        <TableHead>AI vs expected</TableHead>
                        <TableHead>Rules vs expected</TableHead>
                        <TableHead>AI vs rules</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {ALL_FIELDS.filter((f) => cmp(item, f)).map((f) => {
                        const c = cmp(item, f)!
                        return (
                          <TableRow key={f}>
                            <TableCell className="py-1.5 text-sm font-medium">{fieldLabel(f)}</TableCell>
                            <TableCell className="max-w-[16rem] py-1.5"><Val value={c.expected} /></TableCell>
                            <TableCell className="max-w-[16rem] py-1.5"><Val value={c.ai} ok={c.ai_ok} /></TableCell>
                            <TableCell className="max-w-[16rem] py-1.5"><Val value={c.python} ok={c.python_ok} /></TableCell>
                            <TableCell className="py-1.5">{c.ai_ok ? <MatchBadge match={c.ai_ok} /> : <span className="text-muted-foreground text-xs">—</span>}</TableCell>
                            <TableCell className="py-1.5">{c.python_ok ? <MatchBadge match={c.python_ok} /> : <span className="text-muted-foreground text-xs">—</span>}</TableCell>
                            <TableCell className="py-1.5">{c.ai_vs_python ? <MatchBadge match={c.ai_vs_python} /> : <span className="text-muted-foreground text-xs">no AI output</span>}</TableCell>
                          </TableRow>
                        )
                      })}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <p className="text-muted-foreground text-sm">No field comparison: this case was {item.verification_status === 'Duplicate' ? 'linked as a duplicate and not analysed again' : 'not analysed'}.</p>
              )}
              <div className="text-sm">
                <span className="font-medium">Explanation: </span>
                <span className="text-muted-foreground">{item.explanation}</span>
              </div>
            </div>
          </TableCell>
        </TableRow>
      ) : null}
    </>
  )
}
