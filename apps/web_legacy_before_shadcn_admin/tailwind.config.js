/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        knicks: {
          blue: '#006bb6',
          orange: '#f58426',
          silver: '#bec0c2',
          dark: '#1a1a1a',
        },
      },
    },
  },
  plugins: [],
}
