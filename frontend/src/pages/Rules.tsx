import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'
import {
  Braces, Eye, FlaskConical, FolderTree, ListOrdered, Lock, Pencil, Radar, RefreshCw, RotateCcw, Route, Search, Settings2, ShieldAlert, ShieldCheck, Sigma, Siren,
  SlidersHorizontal, Timer, XCircle,
} from 'lucide-react'
import * as React from 'react'
import { useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { EmptyState, ErrorState, ExportMenu, Field, LoadingBlock, PageHeader, Pagination, Spinner, StatCard } from '@/components/app/common'
import { EscalationBadge, PriorityBadge, UrgencyBadge } from '@/components/app/status'
import { PolicyRefLink, PolicyRefList } from '@/components/knowledge/doc-ui'
import {
  asRecord, asString, asStrings, computePriority, CONFIG_INFO, formatParam, IMPACT_LEVELS, type IntegrityReport, integrityIssues, invalidateRules, RULE_TYPES,
  type RuleParameter, type RuleRow, type RulesList, type RulesMeta, unitLabel, URGENCY_LEVELS,
} from '@/components/rules/model'
import { type EditorTarget, IntegrityPanel, IssueList, RuleEditorDialog } from '@/components/rules/RuleEditorDialog'
import { RuleSimulator } from '@/components/rules/RuleSimulator'
import { TaxonomyManager } from '@/components/rules/TaxonomyManager'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Popover, PopoverContent, PopoverTrigger, Tabs, TabsContent, TabsList, TabsTrigger, Tooltip } from '@/components/ui/overlays'
import {
  Alert, AlertDescription, AlertTitle, Badge, Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle, Input, NativeSelect, Switch, Table, TableBody, TableCell,
  TableHead, TableHeader, TableRow, Textarea,
} from '@/components/ui/primitives'
import { api, errorMessage } from '@/lib/api'
import { useAuth, usePublicConfig } from '@/lib/auth'
import { fmtDateTime, fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'

const TABS = ['rules', 'simulator', 'parameters', 'signals', 'config', 'taxonomy'] as const
type Tab = (typeof TABS)[number]
const PAGE_SIZE = 25
const enc = encodeURIComponent

type Lookup = (code?: string | null) => string

export default function RulesPage() {
  const { can, hasRole } = useAuth()
  const manage = can('rules:manage')
  const canTaxonomy = can('taxonomy:manage')
  const canReset = manage && hasRole('admin')
  const cfg = usePublicConfig().data
  const [params, setParams] = useSearchParams()
  const rawTab = params.get('tab') ?? ''
  const tab: Tab = (TABS as readonly string[]).includes(rawTab) ? (rawTab as Tab) : 'rules'
  const [editor, setEditor] = React.useState<EditorTarget | null>(null)
  const [resetOpen, setResetOpen] = React.useState(false)

  const meta = useQuery({ queryKey: ['rules', 'meta'], queryFn: () => api.get<RulesMeta>('/rules/meta') })
  const list = useQuery({ queryKey: ['rules', 'list'], queryFn: () => api.get<RulesList>('/rules') })
  const integrity = useQuery({ queryKey: ['rules', 'integrity'], queryFn: () => api.post<IntegrityReport>('/rules/validate') })

  const deptMap = new Map((cfg?.departments ?? []).map((d) => [d.code, d.name] as const))
  const subMap = new Map((cfg?.categories ?? []).flatMap((c) => c.subcategories.map((s) => [s.code, s.name] as const)))
  const deptName: Lookup = (code) => (code ? deptMap.get(code) ?? code : '—')
  const subName: Lookup = (code) => (code ? subMap.get(code) ?? code : '—')

  const setTab = (value: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams()
        if (value !== 'rules') next.set('tab', value)
        const type = prev.get('type')
        if (type) next.set('type', type)
        return next
      },
      { replace: true },
    )
  const openConfig = (id: string) => setEditor({ ruleType: 'config', ruleId: id, label: CONFIG_INFO[id]?.label })

  return (
    <>
      <PageHeader
        eyebrow="Policies & rules"
        title="Rule Matrix"
        description="The rules used to decide every complaint and check each AI proposal."
        actions={
          <>
            <IntegrityChip query={integrity} />
            <ExportMenu path="/rules/export" formats={['csv', 'xlsx', 'pdf', 'yaml']} label="Export matrix" />
            {canReset ? (
              <Button variant="outline" size="sm" className="text-destructive hover:text-destructive" onClick={() => setResetOpen(true)}>
                <RotateCcw /> Reset to baseline
              </Button>
            ) : null}
          </>
        }
      />

      {!manage ? (
        <Alert variant="info" className="mb-5">
          <Lock />
          <AlertTitle>Read-only access</AlertTitle>
          <AlertDescription>You can browse, export and simulate rules. Only administrators can edit them.</AlertDescription>
        </Alert>
      ) : null}

      {list.isLoading || meta.isLoading ? (
        <LoadingBlock rows={3} />
      ) : list.error || meta.error ? (
        <ErrorState
          error={list.error ?? meta.error}
          onRetry={() => {
            list.refetch()
            meta.refetch()
          }}
        />
      ) : list.data && meta.data ? (
        <StatsRow list={list.data} meta={meta.data} />
      ) : null}

      <Tabs value={tab} onValueChange={setTab} className="mt-6">
        <TabsList aria-label="Rule Matrix sections">
          <TabsTrigger value="rules">
            <SlidersHorizontal /> Rules
            {list.data ? <span className="text-muted-foreground text-xs tabular-nums">{list.data.total}</span> : null}
          </TabsTrigger>
          <TabsTrigger value="simulator">
            <FlaskConical /> Rule simulator
          </TabsTrigger>
          <TabsTrigger value="parameters">
            <Sigma /> Parameters
            {meta.data ? <span className="text-muted-foreground text-xs tabular-nums">{Object.keys(meta.data.parameters).length}</span> : null}
          </TabsTrigger>
          <TabsTrigger value="signals">
            <Radar /> Signals
            {meta.data ? <span className="text-muted-foreground text-xs tabular-nums">{meta.data.signals.length}</span> : null}
          </TabsTrigger>
          <TabsTrigger value="config">
            <Settings2 /> Configuration
          </TabsTrigger>
          <TabsTrigger value="taxonomy">
            <FolderTree /> Taxonomy
          </TabsTrigger>
        </TabsList>

        <TabsContent value="rules">
          {list.data && meta.data ? <RulesTab list={list.data} meta={meta.data} manage={manage} onEdit={setEditor} deptName={deptName} subName={subName} /> : <LoadingBlock rows={8} />}
        </TabsContent>
        <TabsContent value="simulator">
          <RuleSimulator meta={meta.data} deptName={deptName} subName={subName} />
        </TabsContent>
        <TabsContent value="parameters">{meta.data ? <ParametersTab meta={meta.data} manage={manage} /> : <LoadingBlock rows={8} />}</TabsContent>
        <TabsContent value="signals">{meta.data ? <SignalsTab meta={meta.data} rules={list.data?.items ?? []} manage={manage} onEdit={() => openConfig('signals')} /> : <LoadingBlock rows={8} />}</TabsContent>
        <TabsContent value="config">{meta.data ? <ConfigTab meta={meta.data} manage={manage} onOpen={openConfig} /> : <LoadingBlock rows={8} />}</TabsContent>
        <TabsContent value="taxonomy">
          <TaxonomyManager meta={meta.data} canManage={canTaxonomy} />
        </TabsContent>
      </Tabs>

      <RuleEditorDialog target={editor} onOpenChange={(o) => (o ? null : setEditor(null))} canManage={manage} />
      {canReset ? <ResetDialog open={resetOpen} onOpenChange={setResetOpen} /> : null}
    </>
  )
}

