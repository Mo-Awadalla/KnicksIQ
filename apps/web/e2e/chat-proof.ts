import {
  type APIRequestContext,
  type Locator,
  type Page,
  expect,
} from 'playwright/test'
import { z } from 'zod'

const upstream = new URL(
  process.env.CHAT_E2E_UPSTREAM_URL || 'http://127.0.0.1:18930'
).origin
type TextPacket = {
  data: {
    choices: {
      index: number
      delta: { content: string }
      finish_reason: null
    }[]
  }
}
const packet = (text: string): TextPacket => ({
  data: {
    choices: [{ index: 0, delta: { content: text }, finish_reason: null }],
  },
})
const done = [
  { data: { choices: [{ index: 0, delta: {}, finish_reason: 'stop' }] } },
  {
    data: {
      choices: [],
      usage: { prompt_tokens: 25, completion_tokens: 20, total_tokens: 45 },
    },
  },
  { data: '[DONE]' },
]
type Step = { data: unknown } | { gate: string }
type Call = { steps: Step[] } | { status: number; steps: Step[] }

async function plan(request: APIRequestContext, calls: Call[]) {
  const response = await request.post(`${upstream}/__control__/plan`, {
    data: { calls },
  })
  expect(response.ok()).toBeTruthy()
}
async function release(request: APIRequestContext, gate: string) {
  const response = await request.post(`${upstream}/__control__/release`, {
    data: { gate },
  })
  expect(response.ok()).toBeTruthy()
}
async function state(request: APIRequestContext) {
  const response = await request.get(`${upstream}/__control__/state`)
  expect(response.ok()).toBeTruthy()
  return z
    .object({
      requests: z.array(z.unknown()),
      active: z.number().int().nonnegative(),
      gates: z.record(z.string(), z.boolean()),
    })
    .strict()
    .parse(await response.json())
}
async function finish(request: APIRequestContext) {
  await expect.poll(async () => (await state(request)).active).toBe(0)
}
async function send(page: Page, message: string) {
  const composer = page.getByRole('textbox', { name: 'Message KnicksIQ' })
  await composer.fill(message)
  await composer.press('Enter')
}
const textbox = (page: Page) =>
  page.getByRole('textbox', { name: 'Message KnicksIQ' })
const button = (page: Page, name: string) =>
  page.getByRole('button', { name, exact: true })

async function sentenceInView(locator: Locator, sentence: string) {
  return locator.evaluate((element, text) => {
    const offset = (element.textContent || '').indexOf(text)
    if (offset < 0) return false
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
    const range = document.createRange()
    let position = 0
    let started = false
    while (walker.nextNode()) {
      const node = walker.currentNode
      const end = position + (node.textContent || '').length
      if (!started && offset < end) {
        range.setStart(node, offset - position)
        started = true
      }
      if (started && offset + text.length <= end) {
        range.setEnd(node, offset + text.length - position)
        const viewport = element.closest('[role="region"]')
        if (!viewport)
          throw new Error('Conversation has no visible scroll region')
        const clip = viewport.getBoundingClientRect()
        return [...range.getClientRects()].some(
          (rect) => rect.bottom > clip.top && rect.top < clip.bottom
        )
      }
      position = end
    }
    return false
  }, sentence)
}

export {
  packet,
  done,
  plan,
  release,
  state,
  finish,
  send,
  textbox,
  button,
  sentenceInView,
}
