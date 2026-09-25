import { useQuery, useQueryClient } from '@tanstack/react-query'
import * as React from 'react'

import { api } from '@/lib/api'
import type { PublicConfig, Role, Session } from '@/lib/types'

interface AuthState {
  session: Session | null
  loading: boolean
  can: (permission: string) => boolean
  hasRole: (...roles: Role[]) => boolean
  login: (email: string, password: string) => Promise<Session>
  logout: () => Promise<void>
  refresh: () => Promise<unknown>
}

const AuthContext = React.createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient()
  const me = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: () => api.get<Session>('/auth/me').catch(() => null),
    staleTime: 5 * 60_000,
    retry: false,
  })

  React.useEffect(() => {
    const onUnauthorized = () => qc.setQueryData(['auth', 'me'], null)
    window.addEventListener('sn:unauthorized', onUnauthorized)
    return () => window.removeEventListener('sn:unauthorized', onUnauthorized)
  }, [qc])

  const value = React.useMemo<AuthState>(() => {
    const session = me.data ?? null
    const perms = new Set(session?.permissions ?? [])
    return {
      session,
      loading: me.isLoading,
      can: (p) => perms.has(p),
      hasRole: (...roles) => !!session && roles.includes(session.user.role),
      login: async (email, password) => {
        const s = await api.post<Session>('/auth/login', { email, password })
        // drop cached data of any previous user, keep the auth query (its observer drives the session)
        qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'auth' })
        qc.setQueryData(['auth', 'me'], { user: s.user, permissions: s.permissions })
        return s
      },
      logout: async () => {
        try {
          await api.post('/auth/logout')
        } finally {
          qc.setQueryData(['auth', 'me'], null)
          qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'auth' })
        }
      },
      refresh: () => me.refetch(),
    }
  }, [me, qc])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = React.useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}

export function usePublicConfig() {
  const { session } = useAuth()
  return useQuery({
    queryKey: ['config', 'public'],
    queryFn: () => api.get<PublicConfig>('/config/public'),
    enabled: !!session,
    staleTime: 10 * 60_000,
  })
}

export const ROLE_LABELS: Record<Role, string> = {
  customer: 'Customer',
  agent: 'Support Agent',
  reviewer: 'Reviewer',
  manager: 'Support Manager',
  admin: 'Administrator',
}
