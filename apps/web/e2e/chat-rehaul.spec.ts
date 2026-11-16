import { expect } from 'playwright/test'

import { expireChat, test } from './chat-fixture'
import {
  button,
  done,
  finish,
  packet,
  plan,
  release,
  send,
  sentenceInView,
  state,
  textbox,
} from './chat-proof'

test('root is the only product page and makes no archive requests', async ({
  page,
}) => {
  const archiveRequests: string[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (/\/(?:games|reports|archive|sources)(?:\/|\?|$)/i.test(url.pathname))
      archiveRequests.push(url.pathname)
  })
  await page.goto('/')
  await expect(textbox(page)).toBeVisible()
  await expect(button(page, 'New chat')).toBeVisible()
  await expect(button(page, 'More options')).toBeVisible()
  await expect(page.getByRole('navigation')).toHaveCount(0)
  await expect(
    page.getByRole('link', { name: /archive|games|reports|sources|evidence/i })
  ).toHaveCount(0)
  await expect(
    page.getByRole('heading', { name: /archive|reports|sources|evidence/i })
  ).toHaveCount(0)
  expect(archiveRequests).toEqual([])
  for (const path of [
    '/games',
    '/games/0022500001',
    '/reports',
    '/reports/example',
    '/analyst',
    '/archive',
    '/sources.html',
  ]) {
    await page.goto(path)
    await expect(page).toHaveURL(/\/$/)
    await expect(textbox(page)).toBeVisible()
  }
})

for (const [label, viewport] of [
  ['mobile', { width: 375, height: 667 }],
  ['desktop', { width: 1440, height: 900 }],
] as const) {
  test(`${label} stays light and keeps the composer visible`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize(viewport)
    await page.emulateMedia({ colorScheme: 'dark' })
    await page.goto('/')
    const composer = textbox(page)
    await composer.fill('Knicks basketball '.repeat(150))
    await expect(composer).toBeInViewport()
    await expect(button(page, 'Send message')).toBeInViewport()
    const layout = await page.evaluate(() => {
      const colors = [document.body, document.documentElement].map(
        (element) => getComputedStyle(element).backgroundColor
      )
      const bg =
        colors.find((color) => !/^rgba\(.*,\s*0(?:\.0+)?\)$/.test(color)) ||
        'rgb(255, 255, 255)'
      const scroll = document.documentElement.scrollWidth <= innerWidth
      return {
        bg,
        scroll,
        scheme: getComputedStyle(document.documentElement).colorScheme,
      }
    })
    expect(layout.scroll).toBeTruthy()
    expect(layout.scheme).not.toBe('dark')
    const rgb = layout.bg.match(/\d+/g)?.slice(0, 3).map(Number)
    expect(rgb && rgb.reduce((a, b) => a + b, 0)).toBeGreaterThan(500)
    await page.screenshot({
      path: testInfo.outputPath(`${label}-dark-preference.png`),
    })
  })
}

test('keyboard composition, first-send focus, and utility menu', async ({
  page,
  request,
}) => {
  await plan(request, [
    { steps: [packet('A little Knicks optimism helps.'), ...done] },
  ])
  await page.goto('/')
  const composer = textbox(page)
  await composer.fill('First line')
  await composer.press('Shift+Enter')
  await composer.pressSequentially('Second line')
  await expect(composer).toHaveValue('First line\nSecond line')
  await composer.dispatchEvent('compositionstart')
  await composer.dispatchEvent('keydown', {
    key: 'Enter',
    code: 'Enter',
    keyCode: 229,
    isComposing: true,
    bubbles: true,
  })
  expect((await state(request)).requests).toHaveLength(0)
  await composer.dispatchEvent('compositionend')
  await composer.press('Enter')
  await expect(page.getByText('A little Knicks optimism helps.')).toBeVisible()
  await expect(composer).toBeFocused()
  await finish(request)
  const menu = button(page, 'More options')
  await menu.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('menu')).toBeVisible()
  for (const name of [/privacy/i, /terms/i, /feedback/i])
    await expect(page.getByRole('menuitem', { name })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(menu).toBeFocused()
})

