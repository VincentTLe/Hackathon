import hashlib
import secrets
from dataclasses import dataclass
from typing import Literal, Optional

from fastapi import Depends, Header, HTTPException, status

Role = Literal["founder", "receiver"]


@dataclass
class Actor:
    role: Role
    id: str
    name: str
    connection_id: Optional[str] = None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_hex(32)


def _parse_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def get_optional_actor(authorization: Optional[str] = Header(default=None)) -> Optional[Actor]:
    token = _parse_bearer(authorization)
    if not token:
        return None
    from app import store

    h = hash_token(token)
    founder = store.get_founder_by_token_hash(h)
    if founder:
        return Actor(role="founder", id=founder["id"], name=founder["name"])
    receiver = store.get_receiver_by_token_hash(h)
    if receiver:
        return Actor(
            role="receiver",
            id=receiver["id"],
            name=receiver["display_name"],
            connection_id=receiver["connection_id"],
        )
    return None


def get_current_actor(actor: Optional[Actor] = Depends(get_optional_actor)) -> Actor:
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing token.")
    return actor


def require_founder(actor: Actor = Depends(get_current_actor)) -> Actor:
    if actor.role != "founder":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Founder access required.")
    return actor
