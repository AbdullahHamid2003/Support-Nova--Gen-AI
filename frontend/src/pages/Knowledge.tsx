import { keepPreviousData, useQuery, type UseQueryResult } from '@tanstack/react-query'
import {
  BadgeCheck, CheckCircle2, ChevronRight, FileSearch, Filter, History, Layers, Library, ListOrdered, RotateCcw, Scale, Search, SearchCode, ShieldAlert,
  ShieldCheck, Sparkles, Upload, XCircle,
} from 'lucide-react'
import * as React from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { EmptyState, ErrorState, Field, LoadingBlock, PageHeader, SectionTitle, Spinner, StatCard } from '@/components/app/common'
import { DocStatusBadge, DocTypeBadge, ExpandableText, FormatBadge, PolicyRefLink, PolicyRefList } from '@/components/knowledge/doc-ui'
import {
  type ConflictsResponse, type ConflictStatement, DOC_STATUSES, DOC_TYPE_LABEL, DOC_TYPES, type DocSummary, type DocVersion, documentHref, type Evidence,
  flaggedCount, type KnowledgeStats, type OutdatedEvidence, type PolicyConflict, type PrecedenceRule, type SearchResult, sortVersions,
} from '@/components/knowledge/model'
import { UploadDocumentDialog } from '@/components/knowledge/UploadDocumentDialog'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger, Tooltip } from '@/components/ui/overlays'
import {
  Badge, Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle, Input, NativeSelect, Separator, Table, TableBody, TableCell, TableHead, TableHeader,
  TableRow,
} from '@/components/ui/primitives'
import { api } from '@/lib/api'
import { useAuth, usePublicConfig } from '@/lib/auth'
import { fmtDate } from '@/lib/format'
import type { PublicConfig } from '@/lib/types'
import { cn, num, titleCase } from '@/lib/utils'

const TABS = ['documents', 'conflicts', 'playground'] as const
type Tab = (typeof TABS)[number]

function useLookups() {
  const cfg = usePublicConfig().data
  const depts = new Map((cfg?.departments ?? []).map((d) => [d.code, d.name] as const))
  const subs = new Map((cfg?.categories ?? []).flatMap((c) => c.subcategories.map((s) => [s.code, s.name] as const)))
  return {
    categories: cfg?.categories ?? [],
    deptName: (code?: string | null) => (code ? depts.get(code) ?? code : '—'),
    subName: (code?: string | null) => (code ? subs.get(code) ?? code : '—'),
  }
}

export default function KnowledgePage() {
  const { can } = useAuth()
  const manage = can('knowledge:manage')
  const navigate = useNavigate()
  const lookups = useLookups()
  const [params, setParams] = useSearchParams()
  const rawTab = params.get('tab') ?? ''
  const tab: Tab = (TABS as readonly string[]).includes(rawTab) ? (rawTab as Tab) : 'documents'
  const [uploadOpen, setUploadOpen] = React.useState(false)

  const stats = useQuery({ queryKey: ['knowledge', 'stats'], queryFn: () => api.get<KnowledgeStats>('/knowledge/stats') })
  const docs = useQuery({ queryKey: ['documents'], queryFn: () => api.get<{ items: DocSummary[]; total: number }>('/documents') })
  const conflicts = useQuery({ queryKey: ['knowledge', 'conflicts'], queryFn: () => api.get<ConflictsResponse>('/knowledge/conflicts') })
  const conflictCount = conflicts.data?.items.length ?? 0

  const setTab = (value: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (value === 'documents') next.delete('tab')
        else next.set('tab', value)
        return next
      },
      { replace: true },
    )

  return (
    <>
      <PageHeader
        eyebrow="Policies & rules"
        title="Knowledge base"
        description="The policies, SOPs, FAQs and templates behind every decision."
        actions={
          <>
            {stats.data ? (
              <Tooltip content="Goes up with every upload or status change">
                <Badge variant="outline" className="h-8 px-2.5 tabular-nums">
                  Revision {stats.data.revision}
                </Badge>
              </Tooltip>
            ) : null}
            {manage ? (
              <Button size="sm" onClick={() => setUploadOpen(true)}>
                <Upload /> Upload document
              </Button>
            ) : null}
          </>
        }
      />

      {stats.isLoading ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <LoadingBlock key={i} rows={2} />
          ))}
        </div>
      ) : stats.error ? (
        <ErrorState error={stats.error} onRetry={() => stats.refetch()} title="Could not load knowledge base statistics" />
      ) : stats.data ? (
        <StatsRow stats={stats.data} />
      ) : null}

      <Tabs value={tab} onValueChange={setTab} className="mt-6">
        <TabsList aria-label="Knowledge base views">
          <TabsTrigger value="documents">
            <Library /> Documents
            {docs.data ? <span className="text-muted-foreground text-xs tabular-nums">{docs.data.total}</span> : null}
          </TabsTrigger>
          <TabsTrigger value="conflicts">
            <Scale /> Policy conflicts
            {conflictCount ? (
              <Badge variant="warning" className="px-1.5 py-0 tabular-nums">
                {conflictCount}
              </Badge>
            ) : null}
          </TabsTrigger>
          <TabsTrigger value="playground">
            <SearchCode /> Evidence search
          </TabsTrigger>
        </TabsList>

        <TabsContent value="documents">
          <DocumentsTab query={docs} deptName={lookups.deptName} manage={manage} onUpload={() => setUploadOpen(true)} />
        </TabsContent>
        <TabsContent value="conflicts">
          <ConflictsTab query={conflicts} />
        </TabsContent>
        <TabsContent value="playground">
          <PlaygroundTab categories={lookups.categories} subName={lookups.subName} />
        </TabsContent>
      </Tabs>

      {manage ? (
        <UploadDocumentDialog
          open={uploadOpen}
          onOpenChange={setUploadOpen}
          existing={docs.data?.items}
          onUploaded={(r) => navigate(documentHref(r.doc_id, { version: r.version }))}
        />
      ) : null}
    </>
  )
}

