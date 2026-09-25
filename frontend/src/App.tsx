import { ShieldAlert } from 'lucide-react'
import * as React from 'react'
import { createBrowserRouter, Link, Navigate, RouterProvider, useLocation, useRouteError } from 'react-router'

import { EmptyState, LoadingBlock } from '@/components/app/common'
import { AppShell, Logo } from '@/components/app/layout'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/lib/auth'

// Pages are code-split; import.meta.glob keeps the router working while a page module is added or renamed.
const PAGE_MODULES = import.meta.glob<{ default: React.ComponentType }>('./pages/*.tsx')

function lazyPage(name: string) {
  return React.lazy(async () => {
    const loader = PAGE_MODULES[`./pages/${name}.tsx`]
    if (!loader) return { default: () => <EmptyState title="This page is not available" description="Reload the page or go back to the dashboard." /> }
    return loader()
  })
}

const LoginPage = lazyPage('Login')
const DashboardPage = lazyPage('Dashboard')
const ComplaintsPage = lazyPage('Complaints')
const SubmitPage = lazyPage('SubmitComplaint')
const ComplaintDetailPage = lazyPage('ComplaintDetail')
const ReviewsPage = lazyPage('Reviews')
const ReviewWorkspacePage = lazyPage('ReviewWorkspace')
const KnowledgePage = lazyPage('Knowledge')
const DocumentPage = lazyPage('DocumentDetail')
const RulesPage = lazyPage('Rules')
const PromptsPage = lazyPage('Prompts')
const AnalyticsPage = lazyPage('Analytics')
const ReportsPage = lazyPage('Reports')
const EvaluationPage = lazyPage('Evaluation')
const EvaluationRunPage = lazyPage('EvaluationRun')
const LabPage = lazyPage('Lab')
const AuditPage = lazyPage('Audit')
const AdminPage = lazyPage('Admin')

function Splash() {
  return (
    <div className="flex min-h-svh items-center justify-center">
      <div className="flex flex-col items-center gap-4">
        <Logo />
        <div className="bg-muted h-1 w-40 overflow-hidden rounded-full">
          <div className="nova-gradient h-full w-1/2 animate-pulse rounded-full" />
        </div>
      </div>
    </div>
  )
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { session, loading } = useAuth()
  const location = useLocation()
  if (loading) return <Splash />
  if (!session) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />
  return <>{children}</>
}

function Guard({ perm, anyOf, children }: { perm?: string; anyOf?: string[]; children: React.ReactNode }) {
  const { can } = useAuth()
  const allowed = perm ? can(perm) : anyOf ? anyOf.some(can) : true
  if (!allowed)
    return (
      <EmptyState
        icon={ShieldAlert}
        title="You do not have access to this page"
        description="Ask an administrator if you need access."
        action={
          <Button asChild variant="outline" size="sm" className="mt-2">
            <Link to="/">Back to dashboard</Link>
          </Button>
        }
      />
    )
  return <>{children}</>
}

function Page({ children }: { children: React.ReactNode }) {
  return <React.Suspense fallback={<LoadingBlock rows={6} className="pt-2" />}>{children}</React.Suspense>
}

function RouteError() {
  const error = useRouteError() as Error
  return (
    <div className="mx-auto max-w-xl p-10">
      <EmptyState icon={ShieldAlert} title="Something went wrong on this page" description={error?.message ?? 'Reload the page to try again.'} action={<Button asChild size="sm" className="mt-2"><a href="/">Reload</a></Button>} />
    </div>
  )
}

const router = createBrowserRouter([
  { path: '/login', element: <Page><LoginPage /></Page> },
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Page><DashboardPage /></Page> },
      { path: 'complaints', element: <Page><ComplaintsPage /></Page> },
      { path: 'complaints/new', element: <Page><Guard perm="complaint:create"><SubmitPage /></Guard></Page> },
      { path: 'complaints/:ref', element: <Page><ComplaintDetailPage /></Page> },
      { path: 'reviews', element: <Page><Guard perm="review:read"><ReviewsPage /></Guard></Page> },
      { path: 'reviews/:id', element: <Page><Guard perm="review:read"><ReviewWorkspacePage /></Guard></Page> },
      { path: 'knowledge', element: <Page><Guard perm="knowledge:read"><KnowledgePage /></Guard></Page> },
      { path: 'knowledge/:docId', element: <Page><Guard perm="knowledge:read"><DocumentPage /></Guard></Page> },
      { path: 'rules', element: <Page><Guard perm="rules:read"><RulesPage /></Guard></Page> },
      { path: 'prompts', element: <Page><Guard perm="prompts:manage"><PromptsPage /></Guard></Page> },
      { path: 'analytics', element: <Page><Guard perm="analytics:read"><AnalyticsPage /></Guard></Page> },
      { path: 'reports', element: <Page><Guard perm="reports:export"><ReportsPage /></Guard></Page> },
      { path: 'evaluation', element: <Page><Guard perm="evaluation:read"><EvaluationPage /></Guard></Page> },
      { path: 'evaluation/:runId', element: <Page><Guard perm="evaluation:read"><EvaluationRunPage /></Guard></Page> },
      { path: 'lab', element: <Page><Guard perm="lab:use"><LabPage /></Guard></Page> },
      { path: 'audit', element: <Page><Guard anyOf={['audit:read', 'audit:read_complaint']}><AuditPage /></Guard></Page> },
      { path: 'admin', element: <Page><Guard perm="users:read"><AdminPage /></Guard></Page> },
      { path: '*', element: <EmptyState title="Page not found" description="The page you are looking for does not exist." action={<Button asChild size="sm" className="mt-2" variant="outline"><Link to="/">Go to dashboard</Link></Button>} /> },
    ],
  },
])

export function App() {
  return <RouterProvider router={router} />
}
