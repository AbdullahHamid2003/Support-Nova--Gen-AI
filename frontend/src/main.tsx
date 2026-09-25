import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { toast, Toaster } from 'sonner'

import { App } from '@/App'
import { TooltipProvider } from '@/components/ui/overlays'
import { ApiError } from '@/lib/api'
import { AuthProvider } from '@/lib/auth'

import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 20_000,
      refetchOnWindowFocus: false,
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
    },
  },
  queryCache: new QueryCache({
    onError: (err, query) => {
      if (err instanceof ApiError && err.status === 0 && query.state.dataUpdateCount === 0) toast.error(err.message, { id: 'network' })
    },
  }),
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <TooltipProvider delayDuration={200}>
          <App />
          <Toaster richColors closeButton position="top-right" />
        </TooltipProvider>
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)
