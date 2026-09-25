/* Small presentational pieces shared by the knowledge-base pages (and the Rule Matrix):
   document status / type / format badges, policy-reference links and safe text rendering.
   Document text is always rendered as plain text - never as HTML. */
import { Archive, CalendarClock, CheckCircle2, FilePen, History, TimerOff } from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router'

import { DOC_TYPE_LABEL, documentHref, parsePolicyRef, type TextSpan } from '@/components/knowledge/model'
import { Tooltip } from '@/components/ui/overlays'
import { Badge } from '@/components/ui/primitives'
import { cn, titleCase } from '@/lib/utils'

type Variant = 'default' | 'secondary' | 'outline' | 'success' | 'warning' | 'destructive' | 'info' | 'primary' | 'validate' | 'muted'

const DOC_STATUS: Record<string, { v: Variant; icon: React.ElementType; tip: string }> = {
  Active: { v: 'success', icon: CheckCircle2, tip: 'In effect and used as evidence (PRC-001).' },
  Pending: { v: 'info', icon: CalendarClock, tip: 'Not in effect yet, so not used as evidence.' },
  Expired: { v: 'destructive', icon: TimerOff, tip: 'Past its expiry date; treated as outdated (PRC-004).' },
  Previous: { v: 'muted', icon: History, tip: 'Replaced by a newer version; context only (PRC-004).' },
  Superseded: { v: 'destructive', icon: Archive, tip: 'Formally replaced; never used as evidence (PRC-004).' },
  Draft: { v: 'warning', icon: FilePen, tip: 'Not approved yet, so not used as evidence.' },
}

/** Version status / effective state: Active, Pending, Expired, Previous, Superseded, Draft. */
export function DocStatusBadge({ status, className, tooltip = true }: { status?: string | null; className?: string; tooltip?: boolean }) {
  if (!status) return null
  const cfg = DOC_STATUS[status] ?? { v: 'outline' as Variant, icon: CheckCircle2, tip: status }
  const Icon = cfg.icon
  const badge = (
    <Badge variant={cfg.v} className={className}>
      <Icon aria-hidden />
      {status}
    </Badge>
  )
  return tooltip ? <Tooltip content={cfg.tip}>{badge}</Tooltip> : badge
}

const DOC_TYPE_VARIANT: Record<string, Variant> = { policy: 'primary', rules: 'primary', sop: 'info', guideline: 'validate', faq: 'secondary', template: 'muted' }

/** Document type with its precedence rank (1 = strongest). */
export function DocTypeBadge({ type, rank, className }: { type?: string | null; rank?: number | null; className?: string }) {
  if (!type) return null
  return (
    <Badge variant={DOC_TYPE_VARIANT[type] ?? 'outline'} className={className}>
      {DOC_TYPE_LABEL[type] ?? titleCase(type)}
      {rank ? <span className="opacity-70 tabular-nums">· rank {rank}</span> : null}
    </Badge>
  )
}

export function FormatBadge({ format, className }: { format?: string | null; className?: string }) {
  if (!format) return null
  return (
    <Badge variant="outline" className={cn('px-1.5 py-0 font-mono text-[10px] uppercase', className)}>
      {format}
    </Badge>
  )
}

/** "REF-POL-02:3.1" rendered as a link to that section of the document. */
export function PolicyRefLink({ policyRef, version, className }: { policyRef: string; version?: string | null; className?: string }) {
  const { docId, section } = parsePolicyRef(policyRef)
  if (!docId) return null
  return (
    <Link
      to={documentHref(docId, { version, section })}
      className={cn('text-primary font-mono text-xs font-medium whitespace-nowrap hover:underline', className)}
      title={`Open ${docId}${section ? ` section ${section}` : ''}`}
    >
      {docId}
      {section ? <span className="opacity-80"> §{section}</span> : null}
      {version ? <span className="text-muted-foreground"> v{version}</span> : null}
    </Link>
  )
}

export function PolicyRefList({ refs, max = 3, className }: { refs?: string[] | null; max?: number; className?: string }) {
  const list = refs ?? []
  if (!list.length) return <span className="text-muted-foreground text-xs">—</span>
  const shown = list.slice(0, max)
  const rest = list.slice(max)
  return (
    <span className={cn('flex flex-wrap items-center gap-x-2 gap-y-0.5', className)}>
      {shown.map((r) => (
        <PolicyRefLink key={r} policyRef={r} />
      ))}
      {rest.length ? (
        <Tooltip content={rest.join(', ')}>
          <span className="text-muted-foreground cursor-default text-xs" tabIndex={0}>
            +{rest.length}
          </span>
        </Tooltip>
      ) : null}
    </span>
  )
}

/** Plain text with flagged spans wrapped in <mark>. Built from string slices - no HTML is interpreted. */
export function HighlightedText({ text, spans }: { text: string; spans: TextSpan[] }) {
  if (!spans.length) return <>{text}</>
  const parts: React.ReactNode[] = []
  let cursor = 0
  spans.forEach((s, i) => {
    if (s.start < cursor) return
    if (s.start > cursor) parts.push(text.slice(cursor, s.start))
    parts.push(
      <mark
        key={i}
        title={s.label}
        className={cn(
          'rounded-sm px-0.5 font-medium',
          s.tone === 'destructive' ? 'bg-destructive/15 text-destructive decoration-destructive/60 underline decoration-wavy underline-offset-2' : 'bg-warning/25 text-foreground',
        )}
      >
        {text.slice(s.start, s.end)}
      </mark>,
    )
    cursor = s.end
  })
  if (cursor < text.length) parts.push(text.slice(cursor))
  return <>{parts}</>
}

const CLAMP: Record<number, string> = { 2: 'line-clamp-2', 3: 'line-clamp-3', 4: 'line-clamp-4', 6: 'line-clamp-6' }

/** Long plain text clamped to a few lines with a "Show more" toggle. */
export function ExpandableText({ text, lines = 4, className, children }: { text: string; lines?: 2 | 3 | 4 | 6; className?: string; children?: React.ReactNode }) {
  const [open, setOpen] = React.useState(false)
  const long = text.length > lines * 95 || text.split('\n').length > lines
  return (
    <div className={className}>
      <p className={cn('text-sm leading-relaxed break-words whitespace-pre-line', !open && long && CLAMP[lines])}>{children ?? text}</p>
      {long ? (
        <button type="button" className="text-primary mt-1 text-xs font-medium hover:underline" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? 'Show less' : 'Show more'}
        </button>
      ) : null}
    </div>
  )
}
