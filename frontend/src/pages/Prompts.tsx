import { zodResolver } from '@hookform/resolvers/zod'
import { keepPreviousData, useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'
import { Activity, AlertTriangle, CheckCircle2, FileCode2, FlaskConical, KeyRound, Plus, Power, RefreshCw, ShieldCheck, Sparkles, Wand2, XCircle } from 'lucide-react'
import * as React from 'react'
import { Controller, useForm, useWatch } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { CopyButton, EmptyState, ErrorState, Field, KeyValue, LoadingBlock, PageHeader, Spinner } from '@/components/app/common'
import { CheckIcon } from '@/components/app/status'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Tooltip } from '@/components/ui/overlays'
import {
  Alert, AlertDescription, AlertTitle, Badge, Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle, Checkbox, Input, NativeSelect, Table, TableBody,
  TableCell, TableHead, TableHeader, TableRow, Textarea,
} from '@/components/ui/primitives'
import { ApiError, api, errorMessage } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { fmtDate, fmtDateTime, fmtMs, fmtRelative } from '@/lib/format'
import { cn, titleCase } from '@/lib/utils'

// ------------------------------------------------------------------ API shapes
interface PromptVersion {
  version: string
  status: string
  output_schema: string
  params: Record<string, unknown>
  changelog: string
  sha256: string
  created_at: string | null
  system_template: string
  user_template: string
}
interface PromptItem {
  key: string
  description: string
  versions: PromptVersion[]
}
interface AiStatus {
  configured_provider: string
  resolved_provider: string
  active_provider: { provider?: string; model?: string; [k: string]: unknown }
  api_key_configured: boolean
  timeout_seconds: number
  max_attempts: number
  embedding_provider: string
  fault_profiles: Record<string, string>
  /** non-null only when no API key is configured */
  notice: string | null
}
interface AiRun {
  id: number
  complaint_id: number | null
  stage: string
  attempt: number
  provider: string
  model: string
  prompt: string
  parsed_ok: boolean
  error_type: string | null
  error_message: string | null
  latency_ms: number | null
  fault_injection: string | null
  at: string
}
interface AiRuns {
  items: AiRun[]
  stats: { valid: number; invalid: number }
}

const enc = encodeURIComponent
const REQUIRED_PLACEHOLDERS = ['$complaint', '$nonce'] as const
const PLACEHOLDER = /(\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$[A-Za-z_][A-Za-z0-9_]*)/g

function placeholders(text: string): string[] {
  return [...new Set((text.match(PLACEHOLDER) ?? []).map((p) => p.replace(/[{}]/g, '')))]
}

function semverKey(v: string): number[] {
  return v.split('.').map((p) => Number(p) || 0)
}
function compareSemver(a: string, b: string): number {
  const ka = semverKey(a)
  const kb = semverKey(b)
  for (let i = 0; i < 3; i++) if ((ka[i] ?? 0) !== (kb[i] ?? 0)) return (ka[i] ?? 0) - (kb[i] ?? 0)
  return 0
}
function nextVersion(versions: PromptVersion[]): string {
  const latest = [...versions].sort((a, b) => compareSemver(b.version, a.version))[0]
  if (!latest) return '1.0.0'
  const [major, minor] = semverKey(latest.version)
  return `${major ?? 1}.${(minor ?? 0) + 1}.0`
}

export default function PromptsPage() {
  const { can } = useAuth()
  const manage = can('prompts:manage')
  const canRuns = can('evaluation:read')
  const status = useQuery({ queryKey: ['ai', 'status'], queryFn: () => api.get<AiStatus>('/ai/status') })
  const prompts = useQuery({ queryKey: ['prompts'], queryFn: () => api.get<{ items: PromptItem[] }>('/prompts') })

  return (
    <>
      <PageHeader
        eyebrow="Policies & rules"
        title="Prompts & AI"
        description="Manage prompt templates, check the AI provider and review AI calls."
      />
      <ProviderCard query={status} />

      <section className="mt-8 space-y-4" aria-labelledby="templates-title">
        <div>
          <h2 id="templates-title" className="text-lg font-semibold tracking-tight">
            Prompt templates
          </h2>
          <p className="text-muted-foreground text-sm">One version per prompt is active at a time.</p>
        </div>
        {prompts.isLoading ? (
          <LoadingBlock rows={6} />
        ) : prompts.error ? (
          <ErrorState error={prompts.error} onRetry={() => prompts.refetch()} />
        ) : (prompts.data?.items ?? []).length === 0 ? (
          <EmptyState icon={Wand2} title="No prompt templates" description="Templates appear here once the server has loaded them." />
        ) : (
          (prompts.data?.items ?? []).map((p) => <PromptCard key={p.key} prompt={p} manage={manage} />)
        )}
      </section>

      {canRuns ? (
        <section className="mt-8" aria-label="Recent AI attempts">
          <AiRunsCard />
        </section>
      ) : null}
    </>
  )
}

// ------------------------------------------------------------------ provider status
function ProviderCard({ query }: { query: UseQueryResult<AiStatus> }) {
  if (query.isLoading)
    return (
      <Card>
        <CardContent>
          <LoadingBlock rows={3} />
        </CardContent>
      </Card>
    )
  if (query.error) return <ErrorState error={query.error} onRetry={() => query.refetch()} title="Could not load the AI provider status" />
  const s = query.data
  if (!s) return null
  const provider = String(s.active_provider.provider ?? s.resolved_provider)
  const model = String(s.active_provider.model ?? '—')
  const faults = Object.entries(s.fault_profiles ?? {})
  const configured = s.api_key_configured
  return (
    <Card className={cn('overflow-hidden pt-0', configured ? 'border-validate/40' : 'border-warning/50')}>
      <div className={cn('h-1.5', configured ? 'nova-gradient' : 'bg-warning')} aria-hidden />
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-lg">
          {configured ? <Sparkles className="text-validate size-5" aria-hidden /> : <KeyRound className="size-5 text-[oklch(0.5_0.13_60)] dark:text-warning" aria-hidden />}
          {configured ? `AI connected - ${provider} / ${model}` : 'AI not configured'}
          {configured ? <Badge variant="validate">Live AI</Badge> : <Badge variant="warning">No API key</Badge>}
        </CardTitle>
        {configured ? null : <CardDescription className="max-w-4xl">Add the API key on the server and restart it.</CardDescription>}
      </CardHeader>
      <CardContent className="space-y-4">
        <KeyValue
          columns={3}
          items={[
            ['Provider', <span key="p" className="font-medium">{provider}</span>],
            ['Model', <code key="m" className="font-mono text-xs">{model}</code>],
            ['Provider setting', s.configured_provider],
            ['Resolved provider', s.resolved_provider],
            [
              'API key',
              s.api_key_configured ? (
                <Badge key="k" variant="success">
                  <KeyRound aria-hidden /> Configured
                </Badge>
              ) : (
                <Badge key="k" variant="muted">
                  Not configured
                </Badge>
              ),
            ],
            ['Timeout per attempt', `${s.timeout_seconds} s`],
            ['Attempts per stage', s.max_attempts],
            ['Embedding provider', s.embedding_provider],
          ]}
        />
        {faults.length ? (
          <details className="group rounded-lg border">
            <summary className="hover:bg-muted/40 flex cursor-pointer list-none items-center gap-2 rounded-lg px-3 py-2.5 text-sm font-medium">
              <FlaskConical className="text-muted-foreground size-4" aria-hidden /> Fault-injection profiles ({faults.length})
              <span className="text-muted-foreground ml-auto text-xs group-open:hidden">Show</span>
              <span className="text-muted-foreground ml-auto hidden text-xs group-open:inline">Hide</span>
            </summary>
            <div className="border-t px-3 py-3">
              <p className="text-muted-foreground mb-2 text-xs">Used by the Adversarial Lab to simulate faulty AI output.</p>
              <ul className="grid gap-2 md:grid-cols-2">
                {faults.map(([k, d]) => (
                  <li key={k} className="text-sm">
                    <code className="font-mono text-xs font-semibold">{k}</code>
                    <p className="text-muted-foreground text-xs">{d}</p>
                  </li>
                ))}
              </ul>
            </div>
          </details>
        ) : null}
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------------ prompt templates
const PROMPT_STATUS: Record<string, { v: 'success' | 'warning' | 'muted'; label: string }> = {
  active: { v: 'success', label: 'Active' },
  draft: { v: 'warning', label: 'Draft' },
  retired: { v: 'muted', label: 'Retired' },
}

function PromptStatusBadge({ status }: { status: string }) {
  const cfg = PROMPT_STATUS[status] ?? { v: 'muted' as const, label: titleCase(status) }
  return <Badge variant={cfg.v}>{cfg.label}</Badge>
}

function TemplateText({ text }: { text: string }) {
  const parts = text.split(PLACEHOLDER)
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <span key={i} className={cn('rounded px-0.5 font-semibold', (REQUIRED_PLACEHOLDERS as readonly string[]).includes(p.replace(/[{}]/g, '')) ? 'bg-validate/15 text-validate' : 'bg-primary/10 text-primary')}>
            {p}
          </span>
        ) : (
          <React.Fragment key={i}>{p}</React.Fragment>
        ),
      )}
    </>
  )
}

