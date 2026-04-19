from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import store
from app.auth import Actor, require_founder
from app.config import settings

router = APIRouter(prefix="/connections", tags=["connections"])


class CreateConnectionRequest(BaseModel):
    receiver_display_name: str = Field(..., min_length=1, max_length=200)
    relationship: str = Field(..., min_length=1, max_length=100)
    invite_note: str = Field("", max_length=1000)


class CreateConnectionResponse(BaseModel):
    connection_id: str
    magic_link_token: str
    magic_link_url: str


class ConnectionListItem(BaseModel):
    id: str
    receiver_display_name: str
    relationship: str
    accepted: bool
    last_message_at: str | None
    magic_link_url: str


class ListConnectionsResponse(BaseModel):
    connections: list[ConnectionListItem]


class InvitePreviewResponse(BaseModel):
    founder_name: str
    receiver_display_name: str
    relationship: str
    invite_note: str


def _magic_url(token: str) -> str:
    base = settings.app_base_url.rstrip("/")
    return f"{base}/invite/{token}"


@router.post("", response_model=CreateConnectionResponse)
def create_connection(req: CreateConnectionRequest, actor: Actor = Depends(require_founder)):
    result = store.create_connection(
        founder_id=actor.id,
        receiver_display_name=req.receiver_display_name,
        relationship=req.relationship,
        invite_note=req.invite_note,
    )
    return CreateConnectionResponse(
        connection_id=result["connection_id"],
        magic_link_token=result["magic_link_token"],
        magic_link_url=_magic_url(result["magic_link_token"]),
    )


@router.get("", response_model=ListConnectionsResponse)
def list_connections(actor: Actor = Depends(require_founder)):
    rows = store.list_connections_for_founder(actor.id)
    items = [
        ConnectionListItem(
            id=r["id"],
            receiver_display_name=r["receiver_display_name"],
            relationship=r["relationship"],
            accepted=r["accepted"],
            last_message_at=r["last_message_at"],
            magic_link_url=_magic_url(r["magic_link_token"]),
        )
        for r in rows
    ]
    return ListConnectionsResponse(connections=items)


@router.get("/invite/{token}", response_model=InvitePreviewResponse)
def invite_preview(token: str):
    conn = store.get_connection_by_magic_link(token)
    if not conn:
        raise HTTPException(status_code=404, detail="Invite not found.")
    founder = store.get_founder(conn["founder_id"]) or {}
    return InvitePreviewResponse(
        founder_name=founder.get("name", ""),
        receiver_display_name=conn["receiver_display_name"],
        relationship=conn["relationship"],
        invite_note=conn.get("invite_note") or "",
    )