// ------------------------------------------------------------------ header & stats
function IntegrityChip({ query }: { query: UseQueryResult<IntegrityReport> }) {
  if (query.isLoading)
    return (
      <Badge variant="muted" className="h-8 px-2.5">
        <Spinner className="size-3" /> Checking integrity…
      </Badge>
    )
  if (query.error || !query.data)
    return (
      <Button variant="outline" size="sm" onClick={() => query.refetch()}>
        <ShieldAlert /> Integrity check failed - retry
      </Button>
    )
  const r = query.data
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className={cn(r.valid ? 'border-success/40 text-success hover:text-success' : 'border-destructive/40 text-destructive hover:text-destructive')}>
          {r.valid ? <ShieldCheck /> : <ShieldAlert />}
          {r.valid ? 'Integrity valid' : `${r.errors} integrity error${r.errors === 1 ? '' : 's'}`}
          {r.warnings ? <span className="text-muted-foreground font-normal">· {r.warnings} warnings</span> : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[min(26rem,calc(100vw-2rem))] space-y-3">
        <IntegrityPanel report={r} note="Checks that every rule refers to things that exist." />
        <Button size="sm" variant="outline" className="w-full" onClick={() => query.refetch()} disabled={query.isFetching}>
          {query.isFetching ? <Spinner /> : <RefreshCw />} Check again
        </Button>
      </PopoverContent>
    </Popover>
  )
}

function StatsRow({ list, meta }: { list: RulesList; meta: RulesMeta }) {
  const active = list.items.filter((r) => r.is_active).length
  const subs = new Set(list.items.filter((r) => r.rule_type === 'resolution').map((r) => r.subcategory)).size
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <StatCard label="Rules in force" value={`${active} / ${list.total}`} icon={SlidersHorizontal} tone="primary" hint={<span>ruleset <code className="font-mono">{list.ruleset_hash}</code></span>} />
      <StatCard label="Resolution rules" value={list.counts.resolution ?? 0} icon={Route} tone="validate" hint={`covering ${subs} subcategories`} />
      <StatCard label="Escalation rules" value={list.counts.escalation ?? 0} icon={Siren} tone="warning" hint={`${Math.max(0, meta.escalation_levels.length - 1)} escalation levels`} />
      <StatCard label="Policy parameters" value={Object.keys(meta.parameters).length} icon={Sigma} hint="each traced to a policy section" />
    </div>
  )
}

