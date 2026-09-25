/* Complaint analytics & trend detection (SRS Steps 61-65). Every number is computed live by the API
   from the complaint database; Adversarial Lab and evaluation sandboxes are excluded server-side. */
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import {
  AlertTriangle, ArrowRight, BadgeCheck, BookOpen, Building2, ClipboardCheck, Clock, FileText, Flame, GitCompareArrows, Inbox, PieChart,
  ShieldCheck, Siren, Timer, TrendingUp,
} from 'lucide-react'
import * as React from 'react'
import { Link, useSearchParams } from 'react-router'

import { BarList, DonutChart, GroupedBarChart, Legendary, TrendChart } from '@/components/app/charts'
import { EmptyState, ErrorState, LoadingBlock, PageHeader, SectionTitle, Spinner, StatCard } from '@/components/app/common'
import { PriorityBadge } from '@/components/app/status'
import { InfoTip, Metric, RateBar, Segmented } from '@/components/insights/common'
import { dimensionLabel, fieldLabel, humanize, rateColor, ratio, REVIEW_REASONS, reviewReasonLabel, signedPercent } from '@/components/insights/format'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/overlays'
import {
  Badge, Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle, Checkbox, Label, NativeSelect,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/primitives'
import { api } from '@/lib/api'
import { useAuth, usePublicConfig } from '@/lib/auth'
import { fmtDate, fmtMs } from '@/lib/format'
import { PALETTE } from '@/lib/palette'
import type { DistributionItem, PublicConfig } from '@/lib/types'
import { cn, num, pct, titleCase } from '@/lib/utils'

// ------------------------------------------------------------------ response shapes
interface Kpis {
  total: number; open: number; resolved: number; escalated: number; manual_review_pending: number; verified_rate: number | null; analysed: number
  avg_verification_score: number; sla_at_risk: number; sla_breached: number; repeat: number; duplicates: number; injection_detected: number
  ai_python_agreement_rate: number | null; ai_python_mismatches: number; avg_resolution_hours: number | null; avg_processing_ms: number | null
}
interface OverviewData { kpis: Kpis; distributions: Record<string, DistributionItem[]> }
interface TrendsData { granularity: string; dimension: string; series: Record<string, string | number>[]; keys: { key: string; label: string }[] }
interface TrendAlert { type: string; severity: string; key?: string; label?: string; current?: number; previous?: number; change?: number; message: string }
interface CheckStat { code: string; name: string; dimension: string; pass: number; warn: number; fail: number; not_applicable: number }
interface FieldAgreement { field: string; match: number; partial: number; mismatch: number; rate: number }
interface ValidationStats {
  checks: CheckStat[]
  decisions: Record<string, number>
  field_agreement: FieldAgreement[]
  review_reasons: { code: string; count: number }[]
  dimension_scores: Record<string, number>
}
interface SlaRow { priority: string; 'On Track': number; 'At Risk': number; Breached: number; Met: number }
interface ResolutionRow { priority: string; count: number; avg_hours: number; target_hours: number | null }
interface DepartmentRow {
  department: string | null; name: string; volume: number; open: number; resolved: number; escalated: number; breached: number
  avg_resolution_hours: number | null; avg_verification_score: number | null; breach_rate: number
}
interface PolicyUsageRow { doc_id: string; section: string; ai: number; rule: number; retrieval: number }

// ------------------------------------------------------------------ labels & colours
const MUTED = 'var(--muted-foreground)'
const SEMANTIC: Record<string, Record<string, string>> = {
  priority: { P0: 'var(--destructive)', P1: 'var(--warning)', P2: 'var(--info)', P3: 'var(--chart-8)' },
  urgency: { Critical: 'var(--destructive)', High: 'var(--warning)', Medium: 'var(--info)', Low: 'var(--chart-8)' },
  sentiment: { 'Strongly Negative': 'var(--destructive)', Negative: 'var(--warning)', Neutral: 'var(--chart-8)', Mixed: 'var(--info)', Positive: 'var(--success)' },
  verification: { Verified: 'var(--success)', 'Human Verified': 'var(--validate)', 'Manual Review': 'var(--warning)', Pending: 'var(--chart-8)', Duplicate: MUTED },
  sla: { 'On Track': 'var(--success)', 'At Risk': 'var(--warning)', Breached: 'var(--destructive)', Met: 'var(--validate)' },
  status: {
    New: 'var(--info)', Processing: 'var(--primary)', Analyzed: 'var(--chart-1)', Assigned: 'var(--chart-5)', 'In Progress': 'var(--chart-2)',
    'Awaiting Customer': 'var(--warning)', Escalated: 'var(--destructive)', Resolved: 'var(--success)', Closed: 'var(--chart-8)', Reopened: 'var(--chart-6)',
  },
  escalation: {
    'No Escalation': 'var(--chart-8)', 'Supervisor Review': 'var(--chart-5)', 'Department Manager': 'var(--info)', 'Specialist Team': 'var(--warning)',
    'Compliance Review': 'var(--chart-6)', 'Critical Management Escalation': 'var(--destructive)',
  },
}

function colorFor(dimension: string, key: string | null | undefined, index: number): string {
  if (key === null || key === undefined || key === 'None') return MUTED
  return SEMANTIC[dimension]?.[key] ?? PALETTE[index % PALETTE.length]
}

const NULL_LABELS: Record<string, string> = {
  urgency: 'Not analysed', priority: 'Not analysed', sentiment: 'Not analysed', escalation: 'Not analysed', sla: 'No SLA (not analysed)',
  product: 'No product identified', department: 'Not routed', category: 'Unclassified', subcategory: 'Unclassified',
}

/** Friendly label for a distribution / trend key (channel and customer-type codes come back raw). */
function prettyLabel(cfg: PublicConfig | undefined, dimension: string, key: string | null | undefined, label: string): string {
  if (key === null || key === undefined || key === 'None') return NULL_LABELS[dimension] ?? 'Unclassified'
  if (dimension === 'channel') return cfg?.channels.find((c) => c.code === key)?.name ?? titleCase(label)
  if (dimension === 'customer_type') return cfg?.customer_types.find((c) => c.code === key)?.name ?? titleCase(label)
  return label
}

const TABS = ['volume', 'distributions', 'validation', 'sla', 'departments'] as const
type TabKey = (typeof TABS)[number]

// ------------------------------------------------------------------ page
export default function AnalyticsPage() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()
  const raw = params.get('tab') ?? ''
  const tab: TabKey = (TABS as readonly string[]).includes(raw) ? (raw as TabKey) : 'volume'
  const config = usePublicConfig()
  const overview = useQuery({
    queryKey: ['analytics', 'overview'],
    queryFn: () => api.get<OverviewData>('/analytics/overview'),
    refetchInterval: 60_000,
  })
  const kpis = overview.data?.kpis

  const setTab = (value: string) => {
    const next = new URLSearchParams(params)
    next.set('tab', value)
    setParams(next, { replace: true })
  }

  return (
    <>
      <PageHeader
        eyebrow="Insight & quality"
        title="Complaint analytics"
        description="Complaint volume, trends, SLA and AI accuracy."
        actions={
          can('reports:export') ? (
            <Button asChild variant="outline" size="sm">
              <Link to="/reports"><FileText /> Reports & exports</Link>
            </Button>
          ) : null
        }
      />

      {overview.isLoading ? (
        <LoadingBlock rows={2} />
      ) : overview.error ? (
        <ErrorState error={overview.error} onRetry={() => overview.refetch()} />
      ) : kpis ? (
        <KpiRow k={kpis} />
      ) : null}

      <Tabs value={tab} onValueChange={setTab} className="mt-6">
        <TabsList aria-label="Analytics sections">
          <TabsTrigger value="volume"><TrendingUp aria-hidden /> Volume & trends</TabsTrigger>
          <TabsTrigger value="distributions"><PieChart aria-hidden /> Distributions</TabsTrigger>
          <TabsTrigger value="validation"><GitCompareArrows aria-hidden /> AI vs rules</TabsTrigger>
          <TabsTrigger value="sla"><Timer aria-hidden /> SLA & resolution</TabsTrigger>
          <TabsTrigger value="departments"><Building2 aria-hidden /> Departments & policy</TabsTrigger>
        </TabsList>
        <TabsContent value="volume">
          <VolumeTab overview={overview.data} cfg={config.data} />
        </TabsContent>
        <TabsContent value="distributions">
          {overview.data ? <DistributionsTab overview={overview.data} cfg={config.data} /> : <LoadingBlock rows={6} />}
        </TabsContent>
        <TabsContent value="validation">
          <ValidationTab />
        </TabsContent>
        <TabsContent value="sla">
          <SlaTab />
        </TabsContent>
        <TabsContent value="departments">
          <DepartmentsTab />
        </TabsContent>
      </Tabs>
    </>
  )
}

