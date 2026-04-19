'use client'

import { useEffect, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import { api, founderToken, receiverToken } from '../../lib/api'

type Msg = {
  id: string
  sender_role: string
  is_mine: boolean
  translated_content: string
  raw_content?: string
  emotional_interpretation?: string
  educational_context?: string
  created_at: string
}

export default function ChatPage() {
  const { id } = useParams<{ id: string }>()
  const [token, setToken] = useState<string | null>(null)
  const [messages, setMessages] = useState<Msg[]>([])
  const [memory, setMemory] = useState<any>({ summary: '', key_themes: [] })
  const [draft, setDraft] = useState('')
  const [preview, setPreview] = useState<{ preview_id: string; translated_content: string } | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const sinceRef = useRef<string | null>(null)

  useEffect(() => {
    const t = founderToken() ?? receiverToken()
    if (!t) {
      window.location.href = '/onboard'
      return
    }
    setToken(t)
  }, [])

  useEffect(() => {
    if (!token || !id) return
    let alive = true
    const poll = async () => {
      try {
        const r = await api.list(id, sinceRef.current, token)
        if (!alive) return
        if (r.messages.length > 0) {
          setMessages((prev) => {
            const existing = new Set(prev.map((m) => m.id))
            const additions = r.messages.filter((m: Msg) => !existing.has(m.id))
            return [...prev, ...additions]
          })
        }
        sinceRef.current = r.server_time
        setMemory(r.memory)
      } catch (e: any) {
        setErr(e.message)
      }
    }
    poll()
    const iv = setInterval(poll, 2000)
    return () => {
      alive = false
      clearInterval(iv)
    }
  }, [token, id])

  async function doTranslate() {
    if (!token || !draft) return
    setLoading(true)
    setErr(null)
    try {
      const r = await api.translate(id, draft, token)
      setPreview(r)
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function doApprove() {
    if (!token || !preview) return
    setLoading(true)
    try {
      await api.approve(preview.preview_id, token)
      setPreview(null)
      setDraft('')
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="min-h-screen bg-[#f5eedd] text-[#3b2e1e] p-6 max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold mb-2">Conversation</h1>
      {memory.summary && (
        <p className="text-xs opacity-70 mb-4 italic">Memory: {memory.summary}</p>
      )}

      <div className="space-y-3 mb-6 max-h-[50vh] overflow-y-auto">
        {messages.map((m) => (
          <div
            key={m.id}
            className={`p-3 rounded border ${
              m.is_mine ? 'bg-[#3b2e1e] text-[#f5eedd] ml-10' : 'bg-white mr-10'
            }`}
          >
            <div className="text-xs opacity-60 mb-1">
              {m.is_mine ? 'you' : m.sender_role}
            </div>
            <div>{m.translated_content}</div>
            {!m.is_mine && m.emotional_interpretation && (
              <div className="mt-2 pt-2 border-t text-xs">
                <div className="font-semibold">💭 What they mean:</div>
                <div>{m.emotional_interpretation}</div>
                <div className="font-semibold mt-1">📖 Context:</div>
                <div>{m.educational_context}</div>
              </div>
            )}
          </div>
        ))}
      </div>

      {!preview ? (
        <div className="space-y-2">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Say what you actually feel..."
            rows={3}
            className="w-full p-3 border rounded bg-white"
          />
          <button
            onClick={doTranslate}
            disabled={!draft || loading}
            className="bg-[#3b2e1e] text-[#f5eedd] px-5 py-2 rounded disabled:opacity-50"
          >
            {loading ? 'Translating...' : 'Translate'}
          </button>
        </div>
      ) : (
        <div className="p-4 bg-white border rounded">
          <div className="text-xs opacity-60 mb-1">Bridge version:</div>
          <div className="mb-3">{preview.translated_content}</div>
          <div className="flex gap-2">
            <button
              onClick={doApprove}
              disabled={loading}
              className="bg-[#3b2e1e] text-[#f5eedd] px-5 py-2 rounded"
            >
              Send
            </button>
            <button
              onClick={() => setPreview(null)}
              className="px-5 py-2 rounded border"
            >
              Edit
            </button>
          </div>
        </div>
      )}
      {err && <p className="text-red-600 text-sm mt-2">{err}</p>}
    </main>
  )
}
