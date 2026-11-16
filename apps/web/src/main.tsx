import ReactDOM from 'react-dom/client'

import * as Sentry from '@sentry/react'
import { createAgent } from '@ui-sdk/react/agent'

import { Chat } from './chat/chat'
import { Conversation } from './chat/controller'
import { scrubTelemetryEvent } from './lib/telemetry'
import './styles/index.css'

declare global {
  interface Window {
    knicksUI: typeof agent
  }
}
const agent = createAgent()
window.knicksUI = agent

if (import.meta.env.VITE_SENTRY_DSN) {
  Sentry.init({
    dsn: import.meta.env.VITE_SENTRY_DSN,
    sendDefaultPii: false,
    defaultIntegrations: false,
    integrations: [Sentry.globalHandlersIntegration()],
    beforeSend: scrubTelemetryEvent,
    beforeSendTransaction: () => null,
    beforeBreadcrumb: () => null,
    tracesSampleRate: 0,
    attachStacktrace: false,
    normalizeDepth: 2,
  })
}

if (
  window.location.pathname !== '/' ||
  window.location.search ||
  window.location.hash
)
  window.history.replaceState(null, '', '/')
document.documentElement.classList.remove('dark', 'light')
const conversation = new Conversation()
const root = document.getElementById('root')
if (root) ReactDOM.createRoot(root).render(<Chat conversation={conversation} />)
