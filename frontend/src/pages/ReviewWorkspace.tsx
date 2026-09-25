import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Ban, Bot, CheckCircle2, ClipboardCheck, GitCompareArrows, Hand, History, MessageSquare, Pencil, RefreshCw, Scale, ShieldAlert, Shuffle, Siren, Tags } from 'lucide-react'
import * as React from 'react'
import { Link, useParams } from 'react-router'
import { toast } from 'sonner'

import { ComplaintText } from '@/components/complaint/ComplaintText'
import { EmptyState, ErrorState, LoadingBlock, Spinner } from '@/components/app/common'
import { MatchBadge, PriorityBadge, StatusBadge, VerificationBadge } from '@/components/app/status'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/overlays'
import { Alert, AlertDescription, AlertTitle, Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, NativeSelect, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Textarea } from '@/components/ui/primitives'
import { api, errorMessage } from '@/lib/api'
import { useAuth, usePublicConfig } from '@/lib/auth'
import { fmtDateTime, fmtRelative } from '@/lib/format'
import { REASON_LABELS, type ReviewItem } from '@/lib/reviews'
import type { ComplaintDetail } from '@/lib/types'
import { display, titleCase } from '@/lib/utils'

type Action = 'approve' | 'reject' | 'modify' | 'reclassify' | 'reassign' | 'escalate' | 'regenerate' | 'comment'

const ACTIONS: { key: Action; label: string; icon: React.ElementType; hint: string; needsComment: boolean }[] = [
  { key: 'approve', label: 'Approve', icon: CheckCircle2, hint: 'Accept the decision and draft response (becomes Human Verified).', needsComment: false },
  { key: 'modify', label: 'Modify', icon: Pencil, hint: 'Change department, urgency, priority or escalation, or edit the response.', needsComment: true },
  { key: 'reclassify', label: 'Reclassify', icon: Tags, hint: 'Set the correct subcategory and re-run the analysis.', needsComment: true },
  { key: 'reassign', label: 'Reassign', icon: Shuffle, hint: 'Route to another department or agent.', needsComment: true },
  { key: 'escalate', label: 'Escalate', icon: Siren, hint: 'Raise the escalation level.', needsComment: false },
  { key: 'regenerate', label: 'Regenerate', icon: RefreshCw, hint: 'Draft a new AI response, optionally in another tone.', needsComment: false },
  { key: 'reject', label: 'Reject', icon: Ban, hint: 'Reject the draft response; the case stays open.', needsComment: true },
  { key: 'comment', label: 'Comment', icon: MessageSquare, hint: 'Add a note to the audit trail without changing anything.', needsComment: false },
]

