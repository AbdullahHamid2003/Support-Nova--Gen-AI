import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, BookOpen, Bot, ClipboardCheck, Download, FileText, GitCompareArrows, History, MessageSquareText, MoreHorizontal, Paperclip,
  RefreshCw, Send, ShieldAlert, Siren, User, UserCheck,
} from 'lucide-react'
import * as React from 'react'
import { Link, useParams } from 'react-router'
import { toast } from 'sonner'

import { AiRunsPanel, EscalationSlaPanel, EvidencePanel, RelatedCases, ResponsePanel, TimelinePanel } from '@/components/complaint/CasePanels'
import { ComparisonPanel } from '@/components/complaint/ComparisonPanel'
import { ComplaintText } from '@/components/complaint/ComplaintText'
import { FinalIntelligence } from '@/components/complaint/FinalIntelligence'
import { PipelineTracker } from '@/components/complaint/PipelineTracker'
import { EmptyState, ErrorState, KeyValue, LoadingBlock, Spinner } from '@/components/app/common'
import { PriorityBadge, SentimentText, SlaBadge, StatusBadge, UrgencyBadge, VerificationBadge } from '@/components/app/status'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/overlays'
import { Alert, AlertDescription, AlertTitle, Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, NativeSelect, Textarea } from '@/components/ui/primitives'
import { ApiError, api, download, errorMessage } from '@/lib/api'
import { useAuth, usePublicConfig } from '@/lib/auth'
import { fmtBytes, fmtDate, fmtDateTime, fmtDue, fmtRelative, fmtStage } from '@/lib/format'
import type { ComplaintDetail } from '@/lib/types'
import { titleCase } from '@/lib/utils'

const TRANSITIONS: Record<string, string[]> = {
  Analyzed: ['Assigned', 'In Progress', 'Awaiting Customer', 'Escalated', 'Resolved', 'Closed'],
  Assigned: ['In Progress', 'Awaiting Customer', 'Escalated', 'Resolved'],
  'In Progress': ['Awaiting Customer', 'Escalated', 'Resolved'],
  'Awaiting Customer': ['In Progress', 'Escalated', 'Resolved', 'Closed'],
  Escalated: ['In Progress', 'Awaiting Customer', 'Resolved'],
  Resolved: ['Closed', 'Reopened'],
  Closed: ['Reopened'],
  Reopened: ['In Progress', 'Escalated', 'Resolved'],
}

export default function ComplaintDetailPage() {
  const { ref = '' } = useParams()
  const { session } = useAuth()
  const q = useQuery({
    queryKey: ['complaint', ref],
    queryFn: () => api.get<ComplaintDetail>(`/complaints/${ref}`),
    refetchInterval: (query) => (query.state.data && !['completed', 'failed'].includes(query.state.data.processing_stage) ? 1500 : false),
  })
  if (q.isLoading) return <LoadingBlock rows={10} />
  if (q.error) {
    if (q.error instanceof ApiError && q.error.status === 404) return <EmptyState title="Complaint not found" description={`There is no complaint ${ref} you can access.`} action={<Button asChild size="sm" variant="outline" className="mt-2"><Link to="/complaints">Back to complaints</Link></Button>} />
    return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  }
  const c = q.data!
  return session!.user.role === 'customer' ? <CustomerView c={c} /> : <InternalView c={c} />
}