// ------------------------------------------------------------------ stats
function StatsRow({ stats }: { stats: KnowledgeStats }) {
  const s = stats.by_status
  const formats = Object.entries(stats.by_format)
    .sort((a, b) => b[1] - a[1])
    .map(([f, n]) => `${f.toUpperCase()} ${n}`)
    .join(' · ')
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <StatCard label="Documents" value={num(stats.documents)} icon={Library} tone="primary" hint={`${num(stats.versions)} versions`} />
      <StatCard label="Active versions" value={num(s.Active ?? 0)} icon={BadgeCheck} tone="success" hint={`Previous ${s.Previous ?? 0} · Superseded ${s.Superseded ?? 0} · Draft ${s.Draft ?? 0}`} />
      <StatCard label="Indexed chunks" value={num(stats.chunks)} icon={Layers} tone="validate" hint={formats || 'No files yet'} />
      <StatCard
        label="Quarantined chunks"
        value={num(stats.quarantined_chunks)}
        icon={ShieldAlert}
        tone={stats.quarantined_chunks ? 'destructive' : 'default'}
        hint="Embedded instructions detected - never used as evidence"
      />
    </div>
  )
}

// ------------------------------------------------------------------ documents
const CHIP: Record<string, string> = {
  Active: 'border-success/30 bg-success/12 text-success',
  Pending: 'border-info/30 bg-info/10 text-info',
  Expired: 'border-destructive/25 bg-destructive/10 text-destructive',
  Previous: 'border-transparent bg-muted text-muted-foreground',
  Superseded: 'border-destructive/25 bg-destructive/10 text-destructive line-through decoration-destructive/50',
  Draft: 'border-warning/35 bg-warning/15 text-[oklch(0.45_0.12_60)] dark:text-warning',
}

