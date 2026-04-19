'use client'

import { useState } from 'react'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export default function Home() {
  const [rawMessage, setRawMessage] = useState('')
  const [translatedContent, setTranslatedContent] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [showReview, setShowReview] = useState(false)

  async function handleTranslate() {
    if (!rawMessage.trim()) return
    setLoading(true)
    setError('')

    try {
      const res = await fetch(`${API_URL}/messages/translate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_message: rawMessage }),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data?.detail ?? 'Translation failed')
      }

      const data = await res.json()
      setTranslatedContent(data.translated_content)
      setShowReview(true)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Something went wrong. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  function handleReset() {
    setShowReview(false)
    setTranslatedContent('')
    setError('')
  }

  return (
    <main className="min-h-screen bg-stone-50 flex flex-col items-center justify-center p-8">
      <div className="w-full max-w-2xl space-y-6">

        {/* Header */}
        <div className="text-center space-y-1">
          <h1 className="text-2xl font-semibold text-stone-800">Bridge</h1>
          <p className="text-stone-500 text-sm">They love you. Just not in your language.</p>
        </div>

        {!showReview ? (
          /* Compose */
          <div className="space-y-3">
            <label className="block text-sm font-medium text-stone-700">
              Write what you want to say. Don&apos;t worry about how it sounds.
            </label>
            <textarea
              className="w-full h-44 p-4 border border-stone-200 rounded-xl bg-white text-stone-800 resize-none focus:outline-none focus:ring-2 focus:ring-stone-300 text-base"
              placeholder="I've been feeling distant lately and I don't know how to say it..."
              value={rawMessage}
              onChange={e => setRawMessage(e.target.value)}
            />
            {error && (
              <p className="text-red-500 text-sm">{error}</p>
            )}
            <button
              onClick={handleTranslate}
              disabled={!rawMessage.trim() || loading}
              className="w-full py-3 bg-stone-800 text-white rounded-xl font-medium disabled:opacity-40 hover:bg-stone-700 transition-colors"
            >
              {loading ? 'Bridge is translating…' : 'Translate'}
            </button>
          </div>
        ) : (
          /* Review Gate */
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              {/* Raw — grayed */}
              <div className="space-y-2">
                <p className="text-xs font-medium text-stone-400 uppercase tracking-wide">
                  What you wrote
                </p>
                <div className="p-4 bg-stone-100 rounded-xl text-stone-500 text-sm min-h-36 leading-relaxed">
                  {rawMessage}
                </div>
              </div>
              {/* Translated — prominent, read-only */}
              <div className="space-y-2">
                <p className="text-xs font-medium text-stone-700 uppercase tracking-wide">
                  What Bridge will send
                </p>
                <div className="p-4 bg-white border border-stone-200 rounded-xl text-stone-800 text-sm min-h-36 leading-relaxed select-none">
                  {translatedContent}
                </div>
              </div>
            </div>

            <p className="text-xs text-stone-400 text-center">
              Translated by Bridge · You cannot edit this translation
            </p>

            <div className="flex gap-3">
              <button
                onClick={handleReset}
                className="flex-1 py-3 border border-stone-300 text-stone-600 rounded-xl font-medium hover:bg-stone-50 transition-colors"
              >
                ← Start over
              </button>
              <button
                onClick={() => alert('Approve & store coming Day 4 — backend endpoint not wired yet.')}
                className="flex-1 py-3 bg-stone-800 text-white rounded-xl font-medium hover:bg-stone-700 transition-colors"
              >
                Approve & Send
              </button>
            </div>
          </div>
        )}
      </div>
    </main>
  )
}
