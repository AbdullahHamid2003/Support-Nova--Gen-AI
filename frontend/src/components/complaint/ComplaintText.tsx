/* Renders complaint text as plain text (never HTML) and highlights spans the injection screener flagged. */
import { ShieldAlert } from 'lucide-react'
import type * as React from 'react'

import { Tooltip } from '@/components/ui/overlays'

interface Finding { type: string; severity: string; text: string; start: number; end: number; description: string }

export function ComplaintText({ text, findings }: { text: string; findings?: Finding[] }) {
  const flagged = (findings ?? []).filter((f) => f.text && f.end > f.start)
  if (!flagged.length) return <p className="text-[14.5px] leading-relaxed whitespace-pre-wrap">{text}</p>
  // positions refer to the normalised title + description; locate every occurrence of each flagged snippet in
  // the displayed text instead (whitespace-tolerant: normalisation collapses line breaks inside a span)
  const marks: { start: number; end: number; f: Finding }[] = []
  for (const f of flagged) {
    const pattern = f.text.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+')
    if (!pattern) continue
    for (const m of text.matchAll(new RegExp(pattern, 'gi'))) {
      const start = m.index, end = m.index + m[0].length
      if (!marks.some((x) => start < x.end && end > x.start)) marks.push({ start, end, f })
    }
  }
  marks.sort((a, b) => a.start - b.start)
  const parts: React.ReactNode[] = []
  let cursor = 0
  marks.forEach((m, i) => {
    if (m.start > cursor) parts.push(text.slice(cursor, m.start))
    parts.push(
      <Tooltip key={i} content={`${m.f.type.replace(/_/g, ' ')} (${m.f.severity}): ${m.f.description}`}>
        <mark className="bg-destructive/12 text-destructive decoration-destructive/60 rounded px-0.5 underline decoration-wavy underline-offset-4">
          <ShieldAlert className="mr-0.5 inline size-3.5 -translate-y-px" aria-hidden />
          {text.slice(m.start, m.end)}
        </mark>
      </Tooltip>,
    )
    cursor = m.end
  })
  if (cursor < text.length) parts.push(text.slice(cursor))
  return <p className="text-[14.5px] leading-relaxed whitespace-pre-wrap">{parts}</p>
}
