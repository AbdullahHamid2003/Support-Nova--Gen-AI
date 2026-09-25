import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ArrowRight, ClipboardCheck, ShieldAlert } from 'lucide-react'
import { Link, useSearchParams } from 'react-router'

import { BarList } from '@/components/app/charts'
import { EmptyState, ErrorState, LoadingBlock, PageHeader, Pagination, StatCard } from '@/components/app/common'
import { PriorityBadge, VerificationBadge } from '@/components/app/status'
import { Button } from '@/components/ui/button'
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Checkbox, NativeSelect, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/primitives'
import { api } from '@/lib/api'
import { fmtRelative } from '@/lib/format'
import { REASON_LABELS, type ReviewItem } from '@/lib/reviews'

export default function ReviewsPage() {
  const [params, setParams] = useSearchParams()
  const page = Number(params.get('page') ?? 1)
  const reason = params.get('reason') ?? ''
  const status = params.get('status') ?? ''
  const mine = params.get('mine') === 'true'
  const includeLab = params.get('include_lab') === 'true'
  const q = useQuery({
    queryKey: ['reviews', page, reason, status, mine, includeLab],
    queryFn: () => api.get<{ items: ReviewItem[]; total: number; page: number; page_size: number; reason_counts: Record<string, number> }>('/reviews', { page, page_size: 25, reason, status, mine, include_lab: includeLab }),
    placeholderData: keepPreviousData,
    refetchInterval: 20_000,
  })
  const set = (k: string, v: string | null) => {
    const next = new URLSearchParams(params)
    if (v) next.set(k, v)
    else next.delete(k)
    if (k !== 'page') next.delete('page')
    setParams(next, { replace: true })
  }
  const counts = q.data?.reason_counts ?? {}
  return (
    <>
      <PageHeader
        eyebrow="Reviews"
        title="Manual review queue"
        description="Complaints that could not be verified automatically."
      />
      <div className="mb-6 grid gap-4 lg:grid-cols-[1fr_1.3fr]">
        <div className="grid grid-cols-2 gap-4">
          <StatCard label="Waiting" value={q.data?.total ?? '—'} icon={ClipboardCheck} tone="warning" hint={status ? `status ${status}` : 'pending + in review'} />
          <StatCard label="Injection cases" value={counts.prompt_injection_detected ?? 0} icon={ShieldAlert} tone="destructive" />
        </div>
        <Card className="gap-3 py-4">
          <CardHeader>
            <CardTitle className="text-sm">Review reasons</CardTitle>
            <CardDescription>Select a reason to filter</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, n]) => (
                <button key={k} type="button" onClick={() => set('reason', reason === k ? null : k)} className="focus-visible:ring-ring/40 rounded-md focus-visible:ring-2">
                  <Badge variant={reason === k ? 'primary' : 'outline'} className="cursor-pointer">{REASON_LABELS[k] ?? k} · {n}</Badge>
                </button>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <NativeSelect aria-label="Review status" className="h-8 w-auto text-xs" value={status} onChange={(e) => set('status', e.target.value || null)}>
          <option value="">Open (pending + in review)</option>
          <option value="pending">Pending</option>
          <option value="in_review">In review</option>
          <option value="completed">Completed</option>
        </NativeSelect>
        <label className="flex items-center gap-1.5 text-xs"><Checkbox checked={mine} onCheckedChange={(c) => set('mine', c ? 'true' : null)} /> Claimed by me</label>
        <label className="flex items-center gap-1.5 text-xs"><Checkbox checked={includeLab} onCheckedChange={(c) => set('include_lab', c ? 'true' : null)} /> Include Adversarial Lab cases</label>
      </div>
      <Card className="py-0">
        <CardContent className="px-0">
          {q.isLoading ? <div className="p-5"><LoadingBlock rows={8} /></div> : q.error ? <div className="p-5"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div> : q.data!.items.length === 0 ? (
            <div className="p-5"><EmptyState icon={ClipboardCheck} title="Queue is clear" description="Nothing needs review right now." /></div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Complaint</TableHead>
                  <TableHead>Priority</TableHead>
                  <TableHead>Why</TableHead>
                  <TableHead className="hidden lg:table-cell">Verification</TableHead>
                  <TableHead className="hidden md:table-cell">Queued</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {q.data!.items.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="max-w-[20rem]">
                      <div className="font-mono text-xs font-semibold text-primary">{r.complaint?.complaint_ref}</div>
                      <div className="truncate text-sm">{r.complaint?.title}</div>
                      <div className="text-muted-foreground truncate text-xs">{r.complaint?.subcategory} · {r.complaint?.department}</div>
                    </TableCell>
                    <TableCell><PriorityBadge priority={r.priority} compact /></TableCell>
                    <TableCell className="max-w-[18rem]">
                      <div className="flex flex-wrap gap-1">{r.reason_codes.slice(0, 3).map((code) => <Badge key={code} variant="warning" className="text-[10.5px]">{REASON_LABELS[code] ?? code}</Badge>)}{r.reason_codes.length > 3 ? <Badge variant="muted">+{r.reason_codes.length - 3}</Badge> : null}</div>
                    </TableCell>
                    <TableCell className="hidden lg:table-cell"><VerificationBadge status={r.complaint?.verification_status} score={r.complaint?.verification_score} /></TableCell>
                    <TableCell className="text-muted-foreground hidden text-xs md:table-cell">{fmtRelative(r.created_at)}</TableCell>
                    <TableCell>{r.status === 'completed' ? <Badge variant="success">{r.final_decision ?? 'done'}</Badge> : r.status === 'in_review' ? <Badge variant="info">in review</Badge> : <Badge variant="warning">pending</Badge>}</TableCell>
                    <TableCell className="text-right"><Button asChild size="sm" variant={r.status === 'completed' ? 'ghost' : 'secondary'}><Link to={`/reviews/${r.id}`}>{r.status === 'completed' ? 'View' : 'Review'} <ArrowRight /></Link></Button></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      {q.data && q.data.total > 25 ? <Pagination page={page} pageSize={25} total={q.data.total} onPage={(p) => set('page', String(p))} /> : null}
      {Object.keys(counts).length ? (
        <Card className="mt-6">
          <CardHeader><CardTitle className="text-sm">Reason breakdown</CardTitle></CardHeader>
          <CardContent><BarList items={Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, n]) => ({ label: REASON_LABELS[k] ?? k, value: n }))} colorBy={() => 'var(--warning)'} /></CardContent>
        </Card>
      ) : null}
    </>
  )
}
