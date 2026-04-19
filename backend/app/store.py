import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException, status

from app.auth import Actor, hash_token, new_token
from app.db import cursor

MAGIC_LINK_TTL_DAYS = 7


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expiry_iso(days: int = MAGIC_LINK_TTL_DAYS) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def _row_to_dict(row) -> dict:
    return dict(row) if row else {}


# -------------------- founders --------------------

def create_founder(name: str, communication_profile: dict, receiver_seed_profile: dict) -> dict:
    founder_id = _new_id()
    token = new_token()
    with cursor() as cur:
        cur.execute(
            """INSERT INTO founders
            (id, name, token_hash, communication_profile, receiver_seed_profile, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                founder_id,
                name,
                hash_token(token),
                json.dumps(communication_profile, ensure_ascii=False),
                json.dumps(receiver_seed_profile, ensure_ascii=False),
                _now_iso(),
            ),
        )
    return {
        "founder_id": founder_id,
        "founder_token": token,
        "communication_profile": communication_profile,
        "receiver_seed_profile": receiver_seed_profile,
    }


def get_founder(founder_id: str) -> Optional[dict]:
    with cursor() as cur:
        cur.execute("SELECT * FROM founders WHERE id = ?", (founder_id,))
        row = cur.fetchone()
    if not row:
        return None
    d = _row_to_dict(row)
    d["communication_profile"] = json.loads(d["communication_profile"])
    d["receiver_seed_profile"] = json.loads(d["receiver_seed_profile"])
    return d


def get_founder_by_token_hash(token_hash: str) -> Optional[dict]:
    with cursor() as cur:
        cur.execute("SELECT * FROM founders WHERE token_hash = ?", (token_hash,))
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


# -------------------- connections --------------------

def create_connection(
    founder_id: str,
    receiver_display_name: str,
    relationship: str,
    invite_note: str = "",
) -> dict:
    cid = _new_id()
    mlt = new_token()
    with cursor() as cur:
        cur.execute(
            """INSERT INTO connections
            (id, founder_id, receiver_display_name, relationship, invite_note,
             magic_link_token, magic_link_expires_at, created_at, accepted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
            (
                cid,
                founder_id,
                receiver_display_name,
                relationship,
                invite_note or "",
                mlt,
                _expiry_iso(),
                _now_iso(),
            ),
        )
    return {"connection_id": cid, "magic_link_token": mlt}


def list_connections_for_founder(founder_id: str) -> list[dict]:
    with cursor() as cur:
        cur.execute(
            """SELECT c.*, (
                SELECT MAX(m.created_at) FROM messages m WHERE m.connection_id = c.id
            ) AS last_message_at
            FROM connections c
            WHERE c.founder_id = ?
            ORDER BY c.created_at DESC""",
            (founder_id,),
        )
        rows = cur.fetchall()
    out = []
    for r in rows:
        d = _row_to_dict(r)
        out.append({
            "id": d["id"],
            "receiver_display_name": d["receiver_display_name"],
            "relationship": d["relationship"],
            "accepted": d.get("accepted_at") is not None,
            "last_message_at": d.get("last_message_at"),
            "magic_link_token": d["magic_link_token"],
        })
    return out


def get_connection(connection_id: str) -> Optional[dict]:
    with cursor() as cur:
        cur.execute("SELECT * FROM connections WHERE id = ?", (connection_id,))
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_connection_by_magic_link(token: str) -> Optional[dict]:
    with cursor() as cur:
        cur.execute("SELECT * FROM connections WHERE magic_link_token = ?", (token,))
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_connection_record(connection_id: str, actor: Actor) -> dict:
    conn = get_connection(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found.")
    if actor.role == "founder" and conn["founder_id"] != actor.id:
        raise HTTPException(status_code=404, detail="Connection not found.")
    if actor.role == "receiver" and actor.connection_id != connection_id:
        raise HTTPException(status_code=404, detail="Connection not found.")
    founder = get_founder(conn["founder_id"]) or {}
    return {
        "id": conn["id"],
        "founder_id": conn["founder_id"],
        "founder_name": founder.get("name", ""),
        "receiver_display_name": conn["receiver_display_name"],
        "relationship": conn["relationship"],
        "invite_note": conn.get("invite_note") or "",
        "accepted_at": conn.get("accepted_at"),
    }


def accept_connection(connection_id: str, receiver_name: str) -> dict:
    conn = get_connection(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found.")
    token = new_token()
    token_h = hash_token(token)
    now = _now_iso()
    with cursor() as cur:
        cur.execute("SELECT id FROM receivers WHERE connection_id = ?", (connection_id,))
        existing = cur.fetchone()
        if existing:
            receiver_id = existing["id"]
            cur.execute(
                "UPDATE receivers SET display_name = ?, session_token_hash = ? WHERE id = ?",
                (receiver_name, token_h, receiver_id),
            )
        else:
            receiver_id = _new_id()
            cur.execute(
                """INSERT INTO receivers
                (id, connection_id, display_name, session_token_hash, created_at)
                VALUES (?, ?, ?, ?, ?)""",
                (receiver_id, connection_id, receiver_name, token_h, now),
            )
        if conn.get("accepted_at") is None:
            cur.execute(
                "UPDATE connections SET accepted_at = ? WHERE id = ?",
                (now, connection_id),
            )
    founder = get_founder(conn["founder_id"]) or {}
    return {
        "receiver_id": receiver_id,
        "session_token": token,
        "connection_id": connection_id,
        "founder_name": founder.get("name", ""),
    }


def get_receiver_by_token_hash(token_hash: str) -> Optional[dict]:
    with cursor() as cur:
        cur.execute("SELECT * FROM receivers WHERE session_token_hash = ?", (token_hash,))
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_receiver_for_connection(connection_id: str) -> Optional[dict]:
    with cursor() as cur:
        cur.execute("SELECT * FROM receivers WHERE connection_id = ?", (connection_id,))
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


# -------------------- messages / previews --------------------

def create_message_preview(
    actor: Actor,
    connection_id: str,
    raw: str,
    translated: str,
    emotional: str,
    educational: str,
) -> dict:
    pid = _new_id()
    with cursor() as cur:
        cur.execute(
            """INSERT INTO message_previews
            (id, connection_id, sender_role, sender_id, raw_content, translated_content,
             emotional_interpretation, educational_context, created_at, approved)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                pid,
                connection_id,
                actor.role,
                actor.id,
                raw,
                translated,
                emotional,
                educational,
                _now_iso(),
            ),
        )
    return {"id": pid, "translated_content": translated}


def get_preview(preview_id: str) -> Optional[dict]:
    with cursor() as cur:
        cur.execute("SELECT * FROM message_previews WHERE id = ?", (preview_id,))
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def approve_preview(actor: Actor, preview_id: str) -> dict:
    preview = get_preview(preview_id)
    if not preview:
        raise HTTPException(status_code=404, detail="Preview not found.")
    if preview["sender_id"] != actor.id or preview["sender_role"] != actor.role:
        raise HTTPException(status_code=403, detail="Not your preview.")
    if preview["approved"]:
        raise HTTPException(status_code=409, detail="Already approved.")

    msg_id = _new_id()
    with cursor() as cur:
        cur.execute(
            """INSERT INTO messages
            (id, connection_id, sender_role, sender_id, raw_content, translated_content,
             emotional_interpretation, educational_context, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                msg_id,
                preview["connection_id"],
                preview["sender_role"],
                preview["sender_id"],
                preview["raw_content"],
                preview["translated_content"],
                preview["emotional_interpretation"],
                preview["educational_context"],
                _now_iso(),
            ),
        )
        cur.execute("UPDATE message_previews SET approved = 1 WHERE id = ?", (preview_id,))
    return {"message_id": msg_id, "connection_id": preview["connection_id"]}


def list_messages_raw(connection_id: str, since_iso: Optional[str] = None) -> list[dict]:
    query = "SELECT * FROM messages WHERE connection_id = ?"
    params: list[Any] = [connection_id]
    if since_iso:
        query += " AND created_at > ?"
        params.append(since_iso)
    query += " ORDER BY created_at ASC"
    with cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]


def list_messages_for_actor(
    connection_id: str,
    actor: Actor,
    since_iso: Optional[str] = None,
) -> list[dict]:
    raw_rows = list_messages_raw(connection_id, since_iso)
    out = []
    for r in raw_rows:
        is_sender = r["sender_role"] == actor.role and r["sender_id"] == actor.id
        item = {
            "id": r["id"],
            "sender_role": r["sender_role"],
            "is_mine": is_sender,
            "created_at": r["created_at"],
            "translated_content": r["translated_content"],
        }
        if is_sender:
            item["raw_content"] = r["raw_content"]
        else:
            item["emotional_interpretation"] = r["emotional_interpretation"]
            item["educational_context"] = r["educational_context"]
        out.append(item)
    return out


def get_memory(connection_id: str) -> dict:
    with cursor() as cur:
        cur.execute("SELECT * FROM conversation_memory WHERE connection_id = ?", (connection_id,))
        row = cur.fetchone()
    if not row:
        return {"summary": "", "key_themes": [], "updated_at": None}
    d = _row_to_dict(row)
    try:
        d["key_themes"] = json.loads(d["key_themes"])
    except Exception:
        d["key_themes"] = []
    return d


def update_memory(connection_id: str, summary: str, key_themes: list[str]) -> None:
    with cursor() as cur:
        cur.execute(
            """INSERT INTO conversation_memory (connection_id, summary, key_themes, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(connection_id) DO UPDATE SET
              summary = excluded.summary,
              key_themes = excluded.key_themes,
              updated_at = excluded.updated_at""",
            (connection_id, summary, json.dumps(key_themes, ensure_ascii=False), _now_iso()),
        )


def profiles_for_translate(connection_id: str, sender_actor: Actor) -> tuple[str, str]:
    conn = get_connection(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found.")
    founder = get_founder(conn["founder_id"]) or {}
    founder_profile = json.dumps(founder.get("communication_profile", {}), ensure_ascii=False)
    receiver_seed = json.dumps(founder.get("receiver_seed_profile", {}), ensure_ascii=False)
    if sender_actor.role == "founder":
        return founder_profile, receiver_seed
    return receiver_seed, founder_profile
