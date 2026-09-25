import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, ArrowRight, BookOpen, CheckCircle2, CircleDashed, FileSearch, Loader2, Paperclip, ScanSearch, Scale, Send, ShieldCheck, Sparkles, Upload, X } from 'lucide-react'
import * as React from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { z } from 'zod'

import { Field, PageHeader, Spinner } from '@/components/app/common'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription, AlertTitle, Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, NativeSelect, Progress, Textarea } from '@/components/ui/primitives'
import { ApiError, api, errorMessage } from '@/lib/api'
import { useAuth, usePublicConfig } from '@/lib/auth'
import { useDebouncedValue } from '@/hooks/time'
import { fmtBytes } from '@/lib/format'
import { cn } from '@/lib/utils'

const ORDER = /^LMR-\d{6}$/i
const TXN = /^TXN-\d{8}$/i
const CMP = /^CMP-\d{5,}$/i

const schema = z.object({
  customer_ref: z.string().optional(),
  title: z.string().trim().min(5, 'Give the complaint a short title (at least 5 characters).').max(180, 'Keep the title under 180 characters.'),
  description: z
    .string()
    .trim()
    .min(20, 'Please describe what happened (at least 20 characters).')
    .max(8000, 'The description is too long (maximum 8000 characters).')
    .refine((v) => v.split(/\s+/).length >= 4, 'Please describe what happened in a few words.'),
  product_text: z.string().max(200).optional(),
  order_ref: z.string().trim().optional().refine((v) => !v || ORDER.test(v), 'Order references look like LMR-123456.'),
  transaction_ref: z.string().trim().optional().refine((v) => !v || TXN.test(v), 'Transaction references look like TXN-12345678.'),
  previous_complaint_ref: z.string().trim().optional().refine((v) => !v || CMP.test(v), 'Complaint references look like CMP-00042.'),
  channel: z.string().min(1),
  customer_type: z.string().optional(),
  preferred_contact: z.string().min(1),
  requested_resolution: z.string().min(1),
  requested_tone: z.string().min(1),
  supporting_info: z.string().max(6000).optional(),
})
type Values = z.infer<typeof schema>

const STAGES: { key: string; label: string; customerLabel: string; detail: string; icon: React.ElementType }[] = [
  { key: 'preprocessing', label: 'Screening', customerLabel: 'Reading your complaint', detail: 'Injection screening, card redaction, signals and history', icon: ScanSearch },
  { key: 'retrieval', label: 'Policy search', customerLabel: 'Finding the relevant policies', detail: 'Searches the active knowledge base', icon: BookOpen },
  { key: 'ai_analysis', label: 'AI analysis', customerLabel: 'Understanding the issue', detail: 'Classification, urgency, evidence and resolution', icon: Sparkles },
  { key: 'validation', label: 'Rule check', customerLabel: 'Working out the next steps', detail: 'Checks the Rule Matrix and order records', icon: Scale },
  { key: 'response_generation', label: 'Response drafting', customerLabel: 'Preparing our reply', detail: 'Reply written from the final decision', icon: Send },
  { key: 'response_validation', label: 'Response check', customerLabel: 'Reviewing our reply', detail: 'Unsupported promises, timelines, amounts and tone', icon: ShieldCheck },
  { key: 'finalizing', label: 'Routing & SLA', customerLabel: 'Sending it to the right team', detail: 'Department, escalation, follow-up, SLA and audit trail', icon: FileSearch },
]

interface PipelineState {
  complaint_ref: string
  stage: string
  status: string
  done: boolean
  failed: boolean
  stages: { key: string; state: 'done' | 'active' | 'pending' }[]
  verification_status?: string
  score?: number | null
  timings?: Record<string, number>
}

