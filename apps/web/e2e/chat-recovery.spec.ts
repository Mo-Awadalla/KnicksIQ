import { expect } from 'playwright/test'

import { expireChat, test } from './chat-fixture'
import {
  button,
  done,
  finish,
  packet,
  plan,
  send,
  state,
  textbox,
} from './chat-proof'

test('first network-aborted message survives refresh without expiry or generation', async ({
  page,
  request,
}) => {
  await plan(request, [
    { steps: [packet('Only after your explicit send.'), ...done] },
  ])
  await page.goto('/')
  await page.route(
    '**/api/chat/turns',
    (route) => route.abort('internetdisconnected'),
    { times: 1 }
  )
  const message = 'Who was better at their peak, Ewing or Brunson?'
  await send(page, message)
  await expect(page.getByRole('status')).toContainText('not sent')
  await expect(
    page.getByRole('region', { name: 'Unsent message' })
  ).toContainText(message)
  await expect(page.getByRole('status')).not.toContainText('expired')
  await textbox(page).fill('A different next draft')
  await page.reload()
  await expect(textbox(page)).toHaveValue('A different next draft')
  await expect(
    page.getByRole('region', { name: 'Unsent message' })
  ).toContainText(message)
  expect((await state(request)).requests).toHaveLength(0)
  await button(page, 'Send unsent message').click()
  await expect(page.getByText('Only after your explicit send.')).toBeVisible()
  await expect(textbox(page)).toHaveValue('A different next draft')
  await expect(
    page.getByRole('region', { name: 'Unsent message' })
  ).toHaveCount(0)
  await finish(request)
  expect((await state(request)).requests).toHaveLength(1)
})

test('duplicated tab keeps rejected intent beside the authoritative conversation', async ({
  page,
  request,
}) => {
  await plan(request, [
    { steps: [packet('Brunson drives this team.'), ...done] },
    { steps: [packet('Defense travels in May.'), ...done] },
    { steps: [packet('Hart brings the heartbeat.'), ...done] },
  ])
  await page.goto('/')
  await send(page, 'Is Brunson the engine?')
  await expect(page.getByText('Brunson drives this team.')).toBeVisible()
  await finish(request)
  const popup = page.waitForEvent('popup')
  await page.evaluate(() => window.open('/', '_blank'))
  const duplicate = await popup
  await expect(duplicate.getByText('Brunson drives this team.')).toBeVisible()
  await send(page, 'What wins in the playoffs?')
  await expect(page.getByText('Defense travels in May.')).toBeVisible()
  await finish(request)
  const conflict = duplicate.waitForResponse(
    (response) =>
      response.url().endsWith('/chat/turns') && response.status() === 409
  )
  const message = 'My take: Josh Hart is the heart of this roster'
  await send(duplicate, message)
  await conflict
  await expect(duplicate.getByText('Defense travels in May.')).toBeVisible()
  await expect(duplicate.getByRole('status')).toContainText('not sent')
  await expect(
    duplicate.getByRole('region', { name: 'Unsent message' })
  ).toContainText(message)
  await duplicate.reload()
  await expect(
    duplicate.getByRole('region', { name: 'Unsent message' })
  ).toContainText(message)
  expect((await state(request)).requests).toHaveLength(2)
  await button(duplicate, 'Send unsent message').click()
  await expect(duplicate.getByText('Hart brings the heartbeat.')).toBeVisible()
  await finish(request)
  expect((await state(request)).requests).toHaveLength(3)
  await duplicate.close()
})

test('expired open chat carries unsent intent and separate draft into New chat', async ({
  page,
  request,
}) => {
  await plan(request, [
    { steps: [packet('Before retention expires.'), ...done] },
    { steps: [packet('A fresh chat reply.'), ...done] },
  ])
  await page.goto('/')
  await send(page, 'An expiring conversation')
  await expect(page.getByText('Before retention expires.')).toBeVisible()
  await finish(request)
  const token = await page.evaluate(
    () => JSON.parse(sessionStorage.getItem('knicksiq-chat-v1') || '{}').token
  )
  expireChat(token)
  const message = 'Trade idea: Mitchell Robinson for a starting wing'
  await send(page, message)
  await expect(page.getByRole('status')).toContainText('expired')
  await expect(
    page.getByRole('region', { name: 'Unsent message' })
  ).toContainText(message)
  await textbox(page).fill('Keep this next draft separate')
  await page.reload()
  await expect(page.getByRole('status')).toContainText('expired')
  await button(page, 'New chat').click()
  await page.reload()
  await expect(textbox(page)).toHaveValue('Keep this next draft separate')
  await expect(
    page.getByRole('region', { name: 'Unsent message' })
  ).toContainText(message)
  await expect(page.getByText('Before retention expires.')).toHaveCount(0)
  expect((await state(request)).requests).toHaveLength(1)
  await button(page, 'Send unsent message').click()
  await expect(page.getByText('A fresh chat reply.')).toBeVisible()
  await finish(request)
  expect((await state(request)).requests).toHaveLength(2)
})

