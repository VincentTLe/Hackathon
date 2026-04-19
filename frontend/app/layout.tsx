import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Bridge',
  description: 'They love you. Just not in your language.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