function PipelineProgress({ refId, internal }: { refId: string; internal: boolean }) {
  const q = useQuery({
    queryKey: ['pipeline', refId],
    queryFn: () => api.get<PipelineState>(`/complaints/${refId}/pipeline`),
    refetchInterval: (query) => (query.state.data?.done ? false : 600),
  })
  const p = q.data
  const doneCount = p ? p.stages.filter((s) => s.state === 'done').length : 0
  const pct = p?.done ? 100 : Math.round((doneCount / STAGES.length) * 100)
  return (
    <Card className="overflow-hidden">
      <div className="nova-gradient h-1" style={{ width: `${Math.max(4, pct)}%`, transition: 'width 400ms ease' }} aria-hidden />
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {p?.done ? (p.failed ? <AlertTriangle className="text-warning size-5" /> : <CheckCircle2 className="text-success size-5" />) : <Loader2 className="text-primary size-5 animate-spin" />}
          {p?.done ? (p.failed ? 'Received - a specialist will review it' : 'Complaint received and analysed') : 'Processing your complaint…'}
        </CardTitle>
        <CardDescription>
          Reference <span className="text-foreground font-mono font-semibold">{refId}</span>
          {internal && p?.done && p.verification_status ? (
            <> · Rule check: <strong>{p.verification_status}</strong>{p.score !== null && p.score !== undefined ? ` (${Math.round(p.score)}/100)` : ''}</>
          ) : null}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Progress value={pct} aria-label="Processing progress" />
        <ol className="space-y-2" aria-live="polite">
          {STAGES.map((s) => {
            const state = p?.done && !p.failed ? 'done' : p?.stages.find((x) => x.key === s.key)?.state ?? 'pending'
            const Icon = s.icon
            return (
              <li key={s.key} className={cn('flex items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors', state === 'active' && 'border-primary/40 bg-primary/5', state === 'done' && 'bg-muted/40')}>
                <div className={cn('mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md', state === 'done' ? 'bg-success/15 text-success' : state === 'active' ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground')}>
                  {state === 'done' ? <CheckCircle2 className="size-4" /> : state === 'active' ? <Loader2 className="size-4 animate-spin" /> : <CircleDashed className="size-4" />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Icon className="text-muted-foreground size-3.5" aria-hidden /> {internal ? s.label : s.customerLabel}
                    {internal && p?.timings?.[s.key] !== undefined ? <span className="text-muted-foreground ml-auto text-xs tabular-nums">{p.timings[s.key]} ms</span> : null}
                  </div>
                  {internal ? <div className="text-muted-foreground text-xs">{s.detail}</div> : null}
                </div>
              </li>
            )
          })}
        </ol>
        {p?.done ? (
          <div className="flex flex-wrap gap-2 pt-1">
            <Button asChild>
              <Link to={`/complaints/${refId}`}>{internal ? 'Open the case' : 'View my complaint'} <ArrowRight /></Link>
            </Button>
            <Button variant="outline" onClick={() => window.location.reload()}>Submit another</Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

export default function SubmitComplaintPage() {
  const { session } = useAuth()
  const internal = session!.user.role !== 'customer'
  const config = usePublicConfig()
  const navigate = useNavigate()
  const [files, setFiles] = React.useState<File[]>([])
  const [submitted, setSubmitted] = React.useState<string | null>(null)
  const [customerQuery, setCustomerQuery] = React.useState('')
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: '', description: '', product_text: '', order_ref: '', transaction_ref: '', previous_complaint_ref: '', supporting_info: '',
      channel: internal ? 'phone' : 'web_form', preferred_contact: 'email', requested_resolution: 'none', requested_tone: 'professional', customer_ref: '',
    },
  })
  const errors = form.formState.errors
  const cfg = config.data
  const maxMb = cfg?.limits.max_attachment_mb ?? 5

  const customers = useQuery({
    queryKey: ['customers', customerQuery],
    queryFn: () => api.get<{ items: { customer_ref: string; full_name: string; email: string; customer_type: string }[] }>('/customers', { q: customerQuery }),
    enabled: internal && customerQuery.length >= 2,
  })

  // live duplicate / reference pre-check (no complaint is created)
  const watched = useWatch({ control: form.control, name: ['title', 'description', 'order_ref', 'previous_complaint_ref', 'customer_ref'] })
  const descLen = (watched[1] ?? '').length
  const precheckInput = useDebouncedValue(JSON.stringify(watched), 700)
  const precheckQuery = useQuery({
    queryKey: ['precheck', precheckInput],
    queryFn: () => api.post<{ valid: boolean; errors: { field: string; message: string }[]; duplicate_of: string | null }>('/complaints/validate', { ...form.getValues() }),
    enabled: (() => {
      const [title, description] = JSON.parse(precheckInput) as (string | undefined)[]
      return !!title && !!description && description.length >= 20
    })(),
    retry: false,
  })
  const precheck = precheckQuery.data ?? null

  const submit = useMutation({
    mutationFn: async (values: Values) => {
      const payload: Record<string, string> = {}
      for (const [k, v] of Object.entries(values)) if (v !== undefined && v !== '') payload[k] = String(v).trim()
      if (!internal) delete payload.customer_ref
      if (files.length === 0) return api.post<{ complaint_ref: string }>('/complaints', payload)
      const fd = new FormData()
      Object.entries(payload).forEach(([k, v]) => fd.append(k, v))
      files.forEach((f) => fd.append('attachments', f))
      return api.upload<{ complaint_ref: string }>('/complaints', fd)
    },
    onSuccess: (r) => {
      setSubmitted(r.complaint_ref)
      toast.success(`Complaint ${r.complaint_ref} received`)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    },
    onError: (e) => {
      if (e instanceof ApiError) {
        const fe = e.fieldErrors
        Object.entries(fe).forEach(([field, message]) => form.setError(field as keyof Values, { message }))
        if (e.code === 'duplicate_complaint') {
          const dup = (e.details as { duplicate_of?: string } | undefined)?.duplicate_of
          toast.error(e.message, dup ? { action: { label: 'Open', onClick: () => navigate(`/complaints/${dup}`) } } : undefined)
          return
        }
      }
      toast.error(errorMessage(e))
    },
  })

  const addFiles = (list: FileList | null) => {
    if (!list) return
    const next = [...files]
    for (const f of Array.from(list)) {
      if (f.size > maxMb * 1024 * 1024) {
        toast.error(`${f.name} is over ${maxMb} MB - choose a smaller file.`)
        continue
      }
      if (next.length >= 5) {
        toast.error('You can attach up to 5 files.')
        break
      }
      next.push(f)
    }
    setFiles(next)
  }

  if (submitted) {
    return (
      <>
        <PageHeader eyebrow="Complaint submitted" title="Thank you - we are on it" description="You can follow the progress below." />
        <div className="max-w-2xl">
          <PipelineProgress refId={submitted} internal={internal} />
        </div>
      </>
    )
  }

  const opt = (items?: { code: string; name: string }[]) => (items ?? []).map((o) => <option key={o.code} value={o.code}>{o.name}</option>)
  return (
    <>
      <PageHeader
        eyebrow={internal ? 'New complaint' : 'Customer portal'}
        title={internal ? 'Log a complaint' : 'Tell us what went wrong'}
        description={internal ? 'Record a complaint on behalf of a customer.' : 'Include order numbers or dates if you have them.'}
      />
      <form onSubmit={form.handleSubmit((v) => submit.mutate(v))} className="grid gap-6 xl:grid-cols-[1fr_22rem]" noValidate>
        <div className="space-y-6">
          {internal ? (
            <Card>
              <CardHeader>
                <CardTitle>Customer</CardTitle>
                <CardDescription>Link the complaint to a customer account.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 md:grid-cols-2">
                <Field label="Find customer" htmlFor="cust-search" hint="Search by name, email or customer reference">
                  <Input id="cust-search" value={customerQuery} onChange={(e) => setCustomerQuery(e.target.value)} placeholder="e.g. CUST-10042 or Chen" autoComplete="off" />
                </Field>
                <Field label="Customer reference" htmlFor="customer_ref" error={errors.customer_ref?.message}>
                  <NativeSelect id="customer_ref" {...form.register('customer_ref')}>
                    <option value="">Not linked (anonymous)</option>
                    {(customers.data?.items ?? []).map((c) => (
                      <option key={c.customer_ref} value={c.customer_ref}>{c.customer_ref} - {c.full_name} ({c.customer_type})</option>
                    ))}
                  </NativeSelect>
                </Field>
                <Field label="Channel" htmlFor="channel" required>
                  <NativeSelect id="channel" {...form.register('channel')}>{opt(cfg?.channels)}</NativeSelect>
                </Field>
                <Field label="Customer type" htmlFor="customer_type" hint="Defaults to the customer's profile">
                  <NativeSelect id="customer_type" {...form.register('customer_type')}>
                    <option value="">From profile</option>
                    {opt(cfg?.customer_types)}
                  </NativeSelect>
                </Field>
              </CardContent>
            </Card>
          ) : null}

          <Card>
            <CardHeader>
              <CardTitle>The complaint</CardTitle>
              <CardDescription>What happened, in your own words.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Field label="Title" htmlFor="title" error={errors.title?.message} required>
                <Input id="title" placeholder="e.g. Thermostat order arrived a week late" aria-invalid={!!errors.title} {...form.register('title')} />
              </Field>
              <Field label="Description" htmlFor="description" error={errors.description?.message} hint={`${descLen}/8000 characters`} required>
                <Textarea id="description" rows={7} className="min-h-40" placeholder="What happened, when, and what you would like us to do…" aria-invalid={!!errors.description} {...form.register('description')} />
              </Field>
              <div className="grid gap-4 md:grid-cols-2">
                <Field label="Product or service" htmlFor="product_text">
                  <Input id="product_text" list="products" placeholder="e.g. Lumora Aura Smart Thermostat" {...form.register('product_text')} />
                  <datalist id="products">{(cfg?.products ?? []).map((p) => <option key={p.sku} value={p.name} />)}</datalist>
                </Field>
                <Field label="Order reference" htmlFor="order_ref" error={errors.order_ref?.message} hint="Format LMR-123456">
                  <Input id="order_ref" placeholder="LMR-123456" className="font-mono uppercase" aria-invalid={!!errors.order_ref} {...form.register('order_ref')} />
                </Field>
                <Field label="Transaction reference" htmlFor="transaction_ref" error={errors.transaction_ref?.message} hint="Format TXN-12345678 (for payment issues)">
                  <Input id="transaction_ref" placeholder="TXN-12345678" className="font-mono uppercase" aria-invalid={!!errors.transaction_ref} {...form.register('transaction_ref')} />
                </Field>
                <Field label="Previous complaint" htmlFor="previous_complaint_ref" error={errors.previous_complaint_ref?.message} hint="If this follows up an earlier complaint">
                  <Input id="previous_complaint_ref" placeholder="CMP-00042" className="font-mono uppercase" aria-invalid={!!errors.previous_complaint_ref} {...form.register('previous_complaint_ref')} />
                </Field>
              </div>
              <Field label="Supporting information" htmlFor="supporting_info" hint="Anything else: dates, what you have already tried, error messages">
                <Textarea id="supporting_info" rows={3} {...form.register('supporting_info')} />
              </Field>
              <div>
                <div className="mb-1.5 text-sm font-medium">Attachments</div>
                <label className="hover:border-primary/50 hover:bg-accent/30 flex cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border border-dashed px-4 py-6 text-center transition-colors">
                  <Upload className="text-muted-foreground size-5" aria-hidden />
                  <span className="text-sm">Add photos, receipts or documents</span>
                  <span className="text-muted-foreground text-xs">JPG, PNG, WebP, PDF, TXT · up to {maxMb} MB each · max 5</span>
                  <input type="file" multiple className="sr-only" accept=".jpg,.jpeg,.png,.webp,.pdf,.txt" onChange={(e) => { addFiles(e.target.files); e.target.value = '' }} />
                </label>
                {files.length ? (
                  <ul className="mt-2 space-y-1.5">
                    {files.map((f, i) => (
                      <li key={f.name + i} className="flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm">
                        <Paperclip className="text-muted-foreground size-3.5" />
                        <span className="truncate">{f.name}</span>
                        <span className="text-muted-foreground ml-auto text-xs">{fmtBytes(f.size)}</span>
                        <Button type="button" variant="ghost" size="icon-sm" aria-label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((_, j) => j !== i))}>
                          <X />
                        </Button>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Your preferences</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Field label="What would you like us to do?" htmlFor="requested_resolution">
                <NativeSelect id="requested_resolution" {...form.register('requested_resolution')}>{opt(cfg?.requested_resolutions)}</NativeSelect>
              </Field>
              <Field label="Preferred contact" htmlFor="preferred_contact">
                <NativeSelect id="preferred_contact" {...form.register('preferred_contact')}>{opt(cfg?.preferred_contact_methods)}</NativeSelect>
              </Field>
              <Field label="Reply tone" htmlFor="requested_tone" hint="How you would like our reply to sound">
                <NativeSelect id="requested_tone" {...form.register('requested_tone')}>{opt(cfg?.response_tones)}</NativeSelect>
              </Field>
            </CardContent>
          </Card>

          <AnimatePresence>
            {precheck?.duplicate_of ? (
              <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                <Alert variant="warning">
                  <AlertTriangle />
                  <AlertTitle>Looks like a duplicate</AlertTitle>
                  <AlertDescription>
                    This matches {internal ? <Link className="underline" to={`/complaints/${precheck.duplicate_of}`}>{precheck.duplicate_of}</Link> : precheck.duplicate_of}. Submitting again will not open a second case.
                  </AlertDescription>
                </Alert>
              </motion.div>
            ) : null}
            {precheck && precheck.errors.length ? (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                <Alert variant="warning">
                  <AlertTriangle />
                  <AlertTitle>Please check</AlertTitle>
                  <AlertDescription>
                    <ul className="list-disc pl-4">{precheck.errors.map((e) => <li key={e.field + e.message}>{e.message}</li>)}</ul>
                  </AlertDescription>
                </Alert>
              </motion.div>
            ) : null}
          </AnimatePresence>

          <Card className="bg-muted/40 gap-3">
            <CardContent className="space-y-3 text-sm">
              <div className="flex items-center gap-2 font-medium"><ShieldCheck className="text-validate size-4" /> Keep your details safe</div>
              <p className="text-muted-foreground text-xs">Never include passwords or full card numbers. We will never ask for them.</p>
            </CardContent>
          </Card>

          <Button type="submit" size="lg" className="w-full" disabled={submit.isPending}>
            {submit.isPending ? <Spinner /> : <Send />} Submit complaint
          </Button>
          <Badge variant="muted" className="w-full justify-center py-1 font-normal">Fields marked * are required</Badge>
        </div>
      </form>
    </>
  )
}