function TemplateBlock({ label, text }: { label: string; text: string }) {
  return (
    <div className="min-w-0 overflow-hidden rounded-lg border">
      <div className="bg-card flex items-center gap-2 border-b px-3 py-1.5">
        <FileCode2 className="text-muted-foreground size-3.5" aria-hidden />
        <span className="text-xs font-semibold">{label}</span>
        <span className="text-muted-foreground ml-auto text-[11px] tabular-nums">{text.length.toLocaleString()} chars</span>
        <CopyButton value={text} label={`Copy the ${label.toLowerCase()}`} />
      </div>
      <pre className="bg-muted/40 max-h-80 overflow-auto p-3 font-mono text-[11.5px] leading-relaxed break-words whitespace-pre-wrap scrollbar-thin">
        <TemplateText text={text} />
      </pre>
    </div>
  )
}

function PlaceholderCheck({ system, user, baseline }: { system: string; user: string; baseline?: string[] }) {
  const found = placeholders(`${system}\n${user}`)
  const missing = (baseline ?? []).filter((p) => !found.includes(p))
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {REQUIRED_PLACEHOLDERS.map((p) => {
          const ok = system.includes(p) || user.includes(p)
          return (
            <span key={p} className={cn('inline-flex items-center gap-1 rounded-md border px-2 py-1 font-medium', ok ? 'border-success/30 bg-success/8 text-success' : 'border-destructive/30 bg-destructive/8 text-destructive')}>
              <CheckIcon status={ok ? 'pass' : 'fail'} className="size-3.5" />
              <code className="font-mono">{p}</code> {ok ? 'present' : 'missing'}
            </span>
          )
        })}
        <Tooltip content="Keeps complaint text separate from the instructions.">
          <span className="text-muted-foreground inline-flex cursor-help items-center gap-1" tabIndex={0}>
            <ShieldCheck className="size-3.5" aria-hidden /> Why required?
          </span>
        </Tooltip>
      </div>
      {found.length ? (
        <div className="text-muted-foreground flex flex-wrap items-center gap-1 text-xs">
          Placeholders:
          {found.map((p) => (
            <code key={p} className="bg-muted rounded px-1 py-0.5 font-mono text-[11px]">
              {p}
            </code>
          ))}
        </div>
      ) : null}
      {missing.length ? (
        <p className="flex items-start gap-1.5 text-xs text-[oklch(0.45_0.12_60)] dark:text-warning">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden /> No longer used compared with the base version: {missing.join(', ')}. The AI will not see this information.
        </p>
      ) : null}
    </div>
  )
}