export default function ReviewWorkspacePage() {
  const { id = '' } = useParams()
  const { can, session } = useAuth()
  const config = usePublicConfig()
  const qc = useQueryClient()
  const review = useQuery({ queryKey: ['review', id], queryFn: () => api.get<ReviewItem>(`/reviews/${id}`) })
  const ref = review.data?.complaint?.complaint_ref
  const complaint = useQuery({ queryKey: ['complaint', ref], queryFn: () => api.get<ComplaintDetail>(`/complaints/${ref}`), enabled: !!ref })
  const agents = useQuery({ queryKey: ['staff', 'agent'], queryFn: () => api.get<{ items: { id: number; full_name: string; department: string | null }[] }>('/staff', { role: 'agent' }), enabled: can('review:act') })

  const [action, setAction] = React.useState<Action>('approve')
  const [comment, setComment] = React.useState('')
  const [fields, setFields] = React.useState<Record<string, string>>({})
  const [responseBody, setResponseBody] = React.useState('')
  const [subcategory, setSubcategory] = React.useState('')
  const [dept, setDept] = React.useState('')
  const [agentId, setAgentId] = React.useState('')
  const [level, setLevel] = React.useState('')
  const [tone, setTone] = React.useState('')

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['review', id] })
    qc.invalidateQueries({ queryKey: ['complaint', ref] })
    qc.invalidateQueries({ queryKey: ['reviews'] })
  }
  const claim = useMutation({ mutationFn: () => api.post(`/reviews/${id}/claim`), onSuccess: () => { toast.success('Review claimed'); invalidate() }, onError: (e) => toast.error(errorMessage(e)) })
  const act = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = {}
      if (action === 'modify') {
        payload.fields = Object.fromEntries(Object.entries(fields).filter(([, v]) => v))
        if (responseBody.trim()) payload.response_body = responseBody.trim()
        if (tone) payload.tone = tone
      }
      if (action === 'reclassify') payload.subcategory = subcategory
      if (action === 'reassign') {
        if (dept) payload.department_code = dept
        if (agentId) payload.agent_id = Number(agentId)
      }
      if (action === 'escalate') payload.level = level
      if (action === 'regenerate' && tone) payload.tone = tone
      return api.post<{ followup: { response_validation?: { ok: boolean; issues: { message: string }[] }; reprocess?: unknown } }>(`/reviews/${id}/actions`, { action, comment, payload })
    },
    onSuccess: (r) => {
      const rv = r.followup?.response_validation
      if (rv && !rv.ok) toast.warning(`Saved - the edited response has ${rv.issues.length} issue(s) to fix`)
      else toast.success(r.followup?.reprocess ? `${titleCase(action)} recorded - re-running the analysis` : `${titleCase(action)} recorded`)
      setComment('')
      invalidate()
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  if (review.isLoading) return <LoadingBlock rows={8} />
  if (review.error) return <ErrorState error={review.error} onRetry={() => review.refetch()} />
  const r = review.data!
  const c = complaint.data
  const cfg = ACTIONS.find((a) => a.key === action)!
  const done = r.status === 'completed'
  const canAct = can('review:act') && !done
  const vd = c?.validation?.validated_decision
  const ai = c?.analysis?.output as Record<string, unknown> | undefined
  const mismatches = (c?.validation?.comparison.rows ?? []).filter((x) => x.match !== 'match')
  const latestResponse = c?.responses?.[0]
  const subOptions = (config.data?.categories ?? []).flatMap((cat) => cat.subcategories.map((s) => ({ value: s.code, label: `${cat.name} › ${s.name}` })))
  const disabledReason = cfg.needsComment && comment.trim().length < 3 ? 'A comment is required for this action.'
    : action === 'reclassify' && !subcategory ? 'Choose the correct subcategory.'
      : action === 'escalate' && !level ? 'Choose a level.'
        : action === 'reassign' && !dept && !agentId ? 'Choose a department or an agent.' : null

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <Link to="/reviews" className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs"><ArrowLeft className="size-3.5" /> Review queue</Link>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="primary" className="font-mono">Review #{r.id}</Badge>
          {ref ? <Link to={`/complaints/${ref}`} className="font-mono text-sm font-semibold text-primary hover:underline">{ref}</Link> : null}
          <Badge variant={done ? 'success' : r.status === 'in_review' ? 'info' : 'warning'}>{done ? `completed · ${r.final_decision}` : r.status.replace('_', ' ')}</Badge>
          <PriorityBadge priority={r.priority} />
          {c ? <><StatusBadge status={c.status} /><VerificationBadge status={c.verification_status} score={c.verification_score} /></> : null}
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">{r.complaint?.title}</h1>
        <p className="text-muted-foreground text-sm">Queued {fmtRelative(r.created_at)}{r.started_at ? ` · claimed ${fmtRelative(r.started_at)}` : ''}</p>
      </div>

      <Alert variant="warning">
        <ShieldAlert />
        <AlertTitle>Why this needs review</AlertTitle>
        <AlertDescription>
          <ul className="list-disc space-y-0.5 pl-4">
            {r.reasons.map((x) => <li key={x.code}><strong>{REASON_LABELS[x.code] ?? x.name}</strong>{x.message || x.detail ? ` - ${x.message ?? x.detail}` : ''}</li>)}
          </ul>
        </AlertDescription>
      </Alert>

      <div className="grid gap-6 xl:grid-cols-[1.35fr_1fr]">
        <div className="space-y-6">
          {complaint.isLoading ? <LoadingBlock /> : !c ? <EmptyState title="Complaint unavailable" /> : (
            <>
              <Card>
                <CardHeader><CardTitle>Complaint</CardTitle><CardDescription>{c.customer_name ?? 'Unlinked customer'} · {titleCase(c.channel)} · {fmtDateTime(c.complaint_date)}</CardDescription></CardHeader>
                <CardContent><ComplaintText text={c.description} findings={c.preprocessing?.injection?.findings} /></CardContent>
              </Card>
              <Card className="py-0">
                <CardHeader className="pt-5">
                  <CardTitle className="flex items-center gap-2"><GitCompareArrows className="size-4" /> Where AI and rules disagree</CardTitle>
                  <CardDescription>{mismatches.length ? `${mismatches.length} of ${c.validation?.comparison.rows.length} fields differ. The decision uses the rules value unless noted.` : 'AI and rules agree on every field.'}</CardDescription>
                </CardHeader>
                <CardContent className="px-0">
                  {mismatches.length ? (
                    <Table>
                      <TableHeader><TableRow><TableHead>Field</TableHead><TableHead><Bot className="mr-1 inline size-3.5" />AI</TableHead><TableHead><Scale className="mr-1 inline size-3.5" />Rules</TableHead><TableHead /></TableRow></TableHeader>
                      <TableBody>
                        {mismatches.map((m) => (
                          <TableRow key={m.field}>
                            <TableCell className="font-medium">{titleCase(m.field)}</TableCell>
                            <TableCell className="max-w-[14rem] text-sm">{display(m.ai)}</TableCell>
                            <TableCell className="max-w-[14rem] text-sm font-medium">
                              {display(m.python)}
                              {m.explanation ? <div className="text-muted-foreground mt-0.5 text-xs font-normal">{m.explanation}</div> : null}
                            </TableCell>
                            <TableCell><MatchBadge match={m.match} /></TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  ) : null}
                </CardContent>
              </Card>
              <Tabs defaultValue="validated">
                <TabsList>
                  <TabsTrigger value="validated"><Scale /> Final decision</TabsTrigger>
                  <TabsTrigger value="ai"><Bot /> Original AI output</TabsTrigger>
                  <TabsTrigger value="response"><MessageSquare /> Draft response</TabsTrigger>
                </TabsList>
                <TabsContent value="validated">
                  {vd ? (
                    <Card><CardContent className="grid gap-3 text-sm sm:grid-cols-2">
                      <div><div className="text-muted-foreground text-xs">Classification</div>{vd.classification.category_name} › {vd.classification.subcategory_name}</div>
                      <div><div className="text-muted-foreground text-xs">Department</div>{vd.department}{vd.supporting_departments.length ? ` (+ ${vd.supporting_departments.join(', ')})` : ''}</div>
                      <div><div className="text-muted-foreground text-xs">Urgency / priority</div>{vd.urgency} / {vd.priority}</div>
                      <div><div className="text-muted-foreground text-xs">Escalation</div>{vd.escalation.required ? vd.escalation.level : 'None'}</div>
                      <div><div className="text-muted-foreground text-xs">Refund / replacement / compensation</div>{vd.eligibility.refund} / {vd.eligibility.replacement} / {vd.eligibility.compensation}</div>
                      <div><div className="text-muted-foreground text-xs">Selected rule</div><span className="font-mono">{vd.selected_rule.rule_id}</span></div>
                      <div className="sm:col-span-2"><div className="text-muted-foreground text-xs">Resolution steps</div><ol className="list-decimal pl-5">{vd.resolution_steps.map((s, i) => <li key={i}>{s.description} <span className="text-muted-foreground font-mono text-[11px]">{s.action_code}</span></li>)}</ol></div>
                    </CardContent></Card>
                  ) : <EmptyState title="No final decision yet" />}
                </TabsContent>
                <TabsContent value="ai">
                  {ai ? (
                    <Card><CardContent className="grid gap-3 text-sm sm:grid-cols-2">
                      <div><div className="text-muted-foreground text-xs">Classification</div>{String(ai.issue_category)} › {String(ai.subcategory)}</div>
                      <div><div className="text-muted-foreground text-xs">Department</div>{String(ai.department)}</div>
                      <div><div className="text-muted-foreground text-xs">Urgency / priority</div>{String(ai.urgency)} / {String(ai.priority)}</div>
                      <div><div className="text-muted-foreground text-xs">Escalation</div>{String(ai.escalation_level)}</div>
                      <div className="sm:col-span-2"><div className="text-muted-foreground text-xs">Summary</div>{String(ai.summary ?? '')}</div>
                    </CardContent></Card>
                  ) : <EmptyState icon={Bot} title="No usable AI output" description="The decision is based on the rules only." />}
                </TabsContent>
                <TabsContent value="response">
                  {latestResponse ? (
                    <Card><CardHeader><CardTitle className="text-sm">{latestResponse.subject} <Badge variant="outline" className="ml-1">{latestResponse.status.replace('_', ' ')}</Badge></CardTitle></CardHeader>
                      <CardContent className="space-y-3">
                        <p className="text-sm whitespace-pre-wrap">{latestResponse.body}</p>
                        {(latestResponse.validation.issues ?? []).length ? (
                          <Alert variant="destructive"><Ban /><AlertTitle>Issues to fix</AlertTitle><AlertDescription><ul className="list-disc pl-4">{latestResponse.validation.issues!.map((i, k) => <li key={k}>{i.message}</li>)}</ul></AlertDescription></Alert>
                        ) : null}
                      </CardContent></Card>
                  ) : <EmptyState title="No draft response" />}
                </TabsContent>
              </Tabs>
            </>
          )}
        </div>

        <div className="space-y-6">
          <Card className="border-primary/30 xl:sticky xl:top-20">
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><ClipboardCheck className="size-4" /> Reviewer decision</CardTitle>
              <CardDescription>{done ? `Completed ${fmtRelative(r.completed_at)} - ${r.final_decision}.` : 'Every action is recorded in the audit log.'}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {!can('review:act') ? <p className="text-muted-foreground text-sm">Your role can view reviews but not act on them.</p> : null}
              {canAct && r.status === 'pending' ? (
                <Button variant="secondary" className="w-full" onClick={() => claim.mutate()} disabled={claim.isPending}><Hand /> Claim this review ({session?.user.full_name})</Button>
              ) : null}
              {canAct ? (
                <>
                  <div className="grid grid-cols-2 gap-1.5" role="radiogroup" aria-label="Reviewer action">
                    {ACTIONS.map((a) => (
                      <button key={a.key} type="button" role="radio" aria-checked={action === a.key} onClick={() => setAction(a.key)}
                        className={`flex items-center gap-2 rounded-lg border px-2.5 py-2 text-left text-sm transition-colors ${action === a.key ? 'border-primary bg-primary/8 text-primary font-medium' : 'hover:bg-accent'}`}>
                        <a.icon className="size-4" aria-hidden /> {a.label}
                      </button>
                    ))}
                  </div>
                  <p className="text-muted-foreground text-xs">{cfg.hint}</p>
                  {action === 'modify' ? (
                    <div className="space-y-3">
                      <div className="grid grid-cols-2 gap-2">
                        <NativeSelect aria-label="Department" value={fields.department_code ?? ''} onChange={(e) => setFields({ ...fields, department_code: e.target.value })}>
                          <option value="">Department (keep)</option>{(config.data?.departments ?? []).map((d) => <option key={d.code} value={d.code}>{d.name}</option>)}
                        </NativeSelect>
                        <NativeSelect aria-label="Urgency" value={fields.urgency ?? ''} onChange={(e) => setFields({ ...fields, urgency: e.target.value })}>
                          <option value="">Urgency (keep)</option>{['Critical', 'High', 'Medium', 'Low'].map((u) => <option key={u}>{u}</option>)}
                        </NativeSelect>
                        <NativeSelect aria-label="Priority" value={fields.priority ?? ''} onChange={(e) => setFields({ ...fields, priority: e.target.value })}>
                          <option value="">Priority (keep)</option>{['P0', 'P1', 'P2', 'P3'].map((u) => <option key={u}>{u}</option>)}
                        </NativeSelect>
                        <NativeSelect aria-label="Escalation level" value={fields.escalation_level ?? ''} onChange={(e) => setFields({ ...fields, escalation_level: e.target.value })}>
                          <option value="">Escalation (keep)</option>{(config.data?.escalation_levels ?? []).map((u) => <option key={u}>{u}</option>)}
                        </NativeSelect>
                      </div>
                      <label className="text-xs font-medium" htmlFor="rb">Edited customer response (optional)</label>
                      <Textarea id="rb" rows={6} value={responseBody} onChange={(e) => setResponseBody(e.target.value)} placeholder={latestResponse?.body.slice(0, 120)} />
                    </div>
                  ) : null}
                  {action === 'reclassify' ? (
                    <NativeSelect aria-label="Correct subcategory" value={subcategory} onChange={(e) => setSubcategory(e.target.value)}>
                      <option value="">Correct subcategory…</option>{subOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </NativeSelect>
                  ) : null}
                  {action === 'reassign' ? (
                    <div className="grid gap-2">
                      <NativeSelect aria-label="Department" value={dept} onChange={(e) => setDept(e.target.value)}>
                        <option value="">Department (keep)</option>{(config.data?.departments ?? []).map((d) => <option key={d.code} value={d.code}>{d.name}</option>)}
                      </NativeSelect>
                      <NativeSelect aria-label="Agent" value={agentId} onChange={(e) => setAgentId(e.target.value)}>
                        <option value="">Agent (keep)</option>{(agents.data?.items ?? []).filter((a) => !dept || a.department === dept).map((a) => <option key={a.id} value={a.id}>{a.full_name} ({a.department})</option>)}
                      </NativeSelect>
                    </div>
                  ) : null}
                  {action === 'escalate' ? (
                    <NativeSelect aria-label="Escalation level" value={level} onChange={(e) => setLevel(e.target.value)}>
                      <option value="">Level…</option>{(config.data?.escalation_levels ?? []).filter((l) => l !== 'No Escalation').map((l) => <option key={l}>{l}</option>)}
                    </NativeSelect>
                  ) : null}
                  {action === 'regenerate' || action === 'modify' ? (
                    <NativeSelect aria-label="Tone" value={tone} onChange={(e) => setTone(e.target.value)}>
                      <option value="">Tone (keep {c?.requested_tone})</option>{(config.data?.response_tones ?? []).map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}
                    </NativeSelect>
                  ) : null}
                  <div>
                    <label htmlFor="cmt" className="text-xs font-medium">Comment {cfg.needsComment ? <span className="text-destructive">*</span> : '(optional)'}</label>
                    <Textarea id="cmt" rows={3} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Explain your decision" />
                  </div>
                  {disabledReason ? <p className="text-muted-foreground text-xs">{disabledReason}</p> : null}
                  <Button className="w-full" onClick={() => act.mutate()} disabled={!!disabledReason || act.isPending} variant={action === 'reject' ? 'destructive' : action === 'approve' ? 'success' : 'default'}>
                    {act.isPending ? <Spinner /> : <cfg.icon />} {cfg.label}
                  </Button>
                </>
              ) : null}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2 text-sm"><History className="size-4" /> Review history</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {r.actions.length === 0 ? <p className="text-muted-foreground text-sm">No actions yet.</p> : null}
              {r.actions.map((a, i) => (
                <div key={i} className="border-l-2 pl-3 text-sm">
                  <div className="flex items-center gap-2"><Badge variant="outline">{a.action}</Badge><span className="text-muted-foreground text-xs">{fmtDateTime(a.at)}</span></div>
                  <div className="text-muted-foreground text-xs">by {a.actor}</div>
                  {a.comment ? <p className="mt-1">{a.comment}</p> : null}
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