// ------------------------------------------------------------------ rules tab
function RuleEffect({ rule, meta, deptName }: { rule: RuleRow; meta: RulesMeta; deptName: Lookup }) {
  const b = rule.body
  switch (rule.rule_type) {
    case 'resolution': {
      const urgency = asString(b.urgency)
      const impact = asString(b.impact)
      const priority = computePriority(meta.priority_matrix, urgency, impact)
      const esc = asString(b.escalation)
      return (
        <div className="flex flex-wrap items-center gap-1.5">
          {priority ? <PriorityBadge priority={priority} compact /> : null}
          <span className="text-muted-foreground text-xs whitespace-nowrap">
            {urgency} / {impact}
          </span>
          {esc && esc !== 'No Escalation' ? <EscalationBadge level={esc} required /> : null}
        </div>
      )
    }
    case 'escalation':
      return (
        <div className="space-y-1">
          <EscalationBadge level={asString(b.level)} required />
          <div className="text-muted-foreground text-xs">{asStrings(b.departments).map((d) => deptName(d)).join(', ')}</div>
        </div>
      )
    case 'routing': {
      const supporting = asStrings(b.supporting_departments)
      return (
        <div className="text-sm">
          <span className="font-medium">{deptName(asString(b.primary_department))}</span>
          {supporting.length ? <span className="text-muted-foreground block text-xs">+ {supporting.map((d) => deptName(d)).join(', ')}</span> : null}
        </div>
      )
    }
    case 'conditional_routing':
      return <span className="text-sm">Adds {asStrings(b.add_supporting).map((d) => (d.startsWith('$') ? 'secondary-issue departments' : deptName(d))).join(', ')}</span>
    case 'urgency_floor':
      return (
        <div className="flex flex-wrap items-center gap-1.5">
          {b.urgency ? <UrgencyBadge urgency={asString(b.urgency)} /> : <span className="text-muted-foreground text-xs">urgency unchanged</span>}
          <span className="text-muted-foreground text-xs whitespace-nowrap">impact ≥ {asString(b.impact) || '—'}</span>
        </div>
      )
    case 'category': {
      const terms = Object.keys(asRecord(b.terms))
      return (
        <span className="text-sm">
          {terms.length} keywords
          <span className="text-muted-foreground block max-w-[16rem] truncate text-xs">
            {terms.slice(0, 4).join(', ')}
            {terms.length > 4 ? '…' : ''}
          </span>
        </span>
      )
    }
    case 'missing_info':
      return (
        <div className="flex flex-wrap items-center gap-1.5">
          <code className="font-mono text-xs">{asString(b.field)}</code>
          <Badge variant={b.blocking === true ? 'destructive' : 'muted'}>{b.blocking === true ? 'Blocking' : 'Non-blocking'}</Badge>
        </div>
      )
    case 'followup': {
      const type = asString(b.type)
      const due = asString(b.due_hours)
      return (
        <span className="text-sm">
          {type === '$rule' ? 'Type from the resolution rule' : type}
          <span className="text-muted-foreground block text-xs">due {due === '$rule' ? 'per resolution rule' : due === 'sla_first_response' ? 'at the SLA first-response deadline' : `in ${due} h`}</span>
        </span>
      )
    }
    case 'sla':
      return (
        <div className="flex flex-wrap items-center gap-2">
          <PriorityBadge priority={asString(b.priority)} compact />
          <span className="text-xs whitespace-nowrap tabular-nums">
            respond {asString(b.first_response_hours)} h · resolve {asString(b.resolution_hours)} h
          </span>
        </div>
      )
    case 'review':
      return (
        <div className="flex flex-wrap items-center gap-1.5">
          <code className="font-mono text-xs">{asString(b.code)}</code>
          {b.enabled === false ? <Badge variant="muted">disabled</Badge> : null}
        </div>
      )
    default:
      return <span className="text-muted-foreground text-xs">—</span>
  }
}

const NO_CONDITION: Record<string, string> = {
  category: 'Keyword match',
  routing: 'Every complaint in the subcategory',
  sla: 'Complaints at this priority',
  review: 'Built-in check',
}

function ConditionCell({ rule }: { rule: RuleRow }) {
  if (rule.condition === 'always') return <span className="text-muted-foreground text-xs italic">Always - the subcategory default</span>
  if (rule.condition)
    return (
      <code className="line-clamp-2 block max-w-[20rem] font-mono text-[11.5px] leading-snug break-words" title={rule.condition}>
        {rule.condition}
      </code>
    )
  const signals = asStrings(rule.body.signals)
  const categories = asStrings(rule.body.categories)
  if (signals.length || categories.length)
    return (
      <span className="text-xs">
        {signals.length ? `signals: ${signals.join(', ')}` : ''}
        {signals.length && categories.length ? ' · ' : ''}
        {categories.length ? `categories: ${categories.join(', ')}` : ''}
      </span>
    )
  return <span className="text-muted-foreground text-xs">{NO_CONDITION[rule.rule_type] ?? '—'}</span>
}

