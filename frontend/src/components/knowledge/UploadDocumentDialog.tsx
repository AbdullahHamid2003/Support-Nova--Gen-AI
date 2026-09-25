/* Upload a knowledge-base document (new document or new version of an existing one).
   1) the file is parsed server-side WITHOUT saving (POST /documents/preview) to pre-fill metadata
      and show the section outline; 2) the reviewed metadata + file are uploaded (POST /documents). */
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, FileText, FileUp, GitBranch, Info, ListTree, RefreshCw, Upload, XCircle } from 'lucide-react'
import * as React from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { Field, Spinner } from '@/components/app/common'
import { FormatBadge } from '@/components/knowledge/doc-ui'
import {
  compareVersions, DOC_FORMATS, DOC_ID_PATTERN, DOC_STATUSES, DOC_TYPE_LABEL, DOC_TYPES, inferDocType, type PreviewResult, quarantinedCount,
  sortVersions, type UploadResult, VERSION_PATTERN,
} from '@/components/knowledge/model'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, ScrollArea } from '@/components/ui/overlays'
import { Alert, AlertDescription, AlertTitle, Badge, Input, NativeSelect } from '@/components/ui/primitives'
import { ApiError, api, errorMessage } from '@/lib/api'
import { usePublicConfig } from '@/lib/auth'
import { fmtBytes } from '@/lib/format'
import type { Option } from '@/lib/types'
import { cn } from '@/lib/utils'

const schema = z
  .object({
    doc_id: z.string().trim().toUpperCase().regex(DOC_ID_PATTERN, 'Use the pattern ABC-POL-12 (2-5 letters, 2-5 letters, 2-3 digits).'),
    title: z.string().trim().min(1, 'Title is required.').max(300, 'Keep the title under 300 characters.'),
    doc_type: z.string().refine((v) => (DOC_TYPES as readonly string[]).includes(v), 'Choose a document type.'),
    version: z.string().trim().regex(VERSION_PATTERN, 'Use a numeric version such as 2.0 or 3.1.'),
    status: z.string().refine((v) => (DOC_STATUSES as readonly string[]).includes(v), 'Choose a status.'),
    effective_date: z.string().min(1, 'Effective date is required.'),
    expiry_date: z.string(),
    owner_department: z.string(),
    topics: z.string().max(500, 'Keep topics under 500 characters.'),
  })
  .refine((v) => !v.expiry_date || !v.effective_date || v.expiry_date >= v.effective_date, {
    path: ['expiry_date'],
    message: 'Expiry date cannot be before the effective date.',
  })

type Values = z.infer<typeof schema>
type FieldName = keyof Values
export type UploadDefaults = Partial<Values>

const EMPTY: Values = { doc_id: '', title: '', doc_type: '', version: '', status: 'Draft', effective_date: '', expiry_date: '', owner_department: '', topics: '' }
const FIELDS = Object.keys(EMPTY) as FieldName[]

const STATUS_HINT: Record<string, string> = {
  Active: 'Becomes primary evidence once its effective date is reached.',
  Draft: 'Stored and searchable for review, never used as evidence.',
  Previous: 'Historic version - shown as outdated context only.',
  Superseded: 'Formally replaced - never primary evidence.',
}

interface ExistingDoc {
  doc_id: string
  title: string
  versions: { version: string; status: string }[]
}

function toDateInput(value: string): string {
  if (!value) return ''
  if (/^\d{4}-\d{2}-\d{2}/.test(value)) return value.slice(0, 10)
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '' : d.toISOString().slice(0, 10)
}

