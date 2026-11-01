import type { Event } from '@sentry/react'

const QUERY_DELIMITER = /[?#]/

export function scrubTelemetryEvent<T extends Event>(event: T): T {
  delete event.user
  delete event.request
  delete event.extra
  event.breadcrumbs = []
  if (event.message) event.message = '<redacted>'
  for (const exception of event.exception?.values ?? []) {
    exception.value = '<redacted>'
    for (const frame of exception.stacktrace?.frames ?? []) {
      delete frame.vars
    }
  }
  if (event.transaction) {
    const boundary = event.transaction.search(QUERY_DELIMITER)
    if (boundary !== -1)
      event.transaction = event.transaction.slice(0, boundary)
  }
  const sampling = event.sdkProcessingMetadata?.dynamicSamplingContext
  if (sampling?.transaction) {
    const boundary = sampling.transaction.search(QUERY_DELIMITER)
    if (boundary !== -1)
      sampling.transaction = sampling.transaction.slice(0, boundary)
  }
  return event
}
