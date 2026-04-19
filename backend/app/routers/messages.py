from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.services import ai_service

router = APIRouter(prefix="/messages", tags=["messages"])


class TranslateRequest(BaseModel):
    raw_message: str = Field(..., min_length=1, max_length=2000)
    sender_profile: str = Field("", max_length=2000)
    receiver_profile: str = Field("", max_length=2000)


class TranslateResponse(BaseModel):
    translated_content: str
    emotional_interpretation: str
    educational_context: str


@router.post("/translate", response_model=TranslateResponse)
def translate(req: TranslateRequest):
    result = ai_service.translate_message(
        raw_message=req.raw_message,
        sender_profile=req.sender_profile,
        receiver_profile=req.receiver_profile,
    )

    if result["crisis"]:
        raise HTTPException(
            status_code=422,
            detail="Crisis signal detected. Please reach out to a trusted person or call a helpline.",
        )

    if not result["translated_content"]:
        raise HTTPException(500, "Translation failed — no output from AI.")

    return TranslateResponse(
        translated_content=result["translated_content"],
        emotional_interpretation=result["emotional_interpretation"],
        educational_context=result["educational_context"],
    )
