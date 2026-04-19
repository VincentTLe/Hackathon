'use client'

import { useEffect, useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import Link from 'next/link'
import { api, founderToken } from '../lib/api'

export default function ConnectionsPage() {
  const [conns, setConns] = useState<any[]>([])
  const [lastLink, setLastLink] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  async function refresh() {
    try {
      const r = await api.listConnections()
      setConns(r.connections)
      const latest = r.connections?.[0]
      if (latest?.magic_link_url) {
        setLastLink(latest.magic_link_url)
      }
    } catch (e: any) {
      setErr(e.message)
    }
  }

  useEffect(() => {
    if (!founderToken()) {
      window.location.href = '/onboard'
      return
    }
    refresh()
  }, [])

  return (
    <main className="min-h-screen bg-[#f5eedd] text-[#3b2e1e] p-8 max-w-3xl mx-auto">
      <h1 className="text-3xl font-bold mb-6">Your connections</h1>

      {err && <p className="text-red-600 text-sm mb-4">{err}</p>}
      {lastLink && (
        <section className="mb-10 p-5 bg-white rounded border border-[#8b7355]">
          <p className="text-sm mb-2">Share this link / QR with them:</p>
          <code className="text-xs break-all block mb-3">{lastLink}</code>
          <QRCodeSVG value={lastLink} size={160} />
        </section>
      )}

      <section>
        <h2 className="font-semibold mb-3">Existing</h2>
        {conns.length === 0 && <p className="text-sm opacity-60">None yet.</p>}
        <ul className="space-y-2">
          {conns.map((c) => (
            <li key={c.id} className="p-3 bg-white border rounded flex justify-between items-center">
              <div>
                <div className="font-semibold">{c.receiver_display_name}</div>
                <div className="text-xs opacity-70">
                  {c.relationship} · {c.accepted ? 'accepted' : 'pending'}
                </div>
              </div>
              <Link
                href={`/chat/${c.id}`}
                className="text-sm underline"
              >
                Open chat →
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </main>
  )
}
