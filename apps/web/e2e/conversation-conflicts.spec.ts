import { expect } from 'playwright/test'
import { api, test } from './parity-fixtures'

test('stale revision keeps the pending turn and retries at the reported revision', async ({ page }) => {
  const requests: { question?: string; turn_id?: string; expected_revision?: number; session_token?: string }[] = []
  await page.route(api('/analysis/query'), (route) => {
    const body = route.request().postDataJSON()
    requests.push(body)
    if (requests.length === 1) return route.fulfill({ json: {
      answer: 'First answer.', warnings: [], citations: [], degraded: false,
      refused: false, data_version: 'parity.1', session_token: 'a'.repeat(64),
      revision: 1, state_committed: true, session_expires_at: '2099-01-01T00:00:00Z',
    } })
    if (requests.length === 2) return route.fulfill({ status: 409,
      json: { error: {
        code: 'revision_conflict',
        message: 'The conversation changed. Retry your question.',
        current_revision: 4,
      } } })
    return route.fulfill({ json: {
      answer: 'Second answer.', warnings: [], citations: [], degraded: false,
      refused: false, data_version: 'parity.1', session_token: 'a'.repeat(64),
      revision: 5, state_committed: true, session_expires_at: '2099-01-01T00:00:00Z',
    } })
  })
  await page.goto('/analyst')
  const box = page.getByRole('textbox', { name: 'Ask a season question' })
  await box.fill('First question')
  await box.press('Enter')
  await expect(page.getByText('First answer.')).toBeVisible()
  await box.fill('Second question')
  await box.press('Enter')
  await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
  expect(requests[1]).toMatchObject({
    question: 'Second question',
    expected_revision: 1,
    session_token: 'a'.repeat(64),
  })
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('Second answer.')).toBeVisible()
  expect(requests[2]).toMatchObject({
    question: 'Second question',
    turn_id: requests[1].turn_id,
    expected_revision: 4,
    session_token: 'a'.repeat(64),
  })
  await expect(page.getByText('Second question', { exact: true })).toHaveCount(1)
})

test('an in-progress turn replays the identical request on retry', async ({ page }) => {
  const requests: { question?: string; turn_id?: string; expected_revision?: number; session_token?: string }[] = []
  await page.route(api('/analysis/query'), (route) => {
    const body = route.request().postDataJSON()
    requests.push(body)
    if (requests.length === 1) return route.fulfill({ json: {
      answer: 'First answer.', warnings: [], citations: [], degraded: false,
      refused: false, data_version: 'parity.1', session_token: 'a'.repeat(64),
      revision: 1, state_committed: true, session_expires_at: '2099-01-01T00:00:00Z',
    } })
    if (requests.length === 2) return route.fulfill({ status: 409,
      json: { error: {
        code: 'turn_in_progress',
        message: 'This conversation turn is still in progress.',
      } } })
    return route.fulfill({ json: {
      answer: 'Replayed answer.', warnings: [], citations: [], degraded: false,
      refused: false, data_version: 'parity.1', session_token: 'a'.repeat(64),
      revision: 2, state_committed: true, session_expires_at: '2099-01-01T00:00:00Z',
    } })
  })
  await page.goto('/analyst')
  const box = page.getByRole('textbox', { name: 'Ask a season question' })
  await box.fill('First question')
  await box.press('Enter')
  await expect(page.getByText('First answer.')).toBeVisible()
  await box.fill('Second question')
  await box.press('Enter')
  await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('Replayed answer.')).toBeVisible()
  expect(requests[2]).toMatchObject({
    question: 'Second question',
    turn_id: requests[1].turn_id,
    expected_revision: 1,
    session_token: 'a'.repeat(64),
  })
  await expect(page.getByText('Second question', { exact: true })).toHaveCount(1)
})

test('a reused turn identity retries under a fresh identity without a duplicate question', async ({ page }) => {
  const requests: { question?: string; turn_id?: string; expected_revision?: number; session_token?: string }[] = []
  await page.route(api('/analysis/query'), (route) => {
    const body = route.request().postDataJSON()
    requests.push(body)
    if (requests.length === 1) return route.fulfill({ json: {
      answer: 'First answer.', warnings: [], citations: [], degraded: false,
      refused: false, data_version: 'parity.1', session_token: 'a'.repeat(64),
      revision: 1, state_committed: true, session_expires_at: '2099-01-01T00:00:00Z',
    } })
    if (requests.length === 2) return route.fulfill({ status: 409,
      json: { error: {
        code: 'turn_id_reused',
        message: 'This turn identity belongs to a different question.',
      } } })
    return route.fulfill({ json: {
      answer: 'Fresh identity answer.', warnings: [], citations: [], degraded: false,
      refused: false, data_version: 'parity.1', session_token: 'a'.repeat(64),
      revision: 2, state_committed: true, session_expires_at: '2099-01-01T00:00:00Z',
    } })
  })
  await page.goto('/analyst')
  const box = page.getByRole('textbox', { name: 'Ask a season question' })
  await box.fill('First question')
  await box.press('Enter')
  await expect(page.getByText('First answer.')).toBeVisible()
  await box.fill('Second question')
  await box.press('Enter')
  await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
  await expect(page.getByText('Second question', { exact: true })).toHaveCount(1)
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('Fresh identity answer.')).toBeVisible()
  expect(requests[2].turn_id).not.toBe(requests[1].turn_id)
  expect(requests[2]).toMatchObject({
    question: 'Second question',
    expected_revision: 1,
    session_token: 'a'.repeat(64),
  })
  await expect(page.getByText('Second question', { exact: true })).toHaveCount(1)
})