test('full chat carries the rejected message into a fresh chat without merging drafts', async ({
  page,
  request,
}) => {
  test.setTimeout(90_000)
  await plan(
    request,
    Array.from({ length: 20 }, () => ({
      steps: [packet('A short Knicks answer.'), ...done],
    }))
  )
  let completedCalls = 0
  await page.goto('/')
  await send(page, 'Start a full conversation')
  await expect(page.getByText('A short Knicks answer.')).toBeVisible()
  await finish(request)
  const token = await page.evaluate(
    () => JSON.parse(sessionStorage.getItem('knicksiq-chat-v1') || '{}').token
  )
  for (let index = 1; index < 40; index++) {
    if (index === 20) {
      await finish(request)
      completedCalls = (await state(request)).requests.length
      expect(completedCalls).toBe(20)
      await plan(
        request,
        Array.from({ length: 21 }, () => ({
          steps: [packet('A short Knicks answer.'), ...done],
        }))
      )
    }
    const response = await request.post('/api/chat/turns', {
      headers: { 'X-Chat-Token': token },
      data: {
        kind: 'message',
        request_id: crypto.randomUUID(),
        expected_revision: index * 2,
        message: 'Keep talking Knicks',
      },
    })
    expect(response.ok()).toBeTruthy()
    expect(await response.text()).toContain('event: settled')
  }
  await page.reload()
  await expect(
    page
      .getByRole('region', { name: 'Conversation' })
      .getByText('A short Knicks answer.', { exact: false })
  ).toHaveCount(40)
  const message = 'Save this last Knicks take'
  await send(page, message)
  await expect(page.getByRole('status')).toContainText('full')
  await textbox(page).fill('A separate next thought')
  await page.reload()
  await expect(page.getByRole('status')).toContainText('full')
  await button(page, 'New chat').click()
  await page.reload()
  await expect(textbox(page)).toHaveValue('A separate next thought')
  await expect(
    page.getByRole('region', { name: 'Unsent message' })
  ).toContainText(message)
  expect(completedCalls + (await state(request)).requests.length).toBe(40)
  await button(page, 'Send unsent message').click()
  await expect(page.getByText('A short Knicks answer.')).toBeVisible()
  await finish(request)
  expect(completedCalls + (await state(request)).requests.length).toBe(41)
})

test('unconfirmed first send stays visible across refresh while reads are unavailable', async ({
  page,
  request,
}) => {
  await plan(request, [])
  await page.goto('/')
  await page.route(
    '**/api/chat/turns',
    (route) => route.abort('internetdisconnected'),
    { times: 1 }
  )
  await page.route('**/api/chat/current', (route) =>
    route.abort('internetdisconnected')
  )
  const message = 'Keep my Knicks question while offline'
  await send(page, message)
  await expect(button(page, 'Check connection')).toBeVisible()
  await expect(
    page.getByRole('region', { name: 'Unsent message' })
  ).toContainText(message)
  await textbox(page).fill('Do not replace this newer draft')
  await page.reload()
  await expect(button(page, 'Check connection')).toBeVisible()
  await expect(textbox(page)).toHaveValue('Do not replace this newer draft')
  await expect(
    page.getByRole('region', { name: 'Unsent message' })
  ).toContainText(message)
  await expect(button(page, 'Send message')).toBeDisabled()
  expect((await state(request)).requests).toHaveLength(0)
  await page.unroute('**/api/chat/current')
  await button(page, 'Check connection').click()
  await expect(button(page, 'Send unsent message')).toBeVisible()
  await expect(textbox(page)).toHaveValue('Do not replace this newer draft')
  expect((await state(request)).requests).toHaveLength(0)
})