// ============================================================================ internal case view
function InternalView({ c }: { c: ComplaintDetail }) {
  const { can } = useAuth()
  const config = usePublicConfig()
  const qc = useQueryClient()
  const [tab, setTab] = React.useState('overview')
  const [dialog, setDialog] = React.useState<null | 'status' | 'escalate' | 'reprocess'>(null)
  const invalidate = () => qc.invalidateQueries({ queryKey: ['complaint', c.complaint_ref] })
  const running = !['completed', 'failed'].includes(c.processing_stage)
  const vd = c.validation?.validated_decision
  const due = c.sla ? fmtDue(c.sla.resolution_due_at) : null
  const pdf = useMutation({ mutationFn: () => download(`/complaints/${c.complaint_ref}/report.pdf`, undefined, `${c.complaint_ref}.pdf`), onError: (e) => toast.error(errorMessage(e)) })
  const assignMe = useMutation({
    mutationFn: () => api.post(`/complaints/${c.complaint_ref}/assign`, {}),
    onSuccess: () => { toast.success('Assigned to you'); invalidate() },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const injection = c.preprocessing?.injection

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 space-y-2">
          <Link to="/complaints" className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs"><ArrowLeft className="size-3.5" /> Complaints</Link>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm font-semibold text-primary">{c.complaint_ref}</span>
            <StatusBadge status={c.status} />
            <VerificationBadge status={c.verification_status} score={c.verification_score} />
            {c.source && c.source !== 'web' && c.source !== 'dataset' ? <Badge variant="info">{titleCase(c.source)} test case</Badge> : null}
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-balance">{c.title}</h1>
          <div className="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
            <span className="flex items-center gap-1"><User className="size-3.5" /> {c.customer_name ?? 'Unlinked customer'} {c.customer_ref ? <span className="font-mono text-xs">({c.customer_ref})</span> : null} · {titleCase(c.customer_type)}</span>
            <span>Submitted {fmtDateTime(c.complaint_date)} · {config.data?.channels.find((o) => o.code === c.channel)?.name ?? titleCase(c.channel)}</span>
            <span>{c.assigned_agent ? `Assigned to ${c.assigned_agent}` : 'Unassigned'}</span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 lg:shrink-0 lg:flex-nowrap">
          {c.review && c.review.status !== 'completed' && can('review:read') ? (
            <Button asChild variant="secondary" size="sm"><Link to={`/reviews/${c.review.id}`}><ClipboardCheck /> Open review</Link></Button>
          ) : null}
          {!c.assigned_agent && can('complaint:update') ? <Button size="sm" variant="outline" onClick={() => assignMe.mutate()} disabled={assignMe.isPending}><UserCheck /> Assign to me</Button> : null}
          <Button size="sm" variant="outline" onClick={() => pdf.mutate()} disabled={pdf.isPending}>{pdf.isPending ? <Spinner /> : <Download />} Case report</Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button size="sm" variant="outline" aria-label="More actions"><MoreHorizontal /> Actions</Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel>Case actions</DropdownMenuLabel>
              {can('complaint:update') ? <DropdownMenuItem onSelect={() => setDialog('status')}><History /> Change status</DropdownMenuItem> : null}
              {can('escalation:create') ? <DropdownMenuItem onSelect={() => setDialog('escalate')}><Siren /> Escalate</DropdownMenuItem> : null}
              <DropdownMenuSeparator />
              {can('complaint:reprocess') ? <DropdownMenuItem onSelect={() => setDialog('reprocess')}><RefreshCw /> Re-run analysis</DropdownMenuItem> : null}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {[
          ['Category', vd ? `${vd.classification.subcategory_name ?? '—'}` : c.subcategory ?? '—'],
          ['Department', c.department ?? '—'],
          ['Priority', <PriorityBadge key="p" priority={c.priority} />],
          ['Urgency', <UrgencyBadge key="u" urgency={c.urgency} />],
          ['Sentiment', <SentimentText key="s" sentiment={c.sentiment} />],
          ['SLA', <span key="sla" className="flex flex-col gap-0.5"><SlaBadge state={c.sla_state} />{due && !c.resolved_at ? <span className={due.overdue ? 'text-destructive text-[11px]' : 'text-muted-foreground text-[11px]'}>{due.text}</span> : null}</span>],
        ].map(([k, v], i) => (
          <div key={i} className="rounded-xl border bg-card px-3 py-2.5 shadow-xs">
            <div className="text-muted-foreground text-[11px] font-medium uppercase tracking-wide">{k}</div>
            <div className="mt-1 line-clamp-2 text-sm font-medium" title={typeof v === 'string' ? v : undefined}>{v}</div>
          </div>
        ))}
      </div>

      <PipelineTracker complaint={c} onSelect={setTab} />

      {running ? (
        <Alert variant="info"><Spinner /><AlertTitle>Processing: {fmtStage(c.processing_stage)}</AlertTitle><AlertDescription>This page refreshes automatically.</AlertDescription></Alert>
      ) : null}
      {c.processing_stage === 'failed' ? (
        <Alert variant="destructive"><ShieldAlert /><AlertTitle>Processing failed</AlertTitle><AlertDescription>The case went to manual review - check the timeline, then re-run the analysis.</AlertDescription></Alert>
      ) : null}
      {c.is_duplicate ? (
        <Alert variant="warning"><History /><AlertTitle>Duplicate complaint</AlertTitle><AlertDescription>Linked to an earlier complaint - see customer history below.</AlertDescription></Alert>
      ) : null}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="overview"><FileText /> Overview</TabsTrigger>
          <TabsTrigger value="compare"><GitCompareArrows /> AI vs rules</TabsTrigger>
          <TabsTrigger value="evidence"><BookOpen /> Evidence</TabsTrigger>
          <TabsTrigger value="response"><MessageSquareText /> Response</TabsTrigger>
          <TabsTrigger value="sla"><Siren /> Escalation & SLA</TabsTrigger>
          <TabsTrigger value="timeline"><History /> Timeline & audit</TabsTrigger>
          <TabsTrigger value="ai"><Bot /> AI runs</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <div className="grid gap-6 xl:grid-cols-[1fr_1.15fr]">
            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle>Complaint</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {injection?.is_suspicious ? (
                    <Alert variant="destructive">
                      <ShieldAlert />
                      <AlertTitle>Prompt-injection attempt detected</AlertTitle>
                      <AlertDescription>
                        {injection.findings.length} finding(s): {injection.types.map((t) => t.replace(/_/g, ' ')).join(', ')}. The case needs manual review.
                      </AlertDescription>
                    </Alert>
                  ) : null}
                  <ComplaintText text={c.description} findings={injection?.findings} />
                  {c.supporting_info ? <div><div className="text-muted-foreground mb-1 text-xs font-medium">Supporting information</div><p className="text-sm whitespace-pre-wrap">{c.supporting_info}</p></div> : null}
                  <KeyValue items={[
                    ['Product / service', c.product_text || '—'],
                    ['Order reference', c.order_ref ? <span key="o" className="font-mono">{c.order_ref}{c.preprocessing?.order_found === false ? <Badge variant="destructive" className="ml-1.5">not found</Badge> : c.preprocessing?.order_found ? <Badge variant="success" className="ml-1.5">verified</Badge> : null}</span> : '—'],
                    ['Transaction', c.transaction_ref ? <span key="t" className="font-mono">{c.transaction_ref}</span> : '—'],
                    ['Previous complaint', c.previous_complaint_ref ? <Link key="pc" className="font-mono text-primary hover:underline" to={`/complaints/${c.previous_complaint_ref}`}>{c.previous_complaint_ref}</Link> : '—'],
                    ['Requested resolution', titleCase(c.requested_resolution)],
                    ['Preferred contact · tone', `${titleCase(c.preferred_contact)} · ${titleCase(c.requested_tone)}`],
                  ]} />
                  {c.attachments.length ? (
                    <div className="flex flex-wrap gap-2">
                      {c.attachments.map((a) => <Badge key={a.file_name} variant="outline"><Paperclip /> {a.file_name} {a.size_bytes ? `· ${fmtBytes(a.size_bytes)}` : ''}</Badge>)}
                    </div>
                  ) : null}
                </CardContent>
              </Card>
              <PerceptionCard c={c} />
              <RelatedCases complaint={c} />
            </div>
            <div>
              {vd ? <FinalIntelligence vd={vd} /> : <EmptyState icon={GitCompareArrows} title="Decision pending" description="The final decision appears here after the rule check." />}
            </div>
          </div>
        </TabsContent>
        <TabsContent value="compare"><ComparisonPanel complaint={c} /></TabsContent>
        <TabsContent value="evidence"><EvidencePanel complaint={c} /></TabsContent>
        <TabsContent value="response"><ResponsePanel complaint={c} /></TabsContent>
        <TabsContent value="sla"><EscalationSlaPanel complaint={c} /></TabsContent>
        <TabsContent value="timeline"><TimelinePanel complaint={c} /></TabsContent>
        <TabsContent value="ai"><AiRunsPanel complaint={c} /></TabsContent>
      </Tabs>

      <StatusDialog open={dialog === 'status'} onClose={() => setDialog(null)} c={c} onDone={invalidate} />
      <EscalateDialog open={dialog === 'escalate'} onClose={() => setDialog(null)} c={c} levels={(config.data?.escalation_levels ?? []).filter((l) => l !== 'No Escalation')} onDone={invalidate} />
      <ReprocessDialog open={dialog === 'reprocess'} onClose={() => setDialog(null)} c={c} tones={config.data?.response_tones ?? []} onDone={invalidate} />
    </div>
  )
}

function PerceptionCard({ c }: { c: ComplaintDetail }) {
  const p = c.preprocessing
  if (!p) return null
  const signals = Array.isArray(p.signals) ? (p.signals as string[]) : p.signals && typeof p.signals === 'object' ? Object.keys(p.signals as object) : []
  const cls = p.classification
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">What the rules detected</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div>
          <div className="text-muted-foreground mb-1 text-xs font-medium">Risk & context signals</div>
          <div className="flex flex-wrap gap-1">{signals.length ? signals.map((s) => <Badge key={s} variant={/fire|overheat|electric|injur|breach|lock|privacy|legal/.test(s) ? 'destructive' : 'secondary'}>{s.replace(/_/g, ' ')}</Badge>) : <span className="text-muted-foreground">none</span>}</div>
        </div>
        {cls ? (
          <div>
            <div className="text-muted-foreground mb-1 text-xs font-medium">Category rules · confidence {cls.confidence}{cls.ambiguous ? ' · ambiguous' : ''}</div>
            <ul className="space-y-1">
              {cls.candidates.slice(0, 3).map((x) => (
                <li key={x.subcategory} className="flex items-center gap-2 text-xs">
                  <span className="w-16 font-mono font-semibold">{x.subcategory}</span>
                  <div className="bg-muted h-1.5 flex-1 overflow-hidden rounded-full"><div className="bg-primary h-full" style={{ width: `${Math.min(100, (x.score / Math.max(cls.candidates[0].score, 1)) * 100)}%` }} /></div>
                  <span className="text-muted-foreground w-10 text-right tabular-nums">{x.score}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {p.entities?.length ? (
          <div>
            <div className="text-muted-foreground mb-1 text-xs font-medium">Entities</div>
            <div className="flex flex-wrap gap-1">{p.entities.slice(0, 12).map((e, i) => <Badge key={i} variant="outline" className="font-mono text-[10.5px]">{e.type}: {e.value}</Badge>)}</div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function StatusDialog({ open, onClose, c, onDone }: { open: boolean; onClose: () => void; c: ComplaintDetail; onDone: () => void }) {
  const options = TRANSITIONS[c.status] ?? []
  const [status, setStatus] = React.useState('')
  const [note, setNote] = React.useState('')
  const m = useMutation({
    mutationFn: () => api.post(`/complaints/${c.complaint_ref}/status`, { status, note }),
    onSuccess: () => { toast.success(`Status changed to ${status}`); onDone(); onClose() },
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Change status</DialogTitle>
          <DialogDescription>The change is recorded in the timeline and audit log.</DialogDescription>
        </DialogHeader>
        <label className="text-sm font-medium" htmlFor="st">New status</label>
        <NativeSelect id="st" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Choose…</option>
          {options.map((o) => <option key={o} value={o}>{o}</option>)}
        </NativeSelect>
        <label className="text-sm font-medium" htmlFor="stn">Note</label>
        <Textarea id="stn" rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why the status is changing" />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => m.mutate()} disabled={!status || m.isPending}>{m.isPending ? <Spinner /> : null} Update</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function EscalateDialog({ open, onClose, c, levels, onDone }: { open: boolean; onClose: () => void; c: ComplaintDetail; levels: string[]; onDone: () => void }) {
  const [level, setLevel] = React.useState('')
  const [reason, setReason] = React.useState('')
  const m = useMutation({
    mutationFn: () => api.post(`/complaints/${c.complaint_ref}/escalate`, { level, reason }),
    onSuccess: () => { toast.success(`Escalated to ${level}`); onDone(); onClose() },
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Escalate complaint</DialogTitle>
          <DialogDescription>Current level: {c.escalation_level ?? 'none'}. Levels can only go up.</DialogDescription>
        </DialogHeader>
        <label className="text-sm font-medium" htmlFor="lvl">Level</label>
        <NativeSelect id="lvl" value={level} onChange={(e) => setLevel(e.target.value)}>
          <option value="">Choose…</option>
          {levels.map((l) => <option key={l} value={l}>{l}</option>)}
        </NativeSelect>
        <label className="text-sm font-medium" htmlFor="rsn">Reason</label>
        <Textarea id="rsn" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button variant="destructive" onClick={() => m.mutate()} disabled={!level || reason.trim().length < 5 || m.isPending}>{m.isPending ? <Spinner /> : <Siren />} Escalate</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ReprocessDialog({ open, onClose, c, tones, onDone }: { open: boolean; onClose: () => void; c: ComplaintDetail; tones: { code: string; name: string }[]; onDone: () => void }) {
  const [tone, setTone] = React.useState(c.requested_tone)
  const m = useMutation({
    mutationFn: () => api.post(`/complaints/${c.complaint_ref}/reprocess`, { tone }),
    onSuccess: () => { toast.success('Re-analysis started'); onDone(); onClose() },
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Re-run the analysis</DialogTitle>
          <DialogDescription>Analyses the complaint again with the current rules and knowledge base. The previous analysis stays in the history.</DialogDescription>
        </DialogHeader>
        <label className="text-sm font-medium" htmlFor="tone">Response tone</label>
        <NativeSelect id="tone" value={tone} onChange={(e) => setTone(e.target.value)}>{tones.map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}</NativeSelect>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => m.mutate()} disabled={m.isPending}>{m.isPending ? <Spinner /> : <RefreshCw />} Re-run</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ============================================================================ customer view (SRS Step 61)
function CustomerView({ c }: { c: ComplaintDetail }) {
  const qc = useQueryClient()
  const [info, setInfo] = React.useState('')
  const [orderRef, setOrderRef] = React.useState('')
  const clarify = useMutation({
    mutationFn: () => api.post(`/complaints/${c.complaint_ref}/clarify`, { information: info, order_ref: orderRef || undefined }),
    onSuccess: () => { toast.success('Thank you - we received your information'); setInfo(''); setOrderRef(''); qc.invalidateQueries({ queryKey: ['complaint', c.complaint_ref] }) },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const reopen = useMutation({
    mutationFn: () => api.post(`/complaints/${c.complaint_ref}/status`, { status: 'Reopened', note: 'Reopened by the customer' }),
    onSuccess: () => { toast.success('Complaint reopened'); qc.invalidateQueries({ queryKey: ['complaint', c.complaint_ref] }) },
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="space-y-2">
        <Link to="/complaints" className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs"><ArrowLeft className="size-3.5" /> My complaints</Link>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm font-semibold text-primary">{c.complaint_ref}</span>
          <StatusBadge status={c.status} />
          {c.resolution_status ? <Badge variant={c.resolution_status === 'Resolved' ? 'success' : 'info'}>{c.resolution_status}</Badge> : null}
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">{c.title}</h1>
        <p className="text-muted-foreground text-sm">Submitted {fmtDate(c.created_at)}{c.department ? ` · handled by ${c.department}` : ''}</p>
      </div>
      {c.latest_update ? (
        <Alert variant={c.status === 'Awaiting Customer' ? 'warning' : 'info'}>
          <History />
          <AlertTitle>Latest update</AlertTitle>
          <AlertDescription>{c.latest_update.message} <span className="opacity-70">({fmtRelative(c.latest_update.at)})</span></AlertDescription>
        </Alert>
      ) : null}
      <div className="grid gap-6 md:grid-cols-[1.3fr_1fr]">
        <div className="space-y-6">
          <Card>
            <CardHeader><CardTitle>Messages from Lumora</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {(c.responses ?? []).length === 0 ? <p className="text-muted-foreground text-sm">We will reply here and by {c.preferred_contact} as soon as your complaint has been reviewed.</p> : null}
              {c.responses.map((r, i) => (
                <div key={i} className="rounded-lg border p-4">
                  <div className="flex items-center justify-between gap-2 text-sm font-medium">{r.subject}<span className="text-muted-foreground text-xs font-normal">{fmtDateTime(r.sent_at)}</span></div>
                  <p className="mt-2 text-sm leading-relaxed whitespace-pre-wrap">{r.body}</p>
                </div>
              ))}
            </CardContent>
          </Card>
          {c.status !== 'Closed' && c.status !== 'Resolved' ? (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><Send className="size-4" /> Add information</CardTitle>
                <CardDescription>Never include passwords or full card numbers.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <label htmlFor="info" className="sr-only">Information</label>
                <Textarea id="info" rows={4} value={info} onChange={(e) => setInfo(e.target.value)} placeholder="Your message…" />
                <label htmlFor="oref" className="text-sm font-medium">Order reference (if asked)</label>
                <Input id="oref" value={orderRef} onChange={(e) => setOrderRef(e.target.value)} placeholder="LMR-123456" className="font-mono uppercase" />
                <Button onClick={() => clarify.mutate()} disabled={info.trim().length < 3 || clarify.isPending}>{clarify.isPending ? <Spinner /> : <Send />} Send</Button>
              </CardContent>
            </Card>
          ) : (
            <Button variant="outline" onClick={() => reopen.mutate()} disabled={reopen.isPending}><RefreshCw /> Not resolved? Reopen this complaint</Button>
          )}
        </div>
        <div className="space-y-6">
          <Card>
            <CardHeader><CardTitle>Progress</CardTitle></CardHeader>
            <CardContent>
              <ol className="relative space-y-4 border-l pl-5">
                {(c.updates ?? []).map((u, i) => (
                  <li key={i} className="relative">
                    <span className="bg-primary absolute -left-[26px] mt-1 size-3 rounded-full border-2 border-card" aria-hidden />
                    <p className="text-sm">{u.message}</p>
                    <p className="text-muted-foreground text-xs">{fmtDateTime(u.at)}</p>
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Your complaint</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm whitespace-pre-wrap">{c.description}</p>
              <KeyValue columns={1} items={[['Order', c.order_ref ?? '—'], ['Requested resolution', titleCase(c.requested_resolution)]]} />
            </CardContent>
          </Card>
          {(c.follow_ups ?? []).length ? (
            <Card>
              <CardHeader><CardTitle>Planned follow-up</CardTitle></CardHeader>
              <CardContent className="space-y-1 text-sm">
                {c.follow_ups.map((f, i) => <div key={i}>{f.type} · {fmtDate(f.due_at)}</div>)}
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>
    </div>
  )
}
