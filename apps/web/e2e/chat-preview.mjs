import { preview } from 'vite'

const target = new URL(process.env.CHAT_E2E_API_URL || 'http://127.0.0.1:18230')
if (!['127.0.0.1', 'localhost', '[::1]'].includes(target.hostname) || target.protocol !== 'http:') {
  throw new Error('CHAT_E2E_API_URL must be an HTTP loopback URL')
}

await preview({
  configFile: false,
  preview: {
    host: '127.0.0.1',
    port: 4174,
    strictPort: true,
    proxy: {
      '/api': {
        target: target.origin,
        changeOrigin: true,
        headers: { 'X-Forwarded-Proto': 'https' },
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
