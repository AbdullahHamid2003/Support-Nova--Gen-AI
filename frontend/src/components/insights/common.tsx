/* Building blocks shared by the insight & quality pages: download buttons, run status, rate bars,
   metric tiles, info tips and a small segmented toggle. */
import { CheckCircle2, CircleDashed, CircleSlash, FileSpreadsheet, FileText, Info, Loader2, OctagonX, PauseCircle } from 'lucide-react'
import * as React from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Tooltip } from '@/components/ui/overlays'
import { Badge } from '@/components/ui/primitives'
import { rateColor } from '@/components/insights/format'
import { download, errorMessage } from '@/lib/api'
import { cn, pct } from '@/lib/utils'

type BadgeVariant = NonNullable<React.ComponentProps<typeof Badge>['variant']>
type DownloadQuery = Record<string, string | number | boolean | null | undefined>

const FORMAT_NAMES: Record<string, string> = { csv: 'CSV', xlsx: 'Excel', pdf: 'PDF', json: 'JSON' }
const FORMAT_ICONS: Record<string, React.ElementType> = { csv: FileText, xlsx: FileSpreadsheet, pdf: FileText, json: FileText }

/** One button per export format; each calls `download()` with the session cookie. */
export function DownloadButtons({ path, query, formats = ['csv', 'xlsx', 'pdf'], label, size = 'sm', disabled, className }: {
  path: string
  query?: DownloadQuery
  formats?: string[]
  /** What is being downloaded, used for accessible names and toasts. */
  label?: string
  size?: 'sm' | 'default'
  disabled?: boolean
  className?: string
}) {
  const [busy, setBusy] = React.useState<string | null>(null)
  const run = async (format: string) => {
    setBusy(format)
    try {
      await download(path, { ...query, format })
      toast.success(`${label ?? 'Export'} downloaded (${FORMAT_NAMES[format] ?? format.toUpperCase()})`)
    } catch (e) {
      toast.error(errorMessage(e))
    } finally {
      setBusy(null)
    }
  }
  return (
    <div role="group" aria-label={label ? `Download ${label}` : 'Download'} className={cn('flex flex-wrap items-center gap-1.5', className)}>
      {formats.map((f) => {
        const Icon = FORMAT_ICONS[f] ?? FileText
        const name = FORMAT_NAMES[f] ?? f.toUpperCase()
        return (
          <Button
            key={f}
            type="button"
            variant="outline"
            size={size}
            disabled={disabled || busy !== null}
            onClick={() => run(f)}
            aria-label={label ? `Download ${label} as ${name}` : `Download as ${name}`}
          >
            {busy === f ? <Loader2 className="animate-spin" aria-hidden /> : <Icon aria-hidden />}
            {name}
          </Button>
        )
      })}
    </div>
  )
}

const RUN_STATUS: Record<string, { variant: BadgeVariant; icon: React.ElementType; label: string; tip: string; spin?: boolean }> = {
  queued: { variant: 'muted', icon: CircleDashed, label: 'Queued', tip: 'Waiting to start.' },
  running: { variant: 'info', icon: Loader2, label: 'Running', tip: 'Processing cases one at a time.', spin: true },
  completed: { variant: 'success', icon: CheckCircle2, label: 'Completed', tip: 'Every case was processed and the metrics are final.' },
  cancelled: { variant: 'muted', icon: PauseCircle, label: 'Cancelled', tip: 'Stopped early; metrics cover the processed cases only.' },
  failed: { variant: 'destructive', icon: OctagonX, label: 'Failed', tip: 'The run stopped with an error.' },
  interrupted: { variant: 'warning', icon: CircleSlash, label: 'Interrupted', tip: 'The server stopped during the run. Start a new run.' },
}

export function RunStatusBadge({ status, className }: { status: string; className?: string }) {
  const cfg = RUN_STATUS[status] ?? { variant: 'outline' as BadgeVariant, icon: CircleDashed, label: status, tip: status }
  const Icon = cfg.icon
  return (
    <Tooltip content={cfg.tip}>
      <Badge variant={cfg.variant} className={className}>
        <Icon className={cfg.spin ? 'animate-spin' : undefined} aria-hidden />
        {cfg.label}
      </Badge>
    </Tooltip>
  )
}

/** Compact inline bar with a percentage, for tables. */
export function RateBar({ value, color, className, digits = 1, label }: { value: number | null | undefined; color?: string; className?: string; digits?: number; label?: string }) {
  if (value === null || value === undefined || Number.isNaN(value)) return <span className="text-muted-foreground text-xs">—</span>
  const width = Math.max(2, Math.min(100, value * 100))
  return (
    <div className={cn('flex min-w-[7.5rem] items-center gap-2', className)} title={label ? `${label}: ${pct(value, digits)}` : undefined}>
      <div className="bg-muted h-1.5 flex-1 overflow-hidden rounded-full" aria-hidden>
        <div className="h-full rounded-full transition-[width] duration-700" style={{ width: `${width}%`, background: color ?? rateColor(value) }} />
      </div>
      <span className="w-12 shrink-0 text-right text-xs tabular-nums">{pct(value, digits)}</span>
    </div>
  )
}

/** Small "what does this mean?" tooltip trigger placed next to a metric or heading. */
export function InfoTip({ children, label = 'What does this mean?', className }: { children: React.ReactNode; label?: string; className?: string }) {
  return (
    <Tooltip content={children}>
      <button
        type="button"
        aria-label={label}
        className={cn('text-muted-foreground hover:text-foreground focus-visible:ring-ring/40 inline-flex size-4 shrink-0 items-center justify-center rounded-full align-middle focus-visible:ring-2 focus-visible:outline-none', className)}
      >
        <Info className="size-3.5" aria-hidden />
      </button>
    </Tooltip>
  )
}

type Tone = 'default' | 'success' | 'warning' | 'destructive' | 'primary' | 'validate' | 'info'
const TONE_TEXT: Record<Tone, string> = {
  default: '',
  success: 'text-success',
  warning: 'text-[oklch(0.5_0.13_60)] dark:text-warning',
  destructive: 'text-destructive',
  primary: 'text-primary',
  validate: 'text-validate',
  info: 'text-info',
}

/** Light metric tile for use inside cards (StatCard is the standalone version). */
export function Metric({ label, value, hint, tone = 'default', info, className }: {
  label: React.ReactNode
  value: React.ReactNode
  hint?: React.ReactNode
  tone?: Tone
  info?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('bg-muted/35 min-w-0 rounded-lg border px-3 py-2.5', className)}>
      <div className="text-muted-foreground flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide">
        <span className="truncate">{label}</span>
        {info ? <InfoTip>{info}</InfoTip> : null}
      </div>
      <div className={cn('mt-1 text-lg leading-tight font-semibold tabular-nums', TONE_TEXT[tone])}>{value}</div>
      {hint ? <div className="text-muted-foreground mt-0.5 text-xs">{hint}</div> : null}
    </div>
  )
}

/** Two-to-four option toggle (aria-pressed buttons in a labelled group). */
export function Segmented<T extends string>({ value, onChange, options, label, className }: {
  value: T
  onChange: (value: T) => void
  options: { value: T; label: React.ReactNode }[]
  label: string
  className?: string
}) {
  return (
    <div role="group" aria-label={label} className={cn('bg-muted inline-flex shrink-0 items-center rounded-lg p-0.5', className)}>
      {options.map((o) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(o.value)}
            className={cn(
              'focus-visible:ring-ring/40 cursor-pointer rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none',
              active ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
