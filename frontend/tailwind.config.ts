import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        tan: {
          50:  '#faf6ee',
          100: '#f4ecdc',
          200: '#e9dbbd',
          300: '#d9c396',
          400: '#c8a96a',
          500: '#b4904a',
          600: '#987539',
          700: '#755a2e',
          800: '#574327',
          900: '#3b2d1b',
        },
      },
    },
  },
  plugins: [],
}

export default config
