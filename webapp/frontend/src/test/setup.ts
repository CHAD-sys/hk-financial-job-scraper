import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, vi } from 'vitest'

/**
 * WHY THIS FILE INSTALLS localStorage
 * -----------------------------------
 * Node 26 defines `globalThis.localStorage` itself, as a getter that returns
 * `undefined` unless the process was started with `--localstorage-file`. Because
 * the property already *exists*, jsdom (and happy-dom, checked) decline to
 * install their own over the top — so the tests ran in a real DOM that had
 * `sessionStorage`, a `Storage` constructor, and no `localStorage` at all.
 *
 * That is worth knowing rather than working around blindly: it is not a bug in
 * jsdom, and it will not reproduce for anyone on Node 22 or earlier, so a
 * teammate could reasonably delete this and see everything still pass locally.
 *
 * The shim below is a plain Map behind the Storage interface. Every Saved Roles
 * test is about what does and does not end up in this object, so it must behave
 * exactly like the real thing for the handful of methods we use — including
 * returning `null` (not `undefined`) for a missing key, which is what the
 * hook's `??` fallback depends on.
 */
function installLocalStorage(): void {
  const store = new Map<string, string>()
  const shim: Storage = {
    get length() {
      return store.size
    },
    key: (i: number) => [...store.keys()][i] ?? null,
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
  }
  Object.defineProperty(globalThis, 'localStorage', {
    value: shim, writable: true, configurable: true,
  })
  if (typeof window !== 'undefined') {
    Object.defineProperty(window, 'localStorage', {
      value: shim, writable: true, configurable: true,
    })
  }
}

installLocalStorage()

/**
 * Two kinds of state outlive a test unless something clears them, and both were
 * involved in the bug this suite was started for: the DOM, and localStorage. A
 * Saved Roles test that inherits the previous test's localStorage passes or
 * fails depending on file order, which is worse than having no test.
 */
beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})
