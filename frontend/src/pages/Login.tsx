import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { ArrowRight, BadgeCheck, Eye, EyeOff, History, MessageSquareText, ShieldCheck } from 'lucide-react'
import * as React from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useNavigate, useSearchParams } from 'react-router'
import { z } from 'zod'

import { Field, Spinner } from '@/components/app/common'
import { Logo } from '@/components/app/layout'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription, Card, CardContent, Input } from '@/components/ui/primitives'
import { api, errorMessage } from '@/lib/api'
import { ROLE_LABELS, useAuth } from '@/lib/auth'
import type { Role } from '@/lib/types'

const schema = z.object({
  email: z.string().trim().min(1, 'Enter your email address.').email('Enter a valid email address.'),
  password: z.string().min(1, 'Enter your password.'),
})
type Values = z.infer<typeof schema>

/** Demo sign-ins from the first-run seeder - served by the backend only while SEED_DEMO_USERS is on. */
interface DemoAccounts { enabled: boolean; password: string | null; accounts: { email: string; role: Role }[] }

export default function LoginPage() {
  const { session, login } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [error, setError] = React.useState<string | null>(null)
  const [show, setShow] = React.useState(false)
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { email: '', password: '' } })
  const demo = useQuery({ queryKey: ['auth', 'demo-accounts'], queryFn: () => api.get<DemoAccounts>('/auth/demo-accounts'), staleTime: 300_000 })
  const demoPassword = demo.data?.password ?? ''

  if (session) return <Navigate to={params.get('next') || '/'} replace />

  const onSubmit = form.handleSubmit(async (values) => {
    setError(null)
    try {
      await login(values.email, values.password)
      navigate(params.get('next') || '/', { replace: true })
    } catch (e) {
      setError(errorMessage(e))
    }
  })

  return (
    <div className="grid min-h-svh lg:grid-cols-[1.1fr_1fr]">
      <aside className="bg-sidebar text-sidebar-foreground relative hidden overflow-hidden lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div className="bg-grid pointer-events-none absolute inset-0 opacity-[0.07]" />
        <div className="nova-gradient pointer-events-none absolute -top-40 -right-40 size-[520px] rounded-full opacity-25 blur-3xl" />
        <Logo className="relative text-white" />
        <div className="relative max-w-lg space-y-8">
          <motion.h1 initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="text-4xl leading-tight font-semibold tracking-tight text-white">
            Every complaint,
            <br />
            <span className="text-validate">tracked to resolution.</span>
          </motion.h1>
          <ul className="space-y-4 text-[15px]">
            {[
              { icon: MessageSquareText, t: 'Report a problem', d: 'Tell us what went wrong and attach photos or receipts.' },
              { icon: History, t: 'Follow every update', d: 'See where each complaint stands and read our replies.' },
              { icon: BadgeCheck, t: 'Fair, consistent decisions', d: "Every outcome follows Lumora's published policies." },
            ].map(({ icon: Icon, t, d }) => (
              <li key={t} className="flex gap-3">
                <div className="bg-sidebar-accent mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg">
                  <Icon className="text-validate size-4" aria-hidden />
                </div>
                <div>
                  <div className="font-medium text-white">{t}</div>
                  <div className="text-sidebar-muted text-sm leading-relaxed">{d}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <p className="text-sidebar-muted relative text-xs">
          Lumora Home Technologies is a fictional company; all data is synthetic.
        </p>
      </aside>

      <main className="flex items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-md space-y-6">
          <div className="lg:hidden">
            <Logo />
          </div>
          <div className="space-y-1.5">
            <h2 className="text-2xl font-semibold tracking-tight">Sign in</h2>
            <p className="text-muted-foreground text-sm">For Lumora Home Technologies customers and support teams.</p>
          </div>
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            {error ? (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            <Field label="Email" htmlFor="email" error={form.formState.errors.email?.message} required>
              <Input id="email" type="email" autoComplete="username" aria-invalid={!!form.formState.errors.email} {...form.register('email')} />
            </Field>
            <Field label="Password" htmlFor="password" error={form.formState.errors.password?.message} required>
              <div className="relative">
                <Input id="password" type={show ? 'text' : 'password'} autoComplete="current-password" className="pr-10" aria-invalid={!!form.formState.errors.password} {...form.register('password')} />
                <button type="button" onClick={() => setShow((s) => !s)} className="text-muted-foreground hover:text-foreground absolute top-1/2 right-2.5 -translate-y-1/2" aria-label={show ? 'Hide password' : 'Show password'}>
                  {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
            </Field>
            <Button type="submit" className="w-full" size="lg" disabled={form.formState.isSubmitting}>
              {form.formState.isSubmitting ? <Spinner /> : null} Sign in <ArrowRight />
            </Button>
          </form>

          {demo.data?.enabled ? (
          <Card className="gap-3 py-4">
            <CardContent className="space-y-3">
              <div className="flex items-center gap-2 text-sm font-medium">
                <ShieldCheck className="text-validate size-4" aria-hidden /> Demo accounts
                <span className="text-muted-foreground ml-auto font-mono text-xs">{demoPassword}</span>
              </div>
              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {demo.data.accounts.map((d) => (
                  <button
                    key={d.email}
                    type="button"
                    aria-label={`Fill in the ${ROLE_LABELS[d.role].toLowerCase()} demo account`}
                    onClick={() => {
                      form.setValue('email', d.email, { shouldValidate: true })
                      form.setValue('password', demoPassword, { shouldValidate: true })
                    }}
                    className="hover:bg-accent hover:border-primary/30 rounded-lg border px-3 py-2 text-left transition-colors"
                  >
                    <div className="text-sm font-medium">{ROLE_LABELS[d.role]}</div>
                    <div className="text-muted-foreground truncate text-xs">{d.email}</div>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>
          ) : null}
        </div>
      </main>
    </div>
  )
}
