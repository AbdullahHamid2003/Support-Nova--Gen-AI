import { useQuery } from '@tanstack/react-query'
import {
  Activity, AlertTriangle, ArrowRight, BadgeCheck, Bot, CircleGauge, ClipboardCheck, Clock, Flame, GitCompareArrows, Inbox, MessageSquareText,
  PlusCircle, Repeat, ShieldAlert, Siren, TrendingUp,
} from 'lucide-react'
import { Link } from 'react-router'

import { BarList, DonutChart, Legendary, TrendChart } from '@/components/app/charts'
import { EmptyState, ErrorState, LoadingBlock, PageHeader, StatCard } from '@/components/app/common'
import { EscalationBadge, PriorityBadge, SentimentText, SlaBadge, StatusBadge, VerificationBadge } from '@/components/app/status'
import { Button } from '@/components/ui/button'
import { Badge, Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/primitives'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { REASON_LABELS } from '@/lib/reviews'
import { fmtDate, fmtRelative } from '@/lib/format'
import type { DistributionItem } from '@/lib/types'
import { num, pct, titleCase } from '@/lib/utils'

interface Overview {
  total: number; open: number; resolved: number; escalated: number; manual_review_pending: number; verified_rate: number | null; analysed: number
  auto_verified: number; human_verified: number
  avg_verification_score: number; sla_at_risk: number; sla_breached: number; repeat: number; duplicates: number; injection_detected: number
  ai_python_agreement_rate: number | null; ai_python_mismatches: number; avg_resolution_hours: number | null; avg_processing_ms: number | null
}
interface DashboardData {
  role: string
  overview?: Overview
  distributions?: Record<string, DistributionItem[]>
  validation?: { decisions: Record<string, number>; field_agreement: { field: string; rate: number }[]; review_reasons: { code: string; count: number }[]; checks: { code: string; name: string; fail: number; warn: number; pass: number }[] }
  review_queue?: { pending: number; reasons: Record<string, number> }
  sla?: { by_priority: { priority: string; 'On Track': number; 'At Risk': number; Breached: number; Met: number }[] }
  departments?: { department: string; name: string; volume: number; open: number; escalated: number; breach_rate: number; avg_verification_score: number | null }[]
  alerts?: { type: string; severity: string; message: string; label?: string }[]
  system?: Record<string, number | string>
  my_queue?: { open: number; by_priority: Record<string, number>; sla_at_risk: number; escalated: number; needs_review: number; items: AgentItem[] }
  items?: CustomerItem[]
  total?: number
  counts?: Record<string, number>
}
interface AgentItem {
  complaint_ref: string; title: string; status: string; created_at: string; category: string; subcategory: string; priority: string; urgency: string
  sentiment: string; verification_status: string; verification_score: number | null; sla_state: string | null; escalation_level: string | null
  escalation_warning: boolean; ai_recommendation: string | null; guidance: string[]; suggested_response: { id: number; status: string; subject: string } | null; injection_detected: boolean
}
interface CustomerItem { complaint_ref: string; title: string; status: string; submitted_at: string; department: string | null; latest_update: { message: string; at: string } | null; resolution_status: string }

export default function DashboardPage() {
  const { session } = useAuth()
  const q = useQuery({ queryKey: ['dashboard'], queryFn: () => api.get<DashboardData>('/dashboard'), refetchInterval: 30_000 })
  const role = session!.user.role
  if (q.isLoading) return <LoadingBlock rows={8} />
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  const d = q.data!
  if (role === 'customer') return <CustomerDashboard data={d} name={session!.user.full_name} />
  if (role === 'agent') return <AgentDashboard data={d} name={session!.user.full_name} />
  return <OpsDashboard data={d} role={role} />
}

// ------------------------------------------------------------------ customer (SRS Step 61)
function CustomerDashboard({ data, name }: { data: DashboardData; name: string }) {
  const items = data.items ?? []
  return (
    <>
      <PageHeader
        eyebrow="Customer portal"
        title={`Hello, ${name.split(' ')[0]}`}
        description="Track your complaints and replies from Lumora."
        actions={
          <Button asChild>
            <Link to="/complaints/new"><PlusCircle /> New complaint</Link>
          </Button>
        }
      />
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="All complaints" value={data.total ?? 0} icon={Inbox} tone="primary" />
        <StatCard label="In progress" value={items.filter((i) => i.resolution_status === 'In progress').length} icon={Activity} />
        <StatCard label="Waiting for you" value={items.filter((i) => i.resolution_status === 'Waiting for your reply').length} icon={MessageSquareText} tone="warning" />
        <StatCard label="Resolved" value={items.filter((i) => i.resolution_status === 'Resolved').length} icon={BadgeCheck} tone="success" />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Your complaints</CardTitle>
        </CardHeader>
        <CardContent>
          {items.length === 0 ? (
            <EmptyState title="No complaints yet" description="If something went wrong, tell us and we will look into it." action={<Button asChild size="sm" className="mt-2"><Link to="/complaints/new">Submit a complaint</Link></Button>} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Complaint</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="hidden md:table-cell">Submitted</TableHead>
                  <TableHead className="hidden md:table-cell">Department</TableHead>
                  <TableHead>Latest update</TableHead>
                  <TableHead>Resolution</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((c) => (
                  <TableRow key={c.complaint_ref}>
                    <TableCell>
                      <Link to={`/complaints/${c.complaint_ref}`} className="font-mono text-xs font-semibold text-primary hover:underline">{c.complaint_ref}</Link>
                      <div className="max-w-[16rem] truncate text-sm">{c.title}</div>
                    </TableCell>
                    <TableCell><StatusBadge status={c.status} /></TableCell>
                    <TableCell className="hidden md:table-cell text-sm">{fmtDate(c.submitted_at)}</TableCell>
                    <TableCell className="hidden md:table-cell text-sm">{c.department ?? '—'}</TableCell>
                    <TableCell className="max-w-[18rem] text-sm">
                      <div className="truncate">{c.latest_update?.message ?? '—'}</div>
                      <div className="text-muted-foreground text-xs">{c.latest_update ? fmtRelative(c.latest_update.at) : ''}</div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={c.resolution_status === 'Resolved' ? 'success' : c.resolution_status.startsWith('Waiting') ? 'warning' : 'info'}>{c.resolution_status}</Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </>
  )
}

// ------------------------------------------------------------------ agent (SRS Step 62)
function AgentDashboard({ data, name }: { data: DashboardData; name: string }) {
  const mq = data.my_queue!
  return (
    <>
      <PageHeader
        eyebrow="Agent workspace"
        title={`Good to see you, ${name.split(' ')[0]}`}
        description="Your assigned complaints, ordered by priority."
        actions={<Button asChild variant="outline"><Link to="/complaints?assigned_to_me=true">All my complaints <ArrowRight /></Link></Button>}
      />
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Open assigned" value={mq.open} icon={Inbox} tone="primary" hint={Object.entries(mq.by_priority).sort().map(([p, n]) => `${p}: ${n}`).join(' · ')} />
        <StatCard label="SLA at risk / breached" value={mq.sla_at_risk} icon={Clock} tone={mq.sla_at_risk ? 'warning' : 'default'} />
        <StatCard label="Escalation warnings" value={mq.escalated} icon={Siren} tone={mq.escalated ? 'destructive' : 'default'} />
        <StatCard label="Awaiting review" value={mq.needs_review} icon={ClipboardCheck} tone="warning" hint="A reviewer must approve before sending" />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Assigned complaints</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {mq.items.length === 0 ? <EmptyState title="Nothing assigned right now" description="New complaints appear here when they are assigned to you." /> : null}
          {mq.items.map((c) => (
            <Link key={c.complaint_ref} to={`/complaints/${c.complaint_ref}`} className="hover:border-primary/40 hover:bg-accent/30 block rounded-xl border p-4 transition-colors">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs font-semibold text-primary">{c.complaint_ref}</span>
                <PriorityBadge priority={c.priority} />
                <StatusBadge status={c.status} />
                <VerificationBadge status={c.verification_status} score={c.verification_score} />
                {c.escalation_warning ? <EscalationBadge level={c.escalation_level} required /> : null}
                <SlaBadge state={c.sla_state} />
                {c.injection_detected ? <Badge variant="destructive"><ShieldAlert /> Injection flagged</Badge> : null}
                <span className="text-muted-foreground ml-auto text-xs">{fmtRelative(c.created_at)}</span>
              </div>
              <div className="mt-2 font-medium">{c.title}</div>
              <div className="text-muted-foreground mt-0.5 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                <span>{c.category} › {c.subcategory}</span>
                <span>Urgency {c.urgency}</span>
                <span>Sentiment <SentimentText sentiment={c.sentiment} /></span>
              </div>
              {c.ai_recommendation ? (
                <div className="bg-muted/50 mt-3 rounded-lg p-3 text-sm">
                  <div className="text-muted-foreground mb-1 flex items-center gap-1.5 text-xs font-medium"><Bot className="size-3.5" /> Summary and guidance</div>
                  <p className="line-clamp-2">{c.ai_recommendation}</p>
                  {c.guidance.length ? <ul className="text-muted-foreground mt-1.5 list-disc space-y-0.5 pl-4 text-xs">{c.guidance.map((g) => <li key={g}>{g}</li>)}</ul> : null}
                </div>
              ) : null}
              {c.suggested_response ? (
                <div className="mt-2 flex items-center gap-2 text-xs">
                  <MessageSquareText className="text-muted-foreground size-3.5" />
                  Suggested response: <span className="font-medium">{c.suggested_response.subject}</span>
                  <Badge variant={c.suggested_response.status === 'ready' ? 'success' : c.suggested_response.status === 'sent' ? 'muted' : 'warning'}>{c.suggested_response.status.replace('_', ' ')}</Badge>
                </div>
              ) : null}
            </Link>
          ))}
        </CardContent>
      </Card>
    </>
  )
}

// ------------------------------------------------------------------ reviewer / manager / admin (SRS Step 63)
function OpsDashboard({ data, role }: { data: DashboardData; role: string }) {
  const o = data.overview!
  const trends = useQuery({ queryKey: ['trends', 'dash'], queryFn: () => api.get<{ series: Record<string, unknown>[] }>('/analytics/trends', { days: 150, granularity: 'week', dimension: 'category' }) })
  const dist = data.distributions ?? {}
  const statusData = (dist.status ?? []).map((s) => ({ label: s.label, value: s.count }))
  const prio = ['P0', 'P1', 'P2', 'P3'].map((p) => ({ label: p, value: (dist.priority ?? []).find((x) => x.key === p)?.count ?? 0 }))
  const prioColors = ['var(--destructive)', 'var(--warning)', 'var(--info)', 'var(--chart-8)']
  return (
    <>
      <PageHeader
        eyebrow={role === 'admin' ? 'Administrator overview' : role === 'manager' ? 'Operations overview' : 'Quality overview'}
        title="Dashboard"
        description="Live complaint numbers, reviews, escalations and SLA risk."
        actions={<Button asChild variant="outline" size="sm"><Link to="/analytics">Full analytics <ArrowRight /></Link></Button>}
      />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4 xl:grid-cols-6">
        <StatCard label="Total complaints" value={num(o.total)} icon={Inbox} tone="primary" hint={`${num(o.open)} open · ${num(o.resolved)} resolved`} />
        <StatCard label="Verified" value={pct(o.verified_rate)} icon={BadgeCheck} tone="success" hint={`${num(o.auto_verified)} automatic · ${num(o.human_verified)} by reviewers`} />
        <StatCard label="Manual review" value={num(o.manual_review_pending)} icon={ClipboardCheck} tone="warning" hint="pending human decision" />
        <StatCard label="Escalated" value={num(o.escalated)} icon={Siren} tone="destructive" />
        <StatCard label="SLA at risk · breached" value={`${o.sla_at_risk} · ${o.sla_breached}`} icon={Clock} tone={o.sla_breached ? 'destructive' : 'warning'} />
        <StatCard label="AI and rules agree" value={pct(o.ai_python_agreement_rate)} icon={GitCompareArrows} tone="validate" hint={`${num(o.ai_python_mismatches)} field mismatches`} />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Complaint volume by category</CardTitle>
            <CardDescription>Weekly, last 150 days</CardDescription>
            <CardAction><TrendingUp className="text-muted-foreground size-4" /></CardAction>
          </CardHeader>
          <CardContent>
            {trends.data ? (
              <TrendChart
                data={trends.data.series}
                series={((trends.data as unknown as { keys: { key: string; label: string }[] }).keys ?? []).slice(0, 5).map((k) => ({ key: k.key, label: k.label }))}
                stacked
              />
            ) : (
              <LoadingBlock rows={4} />
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Priority levels</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <DonutChart data={prio.map((p, i) => ({ ...p, color: prioColors[i] }))} centerLabel="complaints" />
            <Legendary items={prio.map((p, i) => ({ label: p.label, value: p.value, color: prioColors[i] }))} />
          </CardContent>
        </Card>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>Category distribution</CardTitle></CardHeader>
          <CardContent><BarList items={(dist.category ?? []).slice(0, 11).map((c) => ({ label: c.label, value: c.count, hint: pct(c.share) }))} /></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Department routing</CardTitle></CardHeader>
          <CardContent><BarList items={(dist.department ?? []).slice(0, 10).map((c) => ({ label: c.label, value: c.count, hint: pct(c.share) }))} /></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Resolution status</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <DonutChart data={statusData} centerLabel="complaints" height={180} />
            <Legendary items={statusData.map((s) => ({ label: s.label, value: s.value }))} />
          </CardContent>
        </Card>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Emerging trends & alerts</CardTitle>
            <CardDescription>Rising categories, products and escalations</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {(data.alerts ?? []).length === 0 ? <p className="text-muted-foreground text-sm">No notable trends right now.</p> : null}
            {(data.alerts ?? []).slice(0, 6).map((a, i) => (
              <div key={i} className="flex items-start gap-3 rounded-lg border p-3">
                {a.severity === 'high' ? <Flame className="text-destructive mt-0.5 size-4 shrink-0" /> : <AlertTriangle className="text-warning mt-0.5 size-4 shrink-0" />}
                <div className="text-sm">
                  <div className="font-medium">{a.type.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())}</div>
                  <div className="text-muted-foreground">{a.message}</div>
                </div>
              </div>
            ))}
            {role === 'reviewer' && !data.alerts ? <p className="text-muted-foreground text-sm">Trend alerts are available to managers.</p> : null}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Why complaints need review</CardTitle>
            <CardDescription>Open manual reviews by reason</CardDescription>
            <CardAction>
              <Button asChild variant="ghost" size="sm"><Link to="/reviews">Queue <ArrowRight /></Link></Button>
            </CardAction>
          </CardHeader>
          <CardContent>
            {data.review_queue && Object.keys(data.review_queue.reasons).length ? (
              <BarList items={Object.entries(data.review_queue.reasons).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([k, v]) => ({ label: REASON_LABELS[k] ?? titleCase(k), value: v }))} colorBy={() => 'var(--warning)'} />
            ) : (
              <p className="text-muted-foreground text-sm">The review queue is empty.</p>
            )}
          </CardContent>
        </Card>
      </div>

      {data.departments ? (
        <Card className="mt-6">
          <CardHeader>
            <CardTitle>Department performance</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Department</TableHead>
                  <TableHead className="text-right">Volume</TableHead>
                  <TableHead className="text-right">Open</TableHead>
                  <TableHead className="text-right">Escalated</TableHead>
                  <TableHead className="text-right">SLA breach</TableHead>
                  <TableHead className="text-right">Avg score</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.departments.map((d) => (
                  <TableRow key={d.department ?? d.name}>
                    <TableCell className="font-medium">{d.name}</TableCell>
                    <TableCell className="text-right tabular-nums">{d.volume}</TableCell>
                    <TableCell className="text-right tabular-nums">{d.open}</TableCell>
                    <TableCell className="text-right tabular-nums">{d.escalated}</TableCell>
                    <TableCell className="text-right tabular-nums">{pct(d.breach_rate, 1)}</TableCell>
                    <TableCell className="text-right tabular-nums">{d.avg_verification_score ?? '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}

      <div className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Repeat complaints" value={num(o.repeat)} icon={Repeat} />
        <StatCard label="Duplicates linked" value={num(o.duplicates)} icon={Inbox} />
        <StatCard label="Injection attempts blocked" value={num(o.injection_detected)} icon={ShieldAlert} tone="destructive" />
        <StatCard label="Avg processing time" value={o.avg_processing_ms ? `${(o.avg_processing_ms / 1000).toFixed(2)} s` : '—'} icon={CircleGauge} hint={o.avg_resolution_hours ? `avg resolution ${o.avg_resolution_hours} h` : undefined} />
      </div>
    </>
  )
}
