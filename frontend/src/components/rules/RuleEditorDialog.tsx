/* JSON editor for one Rule Matrix entry (a rule or a configuration row).
   Validate = local JSON checks + the server's integrity check of the live matrix.
   Save     = PUT; the server rebuilds a candidate matrix WITH the change and rejects it if it
              would introduce an integrity error - nothing is stored in that case. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Braces, CheckCircle2, Eye, Pencil, Save, ShieldAlert, ShieldCheck, Undo2, XCircle } from 'lucide-react'
import * as React from 'react'
import { toast } from 'sonner'

import { CopyButton, ErrorState, LoadingBlock, Spinner } from '@/components/app/common'
import { type IntegrityIssue, type IntegrityReport, integrityIssues, invalidateRules, RULE_TYPE_LABEL, type RuleRow } from '@/components/rules/model'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/overlays'
import { Alert, AlertDescription, AlertTitle, Badge, Label, Switch, Textarea } from '@/components/ui/primitives'
import { ApiError, api, errorMessage } from '@/lib/api'
import { fmtDateTime, fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'

export interface EditorTarget {
  ruleType: string
  ruleId: string
  initial?: RuleRow
  label?: string
}

const enc = encodeURIComponent

export function IssueList({ issues, max = 12 }: { issues: IntegrityIssue[]; max?: number }) {
  if (!issues.length) return null
  return (
    <ul className="space-y-1.5">
      {issues.slice(0, max).map((i, idx) => (
        <li key={`${i.rule_id}-${idx}`} className="flex items-start gap-2 text-xs">
          <Badge variant={i.severity === 'error' ? 'destructive' : 'warning'} className="shrink-0 uppercase">
            {i.severity}
          </Badge>
          {i.rule_id ? <code className="text-foreground shrink-0 font-mono">{i.rule_id}</code> : null}
          <span className="text-foreground/90">{i.message}</span>
        </li>
      ))}
      {issues.length > max ? <li className="text-muted-foreground text-xs">…and {issues.length - max} more</li> : null}
    </ul>
  )
}

export function IntegrityPanel({ report, note }: { report: IntegrityReport; note?: React.ReactNode }) {
  return (
    <div className={cn('rounded-lg border p-3', report.valid ? 'border-success/30 bg-success/5' : 'border-destructive/30 bg-destructive/5')} role="status">
      <div className="flex flex-wrap items-center gap-2 text-sm font-semibold">
        {report.valid ? <ShieldCheck className="text-success size-4" aria-hidden /> : <ShieldAlert className="text-destructive size-4" aria-hidden />}
        {report.valid ? 'Rule Matrix integrity: valid' : 'Rule Matrix integrity: errors found'}
        <span className="text-muted-foreground text-xs font-normal tabular-nums">
          {report.errors} error{report.errors === 1 ? '' : 's'} · {report.warnings} warning{report.warnings === 1 ? '' : 's'}
        </span>
        {report.ruleset_hash ? <span className="text-muted-foreground ml-auto font-mono text-[11px] font-normal">hash {report.ruleset_hash}</span> : null}
      </div>
      {note ? <p className="text-muted-foreground mt-1 text-xs">{note}</p> : null}
      {report.issues.length ? (
        <div className="mt-2">
          <IssueList issues={report.issues} />
        </div>
      ) : null}
    </div>
  )
}

export function RuleEditorDialog({ target, onOpenChange, canManage }: { target: EditorTarget | null; onOpenChange: (open: boolean) => void; canManage: boolean }) {
  return (
    <Dialog open={!!target} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        {target ? <EditorLoader key={`${target.ruleType}:${target.ruleId}`} target={target} canManage={canManage} onClose={() => onOpenChange(false)} /> : null}
      </DialogContent>
    </Dialog>
  )
}

function EditorLoader({ target, canManage, onClose }: { target: EditorTarget; canManage: boolean; onClose: () => void }) {
  const q = useQuery({
    queryKey: ['rules', 'item', target.ruleType, target.ruleId],
    queryFn: () => api.get<RuleRow>(`/rules/${enc(target.ruleType)}/${enc(target.ruleId)}`),
    initialData: target.initial,
  })
  const rule = q.data
  const kind = target.ruleType === 'config' ? 'setting' : `${(RULE_TYPE_LABEL[target.ruleType] ?? target.ruleType).toLowerCase()} rule`
  return (
    <>
      <DialogHeader>
        <DialogTitle className="flex flex-wrap items-center gap-2">
          {canManage ? <Pencil className="text-primary size-4.5" aria-hidden /> : <Eye className="text-primary size-4.5" aria-hidden />}
          {canManage ? 'Edit' : 'View'} {kind} <code className="bg-muted rounded px-1.5 py-0.5 font-mono text-sm">{target.ruleId}</code>
          {rule ? (
            <Badge variant="outline" className="tabular-nums">
              v{rule.version}
            </Badge>
          ) : null}
          {rule && target.ruleType !== 'config' ? <Badge variant={rule.is_active ? 'success' : 'muted'}>{rule.is_active ? 'Active' : 'Inactive'}</Badge> : null}
        </DialogTitle>
        <DialogDescription>
          {target.label ?? (rule?.name && rule.name !== rule.rule_id ? rule.name : null)}
          {rule?.updated_at ? (
            <span title={fmtDateTime(rule.updated_at)}>
              {target.label || (rule.name && rule.name !== rule.rule_id) ? ' · ' : ''}updated {fmtRelative(rule.updated_at)}
            </span>
          ) : null}
        </DialogDescription>
      </DialogHeader>
      {q.isLoading ? <LoadingBlock rows={6} /> : q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : rule ? <EditorBody key={rule.version} rule={rule} canManage={canManage} onClose={onClose} /> : null}
    </>
  )
}

type Parsed = { ok: true; value: Record<string, unknown> } | { ok: false; error: string }

function parseBody(text: string, rule: RuleRow): Parsed {
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : 'The text is not valid JSON.' }
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return { ok: false, error: 'Enter a JSON object: { … }.' }
  const body = value as Record<string, unknown>
  if (rule.rule_type !== 'config' && 'rule_id' in body && String(body.rule_id) !== rule.rule_id)
    return { ok: false, error: `Keep "rule_id": "${rule.rule_id}" - changing it would create a different rule.` }
  return { ok: true, value: body }
}

function EditorBody({ rule, canManage, onClose }: { rule: RuleRow; canManage: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const textareaId = React.useId()
  const switchId = React.useId()
  const statusId = React.useId()
  const [initialText] = React.useState(() => JSON.stringify(rule.body, null, 2))
  const [text, setText] = React.useState(initialText)
  const [active, setActive] = React.useState(rule.is_active)
  const [report, setReport] = React.useState<IntegrityReport | null>(null)

  const parsed = parseBody(text, rule)
  const dirty = text !== initialText || active !== rule.is_active
  const lines = text.split('\n').length

  const validate = useMutation({ mutationFn: () => api.post<IntegrityReport>('/rules/validate'), onSuccess: (r) => setReport(r) })
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.put<RuleRow>(`/rules/${enc(rule.rule_type)}/${enc(rule.rule_id)}`, { body, is_active: active }),
    onSuccess: (r) => {
      toast.success(`Saved ${r.rule_id} (v${r.version})`, { description: 'Applies to new decisions right away.' })
      invalidateRules(qc)
      onClose()
    },
  })

  const doSave = () => {
    if (canManage && parsed.ok && dirty && !save.isPending) save.mutate(parsed.value)
  }
  const saveIssues = integrityIssues(save.error)
  const saveFieldErrors = save.error instanceof ApiError ? Object.entries(save.error.fieldErrors) : []

  return (
    <div className="min-w-0 space-y-4">
      {rule.condition ? (
        <div className="bg-muted/50 rounded-lg border p-3">
          <div className="text-muted-foreground text-xs font-medium">Condition</div>
          <code className="mt-1 block font-mono text-xs break-words">{rule.condition}</code>
        </div>
      ) : null}

      <div className="space-y-1.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Label htmlFor={textareaId}>{rule.rule_type === 'config' ? 'Setting (JSON)' : 'Rule definition (JSON)'}</Label>
          <div className="flex items-center gap-1">
            <span className={cn('mr-1 inline-flex items-center gap-1 text-xs font-medium', parsed.ok ? 'text-success' : 'text-destructive')}>
              {parsed.ok ? <CheckCircle2 className="size-3.5" aria-hidden /> : <XCircle className="size-3.5" aria-hidden />}
              {parsed.ok ? 'Valid JSON' : 'Invalid'}
            </span>
            {canManage ? (
              <>
                <Button type="button" variant="ghost" size="sm" onClick={() => parsed.ok && setText(JSON.stringify(parsed.value, null, 2))} disabled={!parsed.ok}>
                  <Braces /> Format
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={!dirty}
                  onClick={() => {
                    setText(initialText)
                    setActive(rule.is_active)
                    setReport(null)
                    save.reset()
                  }}
                >
                  <Undo2 /> Revert
                </Button>
              </>
            ) : null}
            <CopyButton value={text} label="Copy JSON" />
          </div>
        </div>
        <Textarea
          id={textareaId}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
              e.preventDefault()
              doSave()
            }
          }}
          readOnly={!canManage}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          aria-invalid={!parsed.ok}
          aria-describedby={statusId}
          className="max-h-[48vh] min-h-72 font-mono text-[12px] leading-relaxed whitespace-pre"
        />
        <p id={statusId} className={cn('text-xs', parsed.ok ? 'text-muted-foreground' : 'text-destructive')} role={parsed.ok ? undefined : 'alert'}>
          {parsed.ok ? `${lines} lines${canManage ? ' · Ctrl/⌘ + S saves' : ' · read-only for your role'}` : parsed.error}
        </p>
      </div>

      {rule.rule_type !== 'config' ? (
        <div className="flex items-center justify-between gap-3 rounded-lg border p-3">
          <div>
            <Label htmlFor={switchId}>Active</Label>
            <p className="text-muted-foreground mt-1 text-xs">Inactive rules are kept but never applied.</p>
          </div>
          <Switch id={switchId} checked={active} onCheckedChange={setActive} disabled={!canManage} />
        </div>
      ) : null}

      {validate.error ? (
        <p className="text-destructive text-xs" role="alert">
          The integrity check could not run: {errorMessage(validate.error)}
        </p>
      ) : null}
      {report ? (
        <IntegrityPanel report={report} note={dirty ? 'Unsaved changes are not included; they are checked on save.' : undefined} />
      ) : null}

      {save.error ? (
        <Alert variant="destructive">
          <XCircle />
          <AlertTitle>Not saved - {errorMessage(save.error)}</AlertTitle>
          <AlertDescription>
            {saveIssues.length ? <IssueList issues={saveIssues} /> : null}
            {saveFieldErrors.length ? (
              <ul className="list-disc pl-4 text-xs">
                {saveFieldErrors.map(([f, m]) => (
                  <li key={f}>
                    <code className="font-mono">{f}</code>: {m}
                  </li>
                ))}
              </ul>
            ) : null}
            <p className="text-xs">The live Rule Matrix is unchanged.</p>
          </AlertDescription>
        </Alert>
      ) : null}

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          {canManage ? 'Cancel' : 'Close'}
        </Button>
        <Button type="button" variant="secondary" onClick={() => validate.mutate()} disabled={!parsed.ok || validate.isPending}>
          {validate.isPending ? <Spinner /> : <ShieldCheck />} Validate
        </Button>
        {canManage ? (
          <Button type="button" onClick={doSave} disabled={!parsed.ok || !dirty || save.isPending}>
            {save.isPending ? <Spinner /> : <Save />} Save
          </Button>
        ) : null}
      </DialogFooter>
    </div>
  )
}
