import axios from 'axios'

const baseURL = import.meta.env.VITE_API_URL || '/api'

export const api = axios.create({
  baseURL,
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
})

export const apiRoot = baseURL
