import { AlertCircle, ChevronLeft, ChevronRight, Copy, Download, FileSpreadsheet, FileText, Inbox, Loader2, RefreshCw } from 'lucide-react'
import * as React from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/overlays'
import { Alert, AlertDescription, AlertTitle, Card, CardContent, Skeleton } from '@/components/ui/primitives'
import { download, errorMessage } from '@/lib/api'
import { cn, display } from '@/lib/utils'

export function PageHeader({ title, description, actions, eyebrow }: { title: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode; eyebrow?: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-3 pb-6 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0 space-y-1">
        {eyebrow ? <div className="text-primary text-xs font-semibold uppercase tracking-[0.14em]">{eyebrow}</div> : null}
        <h1 className="text-2xl font-semibold tracking-tight text-balance sm:text-[1.7rem]">{title}</h1>
        {description ? <p className="text-muted-foreground max-w-3xl text-sm">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  )
}

export function StatCard({ label, value, hint, icon: Icon, tone = 'default', className }: {
  label: string
  value: React.ReactNode
  hint?: React.ReactNode
  icon?: React.ElementType
  tone?: 'default' | 'success' | 'warning' | 'destructive' | 'primary' | 'validate'
  className?: string
}) {
  const toneCls = {
    default: 'bg-muted text-muted-foreground', success: 'bg-success/12 text-success', warning: 'bg-warning/15 text-[oklch(0.5_0.13_60)] dark:text-warning',
    destructive: 'bg-destructive/10 text-destructive', primary: 'bg-primary/10 text-primary', validate: 'bg-validate/12 text-validate',
  }[tone]
  return (
    <Card className={cn('gap-2 py-4', className)}>
      <CardContent className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-muted-foreground text-xs font-medium uppercase tracking-wide">{label}</div>
          <div className="mt-1.5 text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
          {hint ? <div className="text-muted-foreground mt-1 text-xs">{hint}</div> : null}
        </div>
        {Icon ? (
          <div className={cn('flex size-9 shrink-0 items-center justify-center rounded-lg', toneCls)}>
            <Icon className="size-4.5" aria-hidden />
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

export function EmptyState({ title, description, icon: Icon = Inbox, action }: { title: string; description?: string; icon?: React.ElementType; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-6 py-12 text-center">
      <div className="bg-muted text-muted-foreground mb-1 flex size-11 items-center justify-center rounded-full">
        <Icon className="size-5" aria-hidden />
      </div>
      <div className="font-medium">{title}</div>
      {description ? <p className="text-muted-foreground max-w-md text-sm">{description}</p> : null}
      {action}
    </div>
  )
}

export function ErrorState({ error, onRetry, title = 'Could not load this data' }: { error: unknown; onRetry?: () => void; title?: string }) {
  return (
    <Alert variant="destructive">
      <AlertCircle />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <p>{errorMessage(error)}</p>
        {onRetry ? (
          <Button size="sm" variant="outline" className="mt-2 text-foreground" onClick={onRetry}>
            <RefreshCw /> Try again
          </Button>
        ) : null}
      </AlertDescription>
    </Alert>
  )
}

export function LoadingBlock({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn('space-y-3', className)} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" style={{ opacity: 1 - i * 0.12 }} />
      ))}
    </div>
  )
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn('size-4 animate-spin', className)} aria-hidden />
}

export function KeyValue({ items, columns = 2, className }: { items: [React.ReactNode, React.ReactNode][]; columns?: 1 | 2 | 3; className?: string }) {
  return (
    <dl className={cn('grid gap-x-6 gap-y-3', columns === 1 ? 'grid-cols-1' : columns === 2 ? 'grid-cols-1 sm:grid-cols-2' : 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3', className)}>
      {items.map(([k, v], i) => (
        <div key={i} className="min-w-0">
          <dt className="text-muted-foreground text-xs font-medium">{k}</dt>
          <dd className="mt-0.5 text-sm break-words">{typeof v === 'string' || typeof v === 'number' || v === null || v === undefined ? display(v) : v}</dd>
        </div>
      ))}
    </dl>
  )
}

export function SectionTitle({ children, icon: Icon, action }: { children: React.ReactNode; icon?: React.ElementType; action?: React.ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-2">
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        {Icon ? <Icon className="text-muted-foreground size-4" aria-hidden /> : null}
        {children}
      </h2>
      {action}
    </div>
  )
}

export function JsonView({ value, className }: { value: unknown; className?: string }) {
  return (
    <pre className={cn('bg-muted/60 max-h-[28rem] overflow-auto rounded-lg border p-3 font-mono text-[11.5px] leading-relaxed scrollbar-thin', className)}>
      {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
    </pre>
  )
}

export function CopyButton({ value, label = 'Copy' }: { value: string; label?: string }) {
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      aria-label={label}
      onClick={() => {
        navigator.clipboard?.writeText(value).then(() => toast.success('Copied to clipboard')).catch(() => toast.error('Copy failed'))
      }}
    >
      <Copy />
    </Button>
  )
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1
  const to = Math.min(total, page * pageSize)
  return (
    <div className="flex items-center justify-between gap-2 pt-3 text-sm">
      <span className="text-muted-foreground tabular-nums">
        {from}–{to} of {total.toLocaleString()}
      </span>
      <div className="flex items-center gap-1">
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page">
          <ChevronLeft /> Prev
        </Button>
        <span className="text-muted-foreground px-2 tabular-nums">
          {page} / {pages}
        </span>
        <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page">
          Next <ChevronRight />
        </Button>
      </div>
    </div>
  )
}

/** CSV / Excel / PDF export dropdown bound to an API endpoint that takes ?format=. */
export function ExportMenu({ path, query, label = 'Export', formats = ['csv', 'xlsx', 'pdf'] }: { path: string; query?: Record<string, unknown>; label?: string; formats?: string[] }) {
  const [busy, setBusy] = React.useState(false)
  const run = async (format: string) => {
    setBusy(true)
    try {
      await download(path, { ...(query as Record<string, string>), format })
      toast.success(`Export ready (${format.toUpperCase()})`)
    } catch (e) {
      toast.error(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  const icons: Record<string, React.ElementType> = { csv: FileText, xlsx: FileSpreadsheet, pdf: FileText, yaml: FileText }
  const names: Record<string, string> = { csv: 'CSV', xlsx: 'Excel (.xlsx)', pdf: 'PDF', yaml: 'YAML' }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" disabled={busy}>
          {busy ? <Spinner /> : <Download />} {label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {formats.map((f) => {
          const Icon = icons[f] ?? FileText
          return (
            <DropdownMenuItem key={f} onSelect={() => run(f)}>
              <Icon /> {names[f] ?? f}
            </DropdownMenuItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function Field({ label, htmlFor, error, hint, children, required }: { label: string; htmlFor?: string; error?: string; hint?: string; children: React.ReactNode; required?: boolean }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="text-sm font-medium">
        {label}
        {required ? <span className="text-destructive ml-0.5" aria-hidden>*</span> : null}
      </label>
      {children}
      {error ? (
        <p className="text-destructive text-xs" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="text-muted-foreground text-xs">{hint}</p>
      ) : null}
    </div>
  )
}
