/* COMPLAINT -> AI ANALYSIS -> EVIDENCE -> VALIDATION -> RESOLUTION -> RESPONSE -> ESCALATION -> AUDIT */
import { motion } from 'framer-motion'
import { BookOpen, CheckCircle2, CircleDashed, FileText, Loader2, MessageSquareText, ScrollText, Scale, Siren, Sparkles, Wrench, XCircle } from 'lucide-react'
import type * as React from 'react'

import { Tooltip } from '@/components/ui/overlays'
import type { ComplaintDetail } from '@/lib/types'
import { cn } from '@/lib/utils'

type State = 'done' | 'warn' | 'fail' | 'active' | 'pending' | 'skipped'

interface Step {
  key: string
  label: string
  icon: React.ElementType
  state: State
  summary: string
  tab: string
}

function buildSteps(c: ComplaintDetail): Step[] {
  const a = c.analysis
  const v = c.validation
  const vd = v?.validated_decision
  const running = !['completed', 'failed'].includes(c.processing_stage)
  const failedChecks = (v?.checks ?? []).filter((x) => x.status === 'fail')
  const dimFail = (dims: string[]) => failedChecks.some((x) => dims.includes(x.dimension))
  const resp = c.responses?.[0]
  const esc = vd?.escalation
  return [
    { key: 'complaint', label: 'Complaint', icon: FileText, tab: 'overview', state: c.preprocessing?.injection?.is_suspicious ? 'warn' : 'done',
      summary: c.preprocessing?.injection?.is_suspicious ? `Injection attempt neutralised (${c.preprocessing.injection.types.join(', ')})` : `Received via ${c.channel.replace('_', ' ')}` },
    { key: 'ai', label: 'AI analysis', icon: Sparkles, tab: 'ai', state: !a ? (running ? 'active' : 'pending') : a.status === 'completed' ? (a.ai_attempts > 2 ? 'warn' : 'done') : 'fail',
      summary: !a ? 'Waiting' : `${a.model} · ${a.ai_attempts} AI call${a.ai_attempts === 1 ? '' : 's'}${a.status !== 'completed' ? ' · invalid output' : ''}` },
    { key: 'evidence', label: 'Evidence', icon: BookOpen, tab: 'evidence', state: !a ? 'pending' : (a.retrieval?.evidence?.length ?? 0) > 0 ? (dimFail(['policy']) ? 'warn' : 'done') : 'warn',
      summary: a ? `${a.retrieval?.evidence?.length ?? 0} policy sections · ${a.retrieval?.conflicts?.length ?? 0} conflicts` : 'Waiting' },
    { key: 'validation', label: 'Rule check', icon: Scale, tab: 'compare', state: !v ? (running ? 'active' : 'pending') : v.decision === 'Verified' ? 'done' : failedChecks.some((x) => x.severity === 'critical') ? 'fail' : 'warn',
      summary: v ? `${v.decision} · ${Math.round(v.score)}/100 · ${failedChecks.length} failed` : 'Waiting' },
    { key: 'resolution', label: 'Resolution', icon: Wrench, tab: 'overview', state: !vd ? 'pending' : dimFail(['resolution', 'eligibility']) ? 'warn' : 'done',
      summary: vd ? `${vd.resolution_steps.length} steps · rule ${vd.selected_rule.rule_id ?? '—'}` : 'Waiting' },
    { key: 'response', label: 'Response', icon: MessageSquareText, tab: 'response', state: !resp ? (running ? 'active' : 'pending') : resp.status === 'sent' ? 'done' : resp.status === 'ready' || resp.status === 'approved' ? 'done' : 'warn',
      summary: resp ? `v${resp.version_no} · ${resp.status.replace('_', ' ')}` : 'Waiting' },
    { key: 'escalation', label: 'Escalation', icon: Siren, tab: 'sla', state: !vd ? 'pending' : esc?.required ? (dimFail(['escalation']) ? 'warn' : 'done') : 'skipped',
      summary: esc?.required ? esc.level : 'Not required' },
    { key: 'audit', label: 'Audit trail', icon: ScrollText, tab: 'timeline', state: c.processing_stage === 'completed' ? 'done' : running ? 'active' : 'pending', summary: 'Every action is logged' },
  ]
}

const STATE_STYLE: Record<State, string> = {
  done: 'bg-success text-white', warn: 'bg-warning text-[oklch(0.25_0.06_60)]', fail: 'bg-destructive text-white',
  active: 'bg-primary text-primary-foreground', pending: 'bg-muted text-muted-foreground', skipped: 'bg-muted text-muted-foreground',
}

function StateIcon({ state }: { state: State }) {
  if (state === 'active') return <Loader2 className="size-3.5 animate-spin" />
  if (state === 'fail') return <XCircle className="size-3.5" />
  if (state === 'pending' || state === 'skipped') return <CircleDashed className="size-3.5" />
  return <CheckCircle2 className="size-3.5" />
}

export function PipelineTracker({ complaint, onSelect }: { complaint: ComplaintDetail; onSelect: (tab: string) => void }) {
  const steps = buildSteps(complaint)
  return (
    <nav aria-label="Complaint progress" className="rounded-xl border bg-card p-3 shadow-xs">
      <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
        {steps.map((s, i) => (
          <motion.li key={s.key} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }} className="min-w-0">
            <Tooltip content={s.summary}>
              <button
                type="button"
                onClick={() => onSelect(s.tab)}
                className={cn('group relative flex w-full items-start gap-2.5 rounded-lg p-2 text-left transition-colors hover:bg-accent/60', s.state === 'skipped' && 'opacity-60')}
              >
                <span className={cn('mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full shadow-sm', STATE_STYLE[s.state])}>
                  <s.icon className="size-3.5" aria-hidden />
                </span>
                <span className="min-w-0">
                  <span className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide">
                    {s.label}
                    <span className={cn(s.state === 'done' ? 'text-success' : s.state === 'fail' ? 'text-destructive' : s.state === 'warn' ? 'text-warning' : 'text-muted-foreground')}>
                      <StateIcon state={s.state} />
                    </span>
                  </span>
                  <span className="text-muted-foreground block truncate text-[11.5px] leading-snug">{s.summary}</span>
                </span>
              </button>
            </Tooltip>
          </motion.li>
        ))}
      </ol>
    </nav>
  )
}
