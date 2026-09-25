import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'
import {
  AlertTriangle, ArrowLeft, ArrowRight, BadgeCheck, CalendarClock, CheckCircle2, ChevronDown, CircleDollarSign, Clock, Download, FilePen, FileSearch, FileText,
  GitBranch, GitCompareArrows, Hash, History, KeyRound, Layers, ListTree, MinusCircle, Percent, Search, ShieldAlert, ShieldCheck, Sigma, TimerOff, Upload,
} from 'lucide-react'
import { Accordion } from 'radix-ui'
import * as React from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { CopyButton, EmptyState, ErrorState, KeyValue, LoadingBlock, PageHeader, Spinner } from '@/components/app/common'
import { StatusBadge } from '@/components/app/status'
import { DocStatusBadge, DocTypeBadge, ExpandableText, FormatBadge, HighlightedText } from '@/components/knowledge/doc-ui'
import {
  type AffectedComplaint, type DocChunk, type DocDetail, type DocFact, type DocSection, DOC_STATUSES, DOC_TYPE_LABEL, type DocVersion, findingSpans, formatQuantity,
  type ImpactAnalysis, quarantinedCount, type SecurityFinding, sortVersions, type VersionDetail,
} from '@/components/knowledge/model'
import { UploadDocumentDialog } from '@/components/knowledge/UploadDocumentDialog'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/overlays'
import {
  Alert, AlertDescription, AlertTitle, Badge, Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle, Checkbox, Input, Label, NativeSelect, Table,
  TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/primitives'
import { ApiError, api, download, errorMessage } from '@/lib/api'
import { useAuth, usePublicConfig } from '@/lib/auth'
import { fmtBytes, fmtDate, fmtDateTime, fmtRelative } from '@/lib/format'
import { cn, titleCase } from '@/lib/utils'

const TABS = ['sections', 'chunks', 'facts', 'impact'] as const
type Tab = (typeof TABS)[number]

const enc = encodeURIComponent
const sectionAnchor = (id: string) => `section-${id}`
const chunkAnchor = (uid: string) => `chunk-${uid.replace(/[^A-Za-z0-9_-]/g, '_')}`

function pickDefaultVersion(versions: DocVersion[]): string | undefined {
  const sorted = sortVersions(versions)
  return (
    [...sorted].reverse().find((v) => v.primary_eligible)?.version ??
    [...sorted].reverse().find((v) => v.status === 'Active')?.version ??
    sorted[sorted.length - 1]?.version
  )
}

export default function DocumentDetailPage() {
  const { docId: rawId = '' } = useParams()
  const docId = rawId.toUpperCase()
  const [params, setParams] = useSearchParams()
  const { can } = useAuth()
  const manage = can('knowledge:manage')
  const config = usePublicConfig()
  const [uploadOpen, setUploadOpen] = React.useState(false)
  const [downloading, setDownloading] = React.useState(false)

  const doc = useQuery({ queryKey: ['documents', docId], queryFn: () => api.get<DocDetail>(`/documents/${enc(docId)}`), enabled: !!docId })
  const versions = doc.data ? sortVersions(doc.data.versions) : []
  const requested = params.get('v')
  const selected = requested && versions.some((v) => v.version === requested) ? requested : pickDefaultVersion(versions)
  const selectedMeta = versions.find((v) => v.version === selected)
  const currentActive = [...versions].reverse().find((v) => v.status === 'Active')

  const detail = useQuery({
    queryKey: ['documents', docId, 'versions', selected],
    queryFn: () => api.get<VersionDetail>(`/documents/${enc(docId)}/versions/${enc(selected ?? '')}`),
    enabled: !!selected,
  })
  const impact = useQuery({ queryKey: ['documents', docId, 'impact'], queryFn: () => api.get<{ doc_id: string; impacts: ImpactAnalysis[] }>(`/documents/${enc(docId)}/impact`), enabled: !!docId })

  const rawTab = params.get('tab') ?? ''
  const tab: Tab = (TABS as readonly string[]).includes(rawTab) ? (rawTab as Tab) : 'sections'
  const focusSection = params.get('section')
  const focusChunk = params.get('chunk')

  const update = (changes: Record<string, string | null>) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [k, v] of Object.entries(changes)) {
          if (v === null) next.delete(k)
          else next.set(k, v)
        }
        return next
      },
      { replace: true },
    )

  const deptName = (code?: string | null) => (code ? config.data?.departments.find((d) => d.code === code)?.name ?? code : 'No owner')

  if (doc.isLoading) return <LoadingBlock rows={8} />
  if (doc.error) {
    if (doc.error instanceof ApiError && doc.error.status === 404)
      return (
        <EmptyState
          icon={FileSearch}
          title={`Document ${docId} not found`}
          description="Check the document ID or go back to the knowledge base."
          action={
            <Button asChild size="sm" variant="outline" className="mt-2">
              <Link to="/knowledge">
                <ArrowLeft /> Back to the knowledge base
              </Link>
            </Button>
          }
        />
      )
    return <ErrorState error={doc.error} onRetry={() => doc.refetch()} />
  }
  const d = doc.data
  if (!d) return null

  const onDownload = async () => {
    if (!selectedMeta) return
    setDownloading(true)
    try {
      await download(`/documents/${enc(d.doc_id)}/versions/${enc(selectedMeta.version)}/download`, undefined, selectedMeta.file_name)
      toast.success(`Downloading ${selectedMeta.file_name}`)
    } catch (e) {
      toast.error(errorMessage(e))
    } finally {
      setDownloading(false)
    }
  }

  const findings = detail.data?.security_findings ?? selectedMeta?.security_findings ?? []
  const quarantined = detail.data ? detail.data.chunks.filter((c) => c.is_quarantined).length : quarantinedCount(selectedMeta?.security_findings)
  const impacts = impact.data?.impacts ?? []

  return (
    <>
      <div className="mb-2">
        <Button asChild variant="ghost" size="sm" className="text-muted-foreground -ml-2">
          <Link to="/knowledge">
            <ArrowLeft /> Knowledge base
          </Link>
        </Button>
      </div>
      <PageHeader
        eyebrow={
          <span>
            {DOC_TYPE_LABEL[d.doc_type] ?? titleCase(d.doc_type)} · <span className="font-mono">{d.doc_id}</span>
          </span>
        }
        title={d.title}
        description={
          <>
            Owned by <span className="text-foreground font-medium">{deptName(d.owner_department)}</span> · {versions.length} version{versions.length === 1 ? '' : 's'}
          </>
        }
        actions={
          <>
            {selectedMeta ? (
              <Button variant="outline" size="sm" onClick={onDownload} disabled={downloading}>
                {downloading ? <Spinner /> : <Download />} Download v{selectedMeta.version}
              </Button>
            ) : null}
            {manage ? (
              <Button size="sm" onClick={() => setUploadOpen(true)}>
                <Upload /> Upload new version
              </Button>
            ) : null}
          </>
        }
      />
      <div className="-mt-3 mb-5 flex flex-wrap items-center gap-1.5">
        <DocTypeBadge type={d.doc_type} />
        {d.topics.map((t) => (
          <Badge key={t} variant="secondary" className="font-normal">
            {t}
          </Badge>
        ))}
      </div>

      <VersionTimeline versions={versions} selected={selected} onSelect={(v) => update({ v, section: null, chunk: null })} />

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0">
          <Tabs value={tab} onValueChange={(t) => update({ tab: t === 'sections' ? null : t })}>
            <TabsList aria-label="Version content">
              <TabsTrigger value="sections">
                <ListTree /> Sections
                {detail.data ? <span className="text-muted-foreground text-xs tabular-nums">{detail.data.sections.length}</span> : null}
              </TabsTrigger>
              <TabsTrigger value="chunks">
                <Layers /> Chunks
                {quarantined ? (
                  <Badge variant="destructive" className="px-1.5 py-0 tabular-nums">
                    {quarantined}
                  </Badge>
                ) : detail.data ? (
                  <span className="text-muted-foreground text-xs tabular-nums">{detail.data.chunks.length}</span>
                ) : null}
              </TabsTrigger>
              <TabsTrigger value="facts">
                <Sigma /> Extracted facts
                {detail.data?.facts ? <span className="text-muted-foreground text-xs tabular-nums">{detail.data.facts.length}</span> : null}
              </TabsTrigger>
              <TabsTrigger value="impact">
                <GitCompareArrows /> Revision impact
                {impacts.length ? (
                  <Badge variant="warning" className="px-1.5 py-0 tabular-nums">
                    {impacts.length}
                  </Badge>
                ) : null}
              </TabsTrigger>
            </TabsList>
            <VersionContent
              detail={detail}
              docId={d.doc_id}
              findings={findings}
              focusSection={focusSection}
              focusChunk={focusChunk}
              onOpenSection={(s) => update({ tab: null, section: s, chunk: null })}
            />
            <TabsContent value="impact">
              <ImpactPanel query={impact} selected={selected} />
            </TabsContent>
          </Tabs>
        </div>

        <aside className="order-first min-w-0 space-y-4 lg:order-none">
          {selectedMeta ? <VersionDetailsCard v={selectedMeta} /> : null}
          {manage && selectedMeta ? <StatusCard key={`${selectedMeta.version}-${selectedMeta.status}`} docId={d.doc_id} v={selectedMeta} currentActive={currentActive} /> : null}
          {selectedMeta ? <SecurityCard findings={findings} onOpenChunk={(uid) => update({ tab: 'chunks', chunk: uid })} /> : null}
        </aside>
      </div>

      {manage ? (
        <UploadDocumentDialog
          open={uploadOpen}
          onOpenChange={setUploadOpen}
          title={`Upload a new version of ${d.doc_id}`}
          defaults={{ doc_id: d.doc_id, title: d.title, doc_type: d.doc_type, owner_department: d.owner_department ?? '', topics: d.topics.join(', ') }}
          existing={[d]}
          onUploaded={(r) => {
            if (r.doc_id === d.doc_id) update({ v: r.version, tab: null, section: null, chunk: null })
          }}
        />
      ) : null}
    </>
  )
}

