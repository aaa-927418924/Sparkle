"""Pydantic request/response schemas."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_done: Optional[bool] = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str] = None
    is_done: bool = False
    created_at: str


class CategoryCreate(BaseModel):
    name: str


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class TagCreate(BaseModel):
    name: str


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class ClipCreate(BaseModel):
    url: str
    title: Optional[str] = None
    thumbnail_url: Optional[str] = None
    comment: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = []
    clip_type: Optional[str] = None  # "url" (default) or "local"
    file_ref: Optional[str] = None   # "reference" or "copy"
    project_id: Optional[int] = None


class UrlMetadataOut(BaseModel):
    url: str
    title: Optional[str] = None
    thumbnail_url: Optional[str] = None


class ClipUpdate(BaseModel):
    title: Optional[str] = None
    comment: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    thumbnail_url: Optional[str] = None
    project_id: Optional[int] = None
    project_ids: Optional[List[int]] = None


class ClipOut(BaseModel):
    id: int
    url: str
    title: Optional[str] = None
    thumbnail_url: Optional[str] = None
    comment: Optional[str] = None
    category_id: Optional[int] = None
    is_favorite: bool = False
    created_at: str
    clip_type: Optional[str] = "url"
    file_ref: Optional[str] = None
    file_size: Optional[int] = None
    is_folder: bool = False
    project_id: Optional[int] = None
    project_ids: List[int] = []
    tags: List[TagOut] = []


class LightClipOut(BaseModel):
    id: int
    title: Optional[str] = None
    url: str
    thumbnail_url: Optional[str] = None
    comment: Optional[str] = None
    clip_type: Optional[str] = "url"
    file_ref: Optional[str] = None
    is_folder: bool = False
    project_id: Optional[int] = None
    project_ids: List[int] = []
    tags: List[TagOut] = []


class TaskCreate(BaseModel):
    title: str
    clip_id: Optional[int] = None
    due_date: Optional[str] = None
    priority: Optional[int] = None
    project_id: Optional[int] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    is_done: Optional[bool] = None
    clip_id: Optional[int] = None
    due_date: Optional[str] = None
    priority: Optional[int] = None
    project_id: Optional[int] = None


class TaskOut(BaseModel):
    id: int
    title: str
    is_done: bool = False
    clip_id: Optional[int] = None
    due_date: Optional[str] = None
    priority: Optional[int] = None
    created_at: str
    project_id: Optional[int] = None
    clip: Optional[LightClipOut] = None
    notes: List["LightNoteOut"] = []


class LightNoteOut(BaseModel):
    id: int
    title: str


class LightTaskOut(BaseModel):
    id: int
    title: str
    is_done: bool = False


class NoteCreate(BaseModel):
    title: str
    body: Optional[str] = None
    clip_ids: List[int] = []
    task_id: Optional[int] = None
    task_ids: List[int] = []
    project_id: Optional[int] = None
    project_ids: List[int] = []


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    expected_updated_at: Optional[str] = None
    clip_ids: Optional[List[int]] = None
    task_id: Optional[int] = None
    task_ids: Optional[List[int]] = None
    project_id: Optional[int] = None
    project_ids: Optional[List[int]] = None


class NoteOut(BaseModel):
    id: int
    title: str
    body: Optional[str] = None
    is_done: bool = False
    completed_at: Optional[str] = None
    created_at: str
    updated_at: str
    clips: List[LightClipOut] = []
    task_id: Optional[int] = None
    task: Optional[LightTaskOut] = None
    task_ids: List[int] = []
    project_id: Optional[int] = None
    project_ids: List[int] = []


class ProfileNameUpdate(BaseModel):
    name: str = Field(..., max_length=15)


class ProfileIconUpdate(BaseModel):
    data_url: str


class ClipboardImage(BaseModel):
    data_url: str


class BackupExportPayload(BaseModel):
    browser_settings: dict = {}


class ProfilePickAdd(BaseModel):
    clip_id: int


class ProfileOut(BaseModel):
    username: str
    icon_url: Optional[str] = None
    total_saved: int = 0
    first_used_at: Optional[str] = None
    days_since_first: int = 0
    saved_last_7_days: int = 0
    picks: List[ClipOut] = []
