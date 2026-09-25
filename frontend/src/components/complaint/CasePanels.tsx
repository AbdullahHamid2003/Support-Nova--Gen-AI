import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, BookOpen, Bot, CheckCircle2, Clock, History, Link2, Pencil, ScrollText, Send, ShieldCheck, Siren, Timer, XCircle } from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { CopyButton, EmptyState, ErrorState, JsonView, KeyValue, LoadingBlock, SectionTitle, Spinner } from '@/components/app/common'
import { SlaBadge } from '@/components/app/status'
import { useNow } from '@/hooks/time'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/overlays'
import { Alert, AlertDescription, AlertTitle, Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, NativeSelect, Progress, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Textarea } from '@/components/ui/primitives'
import { api, errorMessage } from '@/lib/api'
import { useAuth, usePublicConfig } from '@/lib/auth'
import { fmtDateTime, fmtDue, fmtMs, fmtRelative, toDate } from '@/lib/format'
import type { AuditEntry, ComplaintDetail, ResponseDraft, TimelineEvent } from '@/lib/types'
import { cn, titleCase } from '@/lib/utils'

// ------------------------------------------------------------------ evidence
const APPLICABILITY: Record<string, 'success' | 'info' | 'muted' | 'destructive'> = {
  Applicable: 'success', 'Conditionally Applicable': 'info', 'Not Applicable': 'muted', Outdated: 'destructive',
}

