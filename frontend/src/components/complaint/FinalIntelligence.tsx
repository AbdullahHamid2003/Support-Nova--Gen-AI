/* The validated "Final Intelligence": every field here was enforced or confirmed by the Python pipeline. */
import { Ban, Bot, CheckCircle2, CircleHelp, Clock, Coins, Gavel, ListChecks, Route, ShieldCheck, Siren, UserCheck } from 'lucide-react'
import type * as React from 'react'

import { KeyValue } from '@/components/app/common'
import { EscalationBadge, PriorityBadge, UrgencyBadge } from '@/components/app/status'
import { Tooltip } from '@/components/ui/overlays'
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Separator } from '@/components/ui/primitives'
import { usePublicConfig } from '@/lib/auth'
import type { ValidatedDecision } from '@/lib/types'
import { cn, titleCase } from '@/lib/utils'

const ELIG: Record<string, { v: 'success' | 'warning' | 'destructive' | 'muted' | 'info'; label: string }> = {
  eligible: { v: 'success', label: 'Eligible' },
  requires_verification: { v: 'warning', label: 'Requires verification' },
  not_eligible: { v: 'destructive', label: 'Not eligible' },
  not_applicable: { v: 'muted', label: 'Not applicable' },
  partial: { v: 'info', label: 'Partial' },
}

function Elig({ label, value, detail }: { label: string; value: string; detail?: React.ReactNode }) {
  const cfg = ELIG[value] ?? { v: 'muted' as const, label: titleCase(value) }
  return (
    <div className="rounded-lg border p-3">
      <div className="text-muted-foreground text-xs font-medium">{label}</div>
      <Badge variant={cfg.v} className="mt-1.5">{cfg.label}</Badge>
      {detail ? <div className="text-muted-foreground mt-1.5 text-xs">{detail}</div> : null}
    </div>
  )
}

function SourceTag({ source }: { source: string }) {
  const map: Record<string, { v: 'validate' | 'primary' | 'warning' | 'info'; label: string; tip: string }> = {
    python_rules: { v: 'validate', label: 'Rules', tip: 'Set by the category rules.' },
    reviewer_override: { v: 'info', label: 'Reviewer', tip: 'Reclassified by a reviewer.' },
    ai_unconfirmed: { v: 'warning', label: 'Provisional (AI)', tip: 'Rules were unsure; the AI label is used until review.' },
    python_low_confidence: { v: 'warning', label: 'Low confidence', tip: 'Rules could not classify it; a reviewer will decide.' },
  }
  const cfg = map[source] ?? { v: 'primary' as const, label: source, tip: source }
  return <Tooltip content={cfg.tip}><Badge variant={cfg.v}>{cfg.label}</Badge></Tooltip>
}

