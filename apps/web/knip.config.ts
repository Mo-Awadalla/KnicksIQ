import type { KnipConfig } from 'knip'

const config: KnipConfig = {
  entry: ['playwright.config.ts', 'e2e/**/*.spec.ts', 'e2e/chat-preview.mjs'],
  project: ['src/**/*.{ts,tsx}', '*.config.ts', 'e2e/**/*.{ts,mjs}'],
}
export default config
