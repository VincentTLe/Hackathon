'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { api, setReceiverToken } from '../../lib/api'

export default function InvitePage() {
  const { token } = useParams<{ token: string }>()
  const router = useRouter()
  const [preview, setPreview] = useState<any>(null)
  const [name, setName] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api
      .invitePreview(token)
      .then(setPreview)
      .catch((e) => setErr(e.message))
  }, [token])

  async function accept() {
    setLoading(true)
    setErr(null)
    try {
      const r = await api.accept(token, name)
      setReceiverToken(r.session_token)
      router.push(`/chat/${r.connection_id}`)
    } catch (e: any) {
      setErr(e.message)
      setLoading(false)
    }
  }

  if (err) return <main className="p-8 text-red-600">{err}</main>
  if (!preview) return <main className="p-8">Loading...</main>

  return (
    <main className="min-h-screen bg-[#f5eedd] text-[#3b2e1e] p-8 max-w-lg mx-auto">
      <h1 className="text-2xl font-bold mb-2">{preview.founder_name} invited you</h1>
      <p className="opacity-75 mb-6">as their {preview.relationship}</p>
      {preview.invite_note && (
        <blockquote className="p-3 bg-white border-l-4 border-[#8b7355] mb-6 italic">
          "{preview.invite_note}"
        </blockquote>
      )}
      <label className="block mb-4">
        <span className="text-sm">Your name</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full mt-1 p-3 border rounded bg-white"
        />
      </label>
      <button
        onClick={accept}
        disabled={!name || loading}
        className="bg-[#3b2e1e] text-[#f5eedd] px-6 py-3 rounded disabled:opacity-50"
      >
        {loading ? 'Joining...' : 'Join conversation'}
      </button>
    </main>
  )
}
