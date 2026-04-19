'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { api, setFounderToken } from '../lib/api'

const QUESTIONS = [
  'When you want to say something hard to them, what usually stops you?',
  "What do you wish they understood about you that they don't seem to?",
  'What emotional response do you hope for from them?',
]

const DEMO_ANSWERS = [
  "I'm scared she'll take it as an attack and shut down. Every time I've tried, the conversation spirals and I end up apologizing for bringing it up.",
  "That I'm not criticizing her — I'm asking for closeness. When I say something hurt me, I need her to hear it as me trusting her, not accusing her.",
  "I want her to pause before reacting. Just acknowledge that what I felt was real, even if she sees it differently. That alone would change everything.",
]

export default function OnboardPage() {
  const router = useRouter()
  const [name, setName] = useState('Linh')
  const [theirName, setTheirName] = useState('Trang')
  const [relationship, setRelationship] = useState('mother')
  const [answers, setAnswers] = useState<string[]>([...DEMO_ANSWERS])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function submit() {
    setLoading(true)
    setErr(null)
    try {
      const res = await api.onboardFounder(name, answers.filter(Boolean))
      setFounderToken(res.founder_token)
      try {
        await api.createConnection(theirName, relationship, '')
      } catch (e: any) {
        setErr(e.message)
      }
      router.push('/connections')
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="min-h-screen bg-[#f5eedd] text-[#3b2e1e] p-8 max-w-2xl mx-auto">
      <h1 className="text-3xl font-bold mb-6">Bridge — Onboarding</h1>
      <label className="block mb-4">
        <span className="text-sm">Your name</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full mt-1 p-3 border border-[#8b7355] rounded bg-white"
        />
      </label>
      <label className="block mb-4">
        <span className="text-sm">Their name</span>
        <input
          value={theirName}
          onChange={(e) => setTheirName(e.target.value)}
          className="w-full mt-1 p-3 border border-[#8b7355] rounded bg-white"
        />
      </label>
      <label className="block mb-4">
        <span className="text-sm">Relationship</span>
        <input
          value={relationship}
          onChange={(e) => setRelationship(e.target.value)}
          className="w-full mt-1 p-3 border border-[#8b7355] rounded bg-white"
        />
      </label>
      {QUESTIONS.map((q, i) => (
        <label key={i} className="block mb-4">
          <span className="text-sm">{q}</span>
          <textarea
            value={answers[i]}
            onChange={(e) => {
              const next = [...answers]
              next[i] = e.target.value
              setAnswers(next)
            }}
            rows={3}
            className="w-full mt-1 p-3 border border-[#8b7355] rounded bg-white"
          />
        </label>
      ))}
      {err && <p className="text-red-600 text-sm mb-3">{err}</p>}
      <button
        onClick={submit}
        disabled={loading || !name}
        className="bg-[#3b2e1e] text-[#f5eedd] px-6 py-3 rounded disabled:opacity-50"
      >
        {loading ? 'Creating...' : 'Continue'}
      </button>
    </main>
  )
}
