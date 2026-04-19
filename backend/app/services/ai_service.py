import re
from google import genai
from app.config import settings

_client = genai.Client(api_key=settings.gemini_api_key)

TRANSLATION_PROMPT = """You are Bridge, an emotional translation engine. Your role is to help two people who love each other actually reach each other — by translating one person's message so the other can truly hear it.

Relationship type: parent_child

Sender profile (how this person expresses themselves):
{sender_profile}

Receiver profile (how this person best receives emotional messages):
{receiver_profile}

You must produce exactly three parts, labeled [1], [2], [3]:

[1] EMOTIONAL INTERPRETATION — what the sender truly means beneath the words
(1-3 sentences, written for the receiver in second-person empathetic tone, e.g. "They're telling you ...")

[2] EDUCATIONAL CONTEXT — why this communication pattern exists in this relationship
(1-3 sentences, non-clinical, helps the receiver understand the dynamic — not a diagnosis)

[3] TRANSLATED MESSAGE — the message adapted for the receiver
(preserves sender's truth, adapts delivery to receiver's profile, still sounds like it could come from the sender — not AI-polished)

Rules:
- Never add emotions the sender did not express
- Never remove or censor emotions the sender did express — reframe instead
- Never take sides or add your own opinion on the relationship
- Keep [1] and [2] brief — [3] is the primary deliverable
- If the message contains crisis signals (self-harm, immediate danger to self or others), respond with [CRISIS] only — nothing else

Message to translate:
---
{raw_message}
---

Return all three parts labeled [1], [2], [3]. Nothing else."""


def translate_message(
    raw_message: str,
    sender_profile: str = "",
    receiver_profile: str = "",
) -> dict:
    prompt = TRANSLATION_PROMPT.format(
        raw_message=raw_message,
        sender_profile=sender_profile.strip() or "(not provided)",
        receiver_profile=receiver_profile.strip() or "(not provided)",
    )
    response = _client.models.generate_content(
        model=settings.model_id,
        contents=prompt,
    )
    return _parse_three_part_output(response.text)


def _parse_three_part_output(text: str) -> dict:
    parts = {
        "emotional_interpretation": "",
        "educational_context": "",
        "translated_content": "",
        "crisis": False,
    }

    if "[CRISIS]" in text:
        parts["crisis"] = True
        return parts

    segments = re.split(r'\[1\]|\[2\]|\[3\]', text)
    markers = re.findall(r'\[1\]|\[2\]|\[3\]', text)

    mapping = {
        "[1]": "emotional_interpretation",
        "[2]": "educational_context",
        "[3]": "translated_content",
    }

    for i, marker in enumerate(markers):
        if i + 1 >= len(segments):
            break
        content = segments[i + 1].strip()
        # Drop an all-caps header line (e.g. "EMOTIONAL INTERPRETATION")
        lines = content.split("\n")
        if lines and lines[0].strip().isupper():
            content = "\n".join(lines[1:]).strip()
        parts[mapping[marker]] = content

    return parts
