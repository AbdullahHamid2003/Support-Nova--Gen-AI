/* Approved complaint taxonomy (categories -> subcategories) and departments, with the
   "new category without a code change" flow: POST /taxonomy/categories | subcategories | departments. */
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building, CheckCircle2, FolderTree, Plus, Search, Tags, XCircle } from 'lucide-react'
import * as React from 'react'
import { Controller, useForm, useWatch } from 'react-hook-form'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { z } from 'zod'

import { EmptyState, ErrorState, Field, LoadingBlock, Spinner } from '@/components/app/common'
import { IssueList } from '@/components/rules/RuleEditorDialog'
import { IMPACT_LEVELS, integrityIssues, invalidateRules, type RulesMeta, type Taxonomy, URGENCY_LEVELS } from '@/components/rules/model'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, ScrollArea } from '@/components/ui/overlays'
import {
  Alert, AlertDescription, AlertTitle, Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Checkbox, Input, NativeSelect, Table, TableBody, TableCell,
  TableHead, TableHeader, TableRow, Textarea,
} from '@/components/ui/primitives'
import { ApiError, api, errorMessage } from '@/lib/api'
import { cn } from '@/lib/utils'

type DialogKind = 'category' | 'subcategory' | 'department'

export function TaxonomyManager({ meta, canManage }: { meta?: RulesMeta; canManage: boolean }) {
  const tax = useQuery({ queryKey: ['taxonomy'], queryFn: () => api.get<Taxonomy>('/taxonomy') })
  const [dialog, setDialog] = React.useState<DialogKind | null>(null)
  const [q, setQ] = React.useState('')

  if (tax.isLoading) return <LoadingBlock rows={8} />
  if (tax.error) return <ErrorState error={tax.error} onRetry={() => tax.refetch()} />
  const data = tax.data
  if (!data) return null

  const deptName = (code?: string | null) => (code ? data.departments.find((d) => d.code === code)?.name ?? code : '—')
  const needle = q.trim().toLowerCase()
  const categories = data.categories
    .map((c) => ({
      ...c,
      subcategories: c.subcategories.filter((s) => !needle || `${c.code} ${c.name} ${s.code} ${s.name} ${s.description}`.toLowerCase().includes(needle)),
    }))
    .filter((c) => !needle || c.subcategories.length || `${c.code} ${c.name}`.toLowerCase().includes(needle))
  const subCount = data.categories.reduce((n, c) => n + c.subcategories.length, 0)
  const close = () => setDialog(null)

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <p className="text-muted-foreground max-w-3xl text-sm">
          {data.categories.length} categories, {subCount} subcategories and {data.departments.length} departments.
        </p>
        {canManage ? (
          <div className="flex shrink-0 flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => setDialog('category')}>
              <Plus /> Category
            </Button>
            <Button size="sm" onClick={() => setDialog('subcategory')}>
              <Plus /> Subcategory
            </Button>
            <Button size="sm" variant="outline" onClick={() => setDialog('department')}>
              <Plus /> Department
            </Button>
          </div>
        ) : null}
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-4">
          <div className="relative">
            <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" aria-hidden />
            <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter categories and subcategories…" className="pl-8" aria-label="Filter taxonomy" />
          </div>
          {categories.length === 0 ? <EmptyState icon={Search} title="Nothing matches" description="Try another code or name." /> : null}
          {categories.map((c) => (
            <Card key={c.code} className="gap-3">
              <CardHeader>
                <CardTitle className="flex flex-wrap items-center gap-2">
                  <FolderTree className="text-muted-foreground size-4" aria-hidden />
                  <code className="bg-muted rounded px-1.5 py-0.5 font-mono text-xs">{c.code}</code>
                  {c.name}
                  {!c.is_active ? <Badge variant="muted">Inactive</Badge> : null}
                </CardTitle>
                {c.description ? <CardDescription>{c.description}</CardDescription> : null}
              </CardHeader>
              <CardContent className="px-0">
                {c.subcategories.length ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Subcategory</TableHead>
                        <TableHead className="hidden md:table-cell">Routed to</TableHead>
                        <TableHead className="text-right">Rules</TableHead>
                        <TableHead>Classification</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {c.subcategories.map((s) => (
                        <TableRow key={s.code}>
                          <TableCell className="max-w-[26rem]">
                            <div className="flex flex-wrap items-center gap-2">
                              <code className="font-mono text-xs font-semibold">{s.code}</code>
                              <span className="text-sm font-medium">{s.name}</span>
                              {!s.is_active ? <Badge variant="muted">Inactive</Badge> : null}
                            </div>
                            {s.description ? <div className="text-muted-foreground truncate text-xs">{s.description}</div> : null}
                          </TableCell>
                          <TableCell className="hidden text-sm md:table-cell">{s.department ? deptName(s.department) : <Badge variant="destructive">No routing</Badge>}</TableCell>
                          <TableCell className="text-right">
                            <Link to={`/rules?type=resolution&subcategory=${encodeURIComponent(s.code)}`} className="text-primary text-sm font-medium tabular-nums hover:underline" title={`Open the resolution rules for ${s.code}`}>
                              {s.rules}
                            </Link>
                          </TableCell>
                          <TableCell>
                            {s.has_classifier ? (
                              <span className="text-success inline-flex items-center gap-1 text-xs">
                                <CheckCircle2 className="size-3.5" aria-hidden /> Keywords
                              </span>
                            ) : (
                              <Badge variant="destructive">
                                <XCircle aria-hidden /> Missing
                              </Badge>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <p className="text-muted-foreground px-5 text-sm">No subcategories yet.</p>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
        <aside>
          <Card className="xl:sticky xl:top-20">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Building className="text-muted-foreground size-4" aria-hidden /> Departments
              </CardTitle>
              <CardDescription>Routing targets for complaints and escalations.</CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="space-y-3">
                {data.departments.map((d) => (
                  <li key={d.code} className="text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{d.name}</span>
                      <code className="text-muted-foreground font-mono text-[11px]">{d.code}</code>
                      {!d.is_active ? <Badge variant="muted">Inactive</Badge> : null}
                    </div>
                    {d.description ? <p className="text-muted-foreground mt-0.5 text-xs">{d.description}</p> : null}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </aside>
      </div>

      <Dialog open={dialog !== null} onOpenChange={(o) => (o ? null : close())}>
        <DialogContent className={cn(dialog === 'subcategory' && 'max-w-3xl')}>
          {dialog === 'category' ? <CategoryForm onDone={close} /> : null}
          {dialog === 'department' ? <DepartmentForm onDone={close} /> : null}
          {dialog === 'subcategory' ? <SubcategoryForm taxonomy={data} meta={meta} onDone={close} /> : null}
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ------------------------------------------------------------------ shared
function useTaxonomyMutation<T>(path: string, onDone: () => void, success: (body: T) => string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: T) => api.post<Record<string, unknown>>(path, body),
    onSuccess: (_r, body) => {
      toast.success(success(body), { description: 'Available right away.' })
      invalidateRules(qc)
      qc.invalidateQueries({ queryKey: ['config', 'public'] })
      onDone()
    },
  })
}

function ServerError({ error }: { error: unknown }) {
  if (!error) return null
  const issues = integrityIssues(error)
  return (
    <Alert variant="destructive">
      <XCircle />
      <AlertTitle>Not created - {errorMessage(error)}</AlertTitle>
      {issues.length ? (
        <AlertDescription>
          <IssueList issues={issues} />
        </AlertDescription>
      ) : null}
    </Alert>
  )
}

function applyFieldErrors<N extends string>(error: unknown, fields: readonly N[], setError: (name: N, e: { message: string }) => void) {
  if (!(error instanceof ApiError)) return
  for (const [f, m] of Object.entries(error.fieldErrors)) if ((fields as readonly string[]).includes(f)) setError(f as N, { message: m })
}

// ------------------------------------------------------------------ category
const categorySchema = z.object({
  code: z.string().trim().toUpperCase().regex(/^[A-Z]{3,4}$/, 'Use 3-4 capital letters, e.g. ENV.'),
  name: z.string().trim().min(3, 'At least 3 characters.').max(120, 'At most 120 characters.'),
  description: z.string().max(1000),
})
type CategoryValues = z.infer<typeof categorySchema>

function CategoryForm({ onDone }: { onDone: () => void }) {
  const form = useForm<CategoryValues>({ resolver: zodResolver(categorySchema), defaultValues: { code: '', name: '', description: '' } })
  const errors = form.formState.errors
  const create = useTaxonomyMutation<CategoryValues>('/taxonomy/categories', onDone, (b) => `Category ${b.code} ${b.name} created`)
  return (
    <form
      noValidate
      className="space-y-4"
      onSubmit={form.handleSubmit((v) => create.mutate(v, { onError: (e) => applyFieldErrors(e, ['code', 'name', 'description'] as const, form.setError) }))}
    >
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <FolderTree className="text-primary size-5" aria-hidden /> New category
        </DialogTitle>
        <DialogDescription>Add a top-level complaint category, then add its subcategories.</DialogDescription>
      </DialogHeader>
      <div className="grid gap-4 sm:grid-cols-[8rem_minmax(0,1fr)]">
        <Field label="Code" htmlFor="cat-code" required error={errors.code?.message}>
          <Input id="cat-code" className="font-mono uppercase" placeholder="ENV" maxLength={4} autoComplete="off" aria-invalid={!!errors.code} {...form.register('code')} />
        </Field>
        <Field label="Name" htmlFor="cat-name" required error={errors.name?.message}>
          <Input id="cat-name" placeholder="Environmental" aria-invalid={!!errors.name} {...form.register('name')} />
        </Field>
      </div>
      <Field label="Description" htmlFor="cat-desc" error={errors.description?.message}>
        <Textarea id="cat-desc" rows={3} placeholder="What complaints belong in this category?" {...form.register('description')} />
      </Field>
      <ServerError error={create.error} />
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? <Spinner /> : <Plus />} Create category
        </Button>
      </DialogFooter>
    </form>
  )
}

// ------------------------------------------------------------------ department
const departmentSchema = z.object({
  code: z.string().trim().toUpperCase().regex(/^DEPT-[A-Z]{3}$/, 'Use the format DEPT-ABC.'),
  name: z.string().trim().min(3, 'At least 3 characters.').max(120, 'At most 120 characters.'),
  description: z.string().max(1000),
})
type DepartmentValues = z.infer<typeof departmentSchema>

function DepartmentForm({ onDone }: { onDone: () => void }) {
  const form = useForm<DepartmentValues>({ resolver: zodResolver(departmentSchema), defaultValues: { code: 'DEPT-', name: '', description: '' } })
  const errors = form.formState.errors
  const create = useTaxonomyMutation<DepartmentValues>('/taxonomy/departments', onDone, (b) => `Department ${b.name} created`)
  return (
    <form
      noValidate
      className="space-y-4"
      onSubmit={form.handleSubmit((v) => create.mutate(v, { onError: (e) => applyFieldErrors(e, ['code', 'name', 'description'] as const, form.setError) }))}
    >
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <Building className="text-primary size-5" aria-hidden /> New department
        </DialogTitle>
        <DialogDescription>Departments receive routed complaints and escalations.</DialogDescription>
      </DialogHeader>
      <div className="grid gap-4 sm:grid-cols-[10rem_minmax(0,1fr)]">
        <Field label="Code" htmlFor="dept-code" required error={errors.code?.message}>
          <Input id="dept-code" className="font-mono uppercase" placeholder="DEPT-ENV" maxLength={8} autoComplete="off" aria-invalid={!!errors.code} {...form.register('code')} />
        </Field>
        <Field label="Name" htmlFor="dept-name" required error={errors.name?.message}>
          <Input id="dept-name" placeholder="Sustainability Office" aria-invalid={!!errors.name} {...form.register('name')} />
        </Field>
      </div>
      <Field label="Description" htmlFor="dept-desc" error={errors.description?.message}>
        <Textarea id="dept-desc" rows={3} placeholder="What does this department handle?" {...form.register('description')} />
      </Field>
      <ServerError error={create.error} />
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? <Spinner /> : <Plus />} Create department
        </Button>
      </DialogFooter>
    </form>
  )
}

// ------------------------------------------------------------------ subcategory
const POLICY_REF = /^[A-Z]{2,5}-[A-Z]{2,5}-\d{2,3}(:[\d.]+)?$/

function splitList(v: string): string[] {
  return v
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

function parseKeywords(text: string): Record<string, number> {
  const out: Record<string, number> = {}
  for (const raw of text.split(/[\n,]/)) {
    const line = raw.trim()
    if (!line) continue
    const m = line.match(/^(.+?)\s*[:=]\s*(\d+(?:\.\d+)?)$/)
    if (m) out[m[1].trim().toLowerCase()] = Number(m[2])
    else out[line.toLowerCase()] = 3
  }
  return out
}

const subcategorySchema = z
  .object({
    category: z.string().min(1, 'Choose a category.'),
    code: z.string().trim().toUpperCase().regex(/^[A-Z]{3,4}-[A-Z]{3}$/, 'Use the format CAT-ABC, e.g. PRD-NOI.'),
    name: z.string().trim().min(3, 'At least 3 characters.').max(120, 'At most 120 characters.'),
    description: z.string().max(1000),
    department: z.string().min(1, 'Choose the primary department.'),
    supporting_departments: z.array(z.string()),
    urgency: z.enum(URGENCY_LEVELS),
    impact: z.enum(IMPACT_LEVELS),
    required_actions: z.array(z.string()).min(1, 'Choose at least one required action.'),
    prohibited_actions: z.array(z.string()),
    policy_refs: z.string().refine((v) => splitList(v).every((r) => POLICY_REF.test(r.toUpperCase())), 'Use references like REF-POL-02:3.1, separated by commas.'),
    follow_up_type: z.string(),
    follow_up_hours: z.number({ message: 'Enter a number of hours.' }).int('Whole hours only.').min(1, 'At least 1 hour.').max(720, 'At most 720 hours.'),
    keywords: z.string().max(4000),
  })
  .refine((v) => !v.supporting_departments.includes(v.department), { path: ['supporting_departments'], message: 'The primary department cannot also be a supporting department.' })
type SubcategoryValues = z.infer<typeof subcategorySchema>
const SUB_FIELDS = ['category', 'code', 'name', 'description', 'department', 'supporting_departments', 'urgency', 'impact', 'required_actions', 'prohibited_actions', 'policy_refs', 'follow_up_type', 'follow_up_hours', 'keywords'] as const

function CheckList({ id, options, value, onChange, invalid, height = 'h-40' }: {
  id: string
  options: { value: string; label: string; hint?: string }[]
  value: string[]
  onChange: (v: string[]) => void
  invalid?: boolean
  height?: string
}) {
  return (
    <ScrollArea className={cn('rounded-lg border', height, invalid && 'border-destructive')}>
      <div role="group" aria-labelledby={`${id}-label`} className="space-y-0.5 p-1.5">
        {options.map((o) => {
          const checked = value.includes(o.value)
          const cid = `${id}-${o.value}`
          return (
            <label key={o.value} htmlFor={cid} className="hover:bg-accent flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 text-sm">
              <Checkbox id={cid} className="mt-0.5" checked={checked} onCheckedChange={(c) => onChange(c === true ? [...value, o.value] : value.filter((x) => x !== o.value))} />
              <span className="min-w-0">
                <span className="block leading-tight">{o.label}</span>
                {o.hint ? <span className="text-muted-foreground block font-mono text-[10.5px]">{o.hint}</span> : null}
              </span>
            </label>
          )
        })}
      </div>
    </ScrollArea>
  )
}

function SubcategoryForm({ taxonomy, meta, onDone }: { taxonomy: Taxonomy; meta?: RulesMeta; onDone: () => void }) {
  const form = useForm<SubcategoryValues>({
    resolver: zodResolver(subcategorySchema),
    defaultValues: {
      category: '', code: '', name: '', description: '', department: '', supporting_departments: [], urgency: 'Medium', impact: 'Medium',
      required_actions: ['REQUEST_ADDITIONAL_INFO'], prohibited_actions: ['GUARANTEE_COMPENSATION'], policy_refs: '', follow_up_type: 'Resolution confirmation',
      follow_up_hours: 72, keywords: '',
    },
  })
  const errors = form.formState.errors
  const [category, code, department] = useWatch({ control: form.control, name: ['category', 'code', 'department'] })
  const create = useTaxonomyMutation<Record<string, unknown>>('/taxonomy/subcategories', onDone, (b) => `Subcategory ${String(b.code)} created with routing, resolution and classification rules`)

  const submit = (v: SubcategoryValues) => {
    const payload = {
      code: v.code,
      category: v.category,
      name: v.name,
      description: v.description.trim(),
      department: v.department,
      supporting_departments: v.supporting_departments,
      urgency: v.urgency,
      impact: v.impact,
      required_actions: v.required_actions,
      prohibited_actions: v.prohibited_actions,
      policy_refs: splitList(v.policy_refs).map((r) => r.toUpperCase()),
      follow_up_type: v.follow_up_type || null,
      follow_up_hours: v.follow_up_hours,
      keywords: parseKeywords(v.keywords),
    }
    create.mutate(payload, { onError: (e) => applyFieldErrors(e, SUB_FIELDS, form.setError) })
  }

  const prefixMismatch = category && code && !code.trim().toUpperCase().startsWith(`${category}-`)
  const deptOptions = taxonomy.departments.map((d) => ({ value: d.code, label: d.name, hint: d.code }))
  const actionOptions = (meta?.actions ?? []).map((a) => ({ value: a.code, label: a.name, hint: a.code }))
  const prohibitedOptions = (meta?.prohibited_actions ?? []).map((a) => ({ value: a.code, label: a.name, hint: `${a.code} · ${a.severity}` }))
  const followUps = meta?.follow_up_types ?? ['Resolution confirmation']
  const kw = (useWatch({ control: form.control, name: 'keywords' }) ?? '').trim()
  const kwCount = kw ? Object.keys(parseKeywords(kw)).length : 0

  return (
    <form noValidate className="min-w-0 space-y-5" onSubmit={form.handleSubmit(submit)}>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <Tags className="text-primary size-5" aria-hidden /> New subcategory
        </DialogTitle>
        <DialogDescription>
          Also creates its rules: <code className="font-mono text-xs">RTE-{code || 'CODE'}</code> (routing), <code className="font-mono text-xs">RES-{code || 'CODE'}-01</code> (default resolution) and <code className="font-mono text-xs">CAT-{code || 'CODE'}</code> (classification).
        </DialogDescription>
      </DialogHeader>

      <fieldset className="grid gap-4 sm:grid-cols-2" disabled={create.isPending}>
        <legend className="sr-only">Identity</legend>
        <Field label="Category" htmlFor="sub-cat" required error={errors.category?.message}>
          <NativeSelect
            id="sub-cat"
            aria-invalid={!!errors.category}
            {...form.register('category', {
              onChange: (e: React.ChangeEvent<HTMLSelectElement>) => {
                const current = form.getValues('code')
                if (!current || /^[A-Z]{0,4}-?$/i.test(current)) form.setValue('code', e.target.value ? `${e.target.value}-` : '')
              },
            })}
          >
            <option value="">Choose…</option>
            {taxonomy.categories.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code} · {c.name}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field label="Code" htmlFor="sub-code" required error={errors.code?.message} hint={prefixMismatch ? `Should start with ${category}-` : 'Format CAT-ABC, e.g. PRD-NOI'}>
          <Input id="sub-code" className="font-mono uppercase" placeholder="PRD-NOI" maxLength={8} autoComplete="off" aria-invalid={!!errors.code} {...form.register('code')} />
        </Field>
        <Field label="Name" htmlFor="sub-name" required error={errors.name?.message}>
          <Input id="sub-name" placeholder="Excessive Noise" aria-invalid={!!errors.name} {...form.register('name')} />
        </Field>
        <Field label="Description" htmlFor="sub-desc" error={errors.description?.message}>
          <Input id="sub-desc" placeholder="Device is louder than specified" {...form.register('description')} />
        </Field>
      </fieldset>

      <fieldset className="grid gap-4 sm:grid-cols-2" disabled={create.isPending}>
        <legend className="mb-2 text-sm font-semibold">Routing & priority</legend>
        <Field label="Primary department" htmlFor="sub-dept" required error={errors.department?.message}>
          <NativeSelect id="sub-dept" aria-invalid={!!errors.department} {...form.register('department')}>
            <option value="">Choose…</option>
            {taxonomy.departments.map((d) => (
              <option key={d.code} value={d.code}>
                {d.name}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Urgency" htmlFor="sub-urg">
            <NativeSelect id="sub-urg" {...form.register('urgency')}>
              {[...URGENCY_LEVELS].reverse().map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field label="Impact" htmlFor="sub-imp">
            <NativeSelect id="sub-imp" {...form.register('impact')}>
              {[...IMPACT_LEVELS].reverse().map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </NativeSelect>
          </Field>
        </div>
        <div className="space-y-1.5 sm:col-span-2">
          <span id="sub-support-label" className="text-sm font-medium">
            Supporting departments
          </span>
          <Controller
            control={form.control}
            name="supporting_departments"
            render={({ field }) => (
              <CheckList id="sub-support" options={deptOptions.filter((o) => o.value !== department)} value={field.value} onChange={field.onChange} invalid={!!errors.supporting_departments} height="h-28" />
            )}
          />
          {errors.supporting_departments?.message ? (
            <p className="text-destructive text-xs" role="alert">
              {errors.supporting_departments.message}
            </p>
          ) : null}
        </div>
      </fieldset>

      <fieldset className="grid gap-4 sm:grid-cols-2" disabled={create.isPending}>
        <legend className="mb-2 text-sm font-semibold">Default resolution rule</legend>
        <div className="space-y-1.5">
          <span id="sub-req-label" className="text-sm font-medium">
            Required actions <span className="text-destructive">*</span>
          </span>
          <Controller
            control={form.control}
            name="required_actions"
            render={({ field }) => <CheckList id="sub-req" options={actionOptions} value={field.value} onChange={field.onChange} invalid={!!errors.required_actions} />}
          />
          {errors.required_actions?.message ? (
            <p className="text-destructive text-xs" role="alert">
              {errors.required_actions.message}
            </p>
          ) : null}
        </div>
        <div className="space-y-1.5">
          <span id="sub-pro-label" className="text-sm font-medium">
            Prohibited actions
          </span>
          <Controller control={form.control} name="prohibited_actions" render={({ field }) => <CheckList id="sub-pro" options={prohibitedOptions} value={field.value} onChange={field.onChange} />} />
        </div>
        <Field label="Policy references" htmlFor="sub-refs" error={errors.policy_refs?.message} hint="Comma-separated, e.g. PRD-POL-03:4.1">
          <Input id="sub-refs" className="font-mono" placeholder="RPL-POL-03:4.1, RTE-RUL-14:3" aria-invalid={!!errors.policy_refs} {...form.register('policy_refs')} />
        </Field>
        <div className="grid grid-cols-[minmax(0,1fr)_6rem] gap-3">
          <Field label="Follow-up" htmlFor="sub-fu">
            <NativeSelect id="sub-fu" {...form.register('follow_up_type')}>
              <option value="">No follow-up</option>
              {followUps.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field label="Due (h)" htmlFor="sub-fuh" error={errors.follow_up_hours?.message}>
            <Input id="sub-fuh" type="number" min={1} max={720} inputMode="numeric" aria-invalid={!!errors.follow_up_hours} {...form.register('follow_up_hours', { valueAsNumber: true })} />
          </Field>
        </div>
      </fieldset>

      <fieldset disabled={create.isPending}>
        <legend className="mb-2 text-sm font-semibold">Classification keywords</legend>
        <Field
          label="Keywords"
          htmlFor="sub-kw"
          error={errors.keywords?.message}
          hint={kwCount ? `${kwCount} keyword${kwCount === 1 ? '' : 's'}. Optional weight after a colon (default 3).` : 'One per line or comma-separated, with an optional weight, e.g. "grinding noise: 4". Leave empty to use the name.'}
        >
          <Textarea id="sub-kw" rows={3} className="font-mono text-xs" placeholder={'too loud: 4\ngrinding noise: 4\nbuzzing'} {...form.register('keywords')} />
        </Field>
      </fieldset>

      <ServerError error={create.error} />
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? <Spinner /> : <Plus />} Create subcategory
        </Button>
      </DialogFooter>
    </form>
  )
}
