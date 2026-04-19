import logging
import re

from google import genai

from app.config import settings

logger = logging.getLogger(__name__)

_client = genai.Client(api_key=settings.gemini_api_key)

TRANSLATION_PROMPT = """You are Bridge, an emotional translation engine.

You help two people who love each other actually reach each other by translating one person's message into language the other person can truly hear.

Sender profile:
{sender_profile}

Receiver profile:
{receiver_profile}

Return exactly three labeled parts:
[1] Emotional interpretation for the receiver
[2] Educational context for the receiver
[3] The translated message itself

Rules:
- Preserve the sender's truth and emotional reality.
- Adapt delivery so the receiver can hear it without becoming defensive.
- Keep [1] and [2] brief and clear.
- Keep [3] human, not robotic or over-polished.
- Match the language of the original message whenever possible.
- If the message contains signals of self-harm or immediate danger, return exactly [CRISIS].

Message:
---
{raw_message}
---

Return only the three labeled parts. Nothing else."""


def translate_message(
    raw_message: str,
    sender_profile: str = "",
    receiver_profile: str = "",
) -> dict:
    sender = sender_profile.strip() or "(not provided)"
    receiver = receiver_profile.strip() or "(not provided)"

    text = _request_translation(
        TRANSLATION_PROMPT.format(
            raw_message=raw_message.strip(),
            sender_profile=sender,
            receiver_profile=receiver,
        )
    )

    if not text:
        logger.warning("Gemini returned no text; using Bridge fallback translation.")
        return _fallback_translation(raw_message)

    parsed = _parse_three_part_output(text)

    if parsed["crisis"]:
        return parsed

    if not parsed["translated_content"]:
        logger.warning("Gemini response could not be parsed cleanly; using Bridge fallback translation.")
        return _fallback_translation(raw_message)

    return parsed


def _request_translation(prompt: str) -> str:
    try:
        response = _client.models.generate_content(
            model=settings.model_id,
            contents=prompt,
        )
        return (response.text or "").strip()
    except Exception:
        logger.exception("Gemini translation request failed.")
        return ""


def _parse_three_part_output(text: str) -> dict:
    parts = {
        "emotional_interpretation": "",
        "educational_context": "",
        "translated_content": "",
        "crisis": False,
    }

    if "[CRISIS]" in text.upper():
        parts["crisis"] = True
        return parts

    segments = re.split(r"\[1\]|\[2\]|\[3\]", text)
    markers = re.findall(r"\[1\]|\[2\]|\[3\]", text)
    mapping = {
        "[1]": "emotional_interpretation",
        "[2]": "educational_context",
        "[3]": "translated_content",
    }

    for index, marker in enumerate(markers):
        if index + 1 >= len(segments):
            break
        content = _strip_header(segments[index + 1].strip())
        parts[mapping[marker]] = content

    return parts


def _strip_header(content: str) -> str:
    lines = content.splitlines()
    if not lines:
        return content

    first_line = lines[0].strip()
    normalized = first_line.lower().rstrip(":")
    known_headers = {
        "emotional interpretation",
        "emotional interpretation for the receiver",
        "educational context",
        "educational context for the receiver",
        "translated message",
        "the translated message itself",
    }

    if first_line.isupper() or normalized in known_headers:
        return "\n".join(lines[1:]).strip()
    return content


def _fallback_translation(raw_message: str) -> dict:
    message = raw_message.strip()
    return {
        "emotional_interpretation": "The sender is trying to communicate something real and emotionally important without wanting it to land as blame.",
        "educational_context": "Bridge is softening the delivery because difficult family conversations often break down at the level of tone before the message itself is heard.",
        "translated_content": message,
        "crisis": False,
    }
