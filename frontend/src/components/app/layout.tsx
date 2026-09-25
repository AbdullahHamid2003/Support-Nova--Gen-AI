import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  AlertTriangle, BookOpen, ChartColumn, ClipboardCheck, FileText, FlaskConical, Inbox, LayoutDashboard, LogOut, Menu, Moon, PlusCircle,
  ScrollText, Search, SlidersHorizontal, Sparkles, Sun, Swords, UserCog, Wand2,
} from 'lucide-react'
import * as React from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router'

import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger, Sheet, SheetContent, SheetDescription, SheetTitle, Tooltip } from '@/components/ui/overlays'
import { Badge, Input, Progress } from '@/components/ui/primitives'
import { api } from '@/lib/api'
import { ROLE_LABELS, useAuth, usePublicConfig } from '@/lib/auth'
import { cn } from '@/lib/utils'

interface NavItem {
  to: string
  label: string
  icon: React.ElementType
  show: (can: (p: string) => boolean, role: string) => boolean
  end?: boolean
}

const NAV: { section: string; items: NavItem[] }[] = [
  {
    section: 'Work',
    items: [
      { to: '/', label: 'Dashboard', icon: LayoutDashboard, show: () => true, end: true },
      { to: '/complaints/new', label: 'Submit complaint', icon: PlusCircle, show: (can) => can('complaint:create') },
      { to: '/complaints', label: 'My complaints', icon: Inbox, show: (_c, role) => role === 'customer', end: true },
      { to: '/complaints', label: 'Complaints', icon: Inbox, show: (can) => can('complaint:read_all'), end: true },
      { to: '/reviews', label: 'Review queue', icon: ClipboardCheck, show: (can) => can('review:read') },
    ],
  },
  {
    section: 'Policies & rules',
    items: [
      { to: '/knowledge', label: 'Knowledge base', icon: BookOpen, show: (can) => can('knowledge:read') },
      { to: '/rules', label: 'Rule Matrix', icon: SlidersHorizontal, show: (can) => can('rules:read') },
      { to: '/prompts', label: 'Prompts & AI', icon: Wand2, show: (can) => can('prompts:manage') },
    ],
  },
  {
    section: 'Insight & quality',
    items: [
      { to: '/analytics', label: 'Analytics', icon: ChartColumn, show: (can) => can('analytics:read') },
      { to: '/reports', label: 'Reports', icon: FileText, show: (can) => can('reports:export') },
      { to: '/evaluation', label: 'Evaluation', icon: FlaskConical, show: (can) => can('evaluation:read') },
      { to: '/lab', label: 'Adversarial Lab', icon: Swords, show: (can) => can('lab:use') },
      { to: '/audit', label: 'Audit log', icon: ScrollText, show: (can) => can('audit:read') || can('audit:read_complaint') },
      { to: '/admin', label: 'Administration', icon: UserCog, show: (can) => can('users:read') },
    ],
  },
]

export function Logo({ compact = false, className }: { compact?: boolean; className?: string }) {
  return (
    <div className={cn('flex items-center gap-2.5', className)}>
      <div className="nova-gradient relative flex size-8 shrink-0 items-center justify-center rounded-lg shadow-md">
        <Sparkles className="size-4.5 text-white" aria-hidden />
      </div>
      {!compact ? (
        <div className="leading-tight">
          <div className="text-[15px] font-semibold tracking-tight">SupportNova</div>
          <div className="text-[10.5px] font-medium tracking-wide opacity-70">ResponseX Intelligence</div>
        </div>
      ) : null}
    </div>
  )
}

function useTheme() {
  const [dark, setDark] = React.useState(() => document.documentElement.classList.contains('dark'))
  const toggle = () => {
    const next = !dark
    document.documentElement.classList.toggle('dark', next)
    try {
      localStorage.setItem('sn-theme', next ? 'dark' : 'light')
    } catch {
      /* storage unavailable */
    }
    setDark(next)
  }
  return { dark, toggle }
}