function prefill(current: Values, p: PreviewResult, departments: Option[]): { values: Values; detected: FieldName[] } {
  const m = p.detected_metadata ?? {}
  const str = (k: string): string => {
    const v = m[k]
    return typeof v === 'string' ? v.trim() : typeof v === 'number' ? String(v) : ''
  }
  const next: Values = { ...current }
  const detected: FieldName[] = []
  const set = (k: FieldName, v: string) => {
    if (!v) return
    next[k] = v
    detected.push(k)
  }
  set('doc_id', str('doc_id').toUpperCase())
  set('title', str('title') || (p.title ?? '').trim())
  set('version', str('version').replace(/^v/i, ''))
  const status = str('status')
  const cap = status ? status.charAt(0).toUpperCase() + status.slice(1).toLowerCase() : ''
  if ((DOC_STATUSES as readonly string[]).includes(cap)) set('status', cap)
  set('effective_date', toDateInput(str('effective_date')))
  set('expiry_date', toDateInput(str('expiry_date')))
  const type = str('doc_type').toLowerCase() || inferDocType(next.doc_id) || ''
  if ((DOC_TYPES as readonly string[]).includes(type)) set('doc_type', type)
  const owner = str('owner').toLowerCase()
  const dept = str('owner_department') || (owner ? departments.find((d) => d.name.toLowerCase() === owner || d.code.toLowerCase() === owner)?.code ?? '' : '')
  set('owner_department', dept)
  const topics = Array.isArray(m.topics) ? m.topics.map(String).join(', ') : str('topics')
  set('topics', topics)
  return { values: next, detected }
}

export function UploadDocumentDialog({ open, onOpenChange, defaults, existing, onUploaded, title = 'Upload document' }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  defaults?: UploadDefaults
  existing?: ExistingDoc[]
  onUploaded?: (result: UploadResult) => void
  title?: string
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Upload className="text-primary size-5" aria-hidden /> {title}
          </DialogTitle>
          <DialogDescription>
            Check the details read from the file. Nothing is saved until you choose <strong>Upload</strong>.
          </DialogDescription>
        </DialogHeader>
        {/* Radix unmounts the content when closed, so every opening starts with a fresh form. */}
        <UploadForm
          defaults={defaults}
          existing={existing}
          onCancel={() => onOpenChange(false)}
          onDone={(r) => {
            onOpenChange(false)
            onUploaded?.(r)
          }}
        />
      </DialogContent>
    </Dialog>
  )
}

