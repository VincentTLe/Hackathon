from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import store

router = APIRouter(prefix="/session", tags=["session"])


class BAcceptRequest(BaseModel):
    magic_link_token: str = Field(..., min_length=1)
    receiver_name: str = Field(..., min_length=1, max_length=200)


class BAcceptResponse(BaseModel):
    session_token: str
    connection_id: str
    founder_name: str


@router.post("/b-accept", response_model=BAcceptResponse)
def b_accept(req: BAcceptRequest):
    conn = store.get_connection_by_magic_link(req.magic_link_token)
    if not conn:
        raise HTTPException(status_code=404, detail="Invalid magic link.")

    expires = conn.get("magic_link_expires_at")
    if expires:
        try:
            exp_dt = datetime.fromisoformat(expires)
            if exp_dt < datetime.now(timezone.utc):
                raise HTTPException(status_code=410, detail="Magic link expired.")
        except ValueError:
            pass

    result = store.accept_connection(conn["id"], req.receiver_name)
    return BAcceptResponse(
        session_token=result["session_token"],
        connection_id=result["connection_id"],
        founder_name=result["founder_name"],
    )