// ------------------------------------------------------------------ version timeline
function VersionTimeline({ versions, selected, onSelect }: { versions: DocVersion[]; selected?: string; onSelect: (v: string) => void }) {
  return (
    <Card className="gap-3 py-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <History className="text-muted-foreground size-4" aria-hidden /> Version history
        </CardTitle>
        <CardDescription>Oldest to newest. Select a version to view it.</CardDescription>
      </CardHeader>
      <CardContent>
        <ol className="flex gap-2 overflow-x-auto pb-1.5 scrollbar-thin" aria-label="Versions">
          {versions.map((v, i) => {
            const active = v.version === selected
            const q = quarantinedCount(v.security_findings)
            return (
              <li key={v.version} className="flex shrink-0 items-center gap-2">
                <button
                  type="button"
                  onClick={() => onSelect(v.version)}
                  aria-pressed={active}
                  aria-label={`Version ${v.version}, ${v.effective_state}`}
                  className={cn(
                    'focus-visible:ring-ring/40 w-56 rounded-xl border p-3 text-left transition-colors outline-none focus-visible:ring-[3px]',
                    active ? 'border-primary bg-primary/5 ring-primary/20 ring-2' : 'hover:bg-accent/40 hover:border-primary/30',
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-sm font-semibold">v{v.version}</span>
                    <DocStatusBadge status={v.effective_state} tooltip={false} />
                  </div>
                  <div className="text-muted-foreground mt-1.5 text-xs">
                    Effective {fmtDate(v.effective_date)}
                    {v.expiry_date ? ` → ${fmtDate(v.expiry_date)}` : ''}
                  </div>
                  <div className="text-muted-foreground mt-0.5 flex items-center gap-1.5 text-xs">
                    <FileText className="size-3.5" aria-hidden /> {v.file_format.toUpperCase()} · {v.section_count} sections · {v.chunk_count} chunks
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
                    {v.primary_eligible ? (
                      <span className="text-success inline-flex items-center gap-1 font-medium">
                        <BadgeCheck className="size-3.5" aria-hidden /> Primary evidence
                      </span>
                    ) : (
                      <span className="text-muted-foreground inline-flex items-center gap-1">
                        <MinusCircle className="size-3.5" aria-hidden /> Context only
                      </span>
                    )}
                    {q ? (
                      <Badge variant="destructive" className="px-1.5 py-0">
                        <ShieldAlert aria-hidden /> {q}
                      </Badge>
                    ) : null}
                  </div>
                </button>
                {i < versions.length - 1 ? <ArrowRight className="text-muted-foreground size-4 shrink-0" aria-hidden /> : null}
              </li>
            )
          })}
        </ol>
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------------ side cards
function eligibility(v: DocVersion): { variant: 'success' | 'info' | 'warning' | 'destructive'; icon: React.ElementType; title: string; text: string } {
  if (v.primary_eligible) return { variant: 'success', icon: BadgeCheck, title: 'Primary evidence', text: 'Active and in effect, so it can be cited as evidence (PRC-001).' }
  switch (v.effective_state) {
    case 'Pending':
      return { variant: 'info', icon: CalendarClock, title: 'Not yet effective', text: `Takes effect on ${fmtDate(v.effective_date)}. Until then it is context only.` }
    case 'Expired':
      return { variant: 'destructive', icon: TimerOff, title: 'Expired', text: `Expired on ${fmtDate(v.expiry_date)}. No longer used as evidence (PRC-004).` }
    case 'Draft':
      return { variant: 'warning', icon: FilePen, title: 'Draft - not in use', text: 'Stored for review. Never used as evidence.' }
    case 'Superseded':
      return { variant: 'destructive', icon: History, title: 'Superseded', text: 'Formally replaced. Shown as context only (PRC-004).' }
    default:
      return { variant: 'warning', icon: History, title: 'Previous version', text: 'Replaced by a newer version. Shown as context only (PRC-004).' }
  }
}

function VersionDetailsCard({ v }: { v: DocVersion }) {
  const e = eligibility(v)
  const Icon = e.icon
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Version {v.version} <DocStatusBadge status={v.effective_state} />
        </CardTitle>
        <CardDescription className="truncate" title={v.file_name}>
          {v.file_name}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Alert variant={e.variant}>
          <Icon />
          <AlertTitle>{e.title}</AlertTitle>
          <AlertDescription>{e.text}</AlertDescription>
        </Alert>
        <KeyValue
          items={[
            ['Status', <DocStatusBadge key="s" status={v.status} />],
            ['Format', <FormatBadge key="f" format={v.file_format} />],
            ['Effective', fmtDate(v.effective_date)],
            ['Expiry', v.expiry_date ? fmtDate(v.expiry_date) : 'None'],
            ['Size', fmtBytes(v.size_bytes)],
            ['Pages', v.page_count ?? '—'],
            ['Sections', v.section_count],
            ['Chunks', v.chunk_count],
            ['Parse status', titleCase(v.parse_status)],
            ['Supersedes', v.supersedes ? `v${v.supersedes}` : '—'],
            ['Uploaded', <span key="u" title={fmtDateTime(v.uploaded_at)}>{fmtRelative(v.uploaded_at)}</span>],
          ]}
        />
        <div className="min-w-0">
          <div className="text-muted-foreground text-xs font-medium">File fingerprint</div>
          <div className="flex items-center gap-1">
            <code className="min-w-0 truncate font-mono text-[11px]" title={v.sha256}>
              {v.sha256}
            </code>
            <CopyButton value={v.sha256} label="Copy file fingerprint" />
          </div>
        </div>
        {v.warnings?.length ? (
          <Alert variant="warning">
            <AlertTriangle />
            <AlertTitle>Upload warnings</AlertTitle>
            <AlertDescription>
              <ul className="list-disc space-y-0.5 pl-4">
                {v.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        ) : null}
      </CardContent>
    </Card>
  )
}

function statusConsequence(next: string, v: DocVersion, currentActive?: DocVersion): string {
  if (next === v.status) return `v${v.version} is currently ${v.status}.`
  const orphan = v.status === 'Active' && next !== 'Active' ? ' The document will then have no Active version, so nothing in it is cited.' : ''
  switch (next) {
    case 'Active':
      return currentActive && currentActive.version !== v.version
        ? `v${v.version} becomes the Active version and v${currentActive.version} becomes Previous. The Revision impact tab then shows what the change affects.`
        : `v${v.version} becomes the Active version and is used as primary evidence${v.effective_date ? ` from ${fmtDate(v.effective_date)}` : ''}.`
    case 'Previous':
      return `v${v.version} stops being primary evidence and is shown as context only.${orphan}`
    case 'Superseded':
      return `v${v.version} is marked as formally replaced and is never used as evidence.${orphan}`
    case 'Draft':
      return `v${v.version} is withdrawn to Draft: kept for review but never used as evidence.${orphan}`
    default:
      return ''
  }
}

function StatusCard({ docId, v, currentActive }: { docId: string; v: DocVersion; currentActive?: DocVersion }) {
  const qc = useQueryClient()
  const [next, setNext] = React.useState(v.status)
  const [confirming, setConfirming] = React.useState(false)
  const mutation = useMutation({
    mutationFn: (status: string) => api.post<DocVersion>(`/documents/${enc(docId)}/versions/${enc(v.version)}/status`, { status }),
    onSuccess: (r) => {
      toast.success(`${docId} v${r.version} is now ${r.status}`, { description: r.status === 'Active' && r.impact ? 'The revision impact has been updated.' : 'Applies to new analyses right away.' })
      setConfirming(false)
      qc.invalidateQueries({ queryKey: ['documents'] })
      qc.invalidateQueries({ queryKey: ['knowledge'] })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const consequence = statusConsequence(next, v, currentActive)
  const selectId = React.useId()
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <GitBranch className="text-muted-foreground size-4" aria-hidden /> Version status
        </CardTitle>
        <CardDescription>Change the status of v{v.version}.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor={selectId}>New status</Label>
          <NativeSelect id={selectId} value={next} onChange={(e) => setNext(e.target.value)}>
            {DOC_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
                {s === v.status ? ' (current)' : ''}
              </option>
            ))}
          </NativeSelect>
        </div>
        <p className="text-muted-foreground text-xs leading-relaxed" aria-live="polite">
          {consequence}
        </p>
        <Button className="w-full" onClick={() => setConfirming(true)} disabled={next === v.status || mutation.isPending}>
          Change status
        </Button>
      </CardContent>
      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              Set {docId} v{v.version} to {next}?
            </DialogTitle>
            <DialogDescription>{consequence}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button variant={next === 'Active' ? 'default' : 'destructive'} onClick={() => mutation.mutate(next)} disabled={mutation.isPending}>
              {mutation.isPending ? <Spinner /> : null} Set to {next}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}

function SecurityCard({ findings, onOpenChunk }: { findings: SecurityFinding[]; onOpenChunk: (uid: string) => void }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="text-validate size-4" aria-hidden /> Injection screening
        </CardTitle>
        <CardDescription>Checks the text for hidden instructions.</CardDescription>
      </CardHeader>
      <CardContent>
        {findings.length === 0 ? (
          <p className="flex items-center gap-2 text-sm">
            <CheckCircle2 className="text-success size-4" aria-hidden /> No instruction-like content found.
          </p>
        ) : (
          <ul className="space-y-2">
            {findings.map((f) => (
              <li key={f.chunk_uid} className={cn('rounded-lg border p-2.5 text-xs', f.is_suspicious ? 'border-destructive/30 bg-destructive/5' : 'border-warning/40 bg-warning/5')}>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={f.is_suspicious ? 'destructive' : 'warning'}>
                    <ShieldAlert aria-hidden /> {f.is_suspicious ? 'Quarantined' : 'Flagged'}
                  </Badge>
                  <span className="font-mono">§{f.section_id}</span>
                  <span className="text-muted-foreground ml-auto tabular-nums">risk {Math.round(f.risk_score * 100)}%</span>
                </div>
                {f.findings.map((x, i) => (
                  <p key={i} className="mt-1.5 leading-relaxed">
                    <span className="font-medium">{titleCase(x.type)}</span> ({x.severity}): “{x.text}” - <span className="text-muted-foreground">{x.description}</span>
                  </p>
                ))}
                <p className="text-muted-foreground mt-1.5">{f.is_suspicious ? 'Never cited or shown to the AI.' : 'Still usable, but highlighted for reviewers.'}</p>
                <Button variant="link" size="sm" className="h-auto px-0 pt-1 text-xs" onClick={() => onOpenChunk(f.chunk_uid)}>
                  Show the chunk →
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------------ version content tabs
function VersionContent({ detail, docId, findings, focusSection, focusChunk, onOpenSection }: {
  detail: UseQueryResult<VersionDetail>
  docId: string
  findings: SecurityFinding[]
  focusSection: string | null
  focusChunk: string | null
  onOpenSection: (sectionId: string) => void
}) {
  const body = (render: (v: VersionDetail) => React.ReactNode) =>
    detail.isLoading ? <LoadingBlock rows={6} /> : detail.error ? <ErrorState error={detail.error} onRetry={() => detail.refetch()} /> : detail.data ? render(detail.data) : null
  return (
    <>
      <TabsContent value="sections">
        {body((v) => (
          <SectionsPanel key={`${v.version}-${focusSection ?? ''}`} docId={docId} sections={v.sections} chunks={v.chunks} findings={findings} focus={focusSection} />
        ))}
      </TabsContent>
      <TabsContent value="chunks">{body((v) => <ChunksPanel key={`${v.version}-${focusChunk ?? ''}`} chunks={v.chunks} findings={findings} focus={focusChunk} />)}</TabsContent>
      <TabsContent value="facts">{body((v) => <FactsPanel facts={v.facts ?? []} onOpenSection={onOpenSection} />)}</TabsContent>
    </>
  )
}

function SectionsPanel({ docId, sections, chunks, findings, focus }: { docId: string; sections: DocSection[]; chunks: DocChunk[]; findings: SecurityFinding[]; focus: string | null }) {
  const [filter, setFilter] = React.useState('')
  const [open, setOpen] = React.useState<string[]>(() => (focus ? [focus] : []))

  React.useEffect(() => {
    if (!focus) return
    const el = document.getElementById(sectionAnchor(focus))
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [focus])

  const quarantinedSections = new Set(chunks.filter((c) => c.is_quarantined).map((c) => c.section_id))
  const chunksPer = new Map<string, number>()
  for (const c of chunks) chunksPer.set(c.section_id, (chunksPer.get(c.section_id) ?? 0) + 1)
  const needle = filter.trim().toLowerCase()
  const shown = needle ? sections.filter((s) => `${s.section_id} ${s.heading} ${s.text}`.toLowerCase().includes(needle)) : sections
  const allOpen = shown.length > 0 && shown.every((s) => open.includes(s.section_id))

  if (!sections.length) return <EmptyState icon={ListTree} title="No sections" description="No sections were found in this version." />
  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" aria-hidden />
          <Input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter sections by number, heading or text…" className="pl-8" aria-label="Filter sections" />
        </div>
        <Button variant="outline" size="sm" onClick={() => setOpen(allOpen ? [] : shown.map((s) => s.section_id))}>
          {allOpen ? 'Collapse all' : 'Expand all'}
        </Button>
      </div>
      {shown.length === 0 ? (
        <EmptyState icon={Search} title="No section matches" description="Try another word or section number." />
      ) : (
        <Accordion.Root type="multiple" value={open} onValueChange={setOpen} className="bg-card divide-y rounded-xl border">
          {shown.map((s) => {
            const flagged = findings.filter((f) => f.section_id === s.section_id)
            const q = quarantinedSections.has(s.section_id)
            const spans = flagged.flatMap((f) => findingSpans(s.text, f)).sort((a, b) => a.start - b.start)
            return (
              <Accordion.Item key={s.section_id} value={s.section_id} id={sectionAnchor(s.section_id)} className={cn('scroll-mt-24', focus === s.section_id && 'bg-primary/5')}>
                <Accordion.Header className="flex">
                  <Accordion.Trigger
                    className="group hover:bg-muted/40 focus-visible:ring-ring/40 flex flex-1 items-center gap-3 py-3 pr-4 text-left text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-inset"
                    style={{ paddingLeft: `${1 + Math.max(0, s.level - 1) * 1.25}rem` }}
                  >
                    <span className="text-muted-foreground w-10 shrink-0 font-mono text-xs">{s.section_id}</span>
                    <span className={cn('min-w-0 flex-1', s.level <= 1 ? 'font-semibold' : 'font-medium')}>{s.heading}</span>
                    {q ? (
                      <Badge variant="destructive" className="shrink-0">
                        <ShieldAlert aria-hidden /> Quarantined chunk
                      </Badge>
                    ) : flagged.length ? (
                      <Badge variant="warning" className="shrink-0">
                        <ShieldAlert aria-hidden /> Flagged
                      </Badge>
                    ) : null}
                    {s.page_start ? (
                      <span className="text-muted-foreground hidden shrink-0 text-xs sm:inline">
                        p. {s.page_start}
                        {s.page_end && s.page_end !== s.page_start ? `–${s.page_end}` : ''}
                      </span>
                    ) : null}
                    <ChevronDown className="text-muted-foreground size-4 shrink-0 transition-transform group-data-[state=open]:rotate-180" aria-hidden />
                  </Accordion.Trigger>
                </Accordion.Header>
                <Accordion.Content className="pr-4 pb-4" style={{ paddingLeft: `${1 + Math.max(0, s.level - 1) * 1.25}rem` }}>
                  {q ? (
                    <p className="text-destructive mb-2 flex items-start gap-1.5 text-xs">
                      <ShieldAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden /> The highlighted text is a hidden instruction and is never used as evidence.
                    </p>
                  ) : null}
                  {s.text ? (
                    <p className="text-sm leading-relaxed break-words whitespace-pre-line">
                      <HighlightedText text={s.text} spans={spans} />
                    </p>
                  ) : (
                    <p className="text-muted-foreground text-sm italic">No text under this heading.</p>
                  )}
                  <div className="text-muted-foreground mt-3 flex flex-wrap items-center gap-2 text-xs">
                    <span>
                      Cite as <code className="bg-muted rounded px-1 py-0.5 font-mono">{`${docId}:${s.section_id}`}</code>
                    </span>
                    <CopyButton value={`${docId}:${s.section_id}`} label={`Copy reference ${docId}:${s.section_id}`} />
                    <span>· {chunksPer.get(s.section_id) ?? 0} chunk(s)</span>
                  </div>
                </Accordion.Content>
              </Accordion.Item>
            )
          })}
        </Accordion.Root>
      )}
    </div>
  )
}

function ChunksPanel({ chunks, findings, focus }: { chunks: DocChunk[]; findings: SecurityFinding[]; focus: string | null }) {
  const [onlyQuarantined, setOnlyQuarantined] = React.useState(false)
  const [filter, setFilter] = React.useState('')
  const checkboxId = React.useId()

  React.useEffect(() => {
    if (!focus) return
    document.getElementById(chunkAnchor(focus))?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [focus])

  const byUid = new Map(findings.map((f) => [f.chunk_uid, f] as const))
  const quarantined = chunks.filter((c) => c.is_quarantined)
  const needle = filter.trim().toLowerCase()
  const shown = chunks.filter((c) => (!onlyQuarantined || c.is_quarantined) && (!needle || `${c.chunk_uid} ${c.heading} ${c.text}`.toLowerCase().includes(needle)))

  return (
    <div className="space-y-4">
      {quarantined.length ? (
        <Alert variant="destructive">
          <ShieldAlert />
          <AlertTitle>
            {quarantined.length} quarantined chunk{quarantined.length === 1 ? '' : 's'}
          </AlertTitle>
          <AlertDescription>They contain hidden instructions, so they are never cited or shown to the AI.</AlertDescription>
        </Alert>
      ) : (
        <Alert variant="success">
          <ShieldCheck />
          <AlertTitle>No quarantined chunks</AlertTitle>
          <AlertDescription>Every chunk in this version passed screening.</AlertDescription>
        </Alert>
      )}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" aria-hidden />
          <Input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter chunks…" className="pl-8" aria-label="Filter chunks" />
        </div>
        <label htmlFor={checkboxId} className="flex items-center gap-2 text-sm">
          <Checkbox id={checkboxId} checked={onlyQuarantined} onCheckedChange={(c) => setOnlyQuarantined(c === true)} disabled={!quarantined.length} />
          Only quarantined ({quarantined.length})
        </label>
      </div>
      <Card className="py-0">
        <CardContent className="px-0">
          {shown.length === 0 ? (
            <div className="p-5">
              <EmptyState icon={Layers} title="No chunks match" />
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Chunk</TableHead>
                  <TableHead className="text-right">Tokens</TableHead>
                  <TableHead>Screening</TableHead>
                  <TableHead>Text</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shown.map((c) => {
                  const finding = byUid.get(c.chunk_uid)
                  const spans = findingSpans(c.text, finding)
                  return (
                    <TableRow
                      key={c.chunk_uid}
                      id={chunkAnchor(c.chunk_uid)}
                      className={cn('scroll-mt-24 align-top', c.is_quarantined && 'bg-destructive/5 hover:bg-destructive/8', focus === c.chunk_uid && 'ring-primary/40 ring-2 ring-inset')}
                    >
                      <TableCell className={cn('min-w-[11rem] align-top', c.is_quarantined && 'border-l-destructive border-l-4')}>
                        <div className="font-mono text-[11px] font-medium break-all">{c.chunk_uid}</div>
                        <div className="text-muted-foreground mt-0.5 text-xs">
                          §{c.section_id} · {c.heading}
                        </div>
                        {c.page_start ? <div className="text-muted-foreground text-xs">page {c.page_start}</div> : null}
                      </TableCell>
                      <TableCell className="text-right align-top text-sm tabular-nums">{c.token_count}</TableCell>
                      <TableCell className="min-w-[11rem] align-top">
                        {c.is_quarantined ? (
                          <div className="space-y-1">
                            <Badge variant="destructive">
                              <ShieldAlert aria-hidden /> Quarantined
                            </Badge>
                            <p className="text-destructive text-xs">{c.quarantine_reason ?? 'Instruction-like content detected.'}</p>
                            {finding?.findings.map((f, i) => (
                              <p key={i} className="text-muted-foreground text-xs">
                                {f.description} ({f.severity})
                              </p>
                            ))}
                          </div>
                        ) : finding ? (
                          <div className="space-y-1">
                            <Badge variant="warning">
                              <ShieldAlert aria-hidden /> Flagged
                            </Badge>
                            <p className="text-muted-foreground text-xs">Still usable, but highlighted.</p>
                          </div>
                        ) : (
                          <span className="text-muted-foreground inline-flex items-center gap-1 text-xs">
                            <CheckCircle2 className="text-success size-3.5" aria-hidden /> Indexed
                          </span>
                        )}
                        <div className="text-muted-foreground mt-1 font-mono text-[10px]">{c.embedding_model}</div>
                      </TableCell>
                      <TableCell className="min-w-[18rem] align-top">
                        <ExpandableText text={c.text} lines={3} className="max-w-2xl">
                          <HighlightedText text={c.text} spans={spans} />
                        </ExpandableText>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

const FACT_KIND: Record<string, { icon: React.ElementType; label: string }> = {
  duration: { icon: Clock, label: 'Duration' },
  money: { icon: CircleDollarSign, label: 'Amount' },
  percent: { icon: Percent, label: 'Percentage' },
  count: { icon: Hash, label: 'Count' },
  keyed: { icon: KeyRound, label: 'Keyed fact' },
}

function FactsPanel({ facts, onOpenSection }: { facts: DocFact[]; onOpenSection: (s: string) => void }) {
  if (!facts.length)
    return <EmptyState icon={Sigma} title="No facts extracted" description="No durations, amounts or policy facts were found in this version." />
  const keyed = facts.filter((f) => f.kind === 'keyed')
  const values = facts.filter((f) => f.kind !== 'keyed')
  const sectionLink = (id: string) => (
    <button type="button" className="text-primary font-mono text-xs hover:underline" onClick={() => onOpenSection(id)}>
      §{id}
    </button>
  )
  return (
    <div className="space-y-4">
      <p className="text-muted-foreground text-sm">Values found in the text, used to spot policy conflicts and changes.</p>
      {keyed.length ? (
        <Card className="gap-3">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <KeyRound className="text-muted-foreground size-4" aria-hidden /> Keyed policy facts
            </CardTitle>
            <CardDescription>Compared across documents to find conflicts</CardDescription>
          </CardHeader>
          <CardContent className="px-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Fact key</TableHead>
                  <TableHead>Value</TableHead>
                  <TableHead>Section</TableHead>
                  <TableHead>Source text</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {keyed.map((f, i) => (
                  <TableRow key={`${f.key}-${i}`}>
                    <TableCell className="font-mono text-xs">{f.key}</TableCell>
                    <TableCell className="font-semibold tabular-nums">{String(f.value)}</TableCell>
                    <TableCell>{sectionLink(f.section_id)}</TableCell>
                    <TableCell className="text-muted-foreground max-w-md text-xs italic">“{f.snippet}”</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}
      {values.length ? (
        <Card className="gap-3">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Sigma className="text-muted-foreground size-4" aria-hidden /> Extracted values
            </CardTitle>
            <CardDescription>Durations, amounts and percentages stated in the text</CardDescription>
          </CardHeader>
          <CardContent className="px-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Kind</TableHead>
                  <TableHead>Value</TableHead>
                  <TableHead>Section</TableHead>
                  <TableHead>Source text</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {values.map((f, i) => {
                  const k = FACT_KIND[f.kind] ?? { icon: Hash, label: titleCase(f.kind) }
                  const Icon = k.icon
                  return (
                    <TableRow key={`${f.kind}-${f.section_id}-${i}`}>
                      <TableCell>
                        <span className="inline-flex items-center gap-1.5 text-sm">
                          <Icon className="text-muted-foreground size-3.5" aria-hidden /> {k.label}
                        </span>
                      </TableCell>
                      <TableCell className="font-semibold whitespace-nowrap tabular-nums">{formatQuantity(f.value, f.unit)}</TableCell>
                      <TableCell>{sectionLink(f.section_id)}</TableCell>
                      <TableCell className="text-muted-foreground max-w-md text-xs italic">“{f.snippet}”</TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}

// ------------------------------------------------------------------ impact analysis
const CHANGE: Record<string, { v: 'success' | 'destructive' | 'warning'; label: string }> = {
  added: { v: 'success', label: 'Added' },
  removed: { v: 'destructive', label: 'Removed' },
  modified: { v: 'warning', label: 'Modified' },
}

function MiniStat({ label, value, tone }: { label: string; value: React.ReactNode; tone?: 'warning' | 'destructive' }) {
  return (
    <div className={cn('rounded-lg border p-3', tone === 'warning' && 'border-warning/40 bg-warning/5', tone === 'destructive' && 'border-destructive/30 bg-destructive/5')}>
      <div className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>
    </div>
  )
}

function ComplaintsTable({ items }: { items: AffectedComplaint[] }) {
  const shown = items.slice(0, 50)
  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Complaint</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Cited sections</TableHead>
            <TableHead>Response</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {shown.map((c) => (
            <TableRow key={c.complaint_ref}>
              <TableCell>
                <Link to={`/complaints/${c.complaint_ref}`} className="text-primary font-mono text-xs font-semibold hover:underline">
                  {c.complaint_ref}
                </Link>
              </TableCell>
              <TableCell>
                <StatusBadge status={c.status} />
              </TableCell>
              <TableCell className="font-mono text-xs">{c.sections.map((s) => `§${s}`).join(', ')}</TableCell>
              <TableCell>
                {c.response_requires_revision ? (
                  <Badge variant="warning">
                    <AlertTriangle aria-hidden /> Revise response
                  </Badge>
                ) : (
                  <span className="text-muted-foreground text-xs">No action</span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {items.length > shown.length ? <p className="text-muted-foreground px-3 pt-2 text-xs">…and {items.length - shown.length} more complaints.</p> : null}
    </>
  )
}

function ImpactCard({ impact, highlight }: { impact: ImpactAnalysis; highlight: boolean }) {
  const rules = [...impact.affected_resolution_rules, ...impact.affected_escalation_rules]
  const outOfSync = impact.affected_parameters.filter((p) => p.out_of_sync)
  return (
    <Card className={cn(highlight && 'border-primary/40 ring-primary/15 ring-2')}>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <GitCompareArrows className="text-muted-foreground size-4" aria-hidden />
          <span className="font-mono">v{impact.old_version}</span>
          <ArrowRight className="text-muted-foreground size-4" aria-hidden />
          <span className="font-mono">v{impact.new_version}</span>
        </CardTitle>
        <CardDescription>
          Analysed {fmtDateTime(impact.analysed_at)}
          {impact.previous_policy_obsolete ? ` · v${impact.old_version} is no longer used as evidence` : ''}
        </CardDescription>
        {highlight ? (
          <CardAction>
            <Badge variant="primary">Selected version</Badge>
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <MiniStat label="Changed sections" value={impact.changed_sections.length} />
          <MiniStat label="Rules citing them" value={rules.length} tone={rules.length ? 'warning' : undefined} />
          <MiniStat label="Parameters out of sync" value={outOfSync.length} tone={outOfSync.length ? 'destructive' : undefined} />
          <MiniStat label="Open complaints" value={impact.affected_complaints.length} tone={impact.affected_complaints.length ? 'warning' : undefined} />
          <MiniStat label="Responses to revise" value={impact.responses_requiring_revision} tone={impact.responses_requiring_revision ? 'warning' : undefined} />
        </div>

        <section>
          <h3 className="mb-2 text-sm font-semibold">Changed sections</h3>
          {impact.changed_sections.length ? (
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Section</TableHead>
                    <TableHead>Change</TableHead>
                    <TableHead>Value changes</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {impact.changed_sections.map((c) => (
                    <TableRow key={`${c.section_id}-${c.change}`}>
                      <TableCell>
                        <span className="font-mono text-xs">§{c.section_id}</span> <span className="text-sm">{c.heading}</span>
                      </TableCell>
                      <TableCell>
                        <Badge variant={CHANGE[c.change]?.v ?? 'warning'}>{CHANGE[c.change]?.label ?? titleCase(c.change)}</Badge>
                        {typeof c.similarity === 'number' ? <span className="text-muted-foreground ml-1.5 text-xs tabular-nums">{Math.round(c.similarity * 100)}% similar</span> : null}
                      </TableCell>
                      <TableCell className="text-sm">
                        {c.value_changes?.length ? (
                          <ul className="space-y-0.5">
                            {c.value_changes.map((vc, i) => (
                              <li key={i} className="tabular-nums">
                                <span className="text-destructive line-through">{formatQuantity(vc.old, vc.unit)}</span> → <span className="text-success font-semibold">{formatQuantity(vc.new, vc.unit)}</span>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <span className="text-muted-foreground text-xs">Wording only</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">No section changed materially.</p>
          )}
        </section>

        <section>
          <h3 className="mb-2 text-sm font-semibold">Rule Matrix rules citing changed sections</h3>
          {rules.length ? (
            <div className="space-y-2">
              <div className="flex flex-wrap gap-1.5">
                {impact.affected_resolution_rules.map((r) => (
                  <Link key={r} to={`/rules?type=resolution&q=${enc(r)}`}>
                    <Badge variant="outline" className="hover:bg-accent font-mono">
                      {r}
                    </Badge>
                  </Link>
                ))}
                {impact.affected_escalation_rules.map((r) => (
                  <Link key={r} to={`/rules?type=escalation&q=${enc(r)}`}>
                    <Badge variant="warning" className="font-mono">
                      {r}
                    </Badge>
                  </Link>
                ))}
              </div>
              {impact.escalation_rules_changed ? (
                <p className="text-xs text-[oklch(0.45_0.12_60)] dark:text-warning">Escalation rules cite changed sections - check that escalation levels still match the new policy.</p>
              ) : null}
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">No resolution or escalation rule cites a changed section.</p>
          )}
        </section>

        {impact.affected_parameters.length ? (
          <section>
            <h3 className="mb-2 text-sm font-semibold">Parameters from changed sections</h3>
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Parameter</TableHead>
                    <TableHead className="text-right">Current</TableHead>
                    <TableHead className="text-right">Policy now says</TableHead>
                    <TableHead>State</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {impact.affected_parameters.map((p) => (
                    <TableRow key={p.key} className={cn(p.out_of_sync && 'bg-destructive/5')}>
                      <TableCell>
                        <Link to={`/rules?tab=parameters&q=${enc(p.key)}`} className="text-primary font-mono text-xs hover:underline">
                          {p.key}
                        </Link>
                        <div className="text-muted-foreground font-mono text-[11px]">{p.source}</div>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{String(p.current_value)}</TableCell>
                      <TableCell className="text-right font-semibold tabular-nums">{p.suggested_value ?? '—'}</TableCell>
                      <TableCell>
                        {p.out_of_sync ? (
                          <Badge variant="destructive">
                            <AlertTriangle aria-hidden /> Out of sync
                          </Badge>
                        ) : (
                          <Badge variant="success">
                            <CheckCircle2 aria-hidden /> In sync
                          </Badge>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </section>
        ) : null}

        <section>
          <h3 className="mb-2 text-sm font-semibold">Open complaints citing v{impact.old_version}</h3>
          {impact.affected_complaints.length ? (
            <div className="rounded-lg border">
              <ComplaintsTable items={impact.affected_complaints} />
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">No open complaint cites a changed section of the previous version.</p>
          )}
        </section>
      </CardContent>
    </Card>
  )
}

function ImpactPanel({ query, selected }: { query: UseQueryResult<{ doc_id: string; impacts: ImpactAnalysis[] }>; selected?: string }) {
  if (query.isLoading) return <LoadingBlock rows={5} />
  if (query.error) return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  const impacts = [...(query.data?.impacts ?? [])].reverse()
  if (!impacts.length)
    return (
      <EmptyState icon={GitCompareArrows} title="No revision impact recorded" description="Shown when a new version replaces the Active one." />
    )
  return (
    <div className="space-y-4">
      {impacts.map((i) => (
        <ImpactCard key={`${i.old_version}-${i.new_version}-${i.analysed_at}`} impact={i} highlight={i.new_version === selected} />
      ))}
    </div>
  )
}
