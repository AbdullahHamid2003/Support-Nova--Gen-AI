/* Model evaluation (SRS Deliverable 8, hidden-dataset readiness): unseen cases run through the
   production pipeline and GenAI (Pipeline 1), Python ground truth (Pipeline 2) and the expected labels
   are compared. Expected labels are read only by the scorer - never by the pipeline. */
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Database, FileUp, FlaskConical, Play, ShieldCheck, Upload } from 'lucide-react'
import * as React from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { z } from 'zod'

import { EmptyState, ErrorState, Field, LoadingBlock, PageHeader, Spinner } from '@/components/app/common'
import { InfoTip, RunStatusBadge } from '@/components/insights/common'
import { FaultProfileNote, FaultProfileOptions } from '@/components/insights/fault-profile-note'
import { faultTitle } from '@/components/insights/fault-profiles'
import { isActiveRun } from '@/components/insights/format'
import type { EvaluationRun, EvaluationRunList } from '@/components/insights/types'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/overlays'
import {
  Alert, AlertDescription, AlertTitle, Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, NativeSelect, Progress,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/primitives'
import { ApiError, api, errorMessage } from '@/lib/api'
import { useAuth, usePublicConfig } from '@/lib/auth'
import { fmtBytes, fmtDateTime, fmtRelative } from '@/lib/format'
import { cn, num, pct } from '@/lib/utils'

interface Dataset { key: string; path: string; exists: boolean; records: number }
interface DatasetsResponse { items: Dataset[]; fault_profiles: Record<string, string> }

const MAX_RECORDS = 5000

const DATASET_NAMES: Record<string, { name: string; note: string }> = {
  holdout: { name: 'Holdout set', note: 'Cases never used for tuning. Use it to measure accuracy.' },
  dev: { name: 'Development set', note: 'Cases the demo data came from; not for measuring accuracy.' },
}
function datasetName(key: string): string {
  if (DATASET_NAMES[key]) return DATASET_NAMES[key].name
  return key.startsWith('file:') ? key.slice(5) : key
}

export default function EvaluationPage() {
  const { can } = useAuth()
  const config = usePublicConfig()
  const datasets = useQuery({ queryKey: ['evaluation', 'datasets'], queryFn: () => api.get<DatasetsResponse>('/evaluation/datasets') })
  const runs = useQuery({
    queryKey: ['evaluation', 'runs'],
    queryFn: () => api.get<EvaluationRunList>('/evaluation/runs'),
    refetchInterval: (q) => (q.state.data?.items.some((r) => isActiveRun(r.status)) ? 2000 : false),
  })
  const items = runs.data?.items ?? []
  const active = items.find((r) => isActiveRun(r.status))
  const latestDone = items.find((r) => r.status === 'completed')
  const canRun = can('evaluation:run')
  const ai = config.data?.ai

  return (
    <>
      <PageHeader
        eyebrow="Insight & quality"
        title="Model evaluation"
        description="Test AI and rules accuracy against expected labels."
        actions={
          latestDone ? (
            <Button asChild variant="outline" size="sm">
              <Link to={`/evaluation/${latestDone.id}`}>Latest results (run #{latestDone.id}) <ArrowRight /></Link>
            </Button>
          ) : null
        }
      />

      {active ? <ActiveRunBanner run={active} /> : null}

      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Start an evaluation run</CardTitle>
            <CardDescription>
              {ai ? (
                <span className="inline-flex flex-wrap items-center gap-1.5">
                  AI model: <span className="text-foreground font-mono text-xs">{ai.provider} / {ai.model}</span>
                  {ai.configured === false ? <Badge variant="warning">Not configured</Badge> : <Badge variant="validate">Live model</Badge>}
                </span>
              ) : (
                'Runs in the background; this page updates live.'
              )}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!canRun ? (
              <Alert variant="info">
                <ShieldCheck />
                <AlertTitle>Read-only access</AlertTitle>
                <AlertDescription>
                  <p>You can view results. Only an administrator can start a run.</p>
                </AlertDescription>
              </Alert>
            ) : datasets.isLoading ? (
              <LoadingBlock rows={4} />
            ) : datasets.error ? (
              <ErrorState error={datasets.error} onRetry={() => datasets.refetch()} />
            ) : (
              <Tabs defaultValue="dataset">
                <TabsList aria-label="Evaluation source">
                  <TabsTrigger value="dataset"><Database aria-hidden /> From a dataset</TabsTrigger>
                  <TabsTrigger value="upload"><FileUp aria-hidden /> Upload a dataset</TabsTrigger>
                </TabsList>
                <TabsContent value="dataset">
                  <StartRunForm datasets={datasets.data!.items} faultProfiles={datasets.data!.fault_profiles} busy={!!active} />
                </TabsContent>
                <TabsContent value="upload">
                  <UploadRunForm faultProfiles={datasets.data!.fault_profiles} busy={!!active} maxMb={config.data?.limits.max_upload_mb ?? 15} />
                </TabsContent>
              </Tabs>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5">
              Available datasets
              <InfoTip>Built-in test sets and files added on the server.</InfoTip>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {datasets.isLoading ? (
              <LoadingBlock rows={3} />
            ) : datasets.error ? (
              <ErrorState error={datasets.error} onRetry={() => datasets.refetch()} />
            ) : (
              <ul className="space-y-2">
                {datasets.data!.items.map((d) => (
                  <li key={d.key} className="rounded-lg border p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium">{datasetName(d.key)}</span>
                      {d.exists ? <Badge variant="secondary" className="tabular-nums">{num(d.records)} cases</Badge> : <Badge variant="warning">Missing</Badge>}
                    </div>
                    {DATASET_NAMES[d.key] ? <p className="text-muted-foreground mt-1 text-xs">{DATASET_NAMES[d.key].note}</p> : null}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-6 py-0">
        <CardHeader className="pt-5">
          <CardTitle>Evaluation runs</CardTitle>
          <CardDescription>Latest 50 runs. Open a run for full results.</CardDescription>
        </CardHeader>
        <CardContent className="px-0 pb-2">
          {runs.isLoading ? (
            <div className="px-5 pb-4"><LoadingBlock rows={4} /></div>
          ) : runs.error ? (
            <div className="px-5 pb-4"><ErrorState error={runs.error} onRetry={() => runs.refetch()} /></div>
          ) : items.length === 0 ? (
            <div className="px-5 pb-4">
              <EmptyState icon={FlaskConical} title="No evaluation runs yet" description={canRun ? 'Start a run above to see results.' : 'An administrator can start a run.'} />
            </div>
          ) : (
            <RunsTable runs={items} />
          )}
        </CardContent>
      </Card>
    </>
  )
}

function ActiveRunBanner({ run }: { run: EvaluationRun }) {
  const value = run.n_cases ? Math.round((run.n_done / run.n_cases) * 100) : 0
  return (
    <Card className="border-info/40 bg-info/5 mb-6 gap-3 py-4" role="status" aria-live="polite">
      <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex items-center gap-2.5">
          <Spinner className="text-info" />
          <div className="text-sm">
            <span className="font-medium">Run #{run.id} · {run.label}</span>
            <span className="text-muted-foreground"> — {run.status === 'queued' ? 'queued' : `${num(run.n_done)} of ${num(run.n_cases)} cases processed`}</span>
          </div>
        </div>
        <Progress value={value} className="sm:flex-1" aria-label={`Run ${run.id} progress`} indicatorClassName="bg-info" />
        <Button asChild size="sm" variant="outline">
          <Link to={`/evaluation/${run.id}`}>Watch live <ArrowRight /></Link>
        </Button>
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------------ start a run from a dataset
const runSchema = z.object({
  dataset: z.string().min(1, 'Choose a dataset.'),
  label: z.string().trim().max(120, 'Keep the label under 120 characters.'),
  limit: z
    .string()
    .trim()
    .refine((v) => v === '' || (/^\d+$/.test(v) && Number(v) >= 1 && Number(v) <= MAX_RECORDS), `Enter a whole number from 1 to ${MAX_RECORDS}, or leave empty for every case.`),
  fault_profile: z.string(),
})
type RunValues = z.infer<typeof runSchema>

function StartRunForm({ datasets, faultProfiles, busy }: { datasets: Dataset[]; faultProfiles: Record<string, string>; busy: boolean }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const usable = datasets.filter((d) => d.exists)
  const form = useForm<RunValues>({
    resolver: zodResolver(runSchema),
    defaultValues: { dataset: usable.find((d) => d.key === 'holdout')?.key ?? usable[0]?.key ?? '', label: '', limit: '', fault_profile: '' },
  })
  const errors = form.formState.errors
  const [datasetKey, faultProfile] = useWatch({ control: form.control, name: ['dataset', 'fault_profile'] })
  const selected = usable.find((d) => d.key === datasetKey)

  const start = useMutation({
    mutationFn: (v: RunValues) =>
      api.post<EvaluationRun>('/evaluation/runs', {
        dataset: v.dataset,
        label: v.label,
        limit: v.limit ? Number(v.limit) : null,
        fault_profile: v.fault_profile || null,
      }),
    onSuccess: (run) => {
      qc.invalidateQueries({ queryKey: ['evaluation', 'runs'] })
      toast.success(`Evaluation run #${run.id} started`, {
        description: `${num(run.n_cases)} cases · ${run.provider} / ${run.model}`,
        action: { label: 'Open', onClick: () => navigate(`/evaluation/${run.id}`) },
      })
      form.reset({ ...form.getValues(), label: '' })
    },
    onError: (e) => {
      if (e instanceof ApiError) Object.entries(e.fieldErrors).forEach(([f, message]) => { if (f in runSchema.shape) form.setError(f as keyof RunValues, { message }) })
      toast.error(errorMessage(e))
    },
  })

  if (usable.length === 0) {
    return <EmptyState icon={Database} title="No datasets found" description="Upload a dataset file instead." />
  }

  return (
    <form className="space-y-4" noValidate onSubmit={form.handleSubmit((v) => start.mutate(v))}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Dataset" htmlFor="ev-dataset" error={errors.dataset?.message} required>
          <NativeSelect id="ev-dataset" aria-invalid={!!errors.dataset} {...form.register('dataset')}>
            {usable.map((d) => (
              <option key={d.key} value={d.key}>{datasetName(d.key)} — {num(d.records)} cases</option>
            ))}
          </NativeSelect>
        </Field>
        <Field label="Label" htmlFor="ev-label" error={errors.label?.message} hint="Shown in the run list and on the report.">
          <Input id="ev-label" placeholder={`e.g. ${datasetKey || 'holdout'} — prompt v1.1`} maxLength={120} aria-invalid={!!errors.label} {...form.register('label')} />
        </Field>
        <Field label="Case limit" htmlFor="ev-limit" error={errors.limit?.message} hint="Optional. Run only the first N cases for a quick check.">
          <Input id="ev-limit" inputMode="numeric" placeholder={selected ? `All ${num(selected.records)}` : 'All'} aria-invalid={!!errors.limit} {...form.register('limit')} />
        </Field>
        <Field label="Deliberate AI defect" htmlFor="ev-fault" hint="Optional. Corrupt every AI answer to test the rule check.">
          <NativeSelect id="ev-fault" {...form.register('fault_profile')}>
            <FaultProfileOptions profiles={faultProfiles} noneLabel="None — evaluate the model as it is" />
          </NativeSelect>
        </Field>
      </div>
      <FaultProfileNote profile={faultProfile} profiles={faultProfiles} />
      <div className="flex flex-wrap items-center gap-3 border-t pt-4">
        <Button type="submit" disabled={start.isPending || busy}>
          {start.isPending ? <Spinner /> : <Play />} Start run
        </Button>
        {busy ? <span className="text-muted-foreground text-xs">A run is in progress. Wait for it to finish or cancel it.</span> : <span className="text-muted-foreground text-xs">Takes a few seconds per case. Nothing is sent to customers.</span>}
      </div>
    </form>
  )
}

// ------------------------------------------------------------------ upload an external / hidden dataset
function UploadRunForm({ faultProfiles, busy, maxMb }: { faultProfiles: Record<string, string>; busy: boolean; maxMb: number }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const inputRef = React.useRef<HTMLInputElement>(null)
  const [file, setFile] = React.useState<File | null>(null)
  const [label, setLabel] = React.useState('')
  const [fault, setFault] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)

  const upload = useMutation({
    mutationFn: () => {
      const form = new FormData()
      form.append('file', file!)
      form.append('label', label.trim())
      form.append('fault_profile', fault)
      return api.upload<EvaluationRun>('/evaluation/runs/upload', form)
    },
    onSuccess: (run) => {
      qc.invalidateQueries({ queryKey: ['evaluation', 'runs'] })
      toast.success(`Evaluation run #${run.id} started`, {
        description: `${num(run.n_cases)} cases from ${file?.name ?? 'the uploaded file'}`,
        action: { label: 'Open', onClick: () => navigate(`/evaluation/${run.id}`) },
      })
      setFile(null)
      setLabel('')
      if (inputRef.current) inputRef.current.value = ''
    },
    onError: (e) => {
      setError(errorMessage(e))
      toast.error(errorMessage(e))
    },
  })

  const pick = (f: File | null) => {
    setError(null)
    if (!f) return setFile(null)
    const ext = f.name.split('.').pop()?.toLowerCase() ?? ''
    if (!['json', 'jsonl', 'csv'].includes(ext)) {
      setFile(null)
      setError('Use a .json, .jsonl or .csv file.')
      return
    }
    if (f.size > maxMb * 1024 * 1024) {
      setFile(null)
      setError(`The file is larger than the ${maxMb} MB limit.`)
      return
    }
    setFile(f)
  }

  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        if (!file) return setError('Choose a dataset file to upload.')
        upload.mutate()
      }}
    >
      <Field label="Dataset file" htmlFor="ev-file" error={error ?? undefined} hint={file ? `${file.name} · ${fmtBytes(file.size)}` : `JSON, JSONL or CSV · up to ${num(MAX_RECORDS)} records · max ${maxMb} MB`} required>
        <Input id="ev-file" ref={inputRef} type="file" accept=".json,.jsonl,.csv,application/json,text/csv" aria-invalid={!!error} onChange={(e) => pick(e.target.files?.[0] ?? null)} />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Label" htmlFor="ev-up-label" hint="Defaults to the file name.">
          <Input id="ev-up-label" value={label} maxLength={120} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Q3 test set" />
        </Field>
        <Field label="Deliberate AI defect" htmlFor="ev-up-fault">
          <NativeSelect id="ev-up-fault" value={fault} onChange={(e) => setFault(e.target.value)}>
            <FaultProfileOptions profiles={faultProfiles} noneLabel="None — evaluate the model as it is" />
          </NativeSelect>
        </Field>
      </div>
      <FaultProfileNote profile={fault} profiles={faultProfiles} />
      <details className="bg-muted/30 rounded-lg border px-3 py-2 text-sm">
        <summary className="cursor-pointer font-medium">Accepted formats</summary>
        <ul className="text-muted-foreground mt-2 list-disc space-y-1 pl-5 text-xs">
          <li><strong>JSON</strong> — an array of complaint records, or an object with a <code className="font-mono">complaints</code> or <code className="font-mono">records</code> array.</li>
          <li><strong>JSONL</strong> — one complaint record per line.</li>
          <li><strong>CSV</strong> — one record per row; <code className="font-mono">expected_*</code> columns hold the expected labels.</li>
          <li>Only <code className="font-mono">title</code> and <code className="font-mono">description</code> are required; other fields are ignored.</li>
          <li>Add an <code className="font-mono">expected</code> object to measure accuracy. Without it, only AI vs rules agreement is measured.</li>
        </ul>
      </details>
      <div className="flex flex-wrap items-center gap-3 border-t pt-4">
        <Button type="submit" disabled={upload.isPending || busy || !file}>
          {upload.isPending ? <Spinner /> : <Upload />} Upload & evaluate
        </Button>
        {busy ? <span className="text-muted-foreground text-xs">A run is in progress. Wait for it to finish or cancel it.</span> : null}
      </div>
    </form>
  )
}

// ------------------------------------------------------------------ runs table
function RunsTable({ runs }: { runs: EvaluationRun[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="pl-5">Run</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="min-w-40">Progress</TableHead>
          <TableHead>AI model</TableHead>
          <TableHead>Defect</TableHead>
          <TableHead className="text-right">
            <span className="inline-flex items-center gap-1">Rules acc. <InfoTip>Rules accuracy on the 6 key fields vs expected labels.</InfoTip></span>
          </TableHead>
          <TableHead className="text-right">
            <span className="inline-flex items-center gap-1">AI acc. <InfoTip>AI accuracy on the 6 key fields, before the rule check.</InfoTip></span>
          </TableHead>
          <TableHead className="text-right">
            <span className="inline-flex items-center gap-1">Errors caught <InfoTip>AI errors the rules fixed or sent to review.</InfoTip></span>
          </TableHead>
          <TableHead>Started</TableHead>
          <TableHead className="pr-5"><span className="sr-only">Open</span></TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((r) => {
          const h = r.metrics?.headline
          const progress = r.n_cases ? Math.round((r.n_done / r.n_cases) * 100) : 0
          return (
            <TableRow key={r.id}>
              <TableCell className="pl-5">
                <Link to={`/evaluation/${r.id}`} className="text-primary font-mono text-xs font-semibold hover:underline">#{r.id}</Link>
                <div className="max-w-[14rem] truncate text-sm font-medium" title={r.label}>{r.label}</div>
                <div className="text-muted-foreground text-xs">{datasetName(r.split)}</div>
              </TableCell>
              <TableCell>
                <RunStatusBadge status={r.status} />
                {r.error ? <div className="text-destructive mt-1 max-w-[12rem] truncate text-xs" title={r.error}>{r.error}</div> : null}
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <Progress value={progress} className="h-1.5 flex-1" aria-label={`Run ${r.id}: ${r.n_done} of ${r.n_cases} cases`} indicatorClassName={cn(r.status === 'completed' ? 'bg-success' : r.status === 'failed' ? 'bg-destructive' : 'bg-info')} />
                  <span className="text-muted-foreground w-16 text-right text-xs tabular-nums">{num(r.n_done)}/{num(r.n_cases)}</span>
                </div>
              </TableCell>
              <TableCell>
                <div className="max-w-[11rem] truncate font-mono text-xs" title={`${r.provider} / ${r.model}`}>{r.provider} / {r.model}</div>
              </TableCell>
              <TableCell>{r.fault_injection ? <Badge variant="warning" title={r.fault_injection}>{faultTitle(r.fault_injection)}</Badge> : <span className="text-muted-foreground text-xs">none</span>}</TableCell>
              <TableCell className="text-validate text-right font-semibold tabular-nums">{pct(h?.python_key_field_accuracy, 1)}</TableCell>
              <TableCell className="text-primary text-right font-semibold tabular-nums">{pct(h?.ai_key_field_accuracy, 1)}</TableCell>
              <TableCell className="text-right tabular-nums">
                {h ? (
                  <>
                    <span className="font-semibold">{num(h.ai_errors_caught)}</span>
                    <span className="text-muted-foreground">/{num(h.ai_cases_with_key_errors)}</span>
                    <div className="text-muted-foreground text-xs">{pct(h.ai_error_catch_rate, 1)}</div>
                  </>
                ) : (
                  '—'
                )}
              </TableCell>
              <TableCell className="text-sm">
                <div>{fmtDateTime(r.created_at)}</div>
                <div className="text-muted-foreground text-xs">{fmtRelative(r.created_at)}{r.duration_seconds !== null ? ` · ${num(r.duration_seconds, 1)} s` : ''}</div>
              </TableCell>
              <TableCell className="pr-5 text-right">
                <Button asChild variant="ghost" size="sm">
                  <Link to={`/evaluation/${r.id}`} aria-label={`Open evaluation run ${r.id}`}>Open <ArrowRight /></Link>
                </Button>
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}
