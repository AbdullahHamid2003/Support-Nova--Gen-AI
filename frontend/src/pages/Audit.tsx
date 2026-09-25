/* Immutable audit log: append-only (PostgreSQL trigger) and hash-chained. Every sign-in, complaint
   decision, review, export, rule change, evaluation and lab run is recorded here. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, ChevronDown, ChevronRight, Filter, RotateCcw, ScrollText, Search, ShieldCheck, ShieldX } from 'lucide-react'
import * as React from 'react'
import { Link, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { BarList } from '@/components/app/charts'
import { CopyButton, EmptyState, ErrorState, ExportMenu, JsonView, LoadingBlock, PageHeader, Pagination, Spinner } from '@/components/app/common'
import { humanize, shortHash } from '@/components/insights/format'
import { Button } from '@/components/ui/button'
import {
  Alert, AlertDescription, AlertTitle, Badge, Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle, Input, Label, NativeSelect,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/primitives'
import { api, errorMessage } from '@/lib/api'
import { ROLE_LABELS, useAuth } from '@/lib/auth'
import { fmtDateTime, fmtRelative } from '@/lib/format'
import type { AuditEntry, Role } from '@/lib/types'
import { cn, num } from '@/lib/utils'

interface AuditPageData { items: AuditEntry[]; total: number; page: number; page_size: number; actions: { action: string; count: number }[] }
interface VerifyResult { valid: boolean; checked: number; broken_at_id: number | null; message: string }

type BadgeVariant = NonNullable<React.ComponentProps<typeof Badge>['variant']>

const PAGE_SIZE = 50
const FILTER_KEYS = ['action', 'entity_type', 'entity_id', 'actor', 'date_from', 'date_to'] as const
const ENTITY_TYPES = [
  'complaint', 'review', 'report', 'evaluation_run', 'user', 'document', 'rule', 'rule_parameter', 'rules', 'prompt', 'dataset',
  'category', 'subcategory', 'department', 'endpoint', 'audit',
]

function actionVariant(action: string): BadgeVariant {
  if (action === 'auth.login_failed' || action === 'access.denied' || action.endsWith('_failed') || action.includes('breach')) return 'destructive'
  if (action.startsWith('auth.')) return 'info'
  if (action.startsWith('complaint.')) return 'primary'
  if (action.startsWith('review.')) return 'validate'
  if (action.startsWith('evaluation.') || action.startsWith('lab.')) return 'warning'
  if (action.startsWith('report.') || action.startsWith('audit.')) return 'secondary'
  return 'outline'
}

function entityHref(type: string, id: string): string | null {
  if (type === 'complaint' && id) return `/complaints/${id}`
  if (type === 'evaluation_run' && /^\d+$/.test(id)) return `/evaluation/${id}`
  return null
}

function roleLabel(role: string | null): string {
  if (!role) return '—'
  return role in ROLE_LABELS ? ROLE_LABELS[role as Role] : humanize(role)
}

export default function AuditPage() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const full = can('audit:read')
  const [params, setParams] = useSearchParams()
  const [entityId, setEntityId] = React.useState(params.get('entity_id') ?? '')
  const [actor, setActor] = React.useState(params.get('actor') ?? '')
  const [open, setOpen] = React.useState<number | null>(null)

  const filters = React.useMemo(() => {
    const out: Record<string, string> = {}
    for (const k of FILTER_KEYS) {
      const v = params.get(k)
      if (v) out[k] = v
    }
    return out
  }, [params])
  const page = Math.max(1, Number(params.get('page') ?? 1) || 1)
  const activeCount = Object.keys(filters).length
  const rangeInvalid = !!filters.date_from && !!filters.date_to && filters.date_from > filters.date_to

  const log = useQuery({
    queryKey: ['audit', 'log', filters, page],
    queryFn: () => api.get<AuditPageData>('/audit', { ...filters, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
    enabled: !rangeInvalid,
  })
  // Unfiltered action list, so the action picker keeps every option while a filter is applied.
  const allActions = useQuery({
    queryKey: ['audit', 'actions'],
    queryFn: () => api.get<AuditPageData>('/audit', { page_size: 1 }),
    staleTime: 60_000,
  })
  const verify = useMutation({
    mutationFn: () => api.get<VerifyResult>('/audit/verify'),
    onSuccess: (r) => {
      if (r.valid) toast.success(`Audit chain intact — ${num(r.checked)} entries verified`)
      else toast.error(`Audit chain broken at entry #${r.broken_at_id}`)
      qc.invalidateQueries({ queryKey: ['audit'] })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    if (!('page' in changes)) next.delete('page')
    setParams(next, { replace: true })
  }
  const reset = () => {
    setEntityId('')
    setActor('')
    setParams(new URLSearchParams(), { replace: true })
  }

  const actionOptions = allActions.data?.actions ?? []
  const prefixes = [...new Set(actionOptions.map((a) => a.action.split('.')[0]).filter((p) => actionOptions.some((a) => a.action.startsWith(`${p}.`))))].sort()
  const breakdown = (log.data?.actions ?? []).slice(0, 8)
  const exportQuery = { ...filters }

  return (
    <>
      <PageHeader
        eyebrow="Governance"
        title="Audit log"
        description="A permanent record of sign-ins, decisions, reviews, exports and rule changes."
        actions={full ? <ExportMenu path="/audit/export" query={exportQuery} label="Export log" /> : null}
      />

      {!full ? (
        <Alert variant="info" className="mb-6">
          <ScrollText />
          <AlertTitle>Complaint trail view</AlertTitle>
          <AlertDescription>
            <p>You see complaint, review, report and evaluation entries. Only administrators can see, export or verify the full log.</p>
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Chain integrity</CardTitle>
            <CardDescription>Checks that no audit entry was changed or deleted.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {verify.data ? (
              verify.data.valid ? (
                <div className="border-success/30 bg-success/8 rounded-xl border p-4" role="status">
                  <div className="text-success flex items-center gap-2 text-lg font-semibold"><ShieldCheck className="size-5" aria-hidden /> Chain intact</div>
                  <div className="mt-1 text-2xl font-semibold tabular-nums">{num(verify.data.checked)}</div>
                  <div className="text-muted-foreground text-xs">entries verified · no break found</div>
                </div>
              ) : (
                <div className="border-destructive/30 bg-destructive/8 rounded-xl border p-4" role="alert">
                  <div className="text-destructive flex items-center gap-2 text-lg font-semibold"><ShieldX className="size-5" aria-hidden /> Chain broken</div>
                  <div className="mt-1 text-2xl font-semibold tabular-nums">entry #{verify.data.broken_at_id}</div>
                  <div className="text-muted-foreground text-xs">{num(verify.data.checked)} entries verified before the break · {verify.data.message}</div>
                </div>
              )
            ) : (
              <div className="bg-muted/40 text-muted-foreground rounded-xl border border-dashed p-4 text-sm">
                {full ? 'Not verified in this session yet.' : 'Only administrators can verify the log.'}
              </div>
            )}
            {full ? (
              <Button onClick={() => verify.mutate()} disabled={verify.isPending} className="w-full">
                {verify.isPending ? <Spinner /> : <ShieldCheck />} Verify chain integrity
              </Button>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5"><Activity className="text-muted-foreground size-4" aria-hidden /> Activity in this view</CardTitle>
            <CardDescription>{log.data ? `${num(log.data.total)} entries match` : 'Loading…'}{activeCount ? ' the current filters' : ''}</CardDescription>
          </CardHeader>
          <CardContent>
            {breakdown.length ? (
              <BarList items={breakdown.map((a) => ({ label: a.action, value: a.count }))} />
            ) : log.isLoading ? (
              <LoadingBlock rows={4} />
            ) : (
              <p className="text-muted-foreground text-sm">No entries.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-6 gap-3 py-4">
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Filter className="text-muted-foreground size-4" aria-hidden /> Filters
            {activeCount ? <Badge variant="primary">{activeCount} active</Badge> : null}
          </div>
          <form
            className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-[repeat(6,minmax(0,1fr))_auto] xl:items-end"
            role="search"
            onSubmit={(e) => {
              e.preventDefault()
              update({ entity_id: entityId.trim() || null, actor: actor.trim() || null })
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="au-action">Action</Label>
              <NativeSelect id="au-action" value={filters.action ?? ''} onChange={(e) => update({ action: e.target.value || null })}>
                <option value="">All actions</option>
                {prefixes.map((p) => (
                  <optgroup key={p} label={humanize(p)}>
                    <option value={`${p}.`}>All {humanize(p).toLowerCase()} actions</option>
                    {actionOptions.filter((a) => a.action.startsWith(`${p}.`)).map((a) => (
                      <option key={a.action} value={a.action}>{a.action} ({num(a.count)})</option>
                    ))}
                  </optgroup>
                ))}
                {actionOptions.filter((a) => !a.action.includes('.')).map((a) => (
                  <option key={a.action} value={a.action}>{a.action} ({num(a.count)})</option>
                ))}
              </NativeSelect>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="au-type">Entity type</Label>
              <NativeSelect id="au-type" value={filters.entity_type ?? ''} onChange={(e) => update({ entity_type: e.target.value || null })}>
                <option value="">All entities</option>
                {ENTITY_TYPES.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
              </NativeSelect>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="au-entity">Entity ID</Label>
              <Input id="au-entity" value={entityId} onChange={(e) => setEntityId(e.target.value)} placeholder="CMP-00042, 1, …" className="font-mono" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="au-actor">Actor</Label>
              <Input id="au-actor" value={actor} onChange={(e) => setActor(e.target.value)} placeholder="Name, email or role" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="au-from">From</Label>
              <Input id="au-from" type="date" value={filters.date_from ?? ''} max={filters.date_to} onChange={(e) => update({ date_from: e.target.value || null })} aria-invalid={rangeInvalid} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="au-to">To</Label>
              <Input id="au-to" type="date" value={filters.date_to ?? ''} min={filters.date_from} onChange={(e) => update({ date_to: e.target.value || null })} aria-invalid={rangeInvalid} />
            </div>
            <div className="flex gap-2">
              <Button type="submit" variant="secondary"><Search /> Apply</Button>
              <Button type="button" variant="ghost" onClick={reset} disabled={!activeCount && !entityId && !actor}><RotateCcw /> Reset</Button>
            </div>
          </form>
          {rangeInvalid ? <p className="text-destructive text-xs" role="alert">The “from” date must be on or before the “to” date.</p> : <p className="text-muted-foreground text-xs">Press Enter or Apply to search by entity ID or actor.</p>}
        </CardContent>
      </Card>

      <Card className="mt-4 py-0">
        <CardHeader className="pt-5">
          <CardTitle>Entries</CardTitle>
          <CardDescription>Newest first. Expand an entry to see its details.</CardDescription>
          <CardAction>{log.isFetching && !log.isLoading ? <Spinner className="text-muted-foreground" /> : null}</CardAction>
        </CardHeader>
        <CardContent className="px-0 pb-2">
          {log.isLoading ? (
            <div className="px-5 pb-4"><LoadingBlock rows={8} /></div>
          ) : log.error ? (
            <div className="px-5 pb-4"><ErrorState error={log.error} onRetry={() => log.refetch()} /></div>
          ) : !log.data || log.data.items.length === 0 ? (
            <div className="px-5 pb-4">
              <EmptyState icon={ScrollText} title="No audit entries match" description={activeCount ? 'Try removing a filter.' : 'Entries appear as soon as anyone uses the system.'} />
            </div>
          ) : (
            <Table className={cn(log.isPlaceholderData && 'opacity-60')}>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8 pl-4"><span className="sr-only">Details</span></TableHead>
                  <TableHead>#</TableHead>
                  <TableHead>When</TableHead>
                  <TableHead>Actor</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Entity</TableHead>
                  <TableHead className="min-w-64">Summary</TableHead>
                  <TableHead className="pr-5">Fingerprint</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {log.data.items.map((a) => (
                  <AuditRows key={a.id} entry={a} open={open === a.id} onToggle={() => setOpen(open === a.id ? null : a.id)} />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      {log.data && log.data.total > 0 ? <Pagination page={page} pageSize={PAGE_SIZE} total={log.data.total} onPage={(p) => update({ page: String(p) })} /> : null}
    </>
  )
}

function AuditRows({ entry: a, open, onToggle }: { entry: AuditEntry; open: boolean; onToggle: () => void }) {
  const href = entityHref(a.entity_type, a.entity_id)
  const detailId = `audit-${a.id}`
  const hasDetails = a.details && Object.keys(a.details).length > 0
  return (
    <>
      <TableRow data-state={open ? 'selected' : undefined}>
        <TableCell className="pl-4">
          <Button variant="ghost" size="icon-sm" onClick={onToggle} aria-expanded={open} aria-controls={detailId} aria-label={`${open ? 'Hide' : 'Show'} details of audit entry ${a.id}`}>
            {open ? <ChevronDown /> : <ChevronRight />}
          </Button>
        </TableCell>
        <TableCell className="text-muted-foreground font-mono text-xs tabular-nums">{a.id}</TableCell>
        <TableCell className="text-sm whitespace-nowrap">
          <div>{fmtDateTime(a.at)}</div>
          <div className="text-muted-foreground text-xs">{fmtRelative(a.at)}</div>
        </TableCell>
        <TableCell className="max-w-[14rem] text-sm">
          <div className="truncate" title={a.actor}>{a.actor}</div>
          <div className="text-muted-foreground text-xs">{roleLabel(a.role)}</div>
        </TableCell>
        <TableCell><Badge variant={actionVariant(a.action)} className="font-mono text-[11px]">{a.action}</Badge></TableCell>
        <TableCell className="text-sm whitespace-nowrap">
          <div className="text-muted-foreground text-xs">{humanize(a.entity_type)}</div>
          {href ? (
            <Link to={href} className="text-primary font-mono text-xs font-semibold hover:underline">{a.entity_id}</Link>
          ) : (
            <span className="font-mono text-xs">{a.entity_id || '—'}</span>
          )}
        </TableCell>
        <TableCell className="max-w-[28rem] text-sm whitespace-normal">{a.summary || <span className="text-muted-foreground">—</span>}</TableCell>
        <TableCell className="pr-5">
          <div className="flex items-center gap-0.5">
            <code className="text-muted-foreground font-mono text-xs" title={a.hash}>{shortHash(a.hash)}</code>
            <CopyButton value={a.hash} label={`Copy fingerprint of entry ${a.id}`} />
          </div>
        </TableCell>
      </TableRow>
      {open ? (
        <TableRow className="bg-muted/25 hover:bg-muted/25">
          <TableCell colSpan={8} className="p-0">
            <div id={detailId} className="grid gap-4 px-5 py-4 lg:grid-cols-2">
              <div className="space-y-3">
                <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
                  <div>
                    <dt className="text-muted-foreground text-xs font-medium">Request ID</dt>
                    <dd className="font-mono text-xs">{a.request_id ?? '—'}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground text-xs font-medium">IP address</dt>
                    <dd className="font-mono text-xs">{a.ip_address ?? '—'}</dd>
                  </div>
                </dl>
                <div>
                  <div className="text-muted-foreground text-xs font-medium">Fingerprint</div>
                  <div className="flex items-start gap-1">
                    <code className="font-mono text-xs break-all">{a.hash}</code>
                    <CopyButton value={a.hash} label="Copy fingerprint" />
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground text-xs font-medium">Previous fingerprint</div>
                  <div className="flex items-start gap-1">
                    <code className="font-mono text-xs break-all">{a.prev_hash || 'None (first entry)'}</code>
                    {a.prev_hash ? <CopyButton value={a.prev_hash} label="Copy previous fingerprint" /> : null}
                  </div>
                </div>
              </div>
              <div>
                <div className="text-muted-foreground mb-1 text-xs font-medium">Details</div>
                {hasDetails ? <JsonView value={a.details} className="max-h-72" /> : <p className="text-muted-foreground text-sm">No additional details recorded.</p>}
              </div>
            </div>
          </TableCell>
        </TableRow>
      ) : null}
    </>
  )
}
