import type { ErrorEvent } from '@sentry/react'

export function scrubTelemetryEvent(event: ErrorEvent): ErrorEvent {
  return {
    type: undefined,
    event_id: event.event_id,
    timestamp: event.timestamp,
    platform: 'javascript',
    level: 'error',
    message: '<redacted>',
    exception: { values: [{ type: 'Error', value: '<redacted>' }] },
    breadcrumbs: [],
  }
}