test('actual upstream text appears before completion and refresh does not regenerate', async ({
  page,
  request,
}) => {
  const archiveRequests: string[] = []
  page.on('request', (req) => {
    const path = new URL(req.url()).pathname
    if (/\/(?:games|reports|archive|sources)(?:\/|$)/i.test(path))
      archiveRequests.push(path)
  })
  await plan(request, [
    {
      steps: [
        packet('The Knicks had a real edge. '),
        { gate: 'completion' },
        packet('The bench mattered too.'),
        ...done,
      ],
    },
  ])
  await page.goto('/')
  await send(page, 'Were we contenders?')
  await expect(
    page.getByText('The Knicks had a real edge.', { exact: false })
  ).toBeVisible()
  expect((await state(request)).gates.completion).toBe(false)
  await expect(button(page, 'Stop reply')).toBeVisible()
  await textbox(page).fill('Keep this draft')
  await expect(textbox(page)).toBeInViewport()
  await release(request, 'completion')
  await expect(
    page.getByText('The bench mattered too.', { exact: false })
  ).toBeVisible()
  await finish(request)
  await page.reload()
  await expect(page.getByText('Were we contenders?')).toBeVisible()
  await expect(
    page.getByText('The bench mattered too.', { exact: false })
  ).toBeVisible()
  await expect(textbox(page)).toHaveValue('Keep this draft')
  expect((await state(request)).requests).toHaveLength(1)
  expect(archiveRequests).toEqual([])
})

test('reader can leave the live edge and jump back during real streaming', async ({
  page,
  request,
}) => {
  const paragraph = 'Knicks basketball is full of interesting choices. '.repeat(
    35
  )
  await plan(request, [
    {
      steps: [
        packet(paragraph),
        { gate: 'more' },
        packet('Another fresh sentence arrives now. '),
        { gate: 'end' },
        ...done,
      ],
    },
  ])
  await page.setViewportSize({ width: 375, height: 667 })
  await page.goto('/')
  await send(page, 'Tell me about the season')
  await expect(
    page.getByText('Knicks basketball is full of interesting choices.', {
      exact: false,
    })
  ).toBeVisible()
  const opening = page.getByText(
    'Knicks basketball is full of interesting choices.',
    { exact: false }
  )
  await opening.hover()
  await page.mouse.wheel(0, -2000)
  await expect(button(page, 'Jump to latest')).toBeVisible()
  await release(request, 'more')
  const latest = page.getByText('Another fresh sentence arrives now.', {
    exact: false,
  })
  await expect(latest).toBeAttached()
  await expect(button(page, 'Jump to latest')).toBeVisible()
  await expect
    .poll(() => sentenceInView(latest, 'Another fresh sentence arrives now.'))
    .toBe(false)
  await button(page, 'Jump to latest').click()
  await expect
    .poll(() => sentenceInView(latest, 'Another fresh sentence arrives now.'))
    .toBe(true)
  await release(request, 'end')
  await finish(request)
})

test('Stop preserves the prefix, Retry replaces the reply, and refresh keeps one user message', async ({
  page,
  request,
}) => {
  await plan(request, [
    {
      steps: [
        packet('A durable opening sentence. '),
        { gate: 'stopped' },
        packet('A late sentence.'),
        ...done,
      ],
    },
    { steps: [packet('A fresh retry sentence.'), ...done] },
  ])
  await page.goto('/')
  await send(page, 'Give me your take')
  await expect(
    page.getByText('A durable opening sentence.', { exact: false })
  ).toBeVisible()
  const cancellation = page.waitForResponse(
    (response) =>
      response.url().endsWith('/chat/cancel') &&
      response.request().method() === 'POST'
  )
  await button(page, 'Stop reply').click()
  const stopped = await cancellation
  expect(stopped.ok()).toBeTruthy()
  expect((await stopped.json()).exchanges.at(-1).reply.status).toBe('stopped')
  await release(request, 'stopped')
  await finish(request)
  await page.reload()
  await expect(
    page.getByText('A durable opening sentence.', { exact: false })
  ).toBeVisible()
  await expect(page.getByText('A late sentence.')).toHaveCount(0)
  await page.getByRole('button', { name: /retry/i }).click()
  await expect(page.getByText('A fresh retry sentence.')).toBeVisible()
  await finish(request)
  await expect(
    page.getByText('Give me your take', { exact: false })
  ).toHaveCount(1)
  await page.reload()
  await expect(
    page.getByText('Give me your take', { exact: false })
  ).toHaveCount(1)
  await expect(page.getByText('A fresh retry sentence.')).toBeVisible()
  expect((await state(request)).requests).toHaveLength(2)
})

