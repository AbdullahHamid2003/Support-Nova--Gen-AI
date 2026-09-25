import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type * as React from 'react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import { TooltipProvider } from '@/components/ui/overlays'
import { AuthProvider } from '@/lib/auth'

type Handler = (url: string, init?: RequestInit) => { status?: number; body?: unknown } | undefined

/** Mock fetch with a small router: return undefined from the handler to answer 404. */
export function mockFetch(handler: Handler) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    const res = handler(url, init)
    const status = res?.status ?? (res ? 200 : 404)
    const body = res?.body ?? (status >= 400 ? { error: { code: 'x', message: `HTTP ${status}` } } : {})
    return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

export function renderWithProviders(ui: React.ReactElement, { route = '/' }: { route?: string } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <TooltipProvider>
          <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
        </TooltipProvider>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

