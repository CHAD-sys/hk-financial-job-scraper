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
 * WHY THIS FILE ALSO INSTALLS showModal/close
 * -------------------------------------------
 * jsdom parses <dialog> and exposes HTMLDialogElement, but as of jsdom 30 it
 * still does not implement the methods that open one — `showModal` is simply
 * undefined, so any component that calls it throws on mount rather than
 * failing an assertion. Both modals in this app (JobDetailModal and the
 * sign-in prompt in ResumeFeatureSpotlight) open that way, deliberately: the
 * native dialog is what gives them focus trapping, an inert background and
 * Escape-to-close without us writing any of it.
 *
 * The shim is the smallest thing that makes those components testable: the
 * `open` attribute is what actually matters, because that is what decides
 * whether the element is exposed as role="dialog". It does NOT reproduce the
 * top layer, ::backdrop, focus trapping or Escape — none of which jsdom has
 * either. A test that needs to prove *those* belongs in a real browser.
 */
function installDialogMethods(): void {
  if (typeof HTMLDialogElement === 'undefined') return
  const proto = HTMLDialogElement.prototype
  if (typeof proto.showModal !== 'function') {
    proto.showModal = function showModal(this: HTMLDialogElement) {
      this.setAttribute('open', '')
    }
  }
  if (typeof proto.show !== 'function') {
    proto.show = function show(this: HTMLDialogElement) {
      this.setAttribute('open', '')
    }
  }
  if (typeof proto.close !== 'function') {
    proto.close = function close(this: HTMLDialogElement, returnValue?: string) {
      this.removeAttribute('open')
      if (returnValue !== undefined) this.returnValue = returnValue
      this.dispatchEvent(new Event('close'))
    }
  }
}

installDialogMethods()

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
