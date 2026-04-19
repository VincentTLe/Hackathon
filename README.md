# Bridge

*They love you. Just not in your language.*

Bridge is an AI-mediated translator for the hardest conversations — the ones we keep putting off with the people we love most.

Built for **Hack Auggie 2026**.

---

## The conversation that never happened

I'm a Vietnamese international student in the US.

Growing up, I watched the same thing play out over and over — in my own family, in my friends' families, in almost every immigrant household I stepped into:

A kid is struggling. They want to tell their parents something real. They pick up the phone. They hear *"Ăn cơm chưa?"* — have you eaten yet? — and they answer *"Rồi."* Yes.

And the conversation that actually mattered never happened.

Not because nobody cared. Not because nobody loved each other. Because the words to carry that kind of conversation don't exist in the shared language between generations — and nobody ever taught us how to build them.

Bridge is my attempt to build those words.

---

## The numbers behind the silence

This is not a personal story. It's a pattern — and the data is brutally consistent.

### Asian Americans are the least likely to get help

Only about **1 in 4 Asian American adults** with a diagnosable mental illness receives any form of treatment — roughly **half the rate of white adults**, and the lowest rate of any major racial group tracked in the US. *(SAMHSA, National Survey on Drug Use and Health)*

The National Alliance on Mental Illness reports the same pattern consistently: Asian Americans are around 50% less likely than the general population to seek mental health services. *(NAMI, AAPI Mental Health)*

### Suicide is a leading cause of death for AAPI youth

For Asian American and Pacific Islander youth ages 15–24, **suicide ranks among the top three causes of death**, year after year. In some recent reporting years it has been the leading cause. *(CDC WISQARS)*

### 24 million Asian Americans. Most are first-generation immigrants.

Roughly **60% of Asian adults in the US were born outside the country.** Their children grow up culturally and linguistically bilingual. Their parents, usually, do not. *(Pew Research Center, 2023)*

### The "acculturation gap" is measurable — and it hurts

Three decades of research have documented a specific phenomenon: the faster children of immigrants adapt to the new culture, the wider the gap between them and their parents grows. That gap correlates with **higher rates of family conflict, adolescent depression, and anxiety.** *(Telzer, 2010 — "Expanding the Acculturation Gap-Distressing Model", Human Development; summarizing dozens of underlying studies)*

---

## What actually breaks

It's not that parents don't love. It's not that kids don't try.

It's that the tools each side has to talk to the other were built for different worlds.

- **Filial piety** says: don't burden your parents.
- **American self-expression** says: name your feelings out loud.
- **Confucian family norms** say: don't air what happens inside the house.
- **Therapy culture** says: ask for help.

Every one of those is right inside its own frame. **None of them translate.**

So the kid stays silent. The parent assumes everything is fine. And if that kid is in a mental health spiral, the single conversation that might pull them out is the exact one that never gets had.

---

## What Bridge does

Bridge is the agent in the middle.

When one person writes a raw message — *"Mẹ ơi, dạo này con mệt lắm mà con không biết nói thế nào với mẹ"* — Bridge produces three things for the receiver:

1. **Emotional interpretation** — what the sender actually means underneath the words
2. **Educational context** — why this pattern shows up in families like theirs
3. **Translated message** — the message itself, rephrased so the receiver's brain can actually receive it

The sender reviews the translated version before anything is delivered. Both sides know, always, that an AI is in the middle — Bridge is never invisible, never editorial, never takes sides.

The goal isn't for people to depend on Bridge forever. The better it works, the less people need it. It's a bridge — not a crutch.

---

## Why this is a mental health project

Bridge is not therapy. It doesn't diagnose, prescribe, or replace a clinician.

But across every culture studied in the research, the single strongest protective factor against adolescent depression and suicide is the same one-line finding: **feeling understood by family.**

When that channel is open, kids survive hard things.
When it collapses, small things become fatal ones.

In immigrant families — and especially in Asian diaspora families — that channel is structurally harder to keep open than in families that share a culture, a language, and a vocabulary for feelings. That's not a character flaw. That's physics.

Bridge is an attempt to lower the activation energy of that one conversation. Not to replace it. Not to bypass it. Just to help the words arrive in a shape the other person can actually hear.

If that makes one more kid call home — or one more parent finally understand what their kid has been trying to say for years — it has done its job.

---

## Demo flow

1. **Onboard A** — a few questions about how you express yourself
2. **Onboard B** — a few questions about how the other person best receives
3. **Write** a raw message
4. **Review** Bridge's translation
5. **Deliver** — the other person sees the 3-part output
6. **Reply** — their response flows back through the same translator, reversed

## Tech stack

- **Frontend:** Next.js 14 App Router + Tailwind CSS
- **Backend:** Python FastAPI
- **AI:** Google Gemini 2.5 Flash
- **Deploy:** Vercel (frontend) + local-tunnel / Render (backend)

## Running locally

**Backend**
```bash
cd backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # fill GEMINI_API_KEY
uvicorn app.main:app --reload
```

**Frontend**
```bash
cd frontend
npm install
cp .env.local.example .env.local    # set NEXT_PUBLIC_API_URL
npm run dev
```

---

## Sources

- U.S. Substance Abuse and Mental Health Services Administration (SAMHSA), *National Survey on Drug Use and Health* — annual mental health services data by race/ethnicity
- National Alliance on Mental Illness (NAMI), *Asian American / Pacific Islander Mental Health*
- Centers for Disease Control and Prevention, *WISQARS Fatal Injury Reports* — leading causes of death by demographic
- Pew Research Center, *Key facts about Asian Americans* (2023)
- Telzer, E. H. (2010). Expanding the acculturation gap-distressing model: An integrative review of research. *Human Development*, 53(6), 313–340.

---

*Built with care, for the conversations we keep meaning to have.*