test('New chat fences late old events and starts an independent conversation', async ({
  page,
  request,
}) => {
  await plan(request, [
    {
      steps: [
        packet('Old prefix is visible. '),
        { gate: 'old' },
        packet('Old late text leaks.'),
        ...done,
      ],
    },
    { steps: [packet('Fresh conversation answer.'), ...done] },
  ])
  await page.goto('/')
  await send(page, 'Old question')
  await expect(
    page.getByText('Old prefix is visible.', { exact: false })
  ).toBeVisible()
  await button(page, 'New chat').click()
  await expect(textbox(page)).toBeFocused()
  await expect(page.getByText('Old question')).toHaveCount(0)
  await release(request, 'old')
  await finish(request)
  await send(page, 'New question')
  await expect(page.getByText('Fresh conversation answer.')).toBeVisible()
  await expect(page.getByText('Old late text leaks.')).toHaveCount(0)
  await finish(request)
})

test('a separate tab has no transcript or draft while refresh keeps both', async ({
  page,
  context,
  request,
}) => {
  await plan(request, [{ steps: [packet('A tab specific answer.'), ...done] }])
  await page.goto('/')
  await send(page, 'Tab specific question')
  await expect(page.getByText('A tab specific answer.')).toBeVisible()
  await finish(request)
  await textbox(page).fill('Tab specific draft')
  const other = await context.newPage()
  await other.goto('/')
  await expect(other.getByText('Tab specific question')).toHaveCount(0)
  await expect(textbox(other)).toHaveValue('')
  await page.reload()
  await expect(page.getByText('Tab specific question')).toBeVisible()
  await expect(textbox(page)).toHaveValue('Tab specific draft')
  await other.close()
})

test('upstream outage is recoverable and does not expose provider details', async ({
  page,
  request,
}) => {
  await plan(request, [
    { status: 503, steps: [] },
    { steps: [packet('A recovered answer.'), ...done] },
  ])
  await page.goto('/')
  await send(page, 'What do you think?')
  await expect(page.getByRole('button', { name: /retry/i })).toBeVisible()
  await expect(
    page.getByText(/unavailable|interrupted|try again|could not/i).first()
  ).toBeVisible()
  await expect(page.getByText('Scripted upstream failure')).toHaveCount(0)
  await finish(request)
  await page.getByRole('button', { name: /retry/i }).click()
  await expect(page.getByText('A recovered answer.')).toBeVisible()
  await expect(
    page.getByText('What do you think?', { exact: false })
  ).toHaveCount(1)
  await finish(request)
})

test('capability and private upstream content never enter rendered text or telemetry', async ({
  page,
  request,
}) => {
  const posts: string[] = []
  const capabilities: string[] = []
  page.on('request', (req) => {
    const url = new URL(req.url())
    const token = req.headers()['x-chat-token']
    if (token) capabilities.push(token)
    if (req.method() !== 'GET' && !url.pathname.startsWith('/api/chat/'))
      posts.push(`${req.url()} ${req.postData() || ''}`)
    if (token) expect(req.url()).not.toContain(token)
  })
  await plan(request, [
    { steps: [packet('A harmless public response.'), ...done] },
  ])
  await page.goto('/')
  await send(page, 'Private draft marker KIQ_BROWSER_PRIVATE')
  await expect(page.getByText('A harmless public response.')).toBeVisible()
  await finish(request)
  expect(capabilities.length).toBeGreaterThan(0)
  const body = await page.locator('body').innerText()
  for (const token of capabilities) {
    expect(body).not.toContain(token)
    expect(posts.join('\n')).not.toContain(token)
  }
  expect(posts.join('\n')).not.toContain('KIQ_BROWSER_PRIVATE')
  expect(body).not.toMatch(
    /Scripted upstream failure|tool_calls|evidence_id|semantic_summary/
  )
})

test('expired tab reports recovery instead of inventing a transcript', async ({
  page,
  request,
}) => {
  let token = ''
  page.on('request', (req) => {
    token ||= req.headers()['x-chat-token'] || ''
  })
  await plan(request, [
    { steps: [packet('An answer before expiration.'), ...done] },
  ])
  await page.goto('/')
  await send(page, 'An expiring conversation')
  await expect(page.getByText('An answer before expiration.')).toBeVisible()
  await finish(request)
  expect(token).not.toBe('')
  expireChat(token)
  await page.reload()
  await expect(
    page.getByText(/expired|no longer available|start a new chat/i).first()
  ).toBeVisible()
  await expect(page.getByText('An answer before expiration.')).toHaveCount(0)
  expect((await state(request)).requests).toHaveLength(1)
  await button(page, 'New chat').click()
  await expect(textbox(page)).toBeVisible()
})

