/* Administration: users and roles (server-side RBAC) and, for settings:manage, the system configuration,
   AI provider mode and demo-data seed status. The AI key lives only on the server. */
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Cpu, Database, Eye, EyeOff, KeyRound, Pencil, RefreshCw, Search, Server, ShieldCheck, Sparkles, UserCog, UserPlus, Users, Wand2,
} from 'lucide-react'
import * as React from 'react'
import { Controller, useForm, useWatch } from 'react-hook-form'
import { useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { z } from 'zod'

import { EmptyState, ErrorState, Field, KeyValue, LoadingBlock, PageHeader, Spinner, StatCard } from '@/components/app/common'
import { AccessMatrixTable } from '@/components/insights/access-matrix'
import { Metric } from '@/components/insights/common'
import { humanize } from '@/components/insights/format'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/overlays'
import {
  Alert, AlertDescription, AlertTitle, Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, NativeSelect, Progress, Switch,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/primitives'
import { ApiError, api, errorMessage } from '@/lib/api'
import { ROLE_LABELS, useAuth, usePublicConfig } from '@/lib/auth'
import { fmtDateTime, fmtRelative } from '@/lib/format'
import type { Role } from '@/lib/types'
import { cn, num } from '@/lib/utils'

// ------------------------------------------------------------------ response shapes
interface AdminUser {
  id: number
  email: string
  full_name: string
  role: Role
  department: string | null
  customer_ref: string | null
  is_active: boolean
  last_login_at: string | null
  created_at: string | null
}
interface RoleInfo { code: string; name: string; description: string; permissions: string[] }
interface SystemInfo {
  version: string
  environment: string
  database: string
  ai: { provider: string; model: string; configured: boolean; timeout_seconds: number; max_retries: number; refusal_fallback: boolean }
  embedding_provider: string
  retrieval_top_k: number
  workers: number
  sla_monitor_interval_seconds: number
  rate_limits: { per_minute: number; auth_per_minute: number }
  uploads: { max_document_mb: number; max_attachment_mb: number }
  duplicates: { window_hours: number; near_duplicate_threshold: number; reject_exact: boolean }
}
interface SeedStatus { state: string; done: number; total: number; started_at: string | null; finished_at: string | null; error: string | null; lifecycle?: Record<string, number> }

type BadgeVariant = NonNullable<React.ComponentProps<typeof Badge>['variant']>
const ROLE_VARIANT: Record<string, BadgeVariant> = { admin: 'primary', manager: 'validate', reviewer: 'info', agent: 'secondary', customer: 'outline' }
const INTERNAL = ['agent', 'reviewer', 'manager', 'admin']

function roleName(code: string, roles?: RoleInfo[]): string {
  return roles?.find((r) => r.code === code)?.name ?? (code in ROLE_LABELS ? ROLE_LABELS[code as Role] : humanize(code))
}

const TABS = ['users', 'roles', 'system'] as const
type TabKey = (typeof TABS)[number]

// ------------------------------------------------------------------ page
export default function AdminPage() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()
  const canSystem = can('settings:manage')
  const raw = params.get('tab') ?? ''
  const tab: TabKey = (TABS as readonly string[]).includes(raw) && (raw !== 'system' || canSystem) ? (raw as TabKey) : 'users'
  const users = useQuery({ queryKey: ['admin', 'users'], queryFn: () => api.get<{ items: AdminUser[]; total: number }>('/users') })
  const roles = useQuery({ queryKey: ['admin', 'roles'], queryFn: () => api.get<{ items: RoleInfo[] }>('/roles'), staleTime: 10 * 60_000 })
  const [editing, setEditing] = React.useState<AdminUser | 'new' | null>(null)
  const canManage = can('users:manage')

  const items = users.data?.items ?? []
  const active = items.filter((u) => u.is_active).length
  const internal = items.filter((u) => INTERNAL.includes(u.role)).length

  return (
    <>
      <PageHeader
        eyebrow="Administration"
        title="Users, roles & system"
        description="Manage who can use SupportNova and what each role can do."
        actions={
          canManage ? (
            <Button onClick={() => setEditing('new')}>
              <UserPlus /> New user
            </Button>
          ) : null
        }
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Users" value={num(items.length)} icon={Users} tone="primary" hint={`${num(active)} active · ${num(items.length - active)} disabled`} />
        <StatCard label="Staff accounts" value={num(internal)} icon={UserCog} hint="agents, reviewers, managers, admins" />
        <StatCard label="Customer accounts" value={num(items.filter((u) => u.role === 'customer').length)} icon={Users} hint="customer portal sign-ins" />
        <StatCard label="Roles" value={num(roles.data?.items.length ?? 0)} icon={KeyRound} tone="validate" hint="fixed permission sets" />
      </div>

      <Tabs
        value={tab}
        onValueChange={(v) => {
          const next = new URLSearchParams(params)
          next.set('tab', v)
          setParams(next, { replace: true })
        }}
        className="mt-6"
      >
        <TabsList aria-label="Administration sections">
          <TabsTrigger value="users"><Users aria-hidden /> Users</TabsTrigger>
          <TabsTrigger value="roles"><KeyRound aria-hidden /> Roles & permissions</TabsTrigger>
          {canSystem ? <TabsTrigger value="system"><Server aria-hidden /> System</TabsTrigger> : null}
        </TabsList>
        <TabsContent value="users">
          <UsersPanel users={users} roles={roles.data?.items} canManage={canManage} onEdit={setEditing} />
        </TabsContent>
        <TabsContent value="roles">
          <RolesPanel roles={roles} users={items} />
        </TabsContent>
        {canSystem ? (
          <TabsContent value="system">
            <SystemPanel />
          </TabsContent>
        ) : null}
      </Tabs>

      <Dialog open={editing !== null} onOpenChange={(open) => { if (!open) setEditing(null) }}>
        {editing !== null ? (
          <UserDialog key={editing === 'new' ? 'new' : editing.id} user={editing === 'new' ? null : editing} roles={roles.data?.items ?? []} onDone={() => setEditing(null)} />
        ) : null}
      </Dialog>
    </>
  )
}

// ------------------------------------------------------------------ users
function UsersPanel({ users, roles, canManage, onEdit }: {
  users: { isLoading: boolean; error: unknown; data?: { items: AdminUser[] }; refetch: () => unknown }
  roles?: RoleInfo[]
  canManage: boolean
  onEdit: (u: AdminUser) => void
}) {
  const { session } = useAuth()
  const config = usePublicConfig()
  const [q, setQ] = React.useState('')
  const [role, setRole] = React.useState('')
  const [status, setStatus] = React.useState('')
  if (users.isLoading) return <LoadingBlock rows={6} />
  if (users.error) return <ErrorState error={users.error} onRetry={() => users.refetch()} />
  const all = users.data?.items ?? []
  const needle = q.trim().toLowerCase()
  const shown = all.filter(
    (u) =>
      (!needle || u.full_name.toLowerCase().includes(needle) || u.email.toLowerCase().includes(needle) || (u.customer_ref ?? '').toLowerCase().includes(needle)) &&
      (!role || u.role === role) &&
      (!status || (status === 'active' ? u.is_active : !u.is_active)),
  )
  const deptName = (code: string | null) => (code ? config.data?.departments.find((d) => d.code === code)?.name ?? code : null)
  const roleCodes = [...new Set(all.map((u) => u.role))]

  return (
    <Card className="py-0">
      <CardHeader className="pt-5">
        <CardTitle>Users</CardTitle>
        <CardDescription>{canManage ? 'Create, edit and disable user accounts.' : 'Read-only. Only administrators can change users.'}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 px-0 pb-4">
        <div className="flex flex-col gap-2 px-5 sm:flex-row sm:flex-wrap sm:items-center">
          <div className="relative sm:w-72">
            <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" aria-hidden />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, email or customer ref" className="pl-8" aria-label="Search users" />
          </div>
          <NativeSelect aria-label="Filter by role" className="sm:w-48" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="">All roles</option>
            {roleCodes.map((r) => <option key={r} value={r}>{roleName(r, roles)}</option>)}
          </NativeSelect>
          <NativeSelect aria-label="Filter by status" className="sm:w-40" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Any status</option>
            <option value="active">Active</option>
            <option value="disabled">Disabled</option>
          </NativeSelect>
          <span className="text-muted-foreground text-xs sm:ml-auto">{shown.length} of {all.length} users</span>
        </div>
        {shown.length === 0 ? (
          <div className="px-5"><EmptyState icon={Users} title="No users match" description="Try another search or filter." /></div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-5">User</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Department</TableHead>
                <TableHead>Customer</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Last sign-in</TableHead>
                <TableHead className="hidden lg:table-cell">Created</TableHead>
                {canManage ? <TableHead className="pr-5 text-right"><span className="sr-only">Actions</span></TableHead> : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((u) => {
                const me = session?.user.id === u.id
                const initials = u.full_name.split(' ').map((p) => p[0]).slice(0, 2).join('').toUpperCase()
                return (
                  <TableRow key={u.id} className={cn(!u.is_active && 'opacity-60')}>
                    <TableCell className="pl-5">
                      <div className="flex items-center gap-2.5">
                        <span className="nova-gradient flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white" aria-hidden>{initials}</span>
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5 text-sm font-medium">
                            <span className="truncate">{u.full_name}</span>
                            {me ? <Badge variant="muted" className="px-1.5 py-0 text-[10px]">you</Badge> : null}
                          </div>
                          <div className="text-muted-foreground truncate text-xs">{u.email}</div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell><Badge variant={ROLE_VARIANT[u.role] ?? 'outline'}>{roleName(u.role, roles)}</Badge></TableCell>
                    <TableCell className="text-sm">{deptName(u.department) ?? <span className="text-muted-foreground">—</span>}</TableCell>
                    <TableCell className="font-mono text-xs">{u.customer_ref ?? <span className="text-muted-foreground font-sans">—</span>}</TableCell>
                    <TableCell>{u.is_active ? <Badge variant="success">Active</Badge> : <Badge variant="muted">Disabled</Badge>}</TableCell>
                    <TableCell className="text-sm">
                      {u.last_login_at ? <span title={fmtDateTime(u.last_login_at)}>{fmtRelative(u.last_login_at)}</span> : <span className="text-muted-foreground">never</span>}
                    </TableCell>
                    <TableCell className="text-muted-foreground hidden text-sm lg:table-cell">{fmtDateTime(u.created_at)}</TableCell>
                    {canManage ? (
                      <TableCell className="pr-5 text-right">
                        <Button variant="ghost" size="sm" onClick={() => onEdit(u)} aria-label={`Edit ${u.full_name}`}>
                          <Pencil /> Edit
                        </Button>
                      </TableCell>
                    ) : null}
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------------ create / edit user dialog
const userSchema = z
  .object({
    email: z.string().trim().min(1, 'Enter an email address.').email('Enter a valid email address.'),
    full_name: z.string().trim().min(2, 'Enter the full name (at least 2 characters).').max(160, 'Maximum 160 characters.'),
    role: z.string().min(1, 'Choose a role.'),
    password: z.string().max(200, 'Maximum 200 characters.'),
    department: z.string(),
    customer_ref: z.string().trim().max(16, 'Maximum 16 characters.'),
    is_active: z.boolean(),
    creating: z.boolean(),
  })
  .superRefine((v, ctx) => {
    if (v.creating && v.password.length < 10) ctx.addIssue({ code: 'custom', path: ['password'], message: 'Set an initial password of at least 10 characters.' })
    if (!v.creating && v.password && v.password.length < 10) ctx.addIssue({ code: 'custom', path: ['password'], message: 'At least 10 characters — or leave empty to keep the current password.' })
    if (v.role === 'customer' && !v.customer_ref) ctx.addIssue({ code: 'custom', path: ['customer_ref'], message: 'Customer accounts must be linked to a customer reference.' })
  })
type UserValues = z.infer<typeof userSchema>

function generatePassword(): string {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%&*-_+'
  const bytes = new Uint32Array(18)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => chars[b % chars.length]).join('')
}

function UserDialog({ user, roles, onDone }: { user: AdminUser | null; roles: RoleInfo[]; onDone: () => void }) {
  const qc = useQueryClient()
  const { session } = useAuth()
  const config = usePublicConfig()
  const self = !!user && session?.user.id === user.id
  const [showPassword, setShowPassword] = React.useState(false)
  const form = useForm<UserValues>({
    resolver: zodResolver(userSchema),
    defaultValues: {
      email: user?.email ?? '',
      full_name: user?.full_name ?? '',
      role: user?.role ?? 'agent',
      password: '',
      department: user?.department ?? '',
      customer_ref: user?.customer_ref ?? '',
      is_active: user?.is_active ?? true,
      creating: !user,
    },
  })
  const errors = form.formState.errors
  const role = useWatch({ control: form.control, name: 'role' })
  const isCustomer = role === 'customer'
  const roleInfo = roles.find((r) => r.code === role)

  const save = useMutation({
    mutationFn: (v: UserValues) => {
      // Your own role and active flag are locked in the form; never send a change for them.
      const roleCode = self && user ? user.role : v.role
      const body = {
        email: user ? user.email : v.email,
        full_name: v.full_name,
        role: roleCode,
        password: v.password || null,
        department: roleCode === 'customer' ? null : v.department || null,
        customer_ref: roleCode === 'customer' ? v.customer_ref.toUpperCase() || null : null,
        is_active: self ? true : v.is_active,
      }
      return user ? api.put<AdminUser>(`/users/${user.id}`, body) : api.post<AdminUser>('/users', body)
    },
    onSuccess: (u) => {
      toast.success(user ? `Saved ${u.full_name}` : `Created ${u.full_name}`, { description: user ? undefined : `${u.email} can now sign in as ${roleName(u.role, roles)}.` })
      qc.invalidateQueries({ queryKey: ['admin', 'users'] })
      onDone()
    },
    onError: (e) => {
      if (e instanceof ApiError) {
        if (e.status === 409) form.setError('email', { message: e.message })
        const msg = e.message.toLowerCase()
        if (msg.includes('customer reference')) form.setError('customer_ref', { message: e.message })
        if (msg.includes('department')) form.setError('department', { message: e.message })
        Object.entries(e.fieldErrors).forEach(([f, message]) => {
          const key = f.split('.').pop() ?? f
          if (key in userSchema.shape) form.setError(key as keyof UserValues, { message })
        })
      }
      toast.error(errorMessage(e))
    },
  })

  return (
    <DialogContent className="max-w-xl">
      <DialogHeader>
        <DialogTitle>{user ? `Edit ${user.full_name}` : 'New user'}</DialogTitle>
        <DialogDescription>
          {user ? 'Changes take effect right away.' : 'The user signs in with this email and password. The password is not shown again.'}
        </DialogDescription>
      </DialogHeader>
      <form className="space-y-4" noValidate onSubmit={form.handleSubmit((v) => save.mutate(v))}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Email" htmlFor="u-email" error={errors.email?.message} hint={user ? 'The sign-in email cannot be changed.' : undefined} required>
            <Input id="u-email" type="email" autoComplete="off" readOnly={!!user} className={cn(user && 'bg-muted/50 text-muted-foreground')} aria-invalid={!!errors.email} {...form.register('email')} />
          </Field>
          <Field label="Full name" htmlFor="u-name" error={errors.full_name?.message} required>
            <Input id="u-name" autoComplete="off" aria-invalid={!!errors.full_name} {...form.register('full_name')} />
          </Field>
          <Field label="Role" htmlFor="u-role" error={errors.role?.message} hint={self ? 'You cannot change your own role.' : roleInfo?.description} required>
            <NativeSelect id="u-role" disabled={self} aria-invalid={!!errors.role} {...form.register('role')}>
              {(roles.length ? roles : (Object.keys(ROLE_LABELS) as Role[]).map((code) => ({ code, name: ROLE_LABELS[code] }))).map((r) => (
                <option key={r.code} value={r.code}>{r.name}</option>
              ))}
            </NativeSelect>
          </Field>
          {isCustomer ? (
            <Field label="Customer reference" htmlFor="u-cust" error={errors.customer_ref?.message} hint="Links the portal account to the customer record, e.g. CUST-10001." required>
              <Input id="u-cust" className="font-mono uppercase" placeholder="CUST-10001" aria-invalid={!!errors.customer_ref} {...form.register('customer_ref')} />
            </Field>
          ) : (
            <Field label="Department" htmlFor="u-dept" error={errors.department?.message} hint={role === 'agent' ? 'Agents are auto-assigned complaints routed to their department.' : 'Optional for reviewers, managers and admins.'}>
              <NativeSelect id="u-dept" aria-invalid={!!errors.department} {...form.register('department')}>
                <option value="">No department</option>
                {(config.data?.departments ?? []).map((d) => <option key={d.code} value={d.code}>{d.name}</option>)}
              </NativeSelect>
            </Field>
          )}
        </div>
        <Field label={user ? 'New password' : 'Initial password'} htmlFor="u-pass" error={errors.password?.message} hint={user ? 'Leave empty to keep the current password. Minimum 10 characters.' : 'Minimum 10 characters. Share it with the user through a secure channel.'} required={!user}>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Input id="u-pass" type={showPassword ? 'text' : 'password'} autoComplete="new-password" className="pr-9 font-mono" aria-invalid={!!errors.password} {...form.register('password')} />
              <button
                type="button"
                className="text-muted-foreground hover:text-foreground absolute top-1/2 right-2 -translate-y-1/2 rounded p-0.5"
                onClick={() => setShowPassword((s) => !s)}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                aria-pressed={showPassword}
              >
                {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                form.setValue('password', generatePassword(), { shouldValidate: true, shouldDirty: true })
                setShowPassword(true)
              }}
            >
              <Wand2 /> Generate
            </Button>
          </div>
        </Field>
        <Controller
          control={form.control}
          name="is_active"
          render={({ field }) => (
            <div className="flex items-start justify-between gap-4 rounded-lg border p-3">
              <div>
                <label htmlFor="u-active" className="text-sm font-medium">Account active</label>
                <p className="text-muted-foreground text-xs">{self ? 'You cannot disable your own account.' : 'Disabled users cannot sign in; their history stays in the audit log.'}</p>
              </div>
              <Switch id="u-active" checked={field.value} onCheckedChange={field.onChange} disabled={self} />
            </div>
          )}
        />
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onDone}>Cancel</Button>
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? <Spinner /> : user ? <ShieldCheck /> : <UserPlus />} {user ? 'Save changes' : 'Create user'}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  )
}

// ------------------------------------------------------------------ roles & permissions
function RolesPanel({ roles, users }: { roles: { isLoading: boolean; error: unknown; data?: { items: RoleInfo[] }; refetch: () => unknown }; users: AdminUser[] }) {
  const { session } = useAuth()
  if (roles.isLoading) return <LoadingBlock rows={6} />
  if (roles.error) return <ErrorState error={roles.error} onRetry={() => roles.refetch()} />
  const items = roles.data?.items ?? []
  const permissions = [...new Set(items.flatMap((r) => r.permissions))].sort()
  const byRole = new Map(items.map((r) => [r.code, new Set(r.permissions)]))
  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        {items.map((r) => (
          <Card key={r.code} className="gap-3">
            <CardHeader>
              <div className="flex items-center justify-between gap-2">
                <Badge variant={ROLE_VARIANT[r.code] ?? 'outline'}>{r.name}</Badge>
                <span className="text-muted-foreground text-xs tabular-nums">{users.filter((u) => u.role === r.code).length} users</span>
              </div>
            </CardHeader>
            <CardContent className="space-y-2">
              <p className="text-muted-foreground text-sm">{r.description}</p>
              <p className="text-xs"><span className="font-semibold tabular-nums">{r.permissions.length}</span> of {permissions.length} permissions</p>
            </CardContent>
          </Card>
        ))}
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Permission matrix</CardTitle>
          <CardDescription>What each role can do. Your role is highlighted.</CardDescription>
        </CardHeader>
        <CardContent>
          {items.length === 0 ? (
            <EmptyState icon={KeyRound} title="No roles defined" />
          ) : (
            <AccessMatrixTable
              roles={items.map((r) => ({ code: r.code, name: r.name }))}
              permissions={permissions}
              granted={(role, p) => !!byRole.get(role)?.has(p)}
              currentRole={session?.user.role}
              caption="Permissions granted to each role"
            />
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// ------------------------------------------------------------------ system (settings:manage)
const SEED_STATE: Record<string, { variant: BadgeVariant; label: string }> = {
  idle: { variant: 'muted', label: 'Not running' },
  running: { variant: 'info', label: 'Importing' },
  completed: { variant: 'success', label: 'Completed' },
  failed: { variant: 'destructive', label: 'Failed' },
  unavailable: { variant: 'warning', label: 'Dataset missing' },
}

function SystemPanel() {
  const info = useQuery({ queryKey: ['admin', 'system-info'], queryFn: () => api.get<SystemInfo>('/system/info') })
  const seed = useQuery({
    queryKey: ['seed-status'],
    queryFn: () => api.get<SeedStatus>('/system/seed-status'),
    refetchInterval: (q) => (q.state.data?.state === 'running' ? 3000 : false),
  })
  if (info.isLoading) return <LoadingBlock rows={8} />
  if (info.error) return <ErrorState error={info.error} onRetry={() => info.refetch()} />
  const s = info.data!
  const configured = s.ai.configured
  const seedState = SEED_STATE[seed.data?.state ?? ''] ?? { variant: 'outline' as BadgeVariant, label: humanize(seed.data?.state) || '—' }
  const seedPct = seed.data?.total ? Math.round((seed.data.done / seed.data.total) * 100) : 0

  return (
    <div className="space-y-6">
      <Card className={cn(configured ? 'border-success/35' : 'border-warning/45')}>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <span className={cn('flex size-10 items-center justify-center rounded-xl', configured ? 'bg-success/12 text-success' : 'bg-warning/15 text-[oklch(0.5_0.13_60)] dark:text-warning')}>
              {configured ? <Sparkles className="size-5" aria-hidden /> : <KeyRound className="size-5" aria-hidden />}
            </span>
            <div className="min-w-0">
              <CardTitle className="flex flex-wrap items-center gap-2">
                {configured ? `AI connected - ${s.ai.provider} / ${s.ai.model}` : 'AI not configured'}
                {configured ? <Badge variant="success">Live</Badge> : <Badge variant="warning">No API key</Badge>}
              </CardTitle>
              {configured ? null : <CardDescription className="mt-1">Add the API key on the server and restart it.</CardDescription>}
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
            <Metric label="Provider" value={<span className="font-mono text-base">{s.ai.provider}</span>} />
            <Metric label="Model" value={<span className="font-mono text-sm break-all">{s.ai.model}</span>} />
            <Metric label="Key configured" value={s.ai.configured ? 'Yes' : 'No'} tone={s.ai.configured ? 'success' : 'warning'} />
            <Metric label="Timeout" value={`${num(s.ai.timeout_seconds, 1)} s`} />
            <Metric label="Max retries" value={num(s.ai.max_retries)} />
            <Metric label="Refusal fallback" value={s.ai.refusal_fallback ? 'On' : 'Off'} info="If the AI refuses, the case goes to manual review." />
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Cpu className="text-muted-foreground size-4" aria-hidden /> Platform</CardTitle>
          </CardHeader>
          <CardContent>
            <KeyValue
              items={[
                ['Version', <span key="v" className="font-mono text-xs">{s.version}</span>],
                ['Environment', <Badge key="e" variant={s.environment === 'production' ? 'success' : 'warning'}>{s.environment}</Badge>],
                ['Database', s.database],
                ['Embedding provider', s.embedding_provider],
                ['Passages per search', s.retrieval_top_k],
                ['Background workers', s.workers],
                ['SLA monitor interval', `every ${num(s.sla_monitor_interval_seconds)} s`],
              ]}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><ShieldCheck className="text-muted-foreground size-4" aria-hidden /> Limits & safeguards</CardTitle>
            <CardDescription>Rate limits, uploads and duplicate detection</CardDescription>
          </CardHeader>
          <CardContent>
            <KeyValue
              items={[
                ['API rate limit', `${num(s.rate_limits.per_minute)} requests / min per client`],
                ['Sign-in rate limit', `${num(s.rate_limits.auth_per_minute)} attempts / min`],
                ['Max document upload', `${num(s.uploads.max_document_mb)} MB`],
                ['Max attachment', `${num(s.uploads.max_attachment_mb)} MB`],
                ['Duplicate window', `${num(s.duplicates.window_hours)} h`],
                ['Near-duplicate threshold', `similarity ≥ ${s.duplicates.near_duplicate_threshold}`],
                ['Exact duplicates', s.duplicates.reject_exact ? 'Rejected at submission' : 'Linked, not rejected'],
              ]}
            />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="text-muted-foreground size-4" aria-hidden /> Demo dataset import
            <Badge variant={seedState.variant}>{seedState.label}</Badge>
          </CardTitle>
          <CardDescription>Sample complaints loaded for the demo.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {seed.isLoading ? (
            <LoadingBlock rows={2} />
          ) : seed.error ? (
            <ErrorState error={seed.error} onRetry={() => seed.refetch()} />
          ) : seed.data?.state === 'idle' ? (
            <p className="text-muted-foreground text-sm">No import has run since the server started.</p>
          ) : seed.data ? (
            <>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-sm">
                  <span>{num(seed.data.done)} of {num(seed.data.total)} complaints processed</span>
                  <span className="text-muted-foreground tabular-nums">{seedPct}%</span>
                </div>
                <Progress value={seedPct} indicatorClassName={seed.data.state === 'failed' ? 'bg-destructive' : seed.data.state === 'completed' ? 'bg-success' : 'bg-info'} aria-label="Import progress" />
              </div>
              {seed.data.error ? (
                <Alert variant="destructive">
                  <RefreshCw />
                  <AlertTitle>Import problem</AlertTitle>
                  <AlertDescription><p>{seed.data.error}</p></AlertDescription>
                </Alert>
              ) : null}
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
                <Metric label="Started" value={<span className="text-sm">{fmtDateTime(seed.data.started_at)}</span>} />
                <Metric label="Finished" value={<span className="text-sm">{fmtDateTime(seed.data.finished_at)}</span>} />
                {Object.entries(seed.data.lifecycle ?? {}).map(([k, v]) => (
                  <Metric key={k} label={humanize(k)} value={num(v)} hint="lifecycle simulation" />
                ))}
              </div>
            </>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
