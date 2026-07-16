import { describe, expect, it } from 'vitest'
import { retainLastFour } from './conversation'

describe('analyst conversation context', () => {
  it('retains only the four newest user and assistant messages', () => {
    const messages = [1, 2, 3, 4].map((content) => ({ content }))
    expect(
      retainLastFour(messages, { content: 5 }).map((item) => item.content)
    ).toEqual([2, 3, 4, 5])
  })
})