function UploadForm({ defaults, existing, onCancel, onDone }: { defaults?: UploadDefaults; existing?: ExistingDoc[]; onCancel: () => void; onDone: (r: UploadResult) => void }) {
  const qc = useQueryClient()
  const config = usePublicConfig()
  const maxMb = config.data?.limits.max_upload_mb ?? 15
  const departments = config.data?.departments ?? []
  const inputId = React.useId()
  const [file, setFile] = React.useState<File | null>(null)
  const [fileError, setFileError] = React.useState<string | null>(null)
  const [dragging, setDragging] = React.useState(false)
  const [detected, setDetected] = React.useState<FieldName[]>([])

  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { ...EMPTY, ...defaults } })
  const errors = form.formState.errors

  const preview = useMutation({
    mutationFn: (f: File) => {
      const fd = new FormData()
      fd.append('file', f)
      return api.upload<PreviewResult>('/documents/preview', fd)
    },
    onSuccess: (p) => {
      const next = prefill(form.getValues(), p, departments)
      form.reset(next.values)
      setDetected(next.detected)
    },
  })

  const upload = useMutation({
    mutationFn: (values: Values) => {
      if (!file) throw new Error('Choose a file first.')
      const fd = new FormData()
      fd.append('file', file)
      for (const k of FIELDS) fd.append(k, values[k] ?? '')
      return api.upload<UploadResult>('/documents', fd)
    },
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['documents'] })
      qc.invalidateQueries({ queryKey: ['knowledge'] })
      const q = quarantinedCount(r.security_findings)
      const parts = [`${r.section_count} sections`, `${r.chunk_count} chunks`]
      if (q) parts.push(`${q} chunk${q === 1 ? '' : 's'} quarantined`)
      if (r.impact) parts.push('revision impact ready')
      toast.success(`Uploaded ${r.doc_id} v${r.version} (${r.status})`, { description: [parts.join(' · '), ...(r.warnings ?? [])].join(' — ') })
      onDone(r)
    },
    onError: (e) => {
      if (e instanceof ApiError) {
        for (const [field, message] of Object.entries(e.fieldErrors)) if ((FIELDS as string[]).includes(field)) form.setError(field as FieldName, { message })
      }
    },
  })

  const choose = (f: File | null | undefined) => {
    if (!f) return
    const ext = f.name.includes('.') ? f.name.split('.').pop()!.toLowerCase() : ''
    if (!(DOC_FORMATS as readonly string[]).includes(ext)) {
      setFileError(`${ext ? `.${ext}` : 'This'} file type is not supported. Use PDF, DOCX, TXT, Markdown or CSV.`)
      return
    }
    if (f.size > maxMb * 1024 * 1024) {
      setFileError(`${f.name} is ${fmtBytes(f.size)} - the limit is ${maxMb} MB.`)
      return
    }
    setFileError(null)
    setFile(f)
    setDetected([])
    upload.reset()
    preview.mutate(f)
  }

  // ---- version-control hints for the metadata being entered
  const [wDocId, wVersion, wStatus] = useWatch({ control: form.control, name: ['doc_id', 'version', 'status'] })
  const docId = (wDocId ?? '').trim().toUpperCase()
  const version = (wVersion ?? '').trim()
  const match = docId ? existing?.find((d) => d.doc_id === docId) : undefined
  const currentActive = match ? sortVersions(match.versions.filter((v) => v.status === 'Active')).pop() : undefined
  const versionExists = !!match && !!version && match.versions.some((v) => v.version === version)
  const mismatch = defaults?.doc_id && docId && docId !== defaults.doc_id.toUpperCase() ? defaults.doc_id.toUpperCase() : null

  const hint = (k: FieldName, fallback?: string) => (detected.includes(k) ? 'Pre-filled from the file - check it.' : fallback)
  const uploadError = upload.error
  const hasFieldErrors = uploadError instanceof ApiError && Object.keys(uploadError.fieldErrors).length > 0

  return (
    <form onSubmit={form.handleSubmit((v) => upload.mutate(v))} noValidate className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_17rem]">
      <div className="min-w-0 space-y-5">
        {/* ---- file */}
        <label
          htmlFor={inputId}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            choose(e.dataTransfer.files?.[0])
          }}
          className={cn(
            'focus-within:ring-ring/30 flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl border-2 border-dashed px-5 text-center transition-colors focus-within:ring-[3px]',
            file ? 'py-4' : 'py-8',
            dragging ? 'border-primary bg-primary/5' : 'hover:border-primary/50 hover:bg-accent/30',
          )}
        >
          <input
            id={inputId}
            type="file"
            accept=".pdf,.docx,.txt,.md,.csv"
            className="sr-only"
            onChange={(e) => {
              choose(e.target.files?.[0])
              e.target.value = ''
            }}
          />
          {file ? (
            <div className="flex w-full flex-wrap items-center gap-3 text-left">
              <div className="bg-primary/10 text-primary flex size-10 shrink-0 items-center justify-center rounded-lg">
                <FileText className="size-5" aria-hidden />
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{file.name}</div>
                <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
                  {fmtBytes(file.size)}
                  {preview.data ? <FormatBadge format={preview.data.format} /> : null}
                  {preview.data?.page_count ? <span>{preview.data.page_count} pages</span> : null}
                  {preview.data ? <span>{preview.data.sections.length} sections</span> : null}
                </div>
              </div>
              <span className="text-primary text-xs font-medium underline underline-offset-4">Choose another file</span>
            </div>
          ) : (
            <>
              <FileUp className="text-primary size-7" aria-hidden />
              <div className="text-sm font-medium">
                Drop a document here or <span className="text-primary underline underline-offset-4">browse</span>
              </div>
              <div className="text-muted-foreground max-w-md text-xs">PDF, DOCX, TXT, Markdown or CSV · up to {maxMb} MB</div>
            </>
          )}
        </label>

        {fileError ? (
          <Alert variant="destructive">
            <XCircle />
            <AlertTitle>File not accepted</AlertTitle>
            <AlertDescription>{fileError}</AlertDescription>
          </Alert>
        ) : null}
        {preview.isPending ? (
          <div className="text-muted-foreground flex items-center gap-2 text-sm" role="status">
            <Spinner /> Reading the file…
          </div>
        ) : null}
        {preview.error ? (
          <Alert variant="destructive">
            <XCircle />
            <AlertTitle>The file could not be read</AlertTitle>
            <AlertDescription>
              <p>{errorMessage(preview.error)}</p>
              {file ? (
                <Button type="button" size="sm" variant="outline" className="text-foreground mt-1" onClick={() => preview.mutate(file)}>
                  <RefreshCw /> Try again
                </Button>
              ) : null}
            </AlertDescription>
          </Alert>
        ) : null}
        {preview.data && detected.length ? (
          <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
            <CheckCircle2 className="text-success size-3.5" aria-hidden /> {detected.length} field{detected.length === 1 ? '' : 's'} filled in from the file. Check them before uploading.
          </p>
        ) : null}

        {/* ---- metadata */}
        <fieldset className="grid gap-4 sm:grid-cols-2" disabled={upload.isPending}>
          <legend className="sr-only">Document metadata</legend>
          <Field label="Document ID" htmlFor="up-doc-id" required error={errors.doc_id?.message} hint={hint('doc_id', 'For example REF-POL-02. A new ID registers a new document.')}>
            <Input id="up-doc-id" className="font-mono uppercase" placeholder="REF-POL-02" autoComplete="off" aria-invalid={!!errors.doc_id} {...form.register('doc_id')} />
          </Field>
          <Field label="Version" htmlFor="up-version" required error={errors.version?.message} hint={hint('version', 'Numeric, e.g. 2.1')}>
            <Input id="up-version" className="font-mono" placeholder="2.1" autoComplete="off" aria-invalid={!!errors.version} {...form.register('version')} />
          </Field>
          <div className="sm:col-span-2">
            <Field label="Title" htmlFor="up-title" required error={errors.title?.message} hint={hint('title')}>
              <Input id="up-title" placeholder="Refund Policy" aria-invalid={!!errors.title} {...form.register('title')} />
            </Field>
          </div>
          <Field label="Document type" htmlFor="up-type" required error={errors.doc_type?.message} hint={hint('doc_type', 'Sets precedence: Policy = Rules > SOP > Guideline > FAQ > Template.')}>
            <NativeSelect id="up-type" aria-invalid={!!errors.doc_type} {...form.register('doc_type')}>
              <option value="">Choose a type…</option>
              {DOC_TYPES.map((t) => (
                <option key={t} value={t}>
                  {DOC_TYPE_LABEL[t]}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field label="Status" htmlFor="up-status" required error={errors.status?.message} hint={hint('status', STATUS_HINT[wStatus ?? ''])}>
            <NativeSelect id="up-status" aria-invalid={!!errors.status} {...form.register('status')}>
              {DOC_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field label="Effective date" htmlFor="up-eff" required error={errors.effective_date?.message} hint={hint('effective_date')}>
            <Input id="up-eff" type="date" aria-invalid={!!errors.effective_date} {...form.register('effective_date')} />
          </Field>
          <Field label="Expiry date" htmlFor="up-exp" error={errors.expiry_date?.message} hint={hint('expiry_date', 'Optional. After it passes the version is treated as outdated.')}>
            <Input id="up-exp" type="date" aria-invalid={!!errors.expiry_date} {...form.register('expiry_date')} />
          </Field>
          <Field label="Owner department" htmlFor="up-owner" error={errors.owner_department?.message} hint={hint('owner_department')}>
            <NativeSelect id="up-owner" {...form.register('owner_department')}>
              <option value="">No owner</option>
              {departments.map((d) => (
                <option key={d.code} value={d.code}>
                  {d.name}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field label="Topics" htmlFor="up-topics" error={errors.topics?.message} hint={hint('topics', 'Comma-separated, e.g. refunds, returns')}>
            <Input id="up-topics" placeholder="refunds, returns, care-plus" {...form.register('topics')} />
          </Field>
        </fieldset>

        {/* ---- version-control consequences */}
        <div className="space-y-2" aria-live="polite">
          {mismatch ? (
            <Alert variant="warning">
              <AlertTriangle />
              <AlertTitle>Different document ID</AlertTitle>
              <AlertDescription>
                You started from {mismatch}, but the document ID is now {docId}. The upload will be filed under {docId}.
              </AlertDescription>
            </Alert>
          ) : null}
          {versionExists ? (
            <Alert variant="destructive">
              <XCircle />
              <AlertTitle>Version {version} already exists</AlertTitle>
              <AlertDescription>{docId} already has a version {version}. Choose a new version number.</AlertDescription>
            </Alert>
          ) : match ? (
            <Alert variant="info">
              <GitBranch />
              <AlertTitle>New version of {match.doc_id}</AlertTitle>
              <AlertDescription>
                <p>
                  Adds a version to <strong>{match.title}</strong>
                  {currentActive ? ` (current Active version: v${currentActive.version})` : ' (it has no Active version)'}.
                </p>
                {wStatus === 'Active' && currentActive && version && VERSION_PATTERN.test(version) && compareVersions(version, currentActive.version) > 0 ? (
                  <p>
                    v{currentActive.version} will become <strong>Previous</strong> (any Previous version becomes Superseded). The Revision impact tab will show what the change affects.
                  </p>
                ) : null}
                {wStatus === 'Active' && currentActive && version && VERSION_PATTERN.test(version) && compareVersions(version, currentActive.version) < 0 ? (
                  <p className="font-medium">A newer Active version (v{currentActive.version}) exists, so this one cannot be Active. Upload it as Previous or Superseded.</p>
                ) : null}
              </AlertDescription>
            </Alert>
          ) : docId && DOC_ID_PATTERN.test(docId) ? (
            <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
              <Info className="size-3.5" aria-hidden /> {docId} is new - it will be added as a new document.
            </p>
          ) : null}
        </div>

        {uploadError ? (
          <Alert variant="destructive">
            <XCircle />
            <AlertTitle>Upload rejected</AlertTitle>
            <AlertDescription>
              <p>{errorMessage(uploadError)}</p>
              {hasFieldErrors ? <p>The fields that need attention are marked above.</p> : null}
            </AlertDescription>
          </Alert>
        ) : null}
      </div>

      {/* ---- outline */}
      <aside className="min-w-0 space-y-4">
        <div className="rounded-xl border">
          <div className="flex items-center gap-2 border-b px-3 py-2.5 text-sm font-semibold">
            <ListTree className="text-muted-foreground size-4" aria-hidden /> Outline
            {preview.data ? <Badge variant="muted" className="ml-auto">{preview.data.sections.length}</Badge> : null}
          </div>
          {preview.data ? (
            preview.data.sections.length ? (
              <ScrollArea className="h-72">
                <ol className="space-y-0.5 p-2 text-xs">
                  {preview.data.sections.map((s) => (
                    <li key={s.section_id + s.heading} className="flex items-baseline gap-2 rounded-md px-1.5 py-1" style={{ paddingLeft: `${0.375 + Math.max(0, s.level - 1) * 0.75}rem` }}>
                      <span className="text-muted-foreground w-9 shrink-0 font-mono">{s.section_id}</span>
                      <span className="min-w-0 flex-1 truncate" title={s.heading}>
                        {s.heading}
                      </span>
                      <span className="text-muted-foreground shrink-0 tabular-nums">{s.page_start ? `p.${s.page_start}` : `${s.chars}c`}</span>
                    </li>
                  ))}
                </ol>
              </ScrollArea>
            ) : (
              <p className="text-destructive p-3 text-xs">No sections were found. Upload a file with readable text.</p>
            )
          ) : (
            <p className="text-muted-foreground p-3 text-xs">Choose a file to see its sections.</p>
          )}
        </div>
      </aside>

      <DialogFooter className="lg:col-span-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={!file || preview.isPending || upload.isPending || versionExists}>
          {upload.isPending ? <Spinner /> : <Upload />} Upload
        </Button>
      </DialogFooter>
    </form>
  )
}
