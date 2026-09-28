import { describe, expect, it } from 'vitest'
import { recentContext } from './conversation'

describe('analyst conversation context', () => {
  it('retains ten previous messages in order', () => {
    const messages = Array.from({ length: 11 }, (_, index) => ({
      role: index % 2 ? ('assistant' as const) : ('user' as const),
      content: String(index),
    }))
    expect(recentContext(messages).map((item) => item.content)).toEqual(
      Array.from({ length: 10 }, (_, index) => String(index + 1))
    )
  })
})