function KpiRow({ k }: { k: Kpis }) {
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
      <StatCard label="Complaints" value={num(k.total)} icon={Inbox} tone="primary" hint={`${num(k.open)} open · ${num(k.resolved)} resolved or closed`} />
      <StatCard label="Escalated" value={num(k.escalated)} icon={Siren} tone="destructive" hint={`${pct(ratio(k.escalated, k.total), 1)} of all complaints`} />
      <StatCard label="Verified" value={pct(k.verified_rate, 1)} icon={BadgeCheck} tone="success" hint={`auto + human, of ${num(k.analysed)} analysed · avg score ${k.avg_verification_score}`} />
      <StatCard label="Awaiting review" value={num(k.manual_review_pending)} icon={ClipboardCheck} tone="warning" hint="pending or in review" />
      <StatCard label="SLA at risk · breached" value={`${num(k.sla_at_risk)} · ${num(k.sla_breached)}`} icon={Clock} tone={k.sla_breached ? 'destructive' : 'warning'} hint="open complaints only" />
      <StatCard label="AI matches rules" value={pct(k.ai_python_agreement_rate, 1)} icon={GitCompareArrows} tone="validate" hint={`${num(k.ai_python_mismatches)} complaints differ on a key field`} />
    </div>
  )
}

// ------------------------------------------------------------------ volume & trends
const TREND_DIMENSIONS = [
  { value: 'category', label: 'Category' },
  { value: 'department', label: 'Department' },
  { value: 'product', label: 'Product' },
  { value: 'urgency', label: 'Urgency' },
  { value: 'sentiment', label: 'Sentiment' },
  { value: 'priority', label: 'Priority' },
  { value: 'channel', label: 'Channel' },
]
const TREND_WINDOWS = [30, 60, 90, 120, 180, 365, 730]