function VersionChips({ versions }: { versions: DocVersion[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {sortVersions(versions).map((v) => {
        const label = `v${v.version}: ${v.effective_state}${v.effective_date ? `, effective ${fmtDate(v.effective_date)}` : ''}`
        return (
          <Tooltip key={v.version} content={label}>
            <span aria-label={label} className={cn('rounded-md border px-1.5 py-0.5 font-mono text-[11px] leading-none tabular-nums', CHIP[v.effective_state] ?? 'bg-muted')}>
              {v.version}
            </span>
          </Tooltip>
        )
      })}
    </div>
  )
}

function SecurityCell({ doc }: { doc: DocSummary }) {
  const flagged = doc.versions.reduce((n, v) => n + flaggedCount(v.security_findings), 0)
  if (doc.quarantined_chunks)
    return (
      <Tooltip content="Hidden instructions found; never used as evidence.">
        <Badge variant="destructive">
          <ShieldAlert aria-hidden /> {doc.quarantined_chunks} quarantined
        </Badge>
      </Tooltip>
    )
  if (flagged)
    return (
      <Tooltip content="Suspicious wording; still usable but highlighted.">
        <Badge variant="warning">
          <ShieldAlert aria-hidden /> {flagged} flagged
        </Badge>
      </Tooltip>
    )
  return (
    <span className="text-muted-foreground inline-flex items-center gap-1 text-xs">
      <ShieldCheck className="text-success size-3.5" aria-hidden /> Clean
    </span>
  )
}

function DocumentsTab({ query, deptName, manage, onUpload }: {
  query: UseQueryResult<{ items: DocSummary[]; total: number }>
  deptName: (code?: string | null) => string
  manage: boolean
  onUpload: () => void
}) {
  const navigate = useNavigate()
  const [q, setQ] = React.useState('')
  const [type, setType] = React.useState('')
  const [status, setStatus] = React.useState('')

  if (query.isLoading)
    return (
      <Card>
        <CardContent>
          <LoadingBlock rows={8} />
        </CardContent>
      </Card>
    )
  if (query.error) return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  const all = query.data?.items ?? []
  if (!all.length)
    return (
      <EmptyState
        icon={Library}
        title="The knowledge base is empty"
        description="Upload policies, SOPs and FAQs to get started."
        action={
          manage ? (
            <Button size="sm" className="mt-2" onClick={onUpload}>
              <Upload /> Upload document
            </Button>
          ) : undefined
        }
      />
    )

  const needle = q.trim().toLowerCase()
  const items = all.filter((d) => {
    if (type && d.doc_type !== type) return false
    if (status === 'no_active' && d.active_version) return false
    if (status === 'quarantined' && !d.quarantined_chunks) return false
    if (status && status !== 'no_active' && status !== 'quarantined' && !d.versions.some((v) => v.effective_state === status || v.status === status)) return false
    if (!needle) return true
    return [d.doc_id, d.title, d.doc_type, d.owner_department ?? '', deptName(d.owner_department), ...d.topics].some((s) => s.toLowerCase().includes(needle))
  })
  const filtering = !!(needle || type || status)

  return (
    <Card className="gap-0 py-0">
      <div className="flex flex-col gap-2 border-b p-4 md:flex-row md:items-center">
        <div className="relative flex-1">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" aria-hidden />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by ID, title, topic or owner…" className="pl-8" aria-label="Search documents" type="search" />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Filter className="text-muted-foreground size-4" aria-hidden />
          <NativeSelect aria-label="Filter by document type" className="h-9 w-auto" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">All types</option>
            {DOC_TYPES.map((t) => (
              <option key={t} value={t}>
                {DOC_TYPE_LABEL[t]}
              </option>
            ))}
          </NativeSelect>
          <NativeSelect aria-label="Filter by version status" className="h-9 w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Any status</option>
            {[...DOC_STATUSES, 'Pending', 'Expired'].map((s) => (
              <option key={s} value={s}>
                Has a {s} version
              </option>
            ))}
            <option value="no_active">No Active version</option>
            <option value="quarantined">Has quarantined chunks</option>
          </NativeSelect>
          {filtering ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setQ('')
                setType('')
                setStatus('')
              }}
            >
              <RotateCcw /> Reset
            </Button>
          ) : null}
        </div>
      </div>
      <CardContent className="px-0">
        {items.length === 0 ? (
          <div className="p-5">
            <EmptyState icon={Search} title="No documents match" description="Try a different search or remove a filter." />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Document</TableHead>
                <TableHead>Type</TableHead>
                <TableHead className="hidden lg:table-cell">Owner</TableHead>
                <TableHead>Active version</TableHead>
                <TableHead className="hidden md:table-cell">Versions</TableHead>
                <TableHead className="hidden xl:table-cell">Topics</TableHead>
                <TableHead>Screening</TableHead>
                <TableHead className="w-8">
                  <span className="sr-only">Open</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((d) => {
                const active = d.versions.find((v) => v.version === d.active_version)
                return (
                  <TableRow key={d.doc_id} className="cursor-pointer" onClick={() => navigate(documentHref(d.doc_id))}>
                    <TableCell className="max-w-[20rem]">
                      <Link to={documentHref(d.doc_id)} className="text-primary font-mono text-xs font-semibold hover:underline" onClick={(e) => e.stopPropagation()}>
                        {d.doc_id}
                      </Link>
                      <div className="truncate text-sm font-medium">{d.title}</div>
                    </TableCell>
                    <TableCell>
                      <DocTypeBadge type={d.doc_type} />
                    </TableCell>
                    <TableCell className="hidden text-sm lg:table-cell">{deptName(d.owner_department)}</TableCell>
                    <TableCell>
                      {active ? (
                        <div className="space-y-0.5">
                          <div className="flex items-center gap-1.5">
                            <span className="font-mono text-xs font-semibold">v{active.version}</span>
                            <FormatBadge format={active.file_format} />
                            {active.effective_state !== 'Active' ? <DocStatusBadge status={active.effective_state} /> : null}
                          </div>
                          <div className="text-muted-foreground text-xs">effective {fmtDate(active.effective_date)}</div>
                        </div>
                      ) : (
                        <Badge variant="muted">No Active version</Badge>
                      )}
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <VersionChips versions={d.versions} />
                    </TableCell>
                    <TableCell className="hidden max-w-[16rem] xl:table-cell">
                      <div className="flex flex-wrap gap-1">
                        {d.topics.slice(0, 3).map((t) => (
                          <Badge key={t} variant="secondary" className="font-normal">
                            {t}
                          </Badge>
                        ))}
                        {d.topics.length > 3 ? <span className="text-muted-foreground text-xs">+{d.topics.length - 3}</span> : null}
                      </div>
                    </TableCell>
                    <TableCell>
                      <SecurityCell doc={d} />
                    </TableCell>
                    <TableCell>
                      <ChevronRight className="text-muted-foreground size-4" aria-hidden />
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
      <div className="text-muted-foreground flex flex-wrap items-center justify-between gap-2 border-t px-4 py-3 text-xs">
        <span className="tabular-nums">
          Showing {items.length} of {all.length} documents
        </span>
        <span className="flex flex-wrap items-center gap-2">
          Versions:
          {['Active', 'Previous', 'Superseded', 'Draft'].map((s) => (
            <span key={s} className={cn('rounded-md border px-1.5 py-0.5 font-mono text-[10px] leading-none', CHIP[s])}>
              {s}
            </span>
          ))}
        </span>
      </div>
    </Card>
  )
}

// ------------------------------------------------------------------ conflicts
function whyPrevails(p: ConflictStatement, o: ConflictStatement, rank: Record<string, number>): string {
  const pr = rank[p.doc_type] ?? p.precedence_rank
  const or = rank[o.doc_type] ?? o.precedence_rank
  const label = (t: string) => DOC_TYPE_LABEL[t] ?? t
  if (pr < or)
    return `${p.doc_id} is a ${label(p.doc_type)} (rank ${pr}) and outranks ${o.doc_id}, a ${label(o.doc_type)} (rank ${or}) - precedence by document type (PRC-002). The value "${o.value}" from ${o.doc_id} is not used.`
  if (pr === or)
    return `${p.doc_id} and ${o.doc_id} have the same rank (${label(p.doc_type)}), so the more recent effective date wins (PRC-003): ${fmtDate(p.effective_date)} vs ${fmtDate(o.effective_date)}.`
  return `${p.doc_id} prevails over ${o.doc_id} under the precedence rules.`
}

type StatementRole = 'prevails' | 'agrees' | 'overridden'
const ROLE: Record<StatementRole, { label: string; variant: 'success' | 'muted' | 'destructive'; icon: React.ElementType; cls: string }> = {
  prevails: { label: 'Prevails', variant: 'success', icon: CheckCircle2, cls: 'border-success/35 bg-success/5' },
  agrees: { label: 'Consistent', variant: 'muted', icon: CheckCircle2, cls: '' },
  overridden: { label: 'Overridden', variant: 'destructive', icon: XCircle, cls: 'border-destructive/30 bg-destructive/5' },
}

function StatementRow({ s, role, rank }: { s: ConflictStatement; role: StatementRole; rank: Record<string, number> }) {
  const cfg = ROLE[role]
  const Icon = cfg.icon
  return (
    <li className={cn('grid gap-3 rounded-lg border p-3 sm:grid-cols-[6.5rem_minmax(0,1fr)]', cfg.cls)}>
      <div className="flex items-center gap-2 sm:flex-col sm:items-start sm:gap-1.5">
        <span className={cn('text-xl leading-none font-semibold tabular-nums', role === 'overridden' && 'text-destructive line-through decoration-2')}>{String(s.value)}</span>
        <Badge variant={cfg.variant}>
          <Icon aria-hidden /> {cfg.label}
        </Badge>
      </div>
      <div className="min-w-0 space-y-1.5">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <PolicyRefLink policyRef={`${s.doc_id}:${s.section_id}`} version={s.version} />
          <span className="min-w-0 truncate text-sm font-medium">{s.title}</span>
          <DocTypeBadge type={s.doc_type} rank={rank[s.doc_type] ?? s.precedence_rank} />
          <span className="text-muted-foreground text-xs">effective {fmtDate(s.effective_date)}</span>
        </div>
        <blockquote className="text-muted-foreground border-l-2 pl-3 text-sm italic">“{s.snippet}”</blockquote>
      </div>
    </li>
  )
}

function ConflictCard({ conflict: c, rank }: { conflict: PolicyConflict; rank: Record<string, number> }) {
  const overridden = new Set(c.overridden.map((o) => o.chunk_uid))
  const roleOf = (s: ConflictStatement): StatementRole => (s.chunk_uid === c.prevailing.chunk_uid ? 'prevails' : overridden.has(s.chunk_uid) ? 'overridden' : 'agrees')
  const order: Record<StatementRole, number> = { prevails: 0, agrees: 1, overridden: 2 }
  const statements = [...c.statements].sort((a, b) => order[roleOf(a)] - order[roleOf(b)])
  const docs = new Set(c.statements.map((s) => s.doc_id)).size
  const reasons = c.overridden.map((o) => whyPrevails(c.prevailing, o, rank))
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <Scale className="text-warning size-4.5" aria-hidden /> {titleCase(c.fact_key)}
          <code className="bg-muted text-muted-foreground rounded px-1.5 py-0.5 font-mono text-[11px] font-normal">{c.fact_key}</code>
        </CardTitle>
        <CardDescription>
          {c.statements.length} statements in {docs} Active documents · {c.overridden.length} overridden
        </CardDescription>
        <CardAction>
          <Tooltip content="The precedence rule that settled this conflict">
            <Badge variant="primary" className="font-mono">
              {c.resolution_rule}
            </Badge>
          </Tooltip>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="border-success/30 bg-success/6 rounded-xl border p-4">
          <div className="text-success flex items-center gap-1.5 text-xs font-semibold tracking-wide uppercase">
            <CheckCircle2 className="size-3.5" aria-hidden /> Value used by the rules
          </div>
          <div className="mt-1.5 flex flex-wrap items-baseline gap-2 text-sm">
            <span className="text-2xl font-semibold tabular-nums">{String(c.prevailing.value)}</span>
            <span className="text-muted-foreground">from</span>
            <PolicyRefLink policyRef={`${c.prevailing.doc_id}:${c.prevailing.section_id}`} version={c.prevailing.version} className="text-sm" />
            <span className="text-muted-foreground">{c.prevailing.title}</span>
          </div>
          <p className="mt-2 text-sm">{c.explanation}</p>
          {reasons.length ? (
            <ul className="text-muted-foreground mt-2 list-disc space-y-1 pl-5 text-sm">
              {reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          ) : null}
        </div>
        <ol className="space-y-2" aria-label="Statements">
          {statements.map((s) => (
            <StatementRow key={s.chunk_uid} s={s} role={roleOf(s)} rank={rank} />
          ))}
        </ol>
      </CardContent>
    </Card>
  )
}

function PrecedenceCard({ precedence, rank }: { precedence: PrecedenceRule[]; rank: Record<string, number> }) {
  const groups = new Map<number, string[]>()
  for (const [type, r] of Object.entries(rank)) groups.set(r, [...(groups.get(r) ?? []), type])
  const ladder = [...groups.entries()].sort((a, b) => a[0] - b[0])
  return (
    <Card className="lg:sticky lg:top-20">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ListOrdered className="text-muted-foreground size-4" aria-hidden /> Precedence rules
        </CardTitle>
        <CardDescription>How conflicts are settled. The AI never decides this.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ol className="space-y-3">
          {precedence.map((p) => (
            <li key={p.rule_id} className="text-sm">
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="font-mono">
                  {p.rule_id}
                </Badge>
                <span className="font-medium">{p.name}</span>
              </div>
              <p className="text-muted-foreground mt-1 text-xs leading-relaxed">{p.description}</p>
              <PolicyRefList refs={p.policy_refs} className="mt-1" />
            </li>
          ))}
        </ol>
        <Separator />
        <div>
          <div className="text-muted-foreground mb-2 text-xs font-semibold tracking-wide uppercase">Document-type rank (1 = strongest)</div>
          <ol className="space-y-1.5">
            {ladder.map(([r, types]) => (
              <li key={r} className="flex items-center gap-2 text-sm">
                <span className="bg-muted flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular-nums">{r}</span>
                <span className="flex flex-wrap gap-1">
                  {types.sort().map((t) => (
                    <DocTypeBadge key={t} type={t} />
                  ))}
                </span>
              </li>
            ))}
          </ol>
        </div>
      </CardContent>
    </Card>
  )
}

function ConflictsTab({ query }: { query: UseQueryResult<ConflictsResponse> }) {
  if (query.isLoading) return <LoadingBlock rows={6} />
  if (query.error) return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  const data = query.data
  if (!data) return null
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="min-w-0 space-y-4">
        {data.items.length === 0 ? (
          <EmptyState icon={CheckCircle2} title="No conflicting statements" description="All Active documents agree on every tracked policy fact." />
        ) : (
          data.items.map((c) => <ConflictCard key={`${c.fact_key}-${c.prevailing.chunk_uid}`} conflict={c} rank={data.doc_type_rank} />)
        )}
      </div>
      <aside>
        <PrecedenceCard precedence={data.precedence} rank={data.doc_type_rank} />
      </aside>
    </div>
  )
}

// ------------------------------------------------------------------ retrieval playground
const EXAMPLES: { q: string; note: string }[] = [
  { q: 'How many business days until my refund is issued?', note: 'An FAQ contradicts the Refund Policy' },
  { q: 'Returns window 60 days', note: 'The 60-day window only exists in a superseded version' },
  { q: 'My charger overheated and started smoking', note: 'Safety evidence; Draft and Previous SOPs held back' },
  { q: 'Charged twice for my subscription', note: 'Two possible subcategories guide the search' },
]

const METHOD: Record<string, { v: 'info' | 'validate' | 'primary'; label: string; tip: string }> = {
  lexical: { v: 'info', label: 'Keyword', tip: 'Matches the words in the query.' },
  semantic: { v: 'validate', label: 'Semantic', tip: 'Similar in meaning to the query.' },
  'rule-guided': { v: 'primary', label: 'Rule-guided', tip: 'Section the rules cite for this subcategory.' },
}

function MethodBadge({ method }: { method: string }) {
  const cfg = METHOD[method] ?? { v: 'info' as const, label: titleCase(method), tip: method }
  return (
    <Tooltip content={cfg.tip}>
      <Badge variant={cfg.v} className="px-1.5 py-0 text-[10.5px]">
        {cfg.label}
      </Badge>
    </Tooltip>
  )
}

function EvidenceItem({ e, max }: { e: Evidence; max: number }) {
  const pages = e.page_start ? `p. ${e.page_start}${e.page_end && e.page_end !== e.page_start ? `–${e.page_end}` : ''}` : null
  return (
    <li className="bg-card rounded-xl border p-4 shadow-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="bg-primary/10 text-primary rounded-md px-1.5 py-0.5 font-mono text-xs font-semibold">{e.evidence_id}</span>
        <PolicyRefLink policyRef={`${e.doc_id}:${e.section_id}`} version={e.version} />
        <DocStatusBadge status={e.status} />
        <DocTypeBadge type={e.doc_type} rank={e.precedence_rank} />
        <div className="ml-auto text-right leading-tight">
          <div className="text-sm font-semibold tabular-nums">{e.score.toFixed(1)}</div>
          <div className="text-muted-foreground text-[10px] tracking-wide uppercase">score</div>
        </div>
      </div>
      <div className="mt-2 text-sm font-semibold">
        {e.heading} <span className="text-muted-foreground font-normal">· {e.title}</span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <div className="bg-muted h-1.5 w-28 overflow-hidden rounded-full" aria-hidden>
          <div className="nova-gradient h-full rounded-full" style={{ width: `${Math.max(4, (e.score / max) * 100)}%` }} />
        </div>
        <div className="flex flex-wrap gap-1" aria-label="Match methods">
          {e.methods.map((m) => (
            <MethodBadge key={m} method={m} />
          ))}
        </div>
        {pages ? <span className="text-muted-foreground text-xs">{pages}</span> : null}
        {e.effective_date ? <span className="text-muted-foreground text-xs">effective {fmtDate(e.effective_date)}</span> : null}
      </div>
      <ExpandableText text={e.text} className="mt-2" />
    </li>
  )
}

function OutdatedItem({ o }: { o: OutdatedEvidence }) {
  return (
    <li className="bg-card/70 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <PolicyRefLink policyRef={`${o.doc_id}:${o.section_id}`} version={o.version} />
        <DocStatusBadge status={o.status} />
        <span className="text-sm font-medium">{o.heading}</span>
        {o.active_version ? (
          <Link to={documentHref(o.doc_id, { version: o.active_version, section: o.section_id })} className="text-success ml-auto text-xs font-medium hover:underline">
            Active version: v{o.active_version} →
          </Link>
        ) : (
          <span className="text-muted-foreground ml-auto text-xs">No Active version</span>
        )}
      </div>
      <ExpandableText text={o.text} lines={3} className="text-muted-foreground mt-2" />
      <p className="text-muted-foreground mt-1.5 text-xs italic">{o.note}</p>
    </li>
  )
}

function SearchResults({ result, subName, chosen, fetching }: { result: SearchResult; subName: (c?: string | null) => string; chosen?: string; fetching: boolean }) {
  const max = Math.max(1, ...result.evidence.map((e) => e.score))
  const candidates = result.candidate_subcategories.filter((c): c is string => !!c)
  const st = result.stats ?? {}
  return (
    <div className={cn('space-y-4 transition-opacity', fetching && 'opacity-60')} aria-busy={fetching}>
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="gap-2 py-4">
          <CardContent className="space-y-2">
            <div className="text-muted-foreground text-xs font-medium tracking-wide uppercase">Subcategory context</div>
            {candidates.length ? (
              <div className="flex flex-wrap gap-1.5">
                {candidates.map((c) => (
                  <Badge key={c} variant="primary">
                    <span className="font-mono">{c}</span> <span className="font-normal opacity-80">{subName(c)}</span>
                  </Badge>
                ))}
              </div>
            ) : (
              <div className="text-sm">No subcategory detected</div>
            )}
            <p className="text-muted-foreground text-xs">
              {chosen ? 'Chosen by you.' : candidates.length ? 'Detected by the rules, not the AI.' : 'Keyword and semantic matching only.'}
            </p>
          </CardContent>
        </Card>
        <StatCard label="Primary evidence" value={result.evidence.length} icon={BadgeCheck} tone="success" hint={`from ${num(st.eligible_chunks)} eligible chunks`} />
        <StatCard
          label="Search time"
          value={typeof st.latency_ms === 'number' ? `${st.latency_ms} ms` : '—'}
          icon={Sparkles}
          tone="validate"
          hint={`${num(st.lexical_hits)} keyword hits · ${num(st.rule_guided)} rule-guided · ${st.embedder ?? 'embedder n/a'}`}
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_21rem]">
        <div className="min-w-0 space-y-6">
          <section>
            <SectionTitle icon={BadgeCheck}>Primary evidence</SectionTitle>
            {result.evidence.length === 0 ? (
              <EmptyState icon={FileSearch} title="No eligible evidence" description="No Active passage matched, so the case would go to manual review." />
            ) : (
              <ol className="space-y-3">
                {result.evidence.map((e) => (
                  <EvidenceItem key={e.chunk_uid} e={e} max={max} />
                ))}
              </ol>
            )}
          </section>

          <section className="border-warning/45 bg-warning/5 rounded-xl border border-dashed p-4" aria-labelledby="outdated-title">
            <div className="flex items-start gap-3">
              <History className="mt-0.5 size-5 shrink-0 text-[oklch(0.5_0.13_60)] dark:text-warning" aria-hidden />
              <div>
                <h2 id="outdated-title" className="text-sm font-semibold">
                  Outdated versions - context only ({result.outdated.length})
                </h2>
                <p className="text-muted-foreground mt-0.5 text-sm">
                  Matches from older or inactive versions, shown for context and <strong className="text-foreground">never</strong> used for a decision.
                </p>
              </div>
            </div>
            {result.outdated.length ? (
              <ol className="mt-3 space-y-2">
                {result.outdated.map((o) => (
                  <OutdatedItem key={`${o.doc_id}@${o.version}#${o.section_id}`} o={o} />
                ))}
              </ol>
            ) : (
              <p className="text-muted-foreground mt-3 text-sm">No outdated version matched this query.</p>
            )}
          </section>
        </div>

        <aside className="space-y-4">
          <Card className={cn(result.conflicts.length && 'border-warning/50')}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Scale className="text-muted-foreground size-4" aria-hidden /> Conflicts in these results
              </CardTitle>
              <CardDescription>Where the documents found here disagree.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {result.conflicts.length === 0 ? (
                <p className="text-muted-foreground flex items-center gap-1.5 text-sm">
                  <CheckCircle2 className="text-success size-4" aria-hidden /> None - the evidence is consistent.
                </p>
              ) : (
                result.conflicts.map((c) => (
                  <div key={`${c.fact_key}-${c.prevailing.chunk_uid}`} className="rounded-lg border p-3 text-sm">
                    <div className="font-medium">{titleCase(c.fact_key)}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <Badge variant="success">
                        <CheckCircle2 aria-hidden /> {String(c.prevailing.value)}
                      </Badge>
                      <PolicyRefLink policyRef={`${c.prevailing.doc_id}:${c.prevailing.section_id}`} />
                      <span className="text-muted-foreground text-xs">prevails over</span>
                      {c.overridden.map((o) => (
                        <span key={o.chunk_uid} className="inline-flex items-center gap-1">
                          <Badge variant="destructive" className="line-through">
                            {String(o.value)}
                          </Badge>
                          <PolicyRefLink policyRef={`${o.doc_id}:${o.section_id}`} />
                        </span>
                      ))}
                    </div>
                    <p className="text-muted-foreground mt-1.5 text-xs">{c.explanation}</p>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ListOrdered className="text-muted-foreground size-4" aria-hidden /> Rule-guided sections
              </CardTitle>
              <CardDescription>Sections the Rule Matrix cites for these subcategories.</CardDescription>
            </CardHeader>
            <CardContent>
              {result.rule_guided_sections.length ? (
                <div className="flex flex-wrap gap-x-3 gap-y-1.5">
                  {result.rule_guided_sections.map((r) => (
                    <PolicyRefLink key={r} policyRef={r} />
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground text-sm">No rule-guided sections for this query.</p>
              )}
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  )
}

function PlaygroundTab({ categories, subName }: { categories: PublicConfig['categories']; subName: (c?: string | null) => string }) {
  const [text, setText] = React.useState('')
  const [sub, setSub] = React.useState('')
  const [topK, setTopK] = React.useState(8)
  const [submitted, setSubmitted] = React.useState<{ q: string; subcategory?: string; top_k: number } | null>(null)

  const search = useQuery({
    queryKey: ['knowledge', 'search', submitted],
    queryFn: ({ signal }) => api.get<SearchResult>('/knowledge/search', { q: submitted?.q, subcategory: submitted?.subcategory, top_k: submitted?.top_k }, signal),
    enabled: !!submitted,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  })

  const run = (q: string) => {
    const value = q.trim()
    if (!value) return
    setText(value)
    setSubmitted({ q: value, subcategory: sub || undefined, top_k: topK })
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <SearchCode className="text-primary size-4.5" aria-hidden /> Ask the knowledge base
          </CardTitle>
          <CardDescription>See the evidence the AI would get for a complaint.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            role="search"
            onSubmit={(e) => {
              e.preventDefault()
              run(text)
            }}
            className="grid gap-3 md:grid-cols-[minmax(0,1fr)_15rem_8rem_auto] md:items-end"
          >
            <Field label="Complaint text or question" htmlFor="kb-q">
              <Input id="kb-q" value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. My refund still has not arrived after two weeks" maxLength={2000} />
            </Field>
            <Field label="Subcategory" htmlFor="kb-sub">
              <NativeSelect id="kb-sub" value={sub} onChange={(e) => setSub(e.target.value)}>
                <option value="">Auto-detect</option>
                {categories.map((c) => (
                  <optgroup key={c.code} label={c.name}>
                    {c.subcategories.map((s) => (
                      <option key={s.code} value={s.code}>
                        {s.code} · {s.name}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </NativeSelect>
            </Field>
            <Field label="Passages" htmlFor="kb-k">
              <NativeSelect id="kb-k" value={topK} onChange={(e) => setTopK(Number(e.target.value))}>
                {[3, 5, 8, 10, 15, 20].map((k) => (
                  <option key={k} value={k}>
                    Top {k}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <Button type="submit" disabled={!text.trim() || search.isFetching}>
              {search.isFetching ? <Spinner /> : <SearchCode />} Search
            </Button>
          </form>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground">Try:</span>
            {EXAMPLES.map((ex) => (
              <Tooltip key={ex.q} content={ex.note}>
                <button type="button" onClick={() => run(ex.q)} className="hover:bg-accent hover:border-primary/40 rounded-full border px-2.5 py-1 transition-colors">
                  {ex.q}
                </button>
              </Tooltip>
            ))}
          </div>
        </CardContent>
      </Card>

      {!submitted ? (
        <EmptyState icon={FileSearch} title="Search to see the evidence" description="Pick an example or type a complaint." />
      ) : search.isLoading ? (
        <LoadingBlock rows={6} />
      ) : search.error ? (
        <ErrorState error={search.error} onRetry={() => search.refetch()} title="Search failed" />
      ) : search.data ? (
        <SearchResults result={search.data} subName={subName} chosen={submitted.subcategory} fetching={search.isFetching} />
      ) : null}
    </div>
  )
}
