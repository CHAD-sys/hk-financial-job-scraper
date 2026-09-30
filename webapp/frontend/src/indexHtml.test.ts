/// <reference types="node" />

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('development entry document', () => {
  it('lets the real app and device detector handle the root route', () => {
    const html = readFileSync(resolve(process.cwd(), 'index.html'), 'utf8')
    const viteConfig = readFileSync(resolve(process.cwd(), 'vite.config.ts'), 'utf8')

    expect(html).not.toContain('mobile-preview.html')
    expect(html).not.toContain('window.location.replace')
    expect(viteConfig).not.toContain('mobile-preview.html')
  })

  it('discovers web fonts from the document instead of a render-blocking CSS import', () => {
    const html = readFileSync(resolve(process.cwd(), 'index.html'), 'utf8')
    const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8')

    expect(html).toContain('rel="preconnect" href="https://fonts.gstatic.com" crossorigin')
    expect(html).toContain('fonts.googleapis.com/css2')
    expect(css).not.toMatch(/^@import\s+url\(['"]https:\/\/fonts\.googleapis\.com/m)
  })
})
