import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ArrowDownUp, Filter, Inbox, PlusCircle, RotateCcw, Search, ShieldAlert } from 'lucide-react'
import * as React from 'react'
import { Link, useSearchParams } from 'react-router'

import { EmptyState, ErrorState, ExportMenu, LoadingBlock, PageHeader, Pagination } from '@/components/app/common'
import { EscalationBadge, PriorityBadge, SentimentText, SlaBadge, StatusBadge, UrgencyBadge, VerificationBadge } from '@/components/app/status'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger, Tooltip } from '@/components/ui/overlays'
import { Badge, Card, CardContent, Checkbox, Input, Label, NativeSelect, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/primitives'
import { api } from '@/lib/api'
import { useAuth, usePublicConfig } from '@/lib/auth'
import { fmtDate, fmtRelative } from '@/lib/format'
import type { ComplaintSummary, Page } from '@/lib/types'

const MULTI = ['status', 'category', 'department', 'priority', 'urgency', 'sentiment', 'verification', 'sla'] as const
const SINGLE = ['q', 'subcategory', 'channel', 'customer_ref', 'date_from', 'date_to', 'escalated', 'needs_review', 'repeat', 'duplicate', 'injection', 'assigned_to_me', 'source', 'sort', 'order', 'page'] as const

function MultiFilter({ label, options, value, onChange }: { label: string; options: { value: string; label: string }[]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className={value.length ? 'border-primary/50 bg-primary/5' : ''}>
          {label}
          {value.length ? <Badge variant="primary" className="ml-0.5 px-1.5 py-0">{value.length}</Badge> : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-2">
        <div className="max-h-72 space-y-0.5 overflow-y-auto scrollbar-thin" role="group" aria-label={label}>
          {options.map((o) => {
            const checked = value.includes(o.value)
            return (
              <label key={o.value} className="hover:bg-accent flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm">
                <Checkbox checked={checked} onCheckedChange={(c) => onChange(c ? [...value, o.value] : value.filter((x) => x !== o.value))} />
                <span className="truncate">{o.label}</span>
              </label>
            )
          })}
        </div>
        {value.length ? (
          <Button variant="ghost" size="sm" className="mt-1 w-full" onClick={() => onChange([])}>
            Clear
          </Button>
        ) : null}
      </PopoverContent>
    </Popover>
  )
}

export default function ComplaintsPage() {
  const { session, can } = useAuth()
  const internal = session!.user.role !== 'customer'
  const config = usePublicConfig()
  const [params, setParams] = useSearchParams()
  const [q, setQ] = React.useState(params.get('q') ?? '')

  const query = React.useMemo(() => {
    const out: Record<string, string | string[]> = {}
    for (const k of MULTI) {
      const v = params.getAll(k)
      if (v.length) out[k] = v
    }
    for (const k of SINGLE) {
      const v = params.get(k)
      if (v) out[k] = v
    }
    return out
  }, [params])
  const page = Number(params.get('page') ?? 1)

  const list = useQuery({
    queryKey: ['complaints', query],
    queryFn: () => api.get<Page<ComplaintSummary>>('/complaints', { ...query, page, page_size: 25 }),
    placeholderData: keepPreviousData,
    refetchInterval: 15_000,
  })

  const update = (changes: Record<string, string | string[] | null>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(changes)) {
      next.delete(k)
      if (Array.isArray(v)) v.forEach((x) => next.append(k, x))
      else if (v) next.set(k, v)
    }
    if (!('page' in changes)) next.delete('page')
    setParams(next, { replace: true })
  }

  const cfg = config.data
  const opts = {
    status: (cfg?.statuses ?? []).map((s) => ({ value: s, label: s })),
    category: (cfg?.categories ?? []).map((c) => ({ value: c.code, label: c.name })),
    department: (cfg?.departments ?? []).map((d) => ({ value: d.code, label: d.name })),
    priority: ['P0', 'P1', 'P2', 'P3'].map((p) => ({ value: p, label: p })),
    urgency: ['Critical', 'High', 'Medium', 'Low'].map((p) => ({ value: p, label: p })),
    sentiment: ['Strongly Negative', 'Negative', 'Neutral', 'Positive', 'Mixed'].map((p) => ({ value: p, label: p })),
    verification: (cfg?.verification_statuses ?? []).map((s) => ({ value: s, label: s })),
    sla: ['On Track', 'At Risk', 'Breached', 'Met'].map((s) => ({ value: s, label: s })),
  }
  const activeCount = Object.keys(query).filter((k) => !['sort', 'order', 'page'].includes(k)).length

  return (
    <>
      <PageHeader
        eyebrow={internal ? 'Complaints' : 'Customer portal'}
        title={internal ? 'All complaints' : 'My complaints'}
        description={internal ? 'Search and filter all complaints.' : 'Everything you have reported to Lumora and where it stands.'}
        actions={
          <>
            {internal && can('reports:export') ? <ExportMenu path="/complaints-export" query={query} /> : null}
            {can('complaint:create') ? (
              <Button asChild size="sm">
                <Link to="/complaints/new"><PlusCircle /> New complaint</Link>
              </Button>
            ) : null}
          </>
        }
      />
      <Card className="gap-3 py-4">
        <CardContent className="space-y-3">
          <form
            className="flex flex-col gap-2 sm:flex-row"
            role="search"
            onSubmit={(e) => {
              e.preventDefault()
              update({ q: q.trim() || null })
            }}
          >
            <div className="relative flex-1">
              <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" aria-hidden />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={internal ? 'Complaint ID, customer reference or name, order number, title…' : 'Search your complaints'} className="pl-8" aria-label="Search" />
            </div>
            <Button type="submit" variant="secondary">Search</Button>
          </form>
          {internal ? (
            <div className="flex flex-wrap items-center gap-2">
              <Filter className="text-muted-foreground size-4" aria-hidden />
              <MultiFilter label="Status" options={opts.status} value={params.getAll('status')} onChange={(v) => update({ status: v })} />
              <MultiFilter label="Category" options={opts.category} value={params.getAll('category')} onChange={(v) => update({ category: v })} />
              <MultiFilter label="Department" options={opts.department} value={params.getAll('department')} onChange={(v) => update({ department: v })} />
              <MultiFilter label="Priority" options={opts.priority} value={params.getAll('priority')} onChange={(v) => update({ priority: v })} />
              <MultiFilter label="Urgency" options={opts.urgency} value={params.getAll('urgency')} onChange={(v) => update({ urgency: v })} />
              <MultiFilter label="Sentiment" options={opts.sentiment} value={params.getAll('sentiment')} onChange={(v) => update({ sentiment: v })} />
              <MultiFilter label="Verification" options={opts.verification} value={params.getAll('verification')} onChange={(v) => update({ verification: v })} />
              <MultiFilter label="SLA" options={opts.sla} value={params.getAll('sla')} onChange={(v) => update({ sla: v })} />
              <NativeSelect aria-label="Escalation" className="h-8 w-auto text-xs" value={params.get('escalated') ?? ''} onChange={(e) => update({ escalated: e.target.value || null })}>
                <option value="">Escalation: any</option>
                <option value="true">Escalated</option>
                <option value="false">Not escalated</option>
              </NativeSelect>
              <div className="flex items-center gap-1.5">
                <Label htmlFor="df" className="sr-only">From date</Label>
                <Input id="df" type="date" className="h-8 w-auto text-xs" value={params.get('date_from') ?? ''} onChange={(e) => update({ date_from: e.target.value || null })} />
                <span className="text-muted-foreground text-xs">to</span>
                <Label htmlFor="dt" className="sr-only">To date</Label>
                <Input id="dt" type="date" className="h-8 w-auto text-xs" value={params.get('date_to') ?? ''} onChange={(e) => update({ date_to: e.target.value || null })} />
              </div>
              <label className="flex items-center gap-1.5 text-xs">
                <Checkbox checked={params.get('needs_review') === 'true'} onCheckedChange={(c) => update({ needs_review: c ? 'true' : null })} /> Needs review
              </label>
              <label className="flex items-center gap-1.5 text-xs">
                <Checkbox checked={params.get('assigned_to_me') === 'true'} onCheckedChange={(c) => update({ assigned_to_me: c ? 'true' : null })} /> Assigned to me
              </label>
              <NativeSelect aria-label="Source" className="h-8 w-auto text-xs" value={params.get('source') ?? ''} onChange={(e) => update({ source: e.target.value || null })}>
                <option value="">Customer complaints</option>
                <option value="lab">Adversarial Lab runs</option>
                <option value="evaluation">Evaluation cases</option>
              </NativeSelect>
              {activeCount ? (
                <Button variant="ghost" size="sm" onClick={() => { setQ(''); setParams(new URLSearchParams(), { replace: true }) }}>
                  <RotateCcw /> Reset
                </Button>
              ) : null}
              <div className="ml-auto flex items-center gap-1.5">
                <ArrowDownUp className="text-muted-foreground size-3.5" aria-hidden />
                <NativeSelect aria-label="Sort" className="h-8 w-auto text-xs" value={`${params.get('sort') ?? 'created_at'}:${params.get('order') ?? 'desc'}`} onChange={(e) => { const [s, o] = e.target.value.split(':'); update({ sort: s, order: o }) }}>
                  <option value="created_at:desc">Newest first</option>
                  <option value="created_at:asc">Oldest first</option>
                  <option value="priority:asc">Priority (P0 first)</option>
                  <option value="verification_score:asc">Lowest score first</option>
                  <option value="updated_at:desc">Recently updated</option>
                </NativeSelect>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card className="mt-4 py-0">
        <CardContent className="px-0">
          {list.isLoading ? (
            <div className="p-5"><LoadingBlock rows={8} /></div>
          ) : list.error ? (
            <div className="p-5"><ErrorState error={list.error} onRetry={() => list.refetch()} /></div>
          ) : list.data!.items.length === 0 ? (
            <div className="p-5"><EmptyState icon={Inbox} title="No complaints match" description={activeCount ? 'Try removing a filter.' : 'Complaints you submit will appear here.'} /></div>
          ) : internal ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Complaint</TableHead>
                  <TableHead>Customer</TableHead>
                  <TableHead>Classification</TableHead>
                  <TableHead>Priority</TableHead>
                  <TableHead className="hidden 2xl:table-cell">Urgency</TableHead>
                  <TableHead className="hidden 2xl:table-cell">Sentiment</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Verification</TableHead>
                  <TableHead className="hidden lg:table-cell">SLA</TableHead>
                  <TableHead className="hidden 2xl:table-cell">Escalation</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.data!.items.map((c) => (
                  <TableRow key={c.complaint_ref} className={list.isPlaceholderData ? 'opacity-60' : ''}>
                    <TableCell className="max-w-[20rem]">
                      <div className="flex items-center gap-1.5">
                        <Link to={`/complaints/${c.complaint_ref}`} className="font-mono text-xs font-semibold text-primary hover:underline">{c.complaint_ref}</Link>
                        {c.injection_detected ? <Tooltip content="Prompt-injection attempt detected and neutralised"><ShieldAlert className="text-destructive size-3.5" aria-label="injection detected" /></Tooltip> : null}
                        {c.is_repeat ? <Badge variant="muted" className="px-1 py-0 text-[10px]">repeat</Badge> : null}
                        {c.is_duplicate ? <Badge variant="muted" className="px-1 py-0 text-[10px]">duplicate</Badge> : null}
                      </div>
                      <div className="truncate text-sm">{c.title}</div>
                      <div className="text-muted-foreground text-xs">{fmtDate(c.created_at)} · {fmtRelative(c.created_at)}</div>
                    </TableCell>
                    <TableCell className="text-sm">
                      <div className="max-w-[10rem] truncate">{c.customer_name ?? '—'}</div>
                      <div className="text-muted-foreground font-mono text-xs">{c.customer_ref}</div>
                    </TableCell>
                    <TableCell className="max-w-[14rem] text-sm">
                      <div className="truncate">{c.subcategory ?? '—'}</div>
                      <div className="text-muted-foreground truncate text-xs">{c.department ?? ''}</div>
                    </TableCell>
                    <TableCell><PriorityBadge priority={c.priority} compact /></TableCell>
                    <TableCell className="hidden 2xl:table-cell"><UrgencyBadge urgency={c.urgency} /></TableCell>
                    <TableCell className="hidden 2xl:table-cell"><SentimentText sentiment={c.sentiment} /></TableCell>
                    <TableCell><StatusBadge status={c.status} /></TableCell>
                    <TableCell><VerificationBadge status={c.processing_stage === 'completed' || c.verification_status !== 'Pending' ? c.verification_status : 'Pending'} score={c.verification_score} /></TableCell>
                    <TableCell className="hidden lg:table-cell"><SlaBadge state={c.sla_state} /></TableCell>
                    <TableCell className="hidden 2xl:table-cell"><EscalationBadge level={c.escalation_level} required={c.escalation_required} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Complaint</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Submitted</TableHead>
                  <TableHead>Department</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.data!.items.map((c) => (
                  <TableRow key={c.complaint_ref}>
                    <TableCell>
                      <Link to={`/complaints/${c.complaint_ref}`} className="font-mono text-xs font-semibold text-primary hover:underline">{c.complaint_ref}</Link>
                      <div className="text-sm">{c.title}</div>
                    </TableCell>
                    <TableCell><StatusBadge status={c.status} /></TableCell>
                    <TableCell className="text-sm">{fmtDate(c.created_at)}</TableCell>
                    <TableCell className="text-sm">{c.department ?? '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      {list.data && list.data.total > 0 ? <Pagination page={page} pageSize={25} total={list.data.total} onPage={(p) => update({ page: String(p) })} /> : null}
    </>
  )
}
