import { askAnalyst } from '@/api'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api/client'

afterEach(() => vi.restoreAllMocks())

describe('analyst turn transport', () => {
  it('preserves the turn identity and revision across a network retry', async () => {
    const reply = {
      answer: 'Verified answer',
      state_committed: true,
      revision: 2,
    }
    const post = vi
      .spyOn(api, 'post')
      .mockRejectedValueOnce(new Error('connection interrupted'))
      .mockResolvedValueOnce({ data: reply })
    const turn = {
      turn_id: 'same-client-turn-id',
      session_token: 'opaque',
      expected_revision: 1,
    }
    await expect(
      askAnalyst('Another stat?', '2025-26', [], undefined, turn)
    ).rejects.toThrow()
    await expect(
      askAnalyst('Another stat?', '2025-26', [], undefined, turn)
    ).resolves.toEqual(reply)
    expect(post.mock.calls[0]).toEqual(post.mock.calls[1])
    expect(post.mock.calls[1][1]).toMatchObject(turn)
  })
})
