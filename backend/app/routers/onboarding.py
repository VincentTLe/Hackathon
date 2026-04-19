from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import store
from app.services import ai_service

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class FounderOnboardRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    answers: list[str] = Field(..., min_length=1, max_length=20)


class FounderOnboardResponse(BaseModel):
    founder_id: str
    founder_token: str
    communication_profile: dict
    receiver_seed_profile: dict


@router.post("/founder", response_model=FounderOnboardResponse)
def onboard_founder(req: FounderOnboardRequest):
    synthesized = ai_service.synthesize_profiles(req.name, req.answers)
    comm = synthesized.get("communication_profile") or {}
    seed = synthesized.get("receiver_seed_profile") or {}
    record = store.create_founder(req.name, comm, seed)
    return FounderOnboardResponse(
        founder_id=record["founder_id"],
        founder_token=record["founder_token"],
        communication_profile=comm,
        receiver_seed_profile=seed,
    )