export function EvidencePanel({ complaint }: { complaint: ComplaintDetail }) {
  const r = complaint.analysis?.retrieval
  const applicability = complaint.validation?.validated_decision.applicability ?? []
  const byId = new Map(applicability.filter((a) => a.evidence_id).map((a) => [a.evidence_id as string, a]))
  if (!r) return <EmptyState icon={BookOpen} title="No evidence retrieved yet" />
  return (
    <div className="space-y-5">
      {r.rule_guided_sections?.length ? (
        <p className="text-muted-foreground text-sm">
          Sections cited by the rules: <span className="font-mono text-xs">{r.rule_guided_sections.join(', ')}</span>
        </p>
      ) : null}
      <div className="space-y-3">
        {r.evidence.map((e) => {
          const ap = byId.get(e.evidence_id)
          return (
            <Card key={e.evidence_id} className="gap-2 py-4">
              <CardContent className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="primary" className="font-mono">{e.evidence_id}</Badge>
                  <Link to={`/knowledge/${e.doc_id}`} className="font-mono text-xs font-semibold hover:underline">{e.doc_id} v{e.version} § {e.section_id}</Link>
                  <span className="text-sm font-medium">{e.heading}</span>
                  <Badge variant="outline" className="capitalize">{e.doc_type}</Badge>
                  {ap ? <Badge variant={APPLICABILITY[ap.applicability] ?? 'muted'}>{ap.applicability}</Badge> : null}
                  <span className="text-muted-foreground ml-auto text-xs tabular-nums">score {e.score.toFixed(3)} · {e.methods.join(' + ')}</span>
                </div>
                <p className="text-muted-foreground line-clamp-4 text-[13px] leading-relaxed whitespace-pre-wrap">{e.text}</p>
                {ap?.reason ? <p className="text-xs">{ap.reason}</p> : null}
              </CardContent>
            </Card>
          )
        })}
      </div>
      {r.outdated?.length ? (
        <Alert variant="info">
          <History />
          <AlertTitle>Older versions (for context only)</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4">
              {r.outdated.map((o, i) => <li key={i} className="font-mono text-xs">{String(o.doc_id)} v{String(o.version)} § {String(o.section_id)} · {String(o.status)} (active {String(o.active_version)})</li>)}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}
      {r.conflicts?.length ? (
        <Alert variant="warning">
          <AlertTriangle />
          <AlertTitle>Policy conflicts resolved by precedence</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4">
              {r.conflicts.map((c, i) => <li key={i} className="text-xs">{String(c.summary ?? c.message ?? JSON.stringify(c))}</li>)}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}
    </div>
  )
}

// ------------------------------------------------------------------ response
const RESPONSE_STATUS: Record<string, 'success' | 'warning' | 'destructive' | 'muted' | 'info'> = {
  ready: 'success', approved: 'success', sent: 'muted', requires_review: 'warning', rejected: 'destructive', draft: 'info',
}

export function ResponsePanel({ complaint }: { complaint: ComplaintDetail }) {
  const { can } = useAuth()
  const config = usePublicConfig()
  const qc = useQueryClient()
  const [editing, setEditing] = React.useState<ResponseDraft | null>(null)
  const [body, setBody] = React.useState('')
  const [tone, setTone] = React.useState('professional')
  const latest = complaint.responses[0]
  const invalidate = () => qc.invalidateQueries({ queryKey: ['complaint', complaint.complaint_ref] })
  const send = useMutation({
    mutationFn: (id: number) => api.post(`/complaints/${complaint.complaint_ref}/responses/${id}/send`),
    onSuccess: () => { toast.success('Response sent'); invalidate() },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const edit = useMutation({
    mutationFn: () => api.post<{ status: string; validation: { ok: boolean; issues: { message: string }[] } }>(`/complaints/${complaint.complaint_ref}/responses/${editing!.id}/edit`, { body, tone }),
    onSuccess: (r) => {
      if (r.validation.ok) toast.success('Edited response passed validation')
      else toast.warning(`Saved, but validation found ${r.validation.issues.length} issue(s) - it needs reviewer approval`)
      setEditing(null)
      invalidate()
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  if (!latest) return <EmptyState icon={Send} title="No response drafted yet" description="A reply is drafted after the rule check." />
  const issues = latest.validation?.issues ?? []
  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            {latest.subject}
            <Badge variant={RESPONSE_STATUS[latest.status] ?? 'muted'}>{titleCase(latest.status)}</Badge>
            <Badge variant="outline">Tone: {latest.tone}</Badge>
            {latest.source === 'reviewer' ? <Badge variant="validate">Edited by a reviewer</Badge> : null}
          </CardTitle>
          <CardDescription>
            Version {latest.version_no} · drafted {fmtRelative(latest.created_at)}{latest.sent_at ? ` · sent ${fmtDateTime(latest.sent_at)} via ${latest.sent_via}` : ''}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="bg-muted/40 rounded-lg border p-4 text-[14px] leading-relaxed whitespace-pre-wrap">{latest.body}</div>
          {issues.length ? (
            <Alert variant="destructive">
              <XCircle />
              <AlertTitle>Fix these issues before sending</AlertTitle>
              <AlertDescription>
                <ul className="list-disc pl-4">{issues.map((i, k) => <li key={k}><span className="font-mono text-xs">{i.code}</span> {i.message}{i.text ? <> - “{i.text}”</> : null}</li>)}</ul>
              </AlertDescription>
            </Alert>
          ) : latest.status !== 'sent' ? (
            <Alert variant="success">
              <ShieldCheck />
              <AlertTitle>Checked before sending</AlertTitle>
              <AlertDescription>No unsupported promises, timelines, amounts or prohibited statements.</AlertDescription>
            </Alert>
          ) : null}
          {can('complaint:respond') && latest.status !== 'sent' ? (
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => send.mutate(latest.id)} disabled={send.isPending || !['ready', 'approved'].includes(latest.status)}>
                {send.isPending ? <Spinner /> : <Send />} Send to customer
              </Button>
              <Button variant="outline" onClick={() => { setEditing(latest); setBody(latest.body); setTone(latest.tone) }}>
                <Pencil /> Edit
              </Button>
              {!['ready', 'approved'].includes(latest.status) ? <span className="text-muted-foreground self-center text-xs">You can send once the draft passes its checks or a reviewer approves it.</span> : null}
            </div>
          ) : null}
        </CardContent>
      </Card>

      {complaint.responses.length > 1 ? (
        <div>
          <SectionTitle icon={History}>Earlier versions</SectionTitle>
          <div className="space-y-2">
            {complaint.responses.slice(1).map((r) => (
              <details key={r.id} className="rounded-lg border bg-card px-3 py-2">
                <summary className="flex cursor-pointer items-center gap-2 text-sm">
                  v{r.version_no} · {r.subject} <Badge variant={RESPONSE_STATUS[r.status] ?? 'muted'}>{titleCase(r.status)}</Badge>
                  <span className="text-muted-foreground ml-auto text-xs">{fmtRelative(r.created_at)}</span>
                </summary>
                <p className="text-muted-foreground mt-2 text-sm whitespace-pre-wrap">{r.body}</p>
              </details>
            ))}
          </div>
        </div>
      ) : null}

      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Edit the customer response</DialogTitle>
            <DialogDescription>Your edit is checked again before it can be sent.</DialogDescription>
          </DialogHeader>
          <label className="text-sm font-medium" htmlFor="resp-tone">Tone</label>
          <NativeSelect id="resp-tone" value={tone} onChange={(e) => setTone(e.target.value)}>
            {(config.data?.response_tones ?? []).map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}
          </NativeSelect>
          <label className="sr-only" htmlFor="resp-body">Response</label>
          <Textarea id="resp-body" rows={12} value={body} onChange={(e) => setBody(e.target.value)} className="font-[inherit]" />
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)}>Cancel</Button>
            <Button onClick={() => edit.mutate()} disabled={edit.isPending || body.trim().length < 20}>{edit.isPending ? <Spinner /> : <ShieldCheck />} Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ------------------------------------------------------------------ escalation + SLA + follow-ups
function SlaBar({ label, start, due, done }: { label: string; start: string; due: string; done: string | null }) {
  const now = useNow()
  const s = toDate(start)?.getTime() ?? 0
  const d = toDate(due)?.getTime() ?? 0
  const end = done ? toDate(done)?.getTime() ?? now : now
  const pct = d > s ? Math.min(100, ((end - s) / (d - s)) * 100) : 100
  const met = done ? end <= d : undefined
  const due_ = fmtDue(due)
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{label}</span>
        <span className={cn('text-xs', met === true ? 'text-success' : met === false || due_.overdue ? 'text-destructive' : 'text-muted-foreground')}>
          {done ? (met ? `met ${fmtDateTime(done)}` : `missed · done ${fmtDateTime(done)}`) : `${due_.text} (${fmtDateTime(due)})`}
        </span>
      </div>
      <Progress value={pct} indicatorClassName={met === false || (!done && due_.overdue) ? 'bg-destructive' : pct > 75 && !done ? 'bg-warning' : 'bg-success'} />
    </div>
  )
}

export function EscalationSlaPanel({ complaint }: { complaint: ComplaintDetail }) {
  const qc = useQueryClient()
  const { can } = useAuth()
  const complete = useMutation({
    mutationFn: (id: number) => api.post(`/complaints/${complaint.complaint_ref}/follow-ups/${id}/complete`),
    onSuccess: () => { toast.success('Follow-up completed'); qc.invalidateQueries({ queryKey: ['complaint', complaint.complaint_ref] }) },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const sla = complaint.sla
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Timer className="size-4" /> Service level</CardTitle>
          <CardDescription>{sla ? `${sla.priority} targets (${sla.rule_id})` : 'No SLA yet'}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {sla ? (
            <>
              <div className="flex gap-2"><SlaBadge state={sla.resolution_state} /><Badge variant="outline">Response: {sla.response_state}</Badge></div>
              <SlaBar label="First response" start={sla.started_at} due={sla.first_response_due_at} done={sla.first_response_at} />
              <SlaBar label="Resolution" start={sla.started_at} due={sla.resolution_due_at} done={sla.resolved_at} />
            </>
          ) : <p className="text-muted-foreground text-sm">The SLA starts once the priority is confirmed.</p>}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Clock className="size-4" /> Follow-ups</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {complaint.follow_ups.length === 0 ? <p className="text-muted-foreground text-sm">None scheduled.</p> : null}
          {complaint.follow_ups.map((f, i) => (
            <div key={f.id ?? i} className="flex items-start gap-3 rounded-lg border p-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-sm font-medium">{f.type} <Badge variant={f.status === 'completed' ? 'success' : 'info'}>{f.status}</Badge></div>
                {f.message ? <p className="text-muted-foreground mt-0.5 line-clamp-2 text-xs">{f.message}</p> : null}
                <div className="text-muted-foreground mt-1 text-xs">Due {fmtDateTime(f.due_at)}{f.source_rule ? ` · ${f.source_rule}` : ''}</div>
              </div>
              {f.id && f.status === 'scheduled' && can('complaint:update') ? (
                <Button size="sm" variant="outline" onClick={() => complete.mutate(f.id!)} disabled={complete.isPending}><CheckCircle2 /> Done</Button>
              ) : null}
            </div>
          ))}
        </CardContent>
      </Card>
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Siren className="size-4" /> Escalations</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {(complaint.escalations ?? []).length === 0 ? <p className="text-muted-foreground text-sm">No escalation.</p> : null}
          {(complaint.escalations ?? []).map((e) => {
            const notes = e.notes as Record<string, unknown>
            return (
              <div key={e.id} className="rounded-lg border p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={e.level.startsWith('Critical') ? 'destructive' : 'warning'}><AlertTriangle />{e.level}</Badge>
                  <Badge variant="outline">{e.source}</Badge>
                  <Badge variant={e.status === 'open' ? 'info' : 'muted'}>{e.status}</Badge>
                  {e.rule_ids.map((r) => <Badge key={r} variant="muted" className="font-mono">{r}</Badge>)}
                  <span className="text-muted-foreground ml-auto text-xs">{fmtDateTime(e.created_at)}</span>
                </div>
                <p className="mt-2 text-sm">{e.reason}</p>
                {notes && Object.keys(notes).length ? (
                  <KeyValue
                    className="mt-3"
                    items={Object.entries(notes).filter(([k]) => k !== 'source').map(([k, v]) => [titleCase(k), Array.isArray(v) ? v.join(' · ') : String(v ?? '—')] as [string, string])}
                  />
                ) : null}
              </div>
            )
          })}
        </CardContent>
      </Card>
    </div>
  )
}

// ------------------------------------------------------------------ timeline + audit
export function TimelinePanel({ complaint }: { complaint: ComplaintDetail }) {
  const ref = complaint.complaint_ref
  const t = useQuery({ queryKey: ['timeline', ref], queryFn: () => api.get<{ events: TimelineEvent[] }>(`/complaints/${ref}/timeline`) })
  const a = useQuery({ queryKey: ['complaint-audit', ref], queryFn: () => api.get<{ items: AuditEntry[] }>(`/complaints/${ref}/audit`) })
  return (
    <div className="grid gap-6 xl:grid-cols-[1.2fr_1fr]">
      <div>
        <SectionTitle icon={History}>Case timeline</SectionTitle>
        {t.isLoading ? <LoadingBlock /> : t.error ? <ErrorState error={t.error} /> : (
          <ol className="relative space-y-4 border-l pl-5">
            {t.data!.events.map((e) => (
              <li key={e.id} className="relative">
                <span className={cn('absolute -left-[26px] mt-1 size-3 rounded-full border-2 border-card', e.event_type.startsWith('status') ? 'bg-primary' : e.event_type.includes('escalation') ? 'bg-destructive' : e.event_type.includes('review') ? 'bg-warning' : e.event_type.includes('validation') ? 'bg-validate' : 'bg-muted-foreground/60')} aria-hidden />
                <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
                  <span className="font-medium">{titleCase(e.event_type.replace('.', ' · '))}</span>
                  {e.to_status ? <Badge variant="outline">{e.from_status} → {e.to_status}</Badge> : null}
                  <span className="text-muted-foreground text-xs">{fmtDateTime(e.at)}</span>
                </div>
                <p className="text-muted-foreground text-[13px]">{e.message}</p>
                <p className="text-muted-foreground/80 text-[11px]">by {e.actor}</p>
              </li>
            ))}
          </ol>
        )}
      </div>
      <div>
        <SectionTitle icon={ScrollText}>Audit records</SectionTitle>
        {a.isLoading ? <LoadingBlock /> : a.error ? <ErrorState error={a.error} /> : (
          <div className="space-y-2">
            {a.data!.items.map((e) => (
              <div key={e.id} className="rounded-lg border p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="primary" className="font-mono">{e.action}</Badge>
                  <span className="text-muted-foreground text-xs">{fmtDateTime(e.at)}</span>
                </div>
                <p className="mt-1">{e.summary}</p>
                <div className="text-muted-foreground mt-1 flex items-center gap-1 text-[11px]">
                  {e.actor} · <span className="font-mono">#{e.hash.slice(0, 12)}…</span> <CopyButton value={e.hash} label="Copy fingerprint" />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ AI runs
interface AiRun {
  id: number; analysis_id: number; stage: string; attempt: number; provider: string; model: string; prompt: string
  parsed_ok: boolean; error_type: string | null; error_message: string | null; latency_ms: number; input_tokens: number | null
  output_tokens: number | null; fault_injection: string | null; request: Record<string, unknown>; response_text: string | null; at: string
}

export function AiRunsPanel({ complaint }: { complaint: ComplaintDetail }) {
  const ref = complaint.complaint_ref
  const runs = useQuery({ queryKey: ['ai-runs', ref], queryFn: () => api.get<{ items: AiRun[] }>(`/complaints/${ref}/ai-runs`) })
  const a = complaint.analysis
  return (
    <div className="space-y-5">
      {a ? (
        <Card className="gap-3 py-4">
          <CardContent>
            <KeyValue columns={3} items={[
              ['Provider / model', `${a.provider} / ${a.model}`],
              ['Prompt versions', Object.entries(a.prompt_versions).map(([k, v]) => `${k}@${v}`).join(', ')],
              ['Rule Matrix version', <span key="h" className="font-mono text-xs">{a.ruleset_hash}</span>],
              ['Policy versions used', Object.entries(a.policy_versions ?? {}).map(([k, v]) => `${k} v${v}`).join(', ') || '—'],
              ['Processing time', fmtMs(a.total_latency_ms)],
              ['Fault injection', a.fault_injection ?? 'none'],
            ]} />
            {a.stage_timings ? (
              <div className="mt-4 flex flex-wrap gap-1.5">
                {Object.entries(a.stage_timings).map(([k, v]) => <Badge key={k} variant="outline" className="font-mono text-[10.5px]">{k}: {v} ms</Badge>)}
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
      <div>
        <SectionTitle icon={Bot}>AI attempts</SectionTitle>
        {runs.isLoading ? <LoadingBlock /> : runs.error ? <ErrorState error={runs.error} /> : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Stage</TableHead>
                <TableHead>Attempt</TableHead>
                <TableHead>Prompt</TableHead>
                <TableHead>Result</TableHead>
                <TableHead className="text-right">Latency</TableHead>
                <TableHead>Output</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.data!.items.map((r) => (
                <TableRow key={r.id}>
                  <TableCell className="capitalize">{r.stage}</TableCell>
                  <TableCell>#{r.attempt}{r.fault_injection ? <Badge variant="warning" className="ml-1.5">fault: {r.fault_injection}</Badge> : null}</TableCell>
                  <TableCell className="font-mono text-xs">{r.prompt}</TableCell>
                  <TableCell>{r.parsed_ok ? <Badge variant="success"><CheckCircle2 />valid</Badge> : <Badge variant="destructive"><XCircle />{r.error_type ?? 'invalid'}</Badge>}
                    {r.error_message ? <div className="text-muted-foreground mt-1 max-w-xs text-[11px]">{r.error_message.slice(0, 180)}</div> : null}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{fmtMs(r.latency_ms)}</TableCell>
                  <TableCell>
                    <details>
                      <summary className="text-primary cursor-pointer text-xs">raw</summary>
                      <JsonView value={r.response_text ?? ''} className="mt-2 max-w-xl" />
                    </details>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
      {a?.output ? (
        <details className="rounded-lg border bg-card p-3">
          <summary className="cursor-pointer text-sm font-medium">Full AI analysis output</summary>
          <JsonView value={a.output} className="mt-3" />
        </details>
      ) : null}
    </div>
  )
}

// ------------------------------------------------------------------ related
export function RelatedCases({ complaint }: { complaint: ComplaintDetail }) {
  const hist = (complaint.preprocessing?.history ?? {}) as { history?: { complaint_ref: string; date: string; subcategory: string | null; status: string; similarity: number }[] }
  const related = complaint.related ?? []
  if (!related.length && !(hist.history ?? []).length) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm"><Link2 className="size-4" /> Customer history</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {related.map((r) => (
          <div key={r.complaint_ref} className="flex items-center gap-2 text-sm">
            <Badge variant="warning">{r.relation.replace('_', ' ')}</Badge>
            <Link className="font-mono text-xs font-semibold text-primary hover:underline" to={`/complaints/${r.complaint_ref}`}>{r.complaint_ref}</Link>
            <span className="truncate">{r.title}</span>
          </div>
        ))}
        {(hist.history ?? []).slice(0, 6).map((h) => (
          <div key={h.complaint_ref} className="text-muted-foreground flex items-center gap-2 text-xs">
            <Link className="font-mono font-semibold text-primary hover:underline" to={`/complaints/${h.complaint_ref}`}>{h.complaint_ref}</Link>
            <span>{h.date}</span><span>{h.subcategory}</span><span>{h.status}</span><span className="ml-auto tabular-nums">{Math.round(h.similarity * 100)}% similar</span>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