export function FinalIntelligence({ vd }: { vd: ValidatedDecision }) {
  const config = usePublicConfig()
  const dept = (code: string | null) => config.data?.departments.find((d) => d.code === code)?.name ?? code ?? '—'
  const cls = vd.classification
  const e = vd.eligibility
  const required = vd.required_actions.map((a) => (typeof a === 'string' ? a : `one of ${a.any_of.join(' / ')}`))
  return (
    <Card className="border-validate/30">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="text-validate size-5" aria-hidden /> Final decision
        </CardTitle>
        <CardDescription>Checked against the Rule Matrix, order records and policies.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {vd.summary ? <p className="bg-muted/50 rounded-lg p-3 text-sm leading-relaxed">{vd.summary}</p> : null}
        {vd.summary_note ? (
          <p className="text-muted-foreground -mt-3 flex items-center gap-1.5 text-xs"><Ban className="text-destructive size-3.5 shrink-0" aria-hidden /> {vd.summary_note}</p>
        ) : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <div className="text-muted-foreground text-xs font-medium">Classification</div>
            <div className="font-medium">{cls.category_name} › {cls.subcategory_name ?? '—'}</div>
            <div className="flex flex-wrap items-center gap-1.5">
              <SourceTag source={cls.source} />
              {cls.secondary.map((s) => <Badge key={s} variant="outline">+ {s}</Badge>)}
            </div>
          </div>
          <div className="space-y-1.5">
            <div className="text-muted-foreground flex items-center gap-1 text-xs font-medium"><Route className="size-3.5" /> Routing</div>
            <div className="font-medium">{dept(vd.department)}</div>
            {vd.supporting_departments.length ? <div className="text-muted-foreground text-xs">Supporting: {vd.supporting_departments.map(dept).join(', ')}</div> : null}
          </div>
          <div className="space-y-1.5">
            <div className="text-muted-foreground text-xs font-medium">Urgency · impact · priority</div>
            <div className="flex flex-wrap items-center gap-1.5">
              <UrgencyBadge urgency={vd.urgency} />
              <Badge variant="outline">Impact {vd.impact}</Badge>
              <PriorityBadge priority={vd.priority} />
            </div>
            {vd.urgency_sources.length ? <div className="text-muted-foreground text-xs">Basis: {vd.urgency_sources.join(', ')}</div> : null}
          </div>
          <div className="space-y-1.5">
            <div className="text-muted-foreground flex items-center gap-1 text-xs font-medium"><Siren className="size-3.5" /> Escalation</div>
            <EscalationBadge level={vd.escalation.level} required={vd.escalation.required} />
            {vd.escalation.fired.slice(0, 3).map((f) => (
              <div key={f.rule_id} className="text-muted-foreground text-xs"><span className="font-mono">{f.rule_id}</span> {f.reason}</div>
            ))}
          </div>
        </div>

        <Separator />

        <div>
          <div className="text-muted-foreground mb-2 flex items-center gap-1 text-xs font-medium"><Coins className="size-3.5" /> Eligibility</div>
          <div className="grid gap-2 sm:grid-cols-3">
            <Elig label="Refund" value={e.refund} />
            <Elig label="Replacement" value={e.replacement} />
            <Elig
              label="Compensation"
              value={e.compensation}
              detail={e.compensation_type ? `${titleCase(e.compensation_type)}${e.compensation_amount_usd ? ` · USD ${e.compensation_amount_usd}` : ''}${e.compensation_max_usd ? ` (max ${e.compensation_max_usd})` : ''}` : undefined}
            />
          </div>
          {e.pending_rule_ids.length ? <p className="text-warning mt-2 text-xs">Depends on unverified facts ({e.pending_rule_ids.join(', ')}) - verify before confirming any outcome.</p> : null}
        </div>

        <Separator />

        <div className="grid gap-5 lg:grid-cols-2">
          <div>
            <div className="text-muted-foreground mb-2 flex items-center gap-1 text-xs font-medium"><ListChecks className="size-3.5" /> Resolution steps · rule <span className="font-mono">{vd.selected_rule.rule_id ?? '—'}</span></div>
            <ol className="space-y-1.5">
              {vd.resolution_steps.map((s, i) => (
                <li key={s.action_code + i} className="flex items-start gap-2 text-sm">
                  <span className="bg-primary/10 text-primary mt-0.5 flex size-5 shrink-0 items-center justify-center rounded text-[11px] font-semibold">{i + 1}</span>
                  <span className="min-w-0">
                    <span className="font-medium">{s.description}</span>{' '}
                    <span className="text-muted-foreground font-mono text-[11px]">{s.action_code}</span>
                    <Badge variant={s.source === 'rule' ? 'validate' : 'secondary'} className="ml-1.5 px-1 py-0 text-[10px]">{s.source === 'rule' ? 'added by rules' : 'AI · checked'}</Badge>
                  </span>
                </li>
              ))}
            </ol>
            {vd.selected_rule.condition ? <p className="text-muted-foreground mt-2 font-mono text-[11px] leading-relaxed">when {vd.selected_rule.condition}</p> : null}
          </div>
          <div className="space-y-3">
            {required.length ? (
              <div>
                <div className="text-muted-foreground mb-1 flex items-center gap-1 text-xs font-medium"><CheckCircle2 className="size-3.5" /> Required actions</div>
                <div className="flex flex-wrap gap-1">{required.map((a) => <Badge key={a} variant="outline" className="font-mono text-[10.5px]">{a}</Badge>)}</div>
              </div>
            ) : null}
            {vd.prohibited_actions.length ? (
              <div>
                <div className="text-destructive mb-1 flex items-center gap-1 text-xs font-medium"><Ban className="size-3.5" /> Prohibited</div>
                <div className="flex flex-wrap gap-1">{vd.prohibited_actions.map((a) => <Badge key={a} variant="destructive" className="font-mono text-[10.5px]">{a}</Badge>)}</div>
              </div>
            ) : null}
            {vd.excluded_ai_steps?.length ? (
              <div>
                <div className="text-muted-foreground mb-1 flex items-center gap-1 text-xs font-medium"><Bot className="size-3.5" /> AI proposals rejected</div>
                <ul className="space-y-1 text-xs">
                  {vd.excluded_ai_steps.map((s) => (
                    <li key={s.action_code}><span className="font-mono line-through opacity-70">{s.action_code}</span> <span className="text-muted-foreground">- {s.reason}</span></li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </div>

        {vd.missing_information.length || vd.clarification_questions.length ? (
          <>
            <Separator />
            <div>
              <div className="text-muted-foreground mb-2 flex items-center gap-1 text-xs font-medium"><CircleHelp className="size-3.5" /> Missing information</div>
              <div className="flex flex-wrap gap-1.5">
                {vd.missing_information.map((m) => <Badge key={m.field} variant={m.blocking ? 'warning' : 'outline'}>{m.label}{m.blocking ? ' · blocking' : ''}</Badge>)}
              </div>
              {vd.clarification_questions.length ? (
                <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm">{vd.clarification_questions.map((q) => <li key={q}>{q}</li>)}</ul>
              ) : null}
            </div>
          </>
        ) : null}

        {vd.timelines.length ? (
          <>
            <Separator />
            <div>
              <div className="text-muted-foreground mb-2 flex items-center gap-1 text-xs font-medium"><Clock className="size-3.5" /> Timelines the response may quote</div>
              <ul className="space-y-1 text-sm">{vd.timelines.map((t) => <li key={t.param}>{t.text}</li>)}</ul>
            </div>
          </>
        ) : null}

        <Separator />
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <div className="text-muted-foreground mb-1.5 flex items-center gap-1 text-xs font-medium"><Gavel className="size-3.5" /> Guidance for the agent</div>
            <ul className="space-y-1 text-sm">{vd.agent_guidance.validated.map((g) => <li key={g} className="flex gap-1.5"><ShieldCheck className="text-validate mt-0.5 size-3.5 shrink-0" />{g}</li>)}</ul>
          </div>
          <div>
            <div className="text-muted-foreground mb-1.5 flex items-center gap-1 text-xs font-medium"><Bot className="size-3.5" /> AI recommendation</div>
            <ul className={cn('space-y-1 text-sm', !vd.agent_guidance.ai_recommendation.length && 'text-muted-foreground')}>
              {vd.agent_guidance.ai_recommendation.length ? vd.agent_guidance.ai_recommendation.map((g) => <li key={g}>• {g}</li>) : <li>None</li>}
            </ul>
            {vd.agent_guidance.human.length ? (
              <>
                <div className="text-muted-foreground mt-3 mb-1 flex items-center gap-1 text-xs font-medium"><UserCheck className="size-3.5" /> Reviewer notes</div>
                <ul className="space-y-1 text-sm">{vd.agent_guidance.human.map((g) => <li key={g}>• {g}</li>)}</ul>
              </>
            ) : null}
          </div>
        </div>
        {vd.follow_up?.required ? (
          <KeyValue items={[['Follow-up', vd.follow_up.type ?? '—'], ['Due', vd.follow_up.due_hours ? `${vd.follow_up.due_hours} h after analysis` : '—']]} />
        ) : null}
      </CardContent>
    </Card>
  )
}