test('SDK agent discovers and controls the composer', async ({ page }) => {
  await page.goto('/')
  const composer = textbox(page)
  const sendButton = button(page, 'Send message')
  await expect(composer).toBeVisible()
  await expect(composer).toHaveValue('')
  await expect(sendButton).toBeDisabled()
  await expect
    .poll(() =>
      page.evaluate(() => {
        const agent = Reflect.get(window, 'knicksUI')
        return (
          !!agent &&
          typeof agent.snapshot === 'function' &&
          typeof agent.act === 'function'
        )
      })
    )
    .toBe(true)
  const matches = await page.evaluate(() => {
    const agent = Reflect.get(window, 'knicksUI')
    return agent
      .snapshot()
      .filter(
        (entry: { label?: string; component: string; offPage?: boolean }) =>
          entry.label === 'Message KnicksIQ' &&
          entry.component === 'textarea' &&
          !entry.offPage
      )
  })
  expect(matches).toHaveLength(1)
  expect(matches[0].actions).toContain('setValue')
  expect(matches[0].value).toBe('')
  const result = await page.evaluate(async (ref: string) => {
    const agent = Reflect.get(window, 'knicksUI')
    return agent.act({
      steps: [{ ref, action: 'setValue', args: ['Agent draft'] }],
    })
  }, matches[0].ref)
  expect(result).toMatchObject({ ok: true })
  await expect(composer).toHaveValue('Agent draft')
  await expect(sendButton).toBeEnabled()
  await expect
    .poll(() =>
      page.evaluate(() => {
        const agent = Reflect.get(window, 'knicksUI')
        return agent
          .snapshot()
          .find(
            (entry: { label?: string; component: string; offPage?: boolean }) =>
              entry.label === 'Message KnicksIQ' &&
              entry.component === 'textarea' &&
              !entry.offPage
          )?.value
      })
    )
    .toBe('Agent draft')
})

test('private lookup arguments do not appear in chat or telemetry', async ({
  page,
  request,
}) => {
  const marker = 'KIQ_PRIVATE_LOOKUP_PAYLOAD'
  const telemetry: string[] = []
  page.on('request', (req) => {
    if (
      req.method() !== 'GET' &&
      !new URL(req.url()).pathname.startsWith('/api/chat/')
    ) {
      telemetry.push(`${req.url()} ${req.postData() || ''}`)
    }
  })
  await plan(request, [
    {
      steps: [
        {
          data: {
            choices: [
              {
                index: 0,
                delta: {
                  tool_calls: [
                    {
                      index: 0,
                      id: 'private_call',
                      type: 'function',
                      function: {
                        name: 'lookup',
                        arguments: JSON.stringify({ question: marker }),
                      },
                    },
                  ],
                },
                finish_reason: null,
              },
            ],
          },
        },
        {
          data: {
            choices: [{ index: 0, delta: {}, finish_reason: 'tool_calls' }],
          },
        },
        {
          data: {
            choices: [],
            usage: {
              prompt_tokens: 20,
              completion_tokens: 10,
              total_tokens: 30,
            },
          },
        },
        { data: '[DONE]' },
      ],
    },
    { steps: [packet('The lookup is complete.'), ...done] },
  ])
  await page.goto('/')
  await send(page, 'Tell me about the Knicks')
  await expect(page.getByText('The lookup is complete.')).toBeVisible()
  await finish(request)
  expect((await state(request)).requests).toHaveLength(2)
  expect(await page.locator('body').innerText()).not.toContain(marker)
  expect(telemetry.join('\n')).not.toContain(marker)
})

test('New chat stays fresh when storage removal is blocked', async ({
  page,
  request,
}) => {
  await plan(request, [{ steps: [packet('A stored reply.'), ...done] }])
  await page.goto('/')
  await send(page, 'Stored before clearing')
  await expect(page.getByText('A stored reply.')).toBeVisible()
  await finish(request)
  await page.evaluate(() => {
    Storage.prototype.removeItem = () => {
      throw new DOMException('Storage removal denied', 'SecurityError')
    }
  })
  await button(page, 'New chat').click()
  await page.reload()
  await textbox(page).fill('A fresh draft')
  await expect(button(page, 'Send message')).toBeEnabled()
  await expect(
    page.getByText('Stored before clearing', { exact: false })
  ).toHaveCount(0)
})