function PromptCard({ prompt, manage }: { prompt: PromptItem; manage: boolean }) {
  const versions = [...prompt.versions].sort((a, b) => compareSemver(b.version, a.version))
  const active = versions.find((v) => v.status === 'active')
  const [selected, setSelected] = React.useState<string | undefined>(active?.version ?? versions[0]?.version)
  const [creating, setCreating] = React.useState(false)
  const [activating, setActivating] = React.useState<PromptVersion | null>(null)
  const v = versions.find((x) => x.version === selected) ?? active ?? versions[0]
  if (!v) return null
  const params = Object.entries(v.params ?? {})

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <Wand2 className="text-primary size-4.5" aria-hidden /> <code className="font-mono">{prompt.key}</code>
          {active ? (
            <Badge variant="outline" className="font-mono font-normal">
              active v{active.version}
            </Badge>
          ) : (
            <Badge variant="destructive">No active version</Badge>
          )}
        </CardTitle>
        <CardDescription>{prompt.description}</CardDescription>
        {manage ? (
          <CardAction>
            <Button size="sm" variant="outline" onClick={() => setCreating(true)}>
              <Plus /> New version
            </Button>
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent className="grid gap-6 lg:grid-cols-[14rem_minmax(0,1fr)]">
        <nav aria-label={`${prompt.key} versions`}>
          <ol className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin lg:flex-col lg:overflow-visible">
            {versions.map((x) => {
              const sel = x.version === v.version
              return (
                <li key={x.version} className="shrink-0 lg:shrink">
                  <button
                    type="button"
                    aria-pressed={sel}
                    onClick={() => setSelected(x.version)}
                    className={cn(
                      'focus-visible:ring-ring/40 w-52 rounded-lg border p-2.5 text-left transition-colors outline-none focus-visible:ring-[3px] lg:w-full',
                      sel ? 'border-primary bg-primary/5 ring-primary/15 ring-2' : 'hover:bg-accent/40',
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-sm font-semibold">v{x.version}</span>
                      <PromptStatusBadge status={x.status} />
                    </div>
                    {x.changelog ? <div className="text-muted-foreground mt-1 line-clamp-2 text-xs">{x.changelog}</div> : null}
                    <div className="text-muted-foreground mt-1 text-[11px]">{fmtDate(x.created_at)}</div>
                  </button>
                </li>
              )
            })}
          </ol>
        </nav>

        <div className="min-w-0 space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-mono text-sm font-semibold">
              {prompt.key}@{v.version}
            </h3>
            <PromptStatusBadge status={v.status} />
            {manage && v.status !== 'active' ? (
              <Button size="sm" className="ml-auto" onClick={() => setActivating(v)}>
                <Power /> Activate v{v.version}
              </Button>
            ) : null}
          </div>
          <KeyValue
            columns={3}
            items={[
              ['Output schema', <code key="o" className="font-mono text-xs">{v.output_schema}</code>],
              ['Model parameters', params.length ? params.map(([k, val]) => `${k}: ${String(val)}`).join(' · ') : 'Defaults'],
              ['Created', v.created_at ? <span key="c" title={fmtDateTime(v.created_at)}>{fmtRelative(v.created_at)}</span> : '—'],
            ]}
          />
          <div className="min-w-0">
            <div className="text-muted-foreground text-xs font-medium">Fingerprint</div>
            <div className="flex items-center gap-1">
              <code className="min-w-0 truncate font-mono text-[11px]" title={v.sha256}>
                {v.sha256}
              </code>
              <CopyButton value={v.sha256} label="Copy fingerprint" />
            </div>
          </div>
          <PlaceholderCheck system={v.system_template} user={v.user_template} />
          <div className="grid gap-4 2xl:grid-cols-2">
            <TemplateBlock label="System template" text={v.system_template} />
            <TemplateBlock label="User template" text={v.user_template} />
          </div>
          {v.changelog ? (
            <p className="text-sm">
              <span className="text-muted-foreground">Changelog:</span> {v.changelog}
            </p>
          ) : null}
        </div>
      </CardContent>

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent className="max-w-4xl">
          {creating ? (
            <NewVersionForm
              prompt={prompt}
              base={v}
              onClose={() => setCreating(false)}
              onCreated={(version) => {
                setCreating(false)
                setSelected(version)
              }}
            />
          ) : null}
        </DialogContent>
      </Dialog>
      <Dialog open={!!activating} onOpenChange={(o) => (o ? null : setActivating(null))}>
        <DialogContent>{activating ? <ActivateForm prompt={prompt} version={activating} current={active} onClose={() => setActivating(null)} /> : null}</DialogContent>
      </Dialog>
    </Card>
  )
}

function ActivateForm({ prompt, version, current, onClose }: { prompt: PromptItem; version: PromptVersion; current?: PromptVersion; onClose: () => void }) {
  const qc = useQueryClient()
  const activate = useMutation({
    mutationFn: () => api.post<{ key: string; version: string; status: string }>(`/prompts/${enc(prompt.key)}/versions/${enc(version.version)}/activate`),
    onSuccess: (r) => {
      toast.success(`${r.key} v${r.version} is now active`, { description: current && current.version !== r.version ? `v${current.version} was retired. New analyses use the new version right away.` : undefined })
      qc.invalidateQueries({ queryKey: ['prompts'] })
      onClose()
    },
  })
  return (
    <>
      <DialogHeader>
        <DialogTitle>
          Activate <code className="font-mono">{prompt.key}</code> v{version.version}?
        </DialogTitle>
        <DialogDescription>
          {current && current.version !== version.version ? `The active version v${current.version} will be retired. ` : ''}
          New AI calls use this version right away; past analyses keep the version they used.
        </DialogDescription>
      </DialogHeader>
      <PlaceholderCheck system={version.system_template} user={version.user_template} />
      {activate.error ? (
        <Alert variant="destructive">
          <XCircle />
          <AlertTitle>Not activated</AlertTitle>
          <AlertDescription>{errorMessage(activate.error)}</AlertDescription>
        </Alert>
      ) : null}
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={() => activate.mutate()} disabled={activate.isPending}>
          {activate.isPending ? <Spinner /> : <Power />} Activate
        </Button>
      </DialogFooter>
    </>
  )
}

function isJsonObject(s: string): boolean {
  try {
    const v: unknown = JSON.parse(s)
    return !!v && typeof v === 'object' && !Array.isArray(v)
  } catch {
    return false
  }
}

const versionSchema = z
  .object({
    version: z.string().trim().regex(/^\d+\.\d+\.\d+$/, 'Use a version like 1.1.0.'),
    system_template: z.string().min(50, 'The system template must be at least 50 characters.'),
    user_template: z.string().min(20, 'The user template must be at least 20 characters.'),
    output_schema: z.string().trim().min(1, 'The output schema is required.'),
    params: z.string().refine(isJsonObject, 'Parameters must be a JSON object, e.g. {"temperature": 0.1}.'),
    changelog: z.string().trim().min(3, 'Describe what changed (at least 3 characters).').max(2000, 'Keep the changelog under 2000 characters.'),
    activate: z.boolean(),
  })
  .superRefine((v, ctx) => {
    for (const p of REQUIRED_PLACEHOLDERS)
      if (!v.system_template.includes(p) && !v.user_template.includes(p))
        ctx.addIssue({ code: 'custom', path: ['user_template'], message: `The templates must contain the ${p} placeholder.` })
  })
type VersionValues = z.infer<typeof versionSchema>
const VERSION_FIELDS = ['version', 'system_template', 'user_template', 'output_schema', 'params', 'changelog', 'activate'] as const

function NewVersionForm({ prompt, base, onClose, onCreated }: { prompt: PromptItem; base: PromptVersion; onClose: () => void; onCreated: (version: string) => void }) {
  const qc = useQueryClient()
  const form = useForm<VersionValues>({
    resolver: zodResolver(versionSchema),
    defaultValues: {
      version: nextVersion(prompt.versions),
      system_template: base.system_template,
      user_template: base.user_template,
      output_schema: base.output_schema,
      params: JSON.stringify(base.params ?? {}, null, 2),
      changelog: '',
      activate: false,
    },
  })
  const errors = form.formState.errors
  const [system, user] = useWatch({ control: form.control, name: ['system_template', 'user_template'] })
  const create = useMutation({
    mutationFn: (v: VersionValues) =>
      api.post<{ key: string; version: string; status: string; sha256: string }>(`/prompts/${enc(prompt.key)}/versions`, {
        version: v.version,
        system_template: v.system_template,
        user_template: v.user_template,
        output_schema: v.output_schema,
        params: JSON.parse(v.params) as Record<string, unknown>,
        changelog: v.changelog,
        activate: v.activate,
      }),
    onSuccess: (r) => {
      toast.success(`${r.key} v${r.version} created ${r.status === 'active' ? 'and activated' : 'as a draft'}`, { description: `Fingerprint ${r.sha256.slice(0, 16)}…` })
      qc.invalidateQueries({ queryKey: ['prompts'] })
      onCreated(r.version)
    },
    onError: (e) => {
      if (!(e instanceof ApiError)) return
      for (const [f, m] of Object.entries(e.fieldErrors)) if ((VERSION_FIELDS as readonly string[]).includes(f)) form.setError(f as (typeof VERSION_FIELDS)[number], { message: m })
    },
  })

  const submit = (v: VersionValues) => {
    if (prompt.versions.some((x) => x.version === v.version)) {
      form.setError('version', { message: `Version ${v.version} already exists.` })
      return
    }
    create.mutate(v)
  }

  return (
    <form noValidate className="min-w-0 space-y-4" onSubmit={form.handleSubmit(submit)}>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <Plus className="text-primary size-5" aria-hidden /> New version of <code className="font-mono">{prompt.key}</code>
        </DialogTitle>
        <DialogDescription>
          Pre-filled from v{base.version}. It is saved as a draft unless you activate it now.
        </DialogDescription>
      </DialogHeader>
      <fieldset className="grid gap-4 sm:grid-cols-3" disabled={create.isPending}>
        <legend className="sr-only">Version details</legend>
        <Field label="Version" htmlFor="pv-version" required error={errors.version?.message} hint="e.g. 1.2.0">
          <Input id="pv-version" className="font-mono" aria-invalid={!!errors.version} {...form.register('version')} />
        </Field>
        <Field label="Output schema" htmlFor="pv-schema" required error={errors.output_schema?.message} hint="The format the AI reply must follow">
          <Input id="pv-schema" className="font-mono" aria-invalid={!!errors.output_schema} {...form.register('output_schema')} />
        </Field>
        <Field label="Model parameters (JSON)" htmlFor="pv-params" error={errors.params?.message}>
          <Textarea id="pv-params" rows={2} className="min-h-9 font-mono text-xs" spellCheck={false} aria-invalid={!!errors.params} {...form.register('params')} />
        </Field>
      </fieldset>
      <fieldset className="space-y-4" disabled={create.isPending}>
        <legend className="sr-only">Templates</legend>
        <Field label="System template" htmlFor="pv-system" required error={errors.system_template?.message}>
          <Textarea id="pv-system" spellCheck={false} className="max-h-72 min-h-40 font-mono text-[11.5px] leading-relaxed" aria-invalid={!!errors.system_template} {...form.register('system_template')} />
        </Field>
        <Field label="User template" htmlFor="pv-user" required error={errors.user_template?.message}>
          <Textarea id="pv-user" spellCheck={false} className="max-h-60 min-h-28 font-mono text-[11.5px] leading-relaxed" aria-invalid={!!errors.user_template} {...form.register('user_template')} />
        </Field>
        <PlaceholderCheck system={system ?? ''} user={user ?? ''} baseline={placeholders(`${base.system_template}\n${base.user_template}`)} />
        <Field label="Changelog" htmlFor="pv-changelog" required error={errors.changelog?.message}>
          <Input id="pv-changelog" placeholder="What changed and why" aria-invalid={!!errors.changelog} {...form.register('changelog')} />
        </Field>
        <Controller
          control={form.control}
          name="activate"
          render={({ field }) => (
            <label htmlFor="pv-activate" className="flex items-start gap-2.5 rounded-lg border p-3 text-sm">
              <Checkbox id="pv-activate" className="mt-0.5" checked={field.value} onCheckedChange={(c) => field.onChange(c === true)} />
              <span>
                <span className="font-medium">Activate immediately</span>
                <span className="text-muted-foreground block text-xs">Retires the current active version. New AI calls use this one right away.</span>
              </span>
            </label>
          )}
        />
      </fieldset>
      {create.error ? (
        <Alert variant="destructive">
          <XCircle />
          <AlertTitle>Not saved</AlertTitle>
          <AlertDescription>{errorMessage(create.error)}</AlertDescription>
        </Alert>
      ) : null}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? <Spinner /> : <Plus />} Create version
        </Button>
      </DialogFooter>
    </form>
  )
}

// ------------------------------------------------------------------ AI run evidence
function AiRunsCard() {
  const [stage, setStage] = React.useState('')
  const [failedOnly, setFailedOnly] = React.useState(false)
  const [limit, setLimit] = React.useState(50)
  const failedId = React.useId()
  const runs = useQuery({
    queryKey: ['ai', 'runs', { stage, failedOnly, limit }],
    queryFn: () => api.get<AiRuns>('/ai/runs', { stage: stage || undefined, failed_only: failedOnly || undefined, limit }),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  })
  const stats = runs.data?.stats
  const total = (stats?.valid ?? 0) + (stats?.invalid ?? 0)
  const rate = total ? (stats?.valid ?? 0) / total : null
  const stages = [...new Set(['analysis', 'communication', ...(runs.data?.items ?? []).map((r) => r.stage)])]

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Activity className="text-muted-foreground size-4" aria-hidden /> Recent AI attempts
        </CardTitle>
        <CardDescription>Every call to the AI provider, newest first.</CardDescription>
        <CardAction>
          <Button variant="ghost" size="icon-sm" aria-label="Refresh AI attempts" onClick={() => runs.refetch()} disabled={runs.isFetching}>
            {runs.isFetching ? <Spinner /> : <RefreshCw />}
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="rounded-lg border p-3">
            <div className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">Attempts logged</div>
            <div className="mt-1 text-xl font-semibold tabular-nums">{total.toLocaleString()}</div>
          </div>
          <div className="border-success/30 bg-success/5 rounded-lg border p-3">
            <div className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">Valid output</div>
            <div className="mt-1 text-xl font-semibold tabular-nums">
              {(stats?.valid ?? 0).toLocaleString()} <span className="text-muted-foreground text-sm font-normal">{rate !== null ? `(${(rate * 100).toFixed(1)}%)` : ''}</span>
            </div>
          </div>
          <div className={cn('rounded-lg border p-3', stats?.invalid ? 'border-destructive/30 bg-destructive/5' : '')}>
            <div className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">Invalid output</div>
            <div className="mt-1 text-xl font-semibold tabular-nums">{(stats?.invalid ?? 0).toLocaleString()}</div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <NativeSelect aria-label="Filter by stage" className="h-8 w-auto text-xs" value={stage} onChange={(e) => setStage(e.target.value)}>
            <option value="">All stages</option>
            {stages.map((s) => (
              <option key={s} value={s}>
                {titleCase(s)}
              </option>
            ))}
          </NativeSelect>
          <NativeSelect aria-label="Number of attempts to show" className="h-8 w-auto text-xs" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
            {[25, 50, 100, 200].map((n) => (
              <option key={n} value={n}>
                Last {n}
              </option>
            ))}
          </NativeSelect>
          <label htmlFor={failedId} className="flex items-center gap-1.5 text-xs">
            <Checkbox id={failedId} checked={failedOnly} onCheckedChange={(c) => setFailedOnly(c === true)} /> Invalid output only
          </label>
        </div>

        {runs.isLoading ? (
          <LoadingBlock rows={6} />
        ) : runs.error ? (
          <ErrorState error={runs.error} onRetry={() => runs.refetch()} />
        ) : (runs.data?.items ?? []).length === 0 ? (
          <EmptyState icon={Activity} title={failedOnly ? 'No invalid outputs' : 'No AI attempts yet'} description={failedOnly ? 'Every logged attempt returned valid output.' : 'Attempts appear here as complaints are analysed.'} />
        ) : (
          <div className={cn('rounded-lg border transition-opacity', runs.isPlaceholderData && 'opacity-60')}>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Stage</TableHead>
                  <TableHead className="text-right">Attempt</TableHead>
                  <TableHead className="hidden lg:table-cell">Provider · model</TableHead>
                  <TableHead className="hidden md:table-cell">Prompt</TableHead>
                  <TableHead>Output</TableHead>
                  <TableHead className="text-right">Latency</TableHead>
                  <TableHead className="hidden xl:table-cell">Fault injected</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(runs.data?.items ?? []).map((r) => (
                  <TableRow key={r.id} className={cn(!r.parsed_ok && 'bg-destructive/5')}>
                    <TableCell className="whitespace-nowrap">
                      <div className="text-sm" title={fmtDateTime(r.at)}>
                        {fmtRelative(r.at)}
                      </div>
                      <div className="text-muted-foreground text-xs tabular-nums">
                        run #{r.id}
                        {r.complaint_id ? ` · complaint #${r.complaint_id}` : ''}
                      </div>
                    </TableCell>
                    <TableCell className="text-sm">{titleCase(r.stage)}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {r.attempt > 1 ? (
                        <Tooltip content="Retry after the previous attempt failed">
                          <Badge variant="warning" className="tabular-nums">
                            #{r.attempt}
                          </Badge>
                        </Tooltip>
                      ) : (
                        <span className="text-sm">#{r.attempt}</span>
                      )}
                    </TableCell>
                    <TableCell className="hidden lg:table-cell">
                      <div className="text-sm">{r.provider}</div>
                      <code className="text-muted-foreground font-mono text-[11px]">{r.model}</code>
                    </TableCell>
                    <TableCell className="hidden font-mono text-xs md:table-cell">{r.prompt}</TableCell>
                    <TableCell>
                      {r.parsed_ok ? (
                        <span className="text-success inline-flex items-center gap-1 text-xs font-medium">
                          <CheckCircle2 className="size-3.5" aria-hidden /> Valid
                        </span>
                      ) : (
                        <Tooltip content={r.error_message ?? 'The AI reply was not in the expected format.'}>
                          <Badge variant="destructive" tabIndex={0}>
                            <XCircle aria-hidden /> {r.error_type ? titleCase(r.error_type) : 'Invalid'}
                          </Badge>
                        </Tooltip>
                      )}
                    </TableCell>
                    <TableCell className="text-right text-sm whitespace-nowrap tabular-nums">{fmtMs(r.latency_ms)}</TableCell>
                    <TableCell className="hidden xl:table-cell">
                      {r.fault_injection ? (
                        <Badge variant="warning" className="font-mono">
                          {r.fault_injection}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground text-xs">—</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
