'use client'

import { useEffect, useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import Link from 'next/link'
import { api, founderToken } from '../lib/api'

export default function ConnectionsPage() {
  const [conns, setConns] = useState<any[]>([])
  const [name, setName] = useState('')
  const [rel, setRel] = useState('')
  const [note, setNote] = useState('')
  const [lastLink, setLastLink] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  async function refresh() {
    try {
      const r = await api.listConnections()
      setConns(r.connections)
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

  async function create() {
    setErr(null)
    try {
      const r = await api.createConnection(name, rel, note)
      setLastLink(r.magic_link_url)
      setName('')
      setRel('')
      setNote('')
      refresh()
    } catch (e: any) {
      setErr(e.message)
    }
  }

  return (
    <main className="min-h-screen bg-[#f5eedd] text-[#3b2e1e] p-8 max-w-3xl mx-auto">
      <h1 className="text-3xl font-bold mb-6">Your connections</h1>

      <section className="mb-10 p-5 bg-white rounded border border-[#8b7355]">
        <h2 className="font-semibold mb-3">New connection</h2>
        <input
          placeholder="Their name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full p-2 border mb-2 rounded"
        />
        <input
          placeholder="Relationship (e.g. mother)"
          value={rel}
          onChange={(e) => setRel(e.target.value)}
          className="w-full p-2 border mb-2 rounded"
        />
        <textarea
          placeholder="Invite note (optional)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className="w-full p-2 border mb-2 rounded"
        />
        <button
          onClick={create}
          disabled={!name || !rel}
          className="bg-[#3b2e1e] text-[#f5eedd] px-5 py-2 rounded disabled:opacity-50"
        >
          Create + generate link
        </button>
        {err && <p className="text-red-600 text-sm mt-2">{err}</p>}
        {lastLink && (
          <div className="mt-4 p-4 bg-[#f5eedd] border rounded">
            <p className="text-sm mb-2">Share this link / QR with them:</p>
            <code className="text-xs break-all block mb-3">{lastLink}</code>
            <QRCodeSVG value={lastLink} size={160} />
          </div>
        )}
      </section>

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
