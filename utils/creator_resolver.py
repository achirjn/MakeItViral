from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy.orm import Session

from db.models import Creator


def resolve_creator(session: Session, creator_data: Mapping[str, Any]) -> Creator:
    """
    Upsert a Creator based on username (and platform).

    Required:
    - username

    Optional:
    - platform (defaults to "instagram")
    - followers
    - category
    - verified
    """
    username = (creator_data.get("username") or "").strip()
    if not username:
        raise ValueError("creator_data.username is required to resolve creator.")

    platform = (creator_data.get("platform") or "instagram").strip() or "instagram"
    followers = creator_data.get("followers")
    category = creator_data.get("category")
    verified = bool(creator_data.get("verified", False))

    creator = (
        session.query(Creator)
        .filter(Creator.username == username)
        .one_or_none()
    )

    if creator is None:
        creator = Creator(
            username=username,
            platform=platform,
            followers=followers,
            category=category,
            verified=verified,
        )
        session.add(creator)
    else:
        creator.platform = platform
        creator.followers = followers
        creator.category = category
        creator.verified = verified

    session.flush()
    return creator