function RulesTab({ list, meta, manage, onEdit, deptName, subName }: { list: RulesList; meta: RulesMeta; manage: boolean; onEdit: (t: EditorTarget) => void; deptName: Lookup; subName: Lookup }) {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [page, setPage] = React.useState(1)
  const rawType = params.get('type') ?? 'resolution'
  const type = RULE_TYPES.some((t) => t.key === rawType) ? rawType : 'resolution'
  const q = params.get('q') ?? ''
  const sub = params.get('subcategory') ?? ''
  const activeFilter = params.get('active') ?? ''
  const typeInfo = RULE_TYPES.find((t) => t.key === type) ?? RULE_TYPES[0]

  const set = (changes: Record<string, string | null>) => {
    setPage(1)
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [k, v] of Object.entries(changes)) {
          if (v) next.set(k, v)
          else next.delete(k)
        }
        return next
      },
      { replace: true },
    )
  }

  const toggle = useMutation({
    mutationFn: (v: { rule: RuleRow; active: boolean }) => api.post<RuleRow>(`/rules/${enc(v.rule.rule_type)}/${enc(v.rule.rule_id)}/active`, { active: v.active }),
    onSuccess: (r) => {
      toast.success(`${r.rule_id} ${r.is_active ? 'activated' : 'deactivated'} (v${r.version})`, { description: 'Applies to new decisions right away.' })
      invalidateRules(qc)
    },
    onError: (e, v) => {
      const issues = integrityIssues(e)
      toast.error(`Could not ${v.active ? 'activate' : 'deactivate'} ${v.rule.rule_id}: ${errorMessage(e)}`, {
        description: issues.length ? issues.slice(0, 3).map((i) => `${i.rule_id ? `${i.rule_id}: ` : ''}${i.message}`).join(' · ') : undefined,
      })
    },
  })
  const pending = toggle.isPending ? toggle.variables : undefined

  const needle = q.trim().toLowerCase()
  const haystack = (r: RuleRow) => `${r.rule_id} ${r.name} ${r.condition ?? ''} ${JSON.stringify(r.body)}`.toLowerCase()
  const matches = (r: RuleRow) => !needle || haystack(r).includes(needle)
  const ofType = list.items.filter((r) => r.rule_type === type)
  const rows = ofType.filter((r) => matches(r) && (!sub || r.subcategory === sub) && (!activeFilter || (activeFilter === 'active') === r.is_active))
  const subcategories = [...new Set(ofType.map((r) => r.subcategory).filter((s): s is string => !!s))].sort()
  const elsewhere = needle
    ? RULE_TYPES.filter((t) => t.key !== type)
        .map((t) => ({ t, n: list.items.filter((r) => r.rule_type === t.key && matches(r)).length }))
        .filter((x) => x.n > 0)
    : []
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE))
  const current = Math.min(page, pages)
  const shown = rows.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE)
  const filtering = !!(needle || sub || activeFilter)

  return (
    <div className="space-y-4">
      <div role="group" aria-label="Rule type" className="flex flex-wrap gap-1.5">
        {RULE_TYPES.map((t) => {
          const selected = t.key === type
          return (
            <button
              key={t.key}
              type="button"
              aria-pressed={selected}
              onClick={() => set({ type: t.key === 'resolution' ? null : t.key, subcategory: null })}
              className={cn(
                'focus-visible:ring-ring/40 inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm font-medium transition-colors outline-none focus-visible:ring-[3px]',
                selected ? 'border-primary bg-primary text-primary-foreground shadow-sm' : 'bg-card hover:bg-accent',
              )}
            >
              {t.label}
              <span className={cn('rounded-full px-1.5 text-[11px] tabular-nums', selected ? 'bg-primary-foreground/20' : 'bg-muted text-muted-foreground')}>{list.counts[t.key] ?? 0}</span>
            </button>
          )
        })}
      </div>

      <Card className="gap-0 py-0">
        <div className="space-y-3 border-b p-4">
          <div>
            <h2 className="text-base font-semibold">{typeInfo.label} rules</h2>
            <p className="text-muted-foreground mt-0.5 max-w-4xl text-sm">{typeInfo.description}</p>
          </div>
          <div className="flex flex-col gap-2 md:flex-row md:items-center">
            <div className="relative flex-1">
              <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" aria-hidden />
              <Input type="search" value={q} onChange={(e) => set({ q: e.target.value || null })} placeholder="Search rule ID, name or content…" className="pl-8" aria-label="Search rules" />
            </div>
            {subcategories.length ? (
              <NativeSelect aria-label="Filter by subcategory" className="w-auto md:max-w-[16rem]" value={sub} onChange={(e) => set({ subcategory: e.target.value || null })}>
                <option value="">All subcategories</option>
                {subcategories.map((s) => (
                  <option key={s} value={s}>
                    {s} · {subName(s)}
                  </option>
                ))}
              </NativeSelect>
            ) : null}
            <NativeSelect aria-label="Filter by state" className="w-auto" value={activeFilter} onChange={(e) => set({ active: e.target.value || null })}>
              <option value="">Active and inactive</option>
              <option value="active">Active only</option>
              <option value="inactive">Inactive only</option>
            </NativeSelect>
            {filtering ? (
              <Button variant="ghost" size="sm" onClick={() => set({ q: null, subcategory: null, active: null })}>
                <RotateCcw /> Reset
              </Button>
            ) : null}
          </div>
          {elsewhere.length ? (
            <p className="text-muted-foreground flex flex-wrap items-center gap-1.5 text-xs">
              Also matching in:
              {elsewhere.map(({ t, n }) => (
                <button key={t.key} type="button" className="text-primary font-medium hover:underline" onClick={() => set({ type: t.key === 'resolution' ? null : t.key, subcategory: null })}>
                  {t.label} ({n})
                </button>
              ))}
            </p>
          ) : null}
        </div>
        <CardContent className="px-0">
          {shown.length === 0 ? (
            <div className="p-5">
              <EmptyState icon={Search} title="No rules match" description={filtering ? 'Try removing a filter or searching in another rule type.' : 'This rule type has no rules yet.'} />
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Rule</TableHead>
                  <TableHead className="hidden md:table-cell">Applies to</TableHead>
                  <TableHead>Condition</TableHead>
                  <TableHead>Outcome</TableHead>
                  <TableHead className="hidden 2xl:table-cell">Policy</TableHead>
                  <TableHead className="hidden lg:table-cell">Version</TableHead>
                  <TableHead>Active</TableHead>
                  <TableHead className="w-10">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shown.map((r) => {
                  const busy = pending?.rule.rule_id === r.rule_id && pending.rule.rule_type === r.rule_type
                  const checked = busy && pending ? pending.active : r.is_active
                  const open = () => onEdit({ ruleType: r.rule_type, ruleId: r.rule_id, initial: r })
                  return (
                    <TableRow key={`${r.rule_type}:${r.rule_id}`} className={cn(!r.is_active && 'opacity-60')}>
                      <TableCell className="min-w-[11rem] max-w-[16rem] align-top">
                        <button type="button" onClick={open} className="text-primary font-mono text-xs font-semibold hover:underline">
                          {r.rule_id}
                        </button>
                        {r.name && r.name !== r.rule_id ? <div className="text-sm leading-snug">{r.name}</div> : null}
                      </TableCell>
                      <TableCell className="hidden align-top md:table-cell">
                        {r.subcategory ? (
                          <Tooltip content={subName(r.subcategory)}>
                            <Badge variant="outline" className="font-mono">
                              {r.subcategory}
                            </Badge>
                          </Tooltip>
                        ) : (
                          <span className="text-muted-foreground text-xs">All complaints</span>
                        )}
                      </TableCell>
                      <TableCell className="align-top">
                        <ConditionCell rule={r} />
                      </TableCell>
                      <TableCell className="align-top">
                        <RuleEffect rule={r} meta={meta} deptName={deptName} />
                      </TableCell>
                      <TableCell className="hidden align-top 2xl:table-cell">
                        <PolicyRefList refs={asStrings(r.body.policy_refs)} max={2} />
                      </TableCell>
                      <TableCell className="hidden align-top lg:table-cell">
                        <div className="text-sm tabular-nums">v{r.version}</div>
                        {r.updated_at ? (
                          <div className="text-muted-foreground text-xs whitespace-nowrap" title={fmtDateTime(r.updated_at)}>
                            {fmtRelative(r.updated_at)}
                          </div>
                        ) : null}
                      </TableCell>
                      <TableCell className="align-top">
                        {manage ? (
                          <div className="flex items-center gap-1.5">
                            <Switch
                              checked={checked}
                              disabled={toggle.isPending}
                              onCheckedChange={(c) => toggle.mutate({ rule: r, active: c })}
                              aria-label={`${r.is_active ? 'Deactivate' : 'Activate'} ${r.rule_id}`}
                            />
                            {busy ? <Spinner className="size-3.5" /> : null}
                          </div>
                        ) : (
                          <Badge variant={r.is_active ? 'success' : 'muted'}>{r.is_active ? 'Active' : 'Inactive'}</Badge>
                        )}
                      </TableCell>
                      <TableCell className="align-top">
                        <Button variant="ghost" size="icon-sm" onClick={open} aria-label={`${manage ? 'Edit' : 'View'} ${r.rule_id}`}>
                          {manage ? <Pencil /> : <Eye />}
                        </Button>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      {rows.length > PAGE_SIZE ? <Pagination page={current} pageSize={PAGE_SIZE} total={rows.length} onPage={setPage} /> : null}
    </div>
  )
}

// ------------------------------------------------------------------ parameters tab
function ParametersTab({ meta, manage }: { meta: RulesMeta; manage: boolean }) {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const [unit, setUnit] = React.useState('')
  const [editing, setEditing] = React.useState<RuleParameter | null>(null)
  const all = Object.values(meta.parameters).sort((a, b) => a.key.localeCompare(b.key))
  const units = [...new Set(all.map((p) => p.unit))].sort()
  const needle = q.trim().toLowerCase()
  const rows = all.filter((p) => (!unit || p.unit === unit) && (!needle || `${p.key} ${p.description} ${p.source}`.toLowerCase().includes(needle)))
  const setQ = (v: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (v) next.set('q', v)
        else next.delete('q')
        return next
      },
      { replace: true },
    )

  return (
    <div className="space-y-4">
      <Card className="gap-0 py-0">
        <div className="flex flex-col gap-2 border-b p-4 md:flex-row md:items-center">
          <div className="relative flex-1">
            <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" aria-hidden />
            <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search parameter, description or policy…" className="pl-8" aria-label="Search parameters" />
          </div>
          <NativeSelect aria-label="Filter by unit" className="w-auto" value={unit} onChange={(e) => setUnit(e.target.value)}>
            <option value="">All units</option>
            {units.map((u) => (
              <option key={u} value={u}>
                {unitLabel(u) || u}
              </option>
            ))}
          </NativeSelect>
          <span className="text-muted-foreground text-xs tabular-nums">
            {rows.length} of {all.length}
          </span>
        </div>
        <CardContent className="px-0">
          {rows.length === 0 ? (
            <div className="p-5">
              <EmptyState icon={Search} title="No parameters match" />
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Parameter</TableHead>
                  <TableHead className="text-right">Value</TableHead>
                  <TableHead>Source policy</TableHead>
                  {manage ? (
                    <TableHead className="w-10">
                      <span className="sr-only">Edit</span>
                    </TableHead>
                  ) : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((p) => (
                  <TableRow key={p.key}>
                    <TableCell className="max-w-[30rem]">
                      <code className="font-mono text-xs font-semibold">{p.key}</code>
                      <div className="text-muted-foreground text-xs leading-snug">{p.description}</div>
                    </TableCell>
                    <TableCell className="text-right font-semibold whitespace-nowrap tabular-nums">{formatParam(p.value, p.unit)}</TableCell>
                    <TableCell>{p.source ? <PolicyRefLink policyRef={p.source} /> : <span className="text-muted-foreground text-xs">—</span>}</TableCell>
                    {manage ? (
                      <TableCell>
                        <Button variant="ghost" size="icon-sm" aria-label={`Edit ${p.key}`} onClick={() => setEditing(p)}>
                          <Pencil />
                        </Button>
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <Dialog open={!!editing} onOpenChange={(o) => (o ? null : setEditing(null))}>
        <DialogContent>{editing ? <ParameterForm key={editing.key} param={editing} onClose={() => setEditing(null)} /> : null}</DialogContent>
      </Dialog>
    </div>
  )
}

function ParameterForm({ param, onClose }: { param: RuleParameter; onClose: () => void }) {
  const qc = useQueryClient()
  const numeric = typeof param.value === 'number'
  const [value, setValue] = React.useState(String(param.value))
  const [reason, setReason] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)
  const valueId = React.useId()
  const reasonId = React.useId()
  const save = useMutation({
    mutationFn: (v: number | string) => api.put<RuleParameter>(`/rule-parameters/${enc(param.key)}`, { value: v, reason: reason.trim() }),
    onSuccess: (r) => {
      toast.success(`${r.key}: ${formatParam(param.value, param.unit)} → ${formatParam(r.value, r.unit)}`, { description: 'Applies to new decisions right away.' })
      invalidateRules(qc)
      onClose()
    },
  })
  const saveIssues = integrityIssues(save.error)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const raw = value.trim()
    if (!raw) return setError('Enter a value.')
    if (numeric) {
      const n = Number(raw)
      if (!Number.isFinite(n)) return setError('Enter a number.')
      if (n < 0) return setError('The value cannot be negative.')
      setError(null)
      save.mutate(n)
    } else {
      setError(null)
      save.mutate(raw)
    }
  }
  const changed = value.trim() !== String(param.value)

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <DialogHeader>
        <DialogTitle className="flex flex-wrap items-center gap-2">
          <Sigma className="text-primary size-5" aria-hidden /> <code className="font-mono text-base">{param.key}</code>
        </DialogTitle>
        <DialogDescription>{param.description}</DialogDescription>
      </DialogHeader>
      <div className="bg-muted/40 flex flex-wrap items-center gap-2 rounded-lg border p-3 text-sm">
        Source: {param.source ? <PolicyRefLink policyRef={param.source} /> : 'not recorded'}
        <span className="text-muted-foreground text-xs">- the value must stay in line with this section.</span>
      </div>
      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
        <Field label="Value" htmlFor={valueId} required error={error ?? undefined} hint={`Current: ${formatParam(param.value, param.unit)}`}>
          <Input id={valueId} type={numeric ? 'number' : 'text'} inputMode={numeric ? 'decimal' : undefined} step="any" min={numeric ? 0 : undefined} value={value} onChange={(e) => setValue(e.target.value)} aria-invalid={!!error} autoFocus />
        </Field>
        <div className="text-muted-foreground pb-2.5 text-sm">{unitLabel(param.unit)}</div>
      </div>
      <Field label="Reason for the change" htmlFor={reasonId} hint="Recorded in the audit log with the old and new value.">
        <Textarea id={reasonId} rows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. REF-POL-02 v3.0 extends the refund window" />
      </Field>
      {save.error ? (
        <Alert variant="destructive">
          <XCircle />
          <AlertTitle>Not saved - {errorMessage(save.error)}</AlertTitle>
          {saveIssues.length ? (
            <AlertDescription>
              <IssueList issues={saveIssues} />
            </AlertDescription>
          ) : null}
        </Alert>
      ) : null}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={!changed || save.isPending}>
          {save.isPending ? <Spinner /> : null} Save value
        </Button>
      </DialogFooter>
    </form>
  )
}

// ------------------------------------------------------------------ signals tab
function SignalsTab({ meta, rules, manage, onEdit }: { meta: RulesMeta; rules: RuleRow[]; manage: boolean; onEdit: () => void }) {
  const [q, setQ] = React.useState('')
  const bodies = rules.map((r) => ({ id: r.rule_id, text: JSON.stringify(r.body) }))
  const usage = (name: string) => bodies.filter((b) => b.text.includes(`"${name}"`)).map((b) => b.id)
  const needle = q.trim().toLowerCase()
  const signals = meta.signals.filter((s) => !needle || `${s.name} ${s.label} ${s.terms.join(' ')}`.toLowerCase().includes(needle))
  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <p className="text-muted-foreground max-w-3xl text-sm">Words in a complaint that set urgency, escalation and routing.</p>
        <div className="flex shrink-0 gap-2">
          <div className="relative">
            <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" aria-hidden />
            <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter signals…" className="w-56 pl-8" aria-label="Filter signals" />
          </div>
          <Button variant="outline" size="sm" className="h-9" onClick={onEdit}>
            {manage ? <Pencil /> : <Braces />} {manage ? 'Edit signals' : 'View signals'}
          </Button>
        </div>
      </div>
      {signals.length === 0 ? (
        <EmptyState icon={Radar} title="No signals match" />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {signals.map((s) => {
            const used = usage(s.name)
            return (
              <Card key={s.name} className="gap-3 py-4">
                <CardHeader>
                  <CardTitle className="text-sm">{s.label}</CardTitle>
                  <CardDescription className="font-mono text-xs">{s.name}</CardDescription>
                  <CardAction>
                    <Tooltip content={used.length ? used.slice(0, 12).join(', ') + (used.length > 12 ? '…' : '') : 'Not used by any rule'}>
                      <Badge variant={used.length ? 'primary' : 'muted'} className="tabular-nums">
                        {used.length} rule{used.length === 1 ? '' : 's'}
                      </Badge>
                    </Tooltip>
                  </CardAction>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-1">
                    {s.terms.map((t) => (
                      <span key={t} className="bg-muted rounded px-1.5 py-0.5 font-mono text-[11px]">
                        {t}
                      </span>
                    ))}
                    {s.terms.length >= 12 ? <span className="text-muted-foreground px-1 text-[11px]">…</span> : null}
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ configuration tab
function ConfigTab({ meta, manage, onOpen }: { meta: RulesMeta; manage: boolean; onOpen: (id: string) => void }) {
  const sla = Object.values(meta.sla).sort((a, b) => a.priority.localeCompare(b.priority))
  const levels = [...meta.escalation_levels].sort((a, b) => a.rank - b.rank)
  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-2 2xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ListOrdered className="text-muted-foreground size-4" aria-hidden /> Priority matrix
            </CardTitle>
            <CardDescription>Urgency × impact. Sentiment and customer type never count.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full border-separate border-spacing-1 text-sm">
                <caption className="sr-only">Priority by urgency (rows) and impact (columns)</caption>
                <thead>
                  <tr>
                    <th scope="col" className="text-muted-foreground p-1 text-left text-[11px] font-medium">
                      Urgency ↓ · Impact →
                    </th>
                    {IMPACT_LEVELS.map((i) => (
                      <th key={i} scope="col" className="text-muted-foreground p-1 text-center text-xs font-semibold">
                        {i}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {URGENCY_LEVELS.map((u) => (
                    <tr key={u}>
                      <th scope="row" className="p-1 text-left text-xs font-semibold">
                        {u}
                      </th>
                      {IMPACT_LEVELS.map((i) => (
                        <td key={i} className="bg-muted/40 rounded-md p-1.5 text-center">
                          <PriorityBadge priority={meta.priority_matrix[u]?.[i]} compact />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Timer className="text-muted-foreground size-4" aria-hidden /> SLA targets
            </CardTitle>
            <CardDescription>Complaints turn At Risk at {asString(meta.parameters.sla_at_risk_pct?.value) || '—'}% of the time allowed.</CardDescription>
          </CardHeader>
          <CardContent className="px-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Priority</TableHead>
                  <TableHead className="text-right">First response</TableHead>
                  <TableHead className="text-right">Resolution</TableHead>
                  <TableHead className="hidden sm:table-cell">Policy</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sla.map((s) => (
                  <TableRow key={s.rule_id}>
                    <TableCell>
                      <PriorityBadge priority={s.priority} compact />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{s.first_response_hours} h</TableCell>
                    <TableCell className="text-right tabular-nums">{s.resolution_hours} h</TableCell>
                    <TableCell className="hidden sm:table-cell">
                      <PolicyRefList refs={s.policy_refs} max={1} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Siren className="text-muted-foreground size-4" aria-hidden /> Escalation ladder
            </CardTitle>
            <CardDescription>The highest level reached wins; the AI cannot lower it.</CardDescription>
          </CardHeader>
          <CardContent>
            <ol className="space-y-1.5">
              {levels.map((l) => (
                <li key={l.rank} className="flex items-center gap-3 text-sm">
                  <span className={cn('flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular-nums', l.rank >= 4 ? 'bg-destructive/12 text-destructive' : l.rank >= 1 ? 'bg-warning/15' : 'bg-muted')}>{l.rank}</span>
                  <span className="min-w-0 flex-1">{l.name}</span>
                  {l.action_code ? <code className="text-muted-foreground hidden font-mono text-[10.5px] sm:inline">{l.action_code}</code> : null}
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      </div>

      <Card className="gap-0 py-0">
        <div className="border-b p-4">
          <h2 className="text-base font-semibold">Matrix settings</h2>
          <p className="text-muted-foreground mt-0.5 text-sm">Settings that apply to the whole Rule Matrix.</p>
        </div>
        <CardContent className="px-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Setting</TableHead>
                <TableHead className="hidden md:table-cell">What it controls</TableHead>
                <TableHead className="w-24">
                  <span className="sr-only">Open</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {meta.config_ids.map((id) => (
                <TableRow key={id}>
                  <TableCell>
                    <div className="text-sm font-medium">{CONFIG_INFO[id]?.label ?? id}</div>
                    <code className="text-muted-foreground font-mono text-[11px]">{id}</code>
                    <div className="text-muted-foreground mt-0.5 text-xs md:hidden">{CONFIG_INFO[id]?.description}</div>
                  </TableCell>
                  <TableCell className="text-muted-foreground hidden max-w-xl text-sm md:table-cell">{CONFIG_INFO[id]?.description ?? '—'}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="outline" size="sm" onClick={() => onOpen(id)} aria-label={`${manage ? 'Edit' : 'View'} ${CONFIG_INFO[id]?.label ?? id}`}>
                      {manage ? <Pencil /> : <Eye />} {manage ? 'Edit' : 'View'}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}

// ------------------------------------------------------------------ reset to baseline
interface ResetResult {
  rules: number
  ruleset_hash: string
  previous_hash: string
  integrity: IntegrityReport
}

function ResetDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>{open ? <ResetForm onClose={() => onOpenChange(false)} /> : null}</DialogContent>
    </Dialog>
  )
}

function ResetForm({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [text, setText] = React.useState('')
  const inputId = React.useId()
  const reset = useMutation({
    mutationFn: () => api.post<ResetResult>('/rules/reset-to-baseline', undefined, { confirm: true }),
    onSuccess: (r) => {
      const issues = r.integrity?.errors ?? 0
      const message = `Rule Matrix reset to the baseline (${r.rules} rules)`
      const description = `Ruleset ${r.previous_hash} → ${r.ruleset_hash}. The previous state is kept in the audit log.`
      if (issues) toast.warning(message, { description: `${description} ${issues} integrity error(s) - check the integrity report.` })
      else toast.success(message, { description })
      invalidateRules(qc)
      qc.invalidateQueries({ queryKey: ['config'] })
      onClose()
    },
  })
  const confirmed = text.trim().toUpperCase() === 'RESET'
  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault()
        if (confirmed) reset.mutate()
      }}
    >
      <DialogHeader>
        <DialogTitle className="text-destructive flex items-center gap-2">
          <RotateCcw className="size-5" aria-hidden /> Reset the Rule Matrix?
        </DialogTitle>
        <DialogDescription>
          Every rule, setting and parameter goes back to the baseline, and all edits made here are lost for everyone. Categories and departments you added stay, but their rules are removed.
        </DialogDescription>
      </DialogHeader>
      <Field label="Type RESET to confirm" htmlFor={inputId} required>
        <Input id={inputId} value={text} onChange={(e) => setText(e.target.value)} autoComplete="off" className="font-mono uppercase" placeholder="RESET" />
      </Field>
      {reset.error ? (
        <Alert variant="destructive">
          <XCircle />
          <AlertTitle>Reset failed</AlertTitle>
          <AlertDescription>{errorMessage(reset.error)}</AlertDescription>
        </Alert>
      ) : null}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" variant="destructive" disabled={!confirmed || reset.isPending}>
          {reset.isPending ? <Spinner /> : <RotateCcw />} Reset to baseline
        </Button>
      </DialogFooter>
    </form>
  )
}