function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const { can, session } = useAuth()
  const role = session?.user.role ?? 'customer'
  return (
    <nav aria-label="Main" className="flex-1 space-y-5 overflow-y-auto px-3 py-4 scrollbar-thin">
      {NAV.map((group) => {
        const items = group.items.filter((i) => i.show(can, role))
        if (!items.length) return null
        return (
          <div key={group.section}>
            <div className="text-sidebar-muted mb-1.5 px-2 text-[10.5px] font-semibold uppercase tracking-[0.14em]">{group.section}</div>
            <ul className="space-y-0.5">
              {items.map((item) => (
                <li key={item.to + item.label}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      cn(
                        'group flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] font-medium transition-colors',
                        isActive ? 'bg-sidebar-accent text-white shadow-sm' : 'text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-white',
                      )
                    }
                  >
                    <item.icon className="size-4 shrink-0 opacity-85" aria-hidden />
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        )
      })}
    </nav>
  )
}

function AiStatusChip() {
  const config = usePublicConfig()
  const { session } = useAuth()
  const ai = config.data?.ai
  if (!ai || session?.user.role === 'customer') return null
  if (ai.configured === false) {
    return (
      <Tooltip content="No AI key is set. New complaints go to manual review.">
        <Badge variant="warning" tabIndex={0}>
          <AlertTriangle aria-hidden /> <span className="sr-only sm:not-sr-only">AI not configured</span>
        </Badge>
      </Tooltip>
    )
  }
  return (
    <Tooltip content={`AI model: ${ai.provider} / ${ai.model}`}>
      <Badge variant="validate" className="hidden gap-1 sm:inline-flex">
        <Sparkles aria-hidden /> {ai.model}
      </Badge>
    </Tooltip>
  )
}

function QuickSearch() {
  const navigate = useNavigate()
  const [q, setQ] = React.useState('')
  return (
    <form
      role="search"
      className="relative hidden w-full max-w-xs md:block"
      onSubmit={(e) => {
        e.preventDefault()
        const v = q.trim()
        if (!v) return
        if (/^(CMP|LAB|R\d+)-/i.test(v)) navigate(`/complaints/${v.toUpperCase()}`)
        else navigate(`/complaints?q=${encodeURIComponent(v)}`)
        setQ('')
      }}
    >
      <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" aria-hidden />
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search complaints, CMP-00042, customer…" aria-label="Search complaints" className="h-8.5 pl-8 text-[13px]" />
    </form>
  )
}

function SeedBanner() {
  const { can } = useAuth()
  const seed = useQuery({
    queryKey: ['seed-status'],
    queryFn: () => api.get<{ state: string; done: number; total: number }>('/system/seed-status'),
    refetchInterval: (q) => (q.state.data?.state === 'running' ? 3000 : false),
    enabled: can('complaint:read_all'),
  })
  if (seed.data?.state !== 'running') return null
  const pct = seed.data.total ? Math.round((seed.data.done / seed.data.total) * 100) : 0
  return (
    <div className="border-b bg-info/8 px-4 py-2 text-sm sm:px-6" role="status">
      <div className="flex items-center gap-3">
        <Sparkles className="text-info size-4 shrink-0" aria-hidden />
        <span className="shrink-0">
          Importing demo complaints: {seed.data.done} / {seed.data.total}
        </span>
        <Progress value={pct} className="max-w-xs" />
      </div>
    </div>
  )
}

export function AppShell() {
  const { session, logout } = useAuth()
  const { dark, toggle } = useTheme()
  const [open, setOpen] = React.useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const user = session!.user
  const initials = user.full_name.split(' ').map((p) => p[0]).slice(0, 2).join('').toUpperCase()

  return (
    <div className="flex min-h-svh">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground">
        Skip to content
      </a>
      {/* desktop sidebar */}
      <aside className="bg-sidebar text-sidebar-foreground border-sidebar-border sticky top-0 hidden h-svh w-64 shrink-0 flex-col border-r lg:flex">
        <div className="flex h-16 items-center px-5">
          <Logo className="text-white" />
        </div>
        <SidebarNav />
      </aside>
      {/* mobile sidebar */}
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="left" className="bg-sidebar text-sidebar-foreground border-sidebar-border w-72 border-r p-0">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <SheetDescription className="sr-only">Main navigation</SheetDescription>
          <div className="flex h-16 items-center px-5">
            <Logo className="text-white" />
          </div>
          <SidebarNav onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="bg-background/85 sticky top-0 z-30 flex h-16 items-center gap-3 border-b px-4 backdrop-blur supports-[backdrop-filter]:bg-background/70 sm:px-6">
          <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open navigation" onClick={() => setOpen(true)}>
            <Menu />
          </Button>
          <Logo compact className="lg:hidden" />
          <QuickSearch />
          <div className="ml-auto flex items-center gap-2">
            <AiStatusChip />
            <Button variant="ghost" size="icon" onClick={toggle} aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}>
              {dark ? <Sun /> : <Moon />}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button type="button" className="hover:bg-accent flex items-center gap-2 rounded-lg p-1 pr-2 text-left transition-colors" aria-label="Account menu">
                  <span className="nova-gradient flex size-8 items-center justify-center rounded-full text-xs font-semibold text-white">{initials}</span>
                  <span className="hidden leading-tight sm:block">
                    <span className="block max-w-[10rem] truncate text-[13px] font-medium">{user.full_name}</span>
                    <span className="text-muted-foreground block text-[11px]">{ROLE_LABELS[user.role]}</span>
                  </span>
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel>
                  <div className="text-sm font-medium">{user.full_name}</div>
                  <div className="text-muted-foreground text-xs font-normal">{user.email}</div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onSelect={async () => {
                    await logout()
                    navigate('/login', { replace: true })
                  }}
                >
                  <LogOut /> Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>
        <SeedBanner />
        <main id="main" className="bg-grid/0 flex-1 px-4 py-6 sm:px-6 lg:px-8" tabIndex={-1}>
          <motion.div key={location.pathname} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.18, ease: 'easeOut' }} className="mx-auto w-full max-w-[1600px]">
            <Outlet />
          </motion.div>
        </main>
      </div>
    </div>
  )
}
