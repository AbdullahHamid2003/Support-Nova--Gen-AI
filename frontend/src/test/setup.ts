import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

// jsdom lacks these browser APIs used by Radix / Recharts / framer-motion
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = globalThis.ResizeObserver ?? (ResizeObserverStub as unknown as typeof ResizeObserver)
window.matchMedia = window.matchMedia ?? ((query: string) => ({
  matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {},
  addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
}) as unknown as MediaQueryList)
Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {})
Element.prototype.hasPointerCapture = Element.prototype.hasPointerCapture ?? (() => false)