function VolumeTab({ overview, cfg }: { overview?: OverviewData; cfg?: PublicConfig }) {
  const [dimension, setDimension] = React.useState('category')
  const [days, setDays] = React.useState(120)
  const [granularity, setGranularity] = React.useState<'day' | 'week'>('week')
  const trends = useQuery({
    queryKey: ['analytics', 'trends', { days, granularity, dimension }],
    queryFn: () => api.get<TrendsData>('/analytics/trends', { days, granularity, dimension }),
    placeholderData: keepPreviousData,
  })
  const data = trends.data
  const dim = data?.dimension ?? dimension
  const dimLabel = TREND_DIMENSIONS.find((d) => d.value === dim)?.label ?? humanize(dim)
  const pattern = days > 365 ? 'd MMM yy' : 'd MMM'
  const series: Record<string, string | number>[] = (data?.series ?? []).map((p) => ({ ...p, label: fmtDate(String(p.bucket), pattern) }))
  const keys = (data?.keys ?? []).map((k, i) => ({ key: k.key, label: prettyLabel(cfg, dim, k.key, k.label), color: colorFor(dim, k.key, i) }))
  const sum = (field: string) => series.reduce((s, p) => s + Number(p[field] ?? 0), 0)
  const total = sum('total')
  const escalated = sum('escalations')
  const negative = sum('negative')
  const peak = series.reduce<(typeof series)[number] | null>((best, p) => (best === null || Number(p.total) > Number(best.total) ? p : best), null)

  return (
    <div className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Complaint volume trend</CardTitle>
            <CardDescription>
              {granularity === 'week' ? 'Weekly' : 'Daily'}, last {days} days, top {keys.length || 6} {dimLabel.toLowerCase()} values
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <div className="flex items-center gap-1.5">
                <Label htmlFor="trend-dimension" className="text-muted-foreground text-xs font-normal">Split by</Label>
                <NativeSelect id="trend-dimension" className="h-8 w-auto text-xs" value={dimension} onChange={(e) => setDimension(e.target.value)}>
                  {TREND_DIMENSIONS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
                </NativeSelect>
              </div>
              <div className="flex items-center gap-1.5">
                <Label htmlFor="trend-window" className="text-muted-foreground text-xs font-normal">Window</Label>
                <NativeSelect id="trend-window" className="h-8 w-auto text-xs" value={days} onChange={(e) => setDays(Number(e.target.value))}>
                  {TREND_WINDOWS.map((d) => <option key={d} value={d}>Last {d} days</option>)}
                </NativeSelect>
              </div>
              <Segmented label="Granularity" value={granularity} onChange={setGranularity} options={[{ value: 'day', label: 'Daily' }, { value: 'week', label: 'Weekly' }]} />
              {trends.isFetching ? <Spinner className="text-muted-foreground" /> : null}
            </div>
            {trends.isLoading ? (
              <LoadingBlock rows={5} />
            ) : trends.error ? (
              <ErrorState error={trends.error} onRetry={() => trends.refetch()} />
            ) : series.length === 0 ? (
              <EmptyState icon={TrendingUp} title="No complaints in this window" description="Choose a longer window to see the trend." />
            ) : (
              <>
                <TrendChart data={series} xKey="label" series={keys} stacked height={280} />
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <Metric label="In window" value={num(total)} hint={`${series.length} ${granularity === 'week' ? 'weeks' : 'days'}`} />
                  <Metric label="Escalated" value={num(escalated)} hint={`${pct(ratio(escalated, total), 1)} of volume`} tone={escalated ? 'destructive' : 'default'} />
                  <Metric label="Negative sentiment" value={num(negative)} hint={`${pct(ratio(negative, total), 1)} of volume`} tone={negative ? 'warning' : 'default'} />
                  <Metric label={granularity === 'week' ? 'Busiest week' : 'Busiest day'} value={peak ? num(Number(peak.total)) : '—'} hint={peak ? `${granularity === 'week' ? 'week of ' : ''}${fmtDate(String(peak.bucket))}` : undefined} />
                </div>
              </>
            )}
          </CardContent>
        </Card>
        <AlertsCard />
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Escalations and negative sentiment over time</CardTitle>
            <CardDescription>Uses the same filters as the chart above.</CardDescription>
          </CardHeader>
          <CardContent>
            {series.length ? (
              <TrendChart
                data={series}
                xKey="label"
                height={240}
                series={[
                  { key: 'total', label: 'All complaints', color: 'var(--chart-1)' },
                  { key: 'escalations', label: 'Escalated', color: 'var(--destructive)' },
                  { key: 'negative', label: 'Negative sentiment', color: 'var(--warning)' },
                ]}
              />
            ) : trends.isLoading ? (
              <LoadingBlock rows={4} />
            ) : (
              <p className="text-muted-foreground text-sm">No data in this window.</p>
            )}
          </CardContent>
        </Card>
        <EscalationCard overview={overview} />
      </div>

      <SignalsCard overview={overview} />
    </div>
  )
}

const ALERT_TYPES: Record<string, string> = {
  rising_category: 'Rising category',
  rising_department: 'Rising department',
  rising_product: 'Rising product',
  escalation_spike: 'Escalation spike',
  recurring_product_issue: 'Recurring product issue',
  repeated_service_failures: 'Repeated service failures',
}

function AlertsCard() {
  const [windowDays, setWindowDays] = React.useState(14)
  const alerts = useQuery({
    queryKey: ['analytics', 'alerts', windowDays],
    queryFn: () => api.get<{ items: TrendAlert[]; window_days: number }>('/analytics/alerts', { window_days: windowDays }),
    placeholderData: keepPreviousData,
  })
  const items = alerts.data?.items ?? []
  const high = items.filter((a) => a.severity === 'high').length
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          Trend alerts
          <InfoTip>
            Last {windowDays} days compared with the {windowDays} days before.
          </InfoTip>
        </CardTitle>
        <CardDescription>Rising or recurring issues.</CardDescription>
        <CardAction>
          <NativeSelect aria-label="Alert comparison window" className="h-8 w-auto text-xs" value={windowDays} onChange={(e) => setWindowDays(Number(e.target.value))}>
            {[7, 14, 30, 60, 90].map((d) => <option key={d} value={d}>{d} days</option>)}
          </NativeSelect>
        </CardAction>
      </CardHeader>
      <CardContent>
        {alerts.isLoading ? (
          <LoadingBlock rows={4} />
        ) : alerts.error ? (
          <ErrorState error={alerts.error} onRetry={() => alerts.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState icon={ShieldCheck} title="No trend alerts" description={`Nothing rose notably in the last ${windowDays} days.`} />
        ) : (
          <>
            <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
              <Badge variant="destructive">{high} high</Badge>
              <Badge variant="warning">{items.length - high} medium</Badge>
              {alerts.isFetching ? <Spinner className="text-muted-foreground" /> : null}
            </div>
            <ul className="max-h-[27rem] space-y-2 overflow-y-auto pr-1 scrollbar-thin" aria-label="Trend alerts">
              {items.map((a, i) => (
                <AlertItem key={`${a.type}-${a.key ?? i}`} alert={a} />
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function AlertItem({ alert: a }: { alert: TrendAlert }) {
  const high = a.severity === 'high'
  const Icon = high ? Flame : AlertTriangle
  return (
    <li className={cn('flex items-start gap-3 rounded-lg border p-3', high ? 'border-destructive/25 bg-destructive/5' : 'border-warning/35 bg-warning/5')}>
      <Icon className={cn('mt-0.5 size-4 shrink-0', high ? 'text-destructive' : 'text-warning')} aria-hidden />
      <div className="min-w-0 flex-1 text-sm">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-medium">{ALERT_TYPES[a.type] ?? humanize(a.type)}</span>
          <Badge variant={high ? 'destructive' : 'warning'} className="px-1.5 py-0 text-[10px] uppercase tracking-wide">{a.severity}</Badge>
        </div>
        <p className="text-muted-foreground mt-0.5 leading-snug">{a.message}</p>
        {a.current !== undefined ? (
          <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs tabular-nums">
            <span>Now <strong>{a.current}</strong></span>
            {a.previous !== undefined ? <span>{a.type === 'escalation_spike' ? 'Weekly average' : 'Before'} <strong>{a.previous}</strong></span> : null}
            {a.change !== undefined ? <span className={cn('font-semibold', high ? 'text-destructive' : 'text-[oklch(0.5_0.13_60)] dark:text-warning')}>{signedPercent(a.change)}</span> : null}
          </div>
        ) : null}
      </div>
    </li>
  )
}

function EscalationCard({ overview }: { overview?: OverviewData }) {
  if (!overview) return <Card><CardContent><LoadingBlock rows={4} /></CardContent></Card>
  const { kpis, distributions } = overview
  const levels = (distributions.escalation ?? []).filter((d) => d.key && d.key !== 'No Escalation')
  const critical = levels.find((d) => d.key === 'Critical Management Escalation')?.count ?? 0
  return (
    <Card>
      <CardHeader>
        <CardTitle>Escalation levels</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Metric label="Escalated" value={num(kpis.escalated)} tone="destructive" hint={`${pct(ratio(kpis.escalated, kpis.total), 1)} of complaints`} />
          <Metric label="Critical" value={num(critical)} hint="management escalation" tone={critical ? 'destructive' : 'default'} />
        </div>
        {levels.length ? (
          <BarList items={levels.map((d) => ({ label: d.label, value: d.count, hint: pct(d.share, 1) }))} colorBy={(label, i) => colorFor('escalation', label, i)} />
        ) : (
          <p className="text-muted-foreground text-sm">No escalations recorded.</p>
        )}
      </CardContent>
    </Card>
  )
}

function SignalsCard({ overview }: { overview?: OverviewData }) {
  if (!overview) return null
  const k = overview.kpis
  return (
    <Card>
      <CardHeader>
        <CardTitle>Repeat complaints, duplicates and screening</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric
          label="Repeat complaints"
          value={num(k.repeat)}
          hint={`${pct(ratio(k.repeat, k.total), 1)} of complaints`}
          info="Same customer, same issue, within the repeat window."
        />
        <Metric
          label="Duplicates linked"
          value={num(k.duplicates)}
          hint="linked to the original, not re-opened"
          info="Exact or near-identical resubmissions of a complaint."
        />
        <Metric
          label="Prompt-injection attempts"
          value={num(k.injection_detected)}
          tone={k.injection_detected ? 'destructive' : 'default'}
          hint="neutralised and sent to human review"
          info="Hidden instructions found in the complaint text."
        />
        <Metric
          label="Avg processing time"
          value={fmtMs(k.avg_processing_ms)}
          hint={k.avg_resolution_hours !== null ? `avg resolution ${num(k.avg_resolution_hours, 1)} h` : undefined}
          info="Average time to analyse, check and route a complaint."
        />
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------------ distributions
interface DistSpec { dim: string; title: string; info: string; kind?: 'bars' | 'donut'; limit?: number }
const DIST_GROUPS: { title: string; description: string; cards: DistSpec[] }[] = [
  {
    title: 'Classification',
    description: 'What customers complain about.',
    cards: [
      { dim: 'category', title: 'Category', info: 'Final category after the rule check.' },
      { dim: 'subcategory', title: 'Subcategory', info: 'Specific issue type within the category.', limit: 10 },
      { dim: 'product', title: 'Product or service', info: 'Product from the order record or the complaint text.', limit: 10 },
    ],
  },
  {
    title: 'Routing & priority',
    description: 'Where complaints go and how fast they must be handled.',
    cards: [
      { dim: 'department', title: 'Primary department', info: 'Department the complaint was routed to.' },
      { dim: 'urgency_priority', title: 'Urgency and priority', info: 'Priority P0–P3 combines urgency and impact.' },
      { dim: 'escalation', title: 'Escalation level', info: 'Highest escalation level required by the escalation rules.' },
    ],
  },
  {
    title: 'Customer & channel',
    description: 'Who complains, how they reach Lumora, and how they feel.',
    cards: [
      { dim: 'sentiment', title: 'Sentiment', info: 'Strong emotion alone never raises urgency.' },
      { dim: 'channel', title: 'Channel', info: 'How the complaint was submitted.' },
      { dim: 'customer_type', title: 'Customer type', info: 'Affects eligibility, never urgency or priority.' },
    ],
  },
  {
    title: 'Outcome',
    description: 'Where each complaint stands now.',
    cards: [
      { dim: 'status', title: 'Status', kind: 'donut', info: 'Current complaint status.' },
      { dim: 'verification', title: 'Verification', kind: 'donut', info: 'Pending = not analysed, such as linked duplicates.' },
      { dim: 'sla', title: 'SLA state', kind: 'donut', info: 'Met = resolved within the SLA target.' },
    ],
  },
]

function DistributionsTab({ overview, cfg }: { overview: OverviewData; cfg?: PublicConfig }) {
  const dist = overview.distributions
  return (
    <div className="space-y-8">
      {DIST_GROUPS.map((group) => (
        <section key={group.title} aria-labelledby={`dist-${group.title}`}>
          <div className="mb-3">
            <h2 id={`dist-${group.title}`} className="text-sm font-semibold">{group.title}</h2>
            <p className="text-muted-foreground text-xs">{group.description}</p>
          </div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {group.cards.map((spec) =>
              spec.dim === 'urgency_priority' ? (
                <UrgencyPriorityCard key={spec.dim} spec={spec} urgency={dist.urgency ?? []} priority={dist.priority ?? []} />
              ) : (
                <DistributionCard key={spec.dim} spec={spec} items={(dist[spec.dim] ?? []).map((d) => ({ ...d, label: prettyLabel(cfg, spec.dim, d.key, d.label) }))} />
              ),
            )}
          </div>
        </section>
      ))}
    </div>
  )
}

function DistributionCard({ spec, items }: { spec: DistSpec; items: DistributionItem[] }) {
  const [all, setAll] = React.useState(false)
  const limit = spec.limit ?? 12
  const shown = all ? items : items.slice(0, limit)
  const total = items.reduce((s, d) => s + d.count, 0)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5 text-sm">
          {spec.title}
          <InfoTip>{spec.info}</InfoTip>
        </CardTitle>
        <CardDescription className="text-xs">{num(total)} complaints · {items.length} values</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {items.length === 0 ? (
          <p className="text-muted-foreground text-sm">No data yet.</p>
        ) : spec.kind === 'donut' ? (
          <>
            <DonutChart data={items.map((d, i) => ({ label: d.label, value: d.count, color: colorFor(spec.dim, d.key, i) }))} centerLabel="complaints" height={180} />
            <Legendary items={items.map((d, i) => ({ label: d.label, value: `${num(d.count)} · ${pct(d.share)}`, color: colorFor(spec.dim, d.key, i) }))} />
          </>
        ) : (
          <>
            <BarList items={shown.map((d) => ({ label: d.label, value: d.count, hint: pct(d.share, 1) }))} colorBy={(_label, i) => colorFor(spec.dim, shown[i]?.key, i)} />
            {items.length > limit ? (
              <Button variant="ghost" size="sm" className="w-full" onClick={() => setAll((v) => !v)} aria-expanded={all}>
                {all ? 'Show fewer' : `Show all ${items.length}`}
              </Button>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  )
}

function UrgencyPriorityCard({ spec, urgency, priority }: { spec: DistSpec; urgency: DistributionItem[]; priority: DistributionItem[] }) {
  const order = ['P0', 'P1', 'P2', 'P3']
  const prio = [...priority].sort((a, b) => (order.indexOf(a.key ?? '') + 10 * Number(a.key === null)) - (order.indexOf(b.key ?? '') + 10 * Number(b.key === null)))
  const urg = ['Critical', 'High', 'Medium', 'Low'].map((u) => urgency.find((d) => d.key === u)).filter((d): d is DistributionItem => !!d)
  const prioTotal = prio.reduce((s, d) => s + d.count, 0) || 1
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5 text-sm">
          {spec.title}
          <InfoTip>{spec.info}</InfoTip>
        </CardTitle>
        <CardDescription className="text-xs">Priority mix (top) and urgency levels (below)</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <div className="flex h-3 overflow-hidden rounded-full" role="img" aria-label={prio.map((d) => `${d.label}: ${d.count}`).join(', ')}>
            {prio.map((d, i) => (
              <div key={d.key ?? 'none'} style={{ width: `${(d.count / prioTotal) * 100}%`, background: colorFor('priority', d.key, i) }} title={`${d.key ?? 'Not analysed'}: ${d.count}`} />
            ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
            {prio.map((d, i) => (
              <span key={d.key ?? 'none'} className="flex items-center gap-1.5">
                <span className="size-2.5 rounded-sm" style={{ background: colorFor('priority', d.key, i) }} aria-hidden />
                {d.key ?? 'Not analysed'} <span className="text-muted-foreground tabular-nums">{num(d.count)}</span>
              </span>
            ))}
          </div>
        </div>
        <BarList items={urg.map((d) => ({ label: d.label, value: d.count, hint: pct(d.share, 1) }))} colorBy={(label, i) => colorFor('urgency', label, i)} />
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------------ GenAI vs Python validation
function ValidationTab() {
  const v = useQuery({ queryKey: ['analytics', 'validation'], queryFn: () => api.get<ValidationStats>('/analytics/validation') })
  if (v.isLoading) return <LoadingBlock rows={8} />
  if (v.error) return <ErrorState error={v.error} onRetry={() => v.refetch()} />
  const d = v.data!
  const decisions = Object.entries(d.decisions).sort((a, b) => b[1] - a[1])
  const validated = decisions.reduce((s, [, n]) => s + n, 0)
  const decisionColor = (k: string, i: number) => (k === 'Verified' ? 'var(--success)' : k === 'Manual Review' ? 'var(--warning)' : PALETTE[(i + 2) % PALETTE.length])
  const dims = Object.entries(d.dimension_scores).sort((a, b) => a[1] - b[1])
  const dimColor = new Map(dims.map(([k, s]) => [dimensionLabel(k), s >= 90 ? 'var(--success)' : s >= 75 ? 'var(--warning)' : 'var(--destructive)']))
  const fields = [...d.field_agreement].sort((a, b) => b.rate - a.rate)
  const reasonsTotal = d.review_reasons.reduce((s, r) => s + r.count, 0)

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5">
              Rules decision
              <InfoTip>Decision from the latest rule check of each complaint.</InfoTip>
            </CardTitle>
            <CardDescription>{num(validated)} complaints checked</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {decisions.length ? (
              <>
                <DonutChart data={decisions.map(([k, n], i) => ({ label: k, value: n, color: decisionColor(k, i) }))} centerLabel="checked" height={180} />
                <Legendary items={decisions.map(([k, n], i) => ({ label: k, value: `${num(n)} · ${pct(ratio(n, validated))}`, color: decisionColor(k, i) }))} />
              </>
            ) : (
              <p className="text-muted-foreground text-sm">No rule checks yet.</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5">
              Score by check area
              <InfoTip>Average score out of 100, weakest area first.</InfoTip>
            </CardTitle>
            <CardDescription>Green ≥ 90 · amber ≥ 75 · red below</CardDescription>
          </CardHeader>
          <CardContent>
            {dims.length ? (
              <BarList items={dims.map(([k, s]) => ({ label: dimensionLabel(k), value: s }))} max={100} formatValue={(x) => x.toFixed(1)} colorBy={(label) => dimColor.get(label) ?? PALETTE[0]} />
            ) : (
              <p className="text-muted-foreground text-sm">No scores yet.</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5">
              Why complaints went to review
              <InfoTip>One complaint can have several reasons.</InfoTip>
            </CardTitle>
            <CardDescription>{num(reasonsTotal)} reasons in total</CardDescription>
          </CardHeader>
          <CardContent>
            {d.review_reasons.length ? (
              <BarList
                items={d.review_reasons.map((r) => ({ label: reviewReasonLabel(r.code), value: r.count, hint: REVIEW_REASONS[r.code]?.rule }))}
                colorBy={() => 'var(--warning)'}
              />
            ) : (
              <p className="text-muted-foreground text-sm">No complaints sent to review.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            Field agreement: AI vs rules
            <InfoTip>How often the AI value matched the rules value.</InfoTip>
          </CardTitle>
          <CardDescription>Latest check per complaint, sorted by agreement</CardDescription>
        </CardHeader>
        <CardContent>
          {fields.length === 0 ? (
            <EmptyState icon={GitCompareArrows} title="No comparisons yet" description="Field agreement appears once complaints have been analysed." />
          ) : (
            <div className="grid gap-6 xl:grid-cols-5">
              <div className="xl:col-span-3">
                <GroupedBarChart
                  data={fields.map((f) => ({ label: fieldLabel(f.field), match: f.match, partial: f.partial, mismatch: f.mismatch }))}
                  xKey="label"
                  layout="vertical"
                  stacked
                  height={fields.length * 28 + 60}
                  bars={[
                    { key: 'match', label: 'Agree', color: 'var(--success)' },
                    { key: 'partial', label: 'Partial', color: 'var(--warning)' },
                    { key: 'mismatch', label: 'Disagree', color: 'var(--destructive)' },
                  ]}
                />
              </div>
              <div className="xl:col-span-2">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Field</TableHead>
                      <TableHead>Agreement</TableHead>
                      <TableHead className="text-right">Disagree</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {fields.map((f) => (
                      <TableRow key={f.field}>
                        <TableCell className="py-1.5 text-sm">{fieldLabel(f.field)}</TableCell>
                        <TableCell className="py-1.5"><RateBar value={f.rate} label="Agreement" /></TableCell>
                        <TableCell className="py-1.5 text-right text-xs tabular-nums">
                          {num(f.mismatch)}
                          {f.partial ? <span className="text-muted-foreground"> · {num(f.partial)} partial</span> : null}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <ChecksTable checks={d.checks} />
    </div>
  )
}

function ChecksTable({ checks }: { checks: CheckStat[] }) {
  const [dimension, setDimension] = React.useState('')
  const [failingOnly, setFailingOnly] = React.useState(false)
  const [all, setAll] = React.useState(false)
  const dimensions = [...new Set(checks.map((c) => c.dimension))].sort()
  const filtered = checks.filter((c) => (!dimension || c.dimension === dimension) && (!failingOnly || c.fail > 0))
  const shown = all ? filtered : filtered.slice(0, 15)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          Rule checks
          <InfoTip>Fail rate counts only checks that applied.</InfoTip>
        </CardTitle>
        <CardDescription>Latest check per complaint, most failures first</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <NativeSelect aria-label="Filter checks by area" className="h-8 w-auto text-xs" value={dimension} onChange={(e) => setDimension(e.target.value)}>
            <option value="">All areas</option>
            {dimensions.map((dm) => <option key={dm} value={dm}>{dimensionLabel(dm)}</option>)}
          </NativeSelect>
          <label className="flex items-center gap-1.5 text-xs">
            <Checkbox checked={failingOnly} onCheckedChange={(c) => setFailingOnly(c === true)} /> Only checks with failures
          </label>
          <span className="text-muted-foreground ml-auto text-xs">{filtered.length} of {checks.length} checks</span>
        </div>
        {filtered.length === 0 ? (
          <p className="text-muted-foreground py-6 text-center text-sm">No checks match this filter.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Check</TableHead>
                <TableHead className="hidden md:table-cell">Area</TableHead>
                <TableHead className="w-[22%]">Outcome mix</TableHead>
                <TableHead className="text-right">Pass</TableHead>
                <TableHead className="text-right">Warn</TableHead>
                <TableHead className="text-right">Fail</TableHead>
                <TableHead className="hidden text-right sm:table-cell">N/A</TableHead>
                <TableHead className="text-right">Fail rate</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((c) => {
                const applicable = c.pass + c.warn + c.fail
                const failRate = ratio(c.fail, applicable)
                return (
                  <TableRow key={c.code}>
                    <TableCell className="max-w-[22rem]">
                      <div className="font-mono text-xs font-semibold">{c.code}</div>
                      <div className="text-sm leading-snug">{c.name}</div>
                    </TableCell>
                    <TableCell className="hidden md:table-cell"><Badge variant="outline">{dimensionLabel(c.dimension)}</Badge></TableCell>
                    <TableCell><OutcomeBar pass={c.pass} warn={c.warn} fail={c.fail} /></TableCell>
                    <TableCell className="text-right tabular-nums text-success">{num(c.pass)}</TableCell>
                    <TableCell className="text-right tabular-nums text-[oklch(0.5_0.13_60)] dark:text-warning">{num(c.warn)}</TableCell>
                    <TableCell className="text-right font-medium tabular-nums text-destructive">{num(c.fail)}</TableCell>
                    <TableCell className="text-muted-foreground hidden text-right tabular-nums sm:table-cell">{num(c.not_applicable)}</TableCell>
                    <TableCell className="text-right text-xs tabular-nums">{pct(failRate, 1)}</TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
        {filtered.length > 15 ? (
          <Button variant="ghost" size="sm" className="w-full" onClick={() => setAll((v) => !v)} aria-expanded={all}>
            {all ? 'Show fewer checks' : `Show all ${filtered.length} checks`}
          </Button>
        ) : null}
      </CardContent>
    </Card>
  )
}

function OutcomeBar({ pass, warn, fail }: { pass: number; warn: number; fail: number }) {
  const total = pass + warn + fail
  if (!total) return <span className="text-muted-foreground text-xs">not applicable</span>
  const seg = (n: number, color: string, label: string) => (n ? <div style={{ width: `${(n / total) * 100}%`, background: color }} title={`${label}: ${n}`} /> : null)
  return (
    <div className="bg-muted flex h-2 min-w-24 overflow-hidden rounded-full" role="img" aria-label={`${pass} pass, ${warn} warning, ${fail} fail`}>
      {seg(pass, 'var(--success)', 'Pass')}
      {seg(warn, 'var(--warning)', 'Warning')}
      {seg(fail, 'var(--destructive)', 'Fail')}
    </div>
  )
}

// ------------------------------------------------------------------ SLA & resolution
function SlaTab() {
  const sla = useQuery({ queryKey: ['analytics', 'sla'], queryFn: () => api.get<{ by_priority: SlaRow[] }>('/analytics/sla') })
  const res = useQuery({ queryKey: ['analytics', 'resolution-times'], queryFn: () => api.get<{ items: ResolutionRow[] }>('/analytics/resolution-times') })
  const rows = (sla.data?.by_priority ?? []).map((r) => {
    const tracked = r['On Track'] + r['At Risk'] + r.Breached + r.Met
    return { priority: r.priority, met: r.Met, on_track: r['On Track'], at_risk: r['At Risk'], breached: r.Breached, tracked }
  })
  const times = res.data?.items ?? []
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            SLA status by priority
            <InfoTip>Met = resolved in time. Breached = target missed.</InfoTip>
          </CardTitle>
          <CardDescription>All analysed complaints</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {sla.isLoading ? (
            <LoadingBlock rows={5} />
          ) : sla.error ? (
            <ErrorState error={sla.error} onRetry={() => sla.refetch()} />
          ) : rows.length === 0 ? (
            <EmptyState icon={Clock} title="No SLA records yet" />
          ) : (
            <>
              <GroupedBarChart
                data={rows}
                xKey="priority"
                stacked
                height={240}
                bars={[
                  { key: 'met', label: 'Met', color: 'var(--validate)' },
                  { key: 'on_track', label: 'On track', color: 'var(--success)' },
                  { key: 'at_risk', label: 'At risk', color: 'var(--warning)' },
                  { key: 'breached', label: 'Breached', color: 'var(--destructive)' },
                ]}
              />
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Priority</TableHead>
                    <TableHead className="text-right">Tracked</TableHead>
                    <TableHead className="text-right">Met</TableHead>
                    <TableHead className="text-right">On track</TableHead>
                    <TableHead className="text-right">At risk</TableHead>
                    <TableHead className="text-right">Breached</TableHead>
                    <TableHead>Breach rate</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((r) => {
                    const rate = ratio(r.breached, r.tracked)
                    return (
                      <TableRow key={r.priority}>
                        <TableCell><PriorityBadge priority={r.priority} /></TableCell>
                        <TableCell className="text-right tabular-nums">{num(r.tracked)}</TableCell>
                        <TableCell className="text-right tabular-nums">{num(r.met)}</TableCell>
                        <TableCell className="text-right tabular-nums">{num(r.on_track)}</TableCell>
                        <TableCell className="text-right tabular-nums">{num(r.at_risk)}</TableCell>
                        <TableCell className="text-right font-medium tabular-nums text-destructive">{num(r.breached)}</TableCell>
                        <TableCell><RateBar value={rate} color={rate === null ? undefined : rateColor(rate, { good: 0.85, fair: 0.7, invert: true })} label="Breach rate" /></TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            Resolution time vs SLA target
            <InfoTip>An average within target can still hide breaches.</InfoTip>
          </CardTitle>
          <CardDescription>Resolved complaints only · hours</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {res.isLoading ? (
            <LoadingBlock rows={5} />
          ) : res.error ? (
            <ErrorState error={res.error} onRetry={() => res.refetch()} />
          ) : times.length === 0 ? (
            <EmptyState icon={Timer} title="No resolved complaints yet" />
          ) : (
            <>
              <GroupedBarChart
                data={times.map((t) => ({ priority: t.priority, avg: t.avg_hours, target: t.target_hours ?? 0 }))}
                xKey="priority"
                height={240}
                valueFormatter={(v) => `${num(v, 1)} h`}
                bars={[
                  { key: 'avg', label: 'Average resolution', color: 'var(--chart-1)' },
                  { key: 'target', label: 'SLA target', color: 'var(--chart-8)' },
                ]}
              />
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Priority</TableHead>
                    <TableHead className="text-right">Resolved</TableHead>
                    <TableHead className="text-right">Average</TableHead>
                    <TableHead className="text-right">Target</TableHead>
                    <TableHead>Share of target used</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {times.map((t) => {
                    const used = t.target_hours ? t.avg_hours / t.target_hours : null
                    return (
                      <TableRow key={t.priority}>
                        <TableCell><PriorityBadge priority={t.priority} /></TableCell>
                        <TableCell className="text-right tabular-nums">{num(t.count)}</TableCell>
                        <TableCell className="text-right tabular-nums">{num(t.avg_hours, 1)} h</TableCell>
                        <TableCell className="text-right tabular-nums">{t.target_hours !== null ? `${num(t.target_hours)} h` : '—'}</TableCell>
                        <TableCell>
                          {used === null ? (
                            <span className="text-muted-foreground text-xs">no target</span>
                          ) : (
                            <div className="flex items-center gap-2">
                              <RateBar value={Math.min(used, 1)} color={used <= 0.8 ? 'var(--success)' : used <= 1 ? 'var(--warning)' : 'var(--destructive)'} className="flex-1" label="Share of target" />
                              <Badge variant={used <= 1 ? 'success' : 'destructive'} className="shrink-0">{used <= 1 ? 'Within' : 'Over'}</Badge>
                            </div>
                          )}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// ------------------------------------------------------------------ departments & policy usage
function DepartmentsTab() {
  const depts = useQuery({ queryKey: ['analytics', 'departments'], queryFn: () => api.get<{ items: DepartmentRow[] }>('/analytics/departments') })
  const items = depts.data?.items ?? []
  const maxVolume = Math.max(1, ...items.map((d) => d.volume))
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            Department performance
            <InfoTip>Each complaint counts once, under its primary department.</InfoTip>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {depts.isLoading ? (
            <LoadingBlock rows={6} />
          ) : depts.error ? (
            <ErrorState error={depts.error} onRetry={() => depts.refetch()} />
          ) : items.length === 0 ? (
            <EmptyState icon={Building2} title="No routed complaints yet" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Department</TableHead>
                  <TableHead className="min-w-40">Volume</TableHead>
                  <TableHead className="text-right">Open</TableHead>
                  <TableHead className="text-right">Resolved</TableHead>
                  <TableHead className="text-right">Escalated</TableHead>
                  <TableHead className="text-right">Breached</TableHead>
                  <TableHead>Breach rate</TableHead>
                  <TableHead className="text-right">Avg resolution</TableHead>
                  <TableHead className="text-right">Avg score</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((d) => (
                  <TableRow key={d.department ?? 'none'}>
                    <TableCell>
                      <div className="font-medium">{d.department ? d.name : 'Not routed'}</div>
                      {d.department ? <div className="text-muted-foreground font-mono text-[11px]">{d.department}</div> : null}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <div className="bg-muted h-1.5 flex-1 overflow-hidden rounded-full" aria-hidden>
                          <div className="h-full rounded-full bg-[var(--chart-1)]" style={{ width: `${(d.volume / maxVolume) * 100}%` }} />
                        </div>
                        <span className="w-9 text-right text-xs tabular-nums">{num(d.volume)}</span>
                      </div>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{num(d.open)}</TableCell>
                    <TableCell className="text-right tabular-nums">{num(d.resolved)}</TableCell>
                    <TableCell className="text-right tabular-nums">{num(d.escalated)}</TableCell>
                    <TableCell className="text-right tabular-nums">{num(d.breached)}</TableCell>
                    <TableCell><RateBar value={d.breach_rate} color={rateColor(d.breach_rate, { good: 0.85, fair: 0.7, invert: true })} label="SLA breach rate" /></TableCell>
                    <TableCell className="text-right tabular-nums">{d.avg_resolution_hours !== null ? `${num(d.avg_resolution_hours, 1)} h` : '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">{d.avg_verification_score ?? '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <PolicyUsageCard />
    </div>
  )
}

function PolicyUsageCard() {
  const { can } = useAuth()
  const [all, setAll] = React.useState(false)
  const usage = useQuery({ queryKey: ['analytics', 'policy-usage'], queryFn: () => api.get<{ items: PolicyUsageRow[] }>('/analytics/policy-usage') })
  const items = usage.data?.items ?? []
  const shown = all ? items : items.slice(0, 15)
  const top = items.slice(0, 8).map((u) => ({ label: `${u.doc_id} §${u.section}`, ai: u.ai, rule: u.rule, retrieval: u.retrieval }))
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          Policy usage
          <InfoTip>How often each section was cited, required or retrieved.</InfoTip>
        </CardTitle>
        <CardDescription>Most-used policy sections</CardDescription>
        {can('reports:export') ? (
          <CardAction>
            <Button asChild variant="ghost" size="sm">
              <Link to="/reports">Policy usage report <ArrowRight /></Link>
            </Button>
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent>
        {usage.isLoading ? (
          <LoadingBlock rows={6} />
        ) : usage.error ? (
          <ErrorState error={usage.error} onRetry={() => usage.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState icon={BookOpen} title="No policy citations yet" />
        ) : (
          <div className="grid gap-6 xl:grid-cols-2">
            <div>
              <SectionTitle>Top 8 sections</SectionTitle>
              <GroupedBarChart
                data={top}
                xKey="label"
                layout="vertical"
                height={top.length * 44 + 60}
                bars={[
                  { key: 'ai', label: 'Cited by AI', color: 'var(--chart-1)' },
                  { key: 'rule', label: 'Required by rules', color: 'var(--validate)' },
                  { key: 'retrieval', label: 'Retrieved', color: 'var(--chart-8)' },
                ]}
              />
            </div>
            <div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Document</TableHead>
                    <TableHead>Section</TableHead>
                    <TableHead className="text-right">AI</TableHead>
                    <TableHead className="text-right">Rules</TableHead>
                    <TableHead className="text-right">Retrieved</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {shown.map((u) => (
                    <TableRow key={`${u.doc_id}:${u.section}`}>
                      <TableCell className="font-mono text-xs font-semibold">
                        {can('knowledge:read') ? <Link to={`/knowledge/${u.doc_id}`} className="text-primary hover:underline">{u.doc_id}</Link> : u.doc_id}
                      </TableCell>
                      <TableCell className="font-mono text-xs">§{u.section}</TableCell>
                      <TableCell className="text-right tabular-nums">{num(u.ai)}</TableCell>
                      <TableCell className="text-right tabular-nums">{num(u.rule)}</TableCell>
                      <TableCell className="text-muted-foreground text-right tabular-nums">{num(u.retrieval)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {items.length > 15 ? (
                <Button variant="ghost" size="sm" className="mt-2 w-full" onClick={() => setAll((v) => !v)} aria-expanded={all}>
                  {all ? 'Show top 15' : `Show all ${items.length} sections`}
                </Button>
              ) : null}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
