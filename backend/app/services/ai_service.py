import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from google import genai

from app.config import settings

logger = logging.getLogger(__name__)

_client = genai.Client(api_key=settings.gemini_api_key)


AGENT1_EMOTION_PROMPT = """You are the EMOTION INTERPRETER agent of Bridge.

Your only job: read the message below and tell the receiver what the sender truly means beneath the words.

Sender profile (how this person expresses themselves):
{sender_profile}

Receiver profile (how this person best receives):
{receiver_profile}

Conversation memory so far (may be empty):
{memory_summary}

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

Conversation memory so far (may be empty):
{memory_summary}

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

Conversation memory so far (may be empty):
{memory_summary}

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


def _run_prompt(prompt: str) -> str:
    try:
        response = _client.models.generate_content(
            model=settings.model_id,
            contents=prompt,
        )
        return (response.text or "").strip()
    except Exception:
        logger.exception("Gemini request failed.")
        return ""


def translate_message(
    raw_message: str,
    sender_profile: str = "",
    receiver_profile: str = "",
    memory_summary: str = "",
) -> dict[str, Any]:
    sender = sender_profile.strip() or "(not provided)"
    receiver = receiver_profile.strip() or "(not provided)"
    memory = memory_summary.strip() or "(none yet)"
    raw = raw_message.strip()

    result: dict[str, Any] = {
        "emotional_interpretation": "",
        "educational_context": "",
        "translated_content": "",
        "crisis": False,
    }

    emotion = _run_prompt(
        AGENT1_EMOTION_PROMPT.format(
            raw_message=raw,
            sender_profile=sender,
            receiver_profile=receiver,
            memory_summary=memory,
        )
    )

    if not emotion:
        return _fallback(raw)

    if "[CRISIS]" in emotion.upper():
        result["crisis"] = True
        return result

    result["emotional_interpretation"] = emotion

    with ThreadPoolExecutor(max_workers=2) as pool:
        context_future = pool.submit(
            _run_prompt,
            AGENT2_CONTEXT_PROMPT.format(
                raw_message=raw,
                sender_profile=sender,
                receiver_profile=receiver,
                memory_summary=memory,
            ),
        )
        translation_future = pool.submit(
            _run_prompt,
            AGENT3_TRANSLATOR_PROMPT.format(
                raw_message=raw,
                sender_profile=sender,
                receiver_profile=receiver,
                memory_summary=memory,
                emotion_interpretation=emotion,
            ),
        )

        context_text = context_future.result()
        translation_text = translation_future.result()

    result["educational_context"] = context_text or _fallback_context()
    result["translated_content"] = translation_text or raw

    return result


def synthesize_profiles(name: str, answers: list[str]) -> dict[str, Any]:
    prompt = f"""You are Bridge, an emotional translation assistant.

The user is named: {name}

Below are onboarding answers describing how they communicate and how they wish their partner in conversation would receive them.

Return VALID JSON ONLY, no markdown, with exactly this shape:
{{
  "communication_profile": {{
    "summary": "1-2 sentence paragraph on how this person expresses themselves",
    "hard_topics": ["3-5 short phrases"],
    "communication_style": "one short phrase",
    "triggers": ["3-5 short phrases"],
    "support_signals": ["3-5 short phrases"]
  }},
  "receiver_seed_profile": {{
    "best_tone": "short phrase",
    "best_structure": "short phrase",
    "known_triggers": ["3-5 phrases"],
    "trust_signals": ["3-5 phrases"]
  }}
}}

Answers:
{json.dumps(answers, ensure_ascii=False)}
"""
    default = {
        "communication_profile": {
            "summary": "This person is trying to share something emotionally real without it landing as blame.",
            "hard_topics": ["vulnerability", "family expectations"],
            "communication_style": "guarded but sincere",
            "triggers": ["lecturing", "dismissiveness"],
            "support_signals": ["calm questions", "gentle reassurance"],
        },
        "receiver_seed_profile": {
            "best_tone": "warm and respectful",
            "best_structure": "context first, specifics second",
            "known_triggers": ["blame", "abrupt criticism"],
            "trust_signals": ["gratitude", "specific examples"],
        },
    }
    return _extract_json(_run_prompt(prompt), default)


def summarize_memory(transcript: list[dict[str, str]]) -> dict[str, Any]:
    if not transcript:
        return {"summary": "", "key_themes": []}

    prompt = f"""You are Bridge, maintaining a short rolling memory of a relationship.

Return VALID JSON ONLY with exactly this shape:
{{
  "summary": "2-3 sentences on the emotional arc so far",
  "key_themes": ["3-6 short phrase themes"]
}}

Transcript (most recent last):
{json.dumps(transcript, ensure_ascii=False)}
"""
    default = {
        "summary": "Both people are trying to stay honest while avoiding escalation.",
        "key_themes": ["honesty", "fear of misunderstanding", "care"],
    }
    return _extract_json(_run_prompt(prompt), default)


def _extract_json(text: str, default: dict[str, Any]) -> dict[str, Any]:
    if not text:
        return default
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    candidate = match.group(0) if match else text
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        logger.warning("Failed to parse JSON output; using default.")
    return default


def _fallback(raw_message: str) -> dict[str, Any]:
    return {
        "emotional_interpretation": "The sender is trying to communicate something real and emotionally important without it landing as blame.",
        "educational_context": _fallback_context(),
        "translated_content": raw_message.strip(),
        "crisis": False,
    }


def _fallback_context() -> str:
    return "Bridge softens delivery because difficult family conversations often break down at the level of tone before the message itself is heard."
