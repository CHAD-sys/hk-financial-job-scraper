import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config'

/**
 * Test config, separate from vite.config.ts.
 *
 * Vitest can read a `test` key out of the Vite config, but `defineConfig` from
 * 'vite' does not type it and — as this repo found — it is not reliably picked
 * up either: the suite ran with the default `node` environment and every test
 * failed on `localStorage` being undefined. A dedicated file that merges the
 * app config is unambiguous.
 */
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      // jsdom, not node: the things worth testing here are hooks and components,
      // and the Saved Roles bug this suite was started for only reproduces when
      // effects actually run in a mounted tree.
      //
      // Note that jsdom does NOT give us localStorage here — see src/test/setup.ts.
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.{test,spec}.{ts,tsx}'],
    },
  }),
)
