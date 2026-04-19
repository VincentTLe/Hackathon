from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import store
from app.auth import Actor, get_current_actor, get_optional_actor
from app.services import ai_service

router = APIRouter(prefix="/messages", tags=["messages"])

MAX_RAW_LEN = 2000
MEMORY_TRANSCRIPT_LIMIT = 10


class LegacyTranslateRequest(BaseModel):
    raw_message: str = Field(..., min_length=1, max_length=MAX_RAW_LEN)
    sender_profile: str = Field("", max_length=4000)
    receiver_profile: str = Field("", max_length=4000)


class LegacyTranslateResponse(BaseModel):
    translated_content: str
    emotional_interpretation: str
    educational_context: str


class NewTranslateRequest(BaseModel):
    connection_id: str = Field(..., min_length=1)
    raw_message: str = Field(..., min_length=1, max_length=MAX_RAW_LEN)


class NewTranslateResponse(BaseModel):
    preview_id: str
    translated_content: str


class ApproveRequest(BaseModel):
    preview_id: str = Field(..., min_length=1)


class ApproveResponse(BaseModel):
    message_id: str
    connection_id: str
    sender_review_status: str = "approved"


def _crisis_response() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": "crisis_detected",
            "message": "Please reach a trusted person or call a helpline.",
        },
    )


@router.post("/translate")
async def translate(request: Request):
    body = await request.json()
    actor: Optional[Actor] = await _optional_actor_from_request(request)

    if actor and "connection_id" in body:
        req = NewTranslateRequest(**body)
        return _translate_authed(actor, req)

    req = LegacyTranslateRequest(**body)
    return _translate_legacy(req)


async def _optional_actor_from_request(request: Request) -> Optional[Actor]:
    return get_optional_actor(authorization=request.headers.get("authorization"))


def _translate_legacy(req: LegacyTranslateRequest) -> LegacyTranslateResponse:
    result = ai_service.translate_message(
        raw_message=req.raw_message,
        sender_profile=req.sender_profile,
        receiver_profile=req.receiver_profile,
    )
    if result["crisis"]:
        raise _crisis_response()
    if not result["translated_content"]:
        raise HTTPException(500, "Translation failed.")
    return LegacyTranslateResponse(
        translated_content=result["translated_content"],
        emotional_interpretation=result["emotional_interpretation"],
        educational_context=result["educational_context"],
    )


def _translate_authed(actor: Actor, req: NewTranslateRequest) -> NewTranslateResponse:
    conn_record = store.get_connection_record(req.connection_id, actor)
    sender_profile, receiver_profile = store.profiles_for_translate(req.connection_id, actor)
    memory = store.get_memory(req.connection_id)

    result = ai_service.translate_message(
        raw_message=req.raw_message,
        sender_profile=sender_profile,
        receiver_profile=receiver_profile,
        memory_summary=memory.get("summary", ""),
    )
    if result["crisis"]:
        raise _crisis_response()
    if not result["translated_content"]:
        raise HTTPException(500, "Translation failed.")

    preview = store.create_message_preview(
        actor=actor,
        connection_id=req.connection_id,
        raw=req.raw_message,
        translated=result["translated_content"],
        emotional=result["emotional_interpretation"],
        educational=result["educational_context"],
    )
    return NewTranslateResponse(
        preview_id=preview["id"],
        translated_content=preview["translated_content"],
    )


@router.post("/approve", response_model=ApproveResponse)
def approve(req: ApproveRequest, actor: Actor = Depends(get_current_actor)):
    result = store.approve_preview(actor, req.preview_id)
    _update_memory_async(result["connection_id"])
    return ApproveResponse(
        message_id=result["message_id"],
        connection_id=result["connection_id"],
    )


def _update_memory_async(connection_id: str) -> None:
    try:
        raw_msgs = store.list_messages_raw(connection_id)
        transcript = [
            {"role": m["sender_role"], "translated_content": m["translated_content"]}
            for m in raw_msgs[-MEMORY_TRANSCRIPT_LIMIT:]
        ]
        summary_data = ai_service.summarize_memory(transcript)
        store.update_memory(
            connection_id,
            summary_data.get("summary", ""),
            summary_data.get("key_themes", []) or [],
        )
    except Exception:
        pass


@router.get("/{connection_id}")
def list_messages(
    connection_id: str,
    since: Optional[str] = None,
    actor: Actor = Depends(get_current_actor),
):
    conn = store.get_connection_record(connection_id, actor)
    messages = store.list_messages_for_actor(connection_id, actor, since)
    memory = store.get_memory(connection_id)
    return {
        "viewer_role": actor.role,
        "connection": conn,
        "memory": memory,
        "messages": messages,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }
