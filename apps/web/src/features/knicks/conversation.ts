export function retainLastFour<T>(messages: T[], next: T): T[] {
  return [...messages, next].slice(-4)
}
