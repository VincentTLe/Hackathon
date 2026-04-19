'use client'

import { useState } from 'react'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

type Step = 'intro' | 'onboardA' | 'onboardB' | 'composeA' | 'viewB' | 'replyB' | 'viewA'

type Translation = {
  translated_content: string
  emotional_interpretation: string
  educational_context: string
}

const SENDER_QUESTIONS = [
  "When you want to say something hard to them, what usually stops you?",
  "What do you wish they understood about you that they don't seem to?",
  "When they respond in a way that shuts you down — what does that look like?",
]

const RECEIVER_QUESTIONS = [
  "When they seem upset, how do you usually react?",
  "What do you wish they'd share with you more often?",
  "What makes you feel closest to them?",
]

function profileFromAnswers(answers: string[]): string {
  return answers.filter(Boolean).map((a, i) => `Q${i + 1}: ${a}`).join('\n')
}

export default function Home() {
  const [step, setStep] = useState<Step>('intro')

  const [senderName, setSenderName] = useState('')
  const [receiverName, setReceiverName] = useState('')
  const [relationship, setRelationship] = useState('')

  const [answersA, setAnswersA] = useState<string[]>(['', '', ''])
  const [answersB, setAnswersB] = useState<string[]>(['', '', ''])

  const [rawA, setRawA] = useState('')
  const [translationAtoB, setTranslationAtoB] = useState<Translation | null>(null)

  const [rawB, setRawB] = useState('')
  const [translationBtoA, setTranslationBtoA] = useState<Translation | null>(null)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const profileA = profileFromAnswers(answersA)
  const profileB = profileFromAnswers(answersB)

  async function callTranslate(
    raw: string,
    senderProfile: string,
    receiverProfile: string,
  ): Promise<Translation> {
    const res = await fetch(`${API_URL}/messages/translate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        raw_message: raw,
        sender_profile: senderProfile,
        receiver_profile: receiverProfile,
      }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data?.detail ?? 'Translation failed')
    }
    return res.json()
  }

  async function handleTranslateAtoB() {
    if (!rawA.trim()) return
    setLoading(true); setError('')
    try {
      const t = await callTranslate(rawA, profileA, profileB)
      setTranslationAtoB(t)
      setStep('viewB')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Something went wrong.')
    } finally { setLoading(false) }
  }

  async function handleTranslateBtoA() {
    if (!rawB.trim()) return
    setLoading(true); setError('')
    try {
      const t = await callTranslate(rawB, profileB, profileA)
      setTranslationBtoA(t)
      setStep('viewA')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Something went wrong.')
    } finally { setLoading(false) }
  }

  function resetAll() {
    setStep('intro')
    setSenderName(''); setReceiverName(''); setRelationship('')
    setAnswersA(['', '', ''])
    setAnswersB(['', '', ''])
    setRawA(''); setRawB('')
    setTranslationAtoB(null); setTranslationBtoA(null)
    setError('')
  }

  const youLabel = senderName || 'You'
  const themLabel = receiverName || 'Them'

  return (
    <main className="min-h-screen bg-stone-50 flex flex-col items-center p-6 md:p-12">
      <div className="w-full max-w-2xl space-y-6">
        <header className="text-center space-y-1">
          <h1 className="text-3xl font-semibold text-stone-800">Bridge</h1>
          <p className="text-stone-500 text-sm italic">They love you. Just not in your language.</p>
        </header>

        {step === 'intro' && (
          <section className="space-y-5 bg-white rounded-2xl p-8 border border-stone-200">
            <p className="text-stone-700 leading-relaxed">
              Bridge translates a message between two people who love each other but struggle to reach each other.
              Try it with a real conversation you&apos;ve been putting off.
            </p>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-stone-600 mb-1">Your name</label>
                <input
                  className="w-full p-3 border border-stone-200 rounded-lg bg-stone-50 text-stone-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-200"
                  placeholder="e.g. Alex"
                  value={senderName}
                  onChange={e => setSenderName(e.target.value)}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-stone-600 mb-1">Their name</label>
                <input
                  className="w-full p-3 border border-stone-200 rounded-lg bg-stone-50 text-stone-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-200"
                  placeholder="e.g. Mom"
                  value={receiverName}
                  onChange={e => setReceiverName(e.target.value)}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-stone-600 mb-1">Relationship</label>
                <input
                  className="w-full p-3 border border-stone-200 rounded-lg bg-stone-50 text-stone-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-200"
                  placeholder="e.g. mother, partner, best friend, dad"
                  value={relationship}
                  onChange={e => setRelationship(e.target.value)}
                />
              </div>
            </div>

            <button
              onClick={() => setStep('onboardA')}
              disabled={!senderName.trim() || !receiverName.trim()}
              className="w-full py-3 bg-stone-800 text-white rounded-xl font-medium disabled:opacity-40 hover:bg-stone-700"
            >
              Start
            </button>
          </section>
        )}

        {step === 'onboardA' && (
          <OnboardingPanel
            title={`${youLabel} — how you express yourself`}
            subtitle="A few questions so Bridge can translate in your voice."
            questions={SENDER_QUESTIONS}
            answers={answersA}
            onChange={setAnswersA}
            onNext={() => setStep('onboardB')}
            nextLabel={`Next: ${themLabel} →`}
          />
        )}

        {step === 'onboardB' && (
          <OnboardingPanel
            title={`${themLabel} — how they best receive things`}
            subtitle={`Answer these as if you were ${themLabel}. (For the demo, you can role-play.)`}
            questions={RECEIVER_QUESTIONS}
            answers={answersB}
            onChange={setAnswersB}
            onNext={() => setStep('composeA')}
            nextLabel={`${youLabel} writes →`}
          />
        )}

        {step === 'composeA' && (
          <section className="space-y-4">
            <Badge>{youLabel} → {themLabel}{relationship && ` · ${relationship}`}</Badge>
            <label className="block text-sm text-stone-600">
              Write what you actually want to say. Don&apos;t worry about how it lands.
            </label>
            <textarea
              className="w-full h-48 p-4 border border-stone-200 rounded-xl bg-white text-stone-800 resize-none focus:outline-none focus:ring-2 focus:ring-amber-200"
              placeholder="I've been feeling distant lately and I don't know how to say it…"
              value={rawA}
              onChange={e => setRawA(e.target.value)}
            />
            {error && <p className="text-red-500 text-sm">{error}</p>}
            <button
              onClick={handleTranslateAtoB}
              disabled={!rawA.trim() || loading}
              className="w-full py-3 bg-stone-800 text-white rounded-xl font-medium disabled:opacity-40 hover:bg-stone-700"
            >
              {loading ? 'Bridge is translating…' : 'Send through Bridge →'}
            </button>
          </section>
        )}

        {step === 'viewB' && translationAtoB && (
          <section className="space-y-4">
            <Badge>{themLabel} · receiving from {youLabel}</Badge>
            <TranslationView t={translationAtoB} />
            <button
              onClick={() => setStep('replyB')}
              className="w-full py-3 bg-stone-800 text-white rounded-xl font-medium hover:bg-stone-700"
            >
              Reply as {themLabel} →
            </button>
          </section>
        )}

        {step === 'replyB' && (
          <section className="space-y-4">
            <Badge>{themLabel} → {youLabel}</Badge>
            <label className="block text-sm text-stone-600">
              Write {themLabel}&apos;s reply in their own words.
            </label>
            <textarea
              className="w-full h-40 p-4 border border-stone-200 rounded-xl bg-white text-stone-800 resize-none focus:outline-none focus:ring-2 focus:ring-amber-200"
              placeholder="I just want you to be okay…"
              value={rawB}
              onChange={e => setRawB(e.target.value)}
            />
            {error && <p className="text-red-500 text-sm">{error}</p>}
            <button
              onClick={handleTranslateBtoA}
              disabled={!rawB.trim() || loading}
              className="w-full py-3 bg-stone-800 text-white rounded-xl font-medium disabled:opacity-40 hover:bg-stone-700"
            >
              {loading ? 'Bridge is translating…' : 'Send through Bridge →'}
            </button>
          </section>
        )}

        {step === 'viewA' && translationBtoA && (
          <section className="space-y-4">
            <Badge>{youLabel} · receiving from {themLabel}</Badge>
            <TranslationView t={translationBtoA} />
            <button
              onClick={resetAll}
              className="w-full py-3 border border-stone-300 text-stone-600 rounded-xl font-medium hover:bg-stone-50"
            >
              Start a new conversation
            </button>
          </section>
        )}
      </div>
    </main>
  )
}

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <div className="inline-block text-xs font-medium text-stone-500 uppercase tracking-wide bg-stone-100 rounded-full px-3 py-1">
      {children}
    </div>
  )
}

function OnboardingPanel({
  title, subtitle, questions, answers, onChange, onNext, nextLabel,
}: {
  title: string; subtitle: string; questions: string[]; answers: string[]
  onChange: (a: string[]) => void; onNext: () => void; nextLabel: string
}) {
  const canAdvance = answers.some(a => a.trim().length > 0)
  return (
    <section className="space-y-5 bg-white rounded-2xl p-6 border border-stone-200">
      <div>
        <h2 className="text-lg font-semibold text-stone-800">{title}</h2>
        <p className="text-sm text-stone-500">{subtitle}</p>
      </div>
      {questions.map((q, i) => (
        <div key={i} className="space-y-2">
          <label className="block text-sm text-stone-700">{q}</label>
          <textarea
            className="w-full h-20 p-3 border border-stone-200 rounded-lg bg-stone-50 text-stone-800 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-amber-200"
            value={answers[i]}
            onChange={e => {
              const next = [...answers]; next[i] = e.target.value; onChange(next)
            }}
          />
        </div>
      ))}
      <button
        onClick={onNext}
        disabled={!canAdvance}
        className="w-full py-3 bg-stone-800 text-white rounded-xl font-medium disabled:opacity-40 hover:bg-stone-700"
      >
        {nextLabel}
      </button>
    </section>
  )
}

function TranslationView({ t }: { t: Translation }) {
  return (
    <div className="space-y-4">
      <div className="bg-white border border-stone-200 rounded-2xl p-5 space-y-2">
        <p className="text-xs text-stone-400 uppercase tracking-wide">Translator agent</p>
        <p className="text-stone-800 leading-relaxed whitespace-pre-wrap">{t.translated_content}</p>
        <p className="text-xs text-stone-400 pt-2">Translated by Bridge · 3-agent pipeline</p>
      </div>

      <div className="bg-amber-50 border border-amber-200 rounded-2xl p-5 space-y-4">
        <p className="text-xs font-medium text-amber-800 uppercase tracking-wide">
          Bridge sent two more notes so you understand the full picture
        </p>
        <div>
          <p className="text-xs font-medium text-amber-800 uppercase tracking-wide mb-1">
            Emotion agent · what they really meant
          </p>
          <p className="text-stone-700 text-sm leading-relaxed">{t.emotional_interpretation}</p>
        </div>
        <div>
          <p className="text-xs font-medium text-amber-800 uppercase tracking-wide mb-1">
            Context agent · why this happens between you two
          </p>
          <p className="text-stone-700 text-sm leading-relaxed">{t.educational_context}</p>
        </div>
      </div>
    </div>
  )
}
