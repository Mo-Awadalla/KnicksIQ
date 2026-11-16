import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { expect, test } from 'playwright/test'

import { finish, release, state } from './chat-proof'

test.beforeEach(async ({ context }) => {
  await context.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    if (
      url.protocol === 'http:' &&
      ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
    ) {
      await route.continue()
    } else {
      await route.abort('blockedbyclient')
    }
  })
})

test.afterEach(async ({ request }) => {
  const current = await state(request)
  for (const [gate, opened] of Object.entries(current.gates)) {
    if (!opened) await release(request, gate)
  }
  await finish(request)
})

export function expireChat(token: string) {
  const port = process.env.CHAT_E2E_REDIS_PORT || '19382'
  expect(port).toMatch(/^\d+$/)
  expect(token).toMatch(/^[a-f0-9]{64}$/)
  const hash = createHash('sha256').update(token).digest('hex')
  const redis = (...args: string[]) =>
    execFileSync('redis-cli', ['-h', '127.0.0.1', '-p', port, ...args], {
      encoding: 'utf8',
    }).trim()
  const key = `chat:session:${hash}`
  expect(redis('EXISTS', key)).toBe('1')
  expect(redis('PEXPIREAT', key, '1')).toBe('1')
  expect(redis('EXISTS', key)).toBe('0')
}

export { test }
