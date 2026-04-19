from concurrent.futures import ThreadPoolExecutor
from google import genai
from app.config import settings

_client = genai.Client(api_key=settings.gemini_api_key)


AGENT1_EMOTION_PROMPT = """You are the EMOTION INTERPRETER agent of Bridge.

Your only job: read the message below and tell the receiver what the sender truly means beneath the words.

Sender profile (how this person expresses themselves):
{sender_profile}

Receiver profile (how this person best receives):
{receiver_profile}

Message:
---
{raw_message}
---

Rules:
- Write 2-4 sentences, second-person to the receiver ("They're telling you ...").
- Name the emotion(s) actually present. Do not invent feelings the sender did not express.
- Do not censor or soften painful emotions — reframe, don't remove.
- Do not translate or rewrite the message. Only interpret.
- If the message contains signals of self-harm or immediate danger to self or others, respond with exactly [CRISIS] and nothing else.

Output only the interpretation. No labels, no preamble."""


AGENT2_CONTEXT_PROMPT = """You are the CULTURAL CONTEXT agent of Bridge.

Your only job: help the receiver understand WHY this communication pattern shows up between these two people. Non-clinical. Not a diagnosis. Not advice.

Sender profile:
{sender_profile}

Receiver profile:
{receiver_profile}

Message:
---
{raw_message}
---

Rules:
- Write 2-4 sentences explaining the dynamic — family role, cultural norms, generational patterns, emotional language gaps — whichever is actually relevant here.
- Speak TO the receiver about the pattern, not about the sender as a person.
- Do not take sides. Do not prescribe what the receiver should do.
- Do not repeat the message back.

Output only the context paragraph. No labels, no preamble."""


AGENT3_TRANSLATOR_PROMPT = """You are the TRANSLATOR agent of Bridge.

Your job: rewrite the sender's message so the receiver can actually hear it — while preserving the sender's truth and voice.

Sender profile (how this person expresses themselves):
{sender_profile}

Receiver profile (how this person best receives):
{receiver_profile}

Emotional interpretation from the Emotion agent (use this to understand what's really being said):
{emotion_interpretation}

Original message:
---
{raw_message}
---

Rules:
- Keep every emotion the sender actually expressed. Reframe delivery, never remove truth.
- Adapt tone, pacing, and framing to what the receiver can hear — based on their profile.
- Still sound like the sender. Not AI-polished. Not a therapist. Not a greeting card.
- Do not add new information, apologies, or advice the sender did not give.
- Match the language of the original message (if sender wrote Vietnamese, output Vietnamese).

Output only the rewritten message. No labels, no preamble, no quotes around it."""


def _run(prompt: str) -> str:
    response = _client.models.generate_content(
        model=settings.model_id,
        contents=prompt,
    )
    return (response.text or "").strip()


def translate_message(
    raw_message: str,
    sender_profile: str = "",
    receiver_profile: str = "",
) -> dict:
    sender = sender_profile.strip() or "(not provided)"
    receiver = receiver_profile.strip() or "(not provided)"

    result = {
        "emotional_interpretation": "",
        "educational_context": "",
        "translated_content": "",
        "crisis": False,
    }

    # Agent 1 runs first — it's also the crisis gate.
    emotion = _run(AGENT1_EMOTION_PROMPT.format(
        raw_message=raw_message,
        sender_profile=sender,
        receiver_profile=receiver,
    ))

    if "[CRISIS]" in emotion.upper():
        result["crisis"] = True
        return result

    result["emotional_interpretation"] = emotion

    # Agent 2 and Agent 3 run in parallel.
    # Agent 3 gets Agent 1's output so the translation is informed by the emotional read.
    with ThreadPoolExecutor(max_workers=2) as pool:
        context_future = pool.submit(_run, AGENT2_CONTEXT_PROMPT.format(
            raw_message=raw_message,
            sender_profile=sender,
            receiver_profile=receiver,
        ))
        translation_future = pool.submit(_run, AGENT3_TRANSLATOR_PROMPT.format(
            raw_message=raw_message,
            sender_profile=sender,
            receiver_profile=receiver,
            emotion_interpretation=emotion,
        ))

        result["educational_context"] = context_future.result()
        result["translated_content"] = translation_future.result()

    return result
