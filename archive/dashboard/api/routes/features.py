"""Feature tracker / roadmap endpoints — backs the dashboard Roadmap page."""

from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dashboard.api import feature_store

router = APIRouter()


@router.get("/")
def list_features():
    """All tracked features (done / in progress / pending)."""
    return feature_store.list_features()


@router.get("/stats")
def feature_stats():
    """Counts by status and category + overall % complete."""
    return feature_store.stats()


class NewFeature(BaseModel):
    title:    str
    category: str = "Other"
    status:   str = "pending"     # done | in_progress | pending
    priority: str = ""
    phase:    str = ""
    notes:    str = ""
    issue_ref: str = ""


@router.post("/")
def add_feature(f: NewFeature):
    if f.status not in ("done", "in_progress", "pending"):
        raise HTTPException(status_code=400, detail="status must be done | in_progress | pending")
    return feature_store.add_feature(
        title=f.title, category=f.category, status=f.status,
        priority=f.priority, phase=f.phase, notes=f.notes, issue_ref=f.issue_ref,
    )


class FeatureUpdate(BaseModel):
    title:    Optional[str] = None
    category: Optional[str] = None
    status:   Optional[str] = None
    priority: Optional[str] = None
    phase:    Optional[str] = None
    notes:    Optional[str] = None
    issue_ref: Optional[str] = None


@router.patch("/{fid}")
def update_feature(fid: str, upd: FeatureUpdate):
    if upd.status is not None and upd.status not in ("done", "in_progress", "pending"):
        raise HTTPException(status_code=400, detail="status must be done | in_progress | pending")
    item = feature_store.update_feature(fid, **upd.model_dump())
    if item is None:
        raise HTTPException(status_code=404, detail=f"feature '{fid}' not found")
    return item


@router.delete("/{fid}")
def delete_feature(fid: str):
    if not feature_store.delete_feature(fid):
        raise HTTPException(status_code=404, detail=f"feature '{fid}' not found")
    return {"deleted": fid}
