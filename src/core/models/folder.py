"""Folder hierarchy models."""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class FolderCreate(BaseModel):
    """Request model for creating a folder."""
    
    name: str = Field(..., description="Folder name")
    parent_folder_id: Optional[str] = Field(None, description="Parent folder ID (null for root)")


class FolderUpdate(BaseModel):
    """Request model for updating a folder."""
    
    name: Optional[str] = Field(None, description="New folder name")
    parent_folder_id: Optional[str] = Field(None, description="New parent folder ID")


class Folder(BaseModel):
    """Folder for organizing documents in hierarchical structure."""
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., description="Folder name")
    group_id: str = Field(..., description="Group/partition ID")
    parent_folder_id: Optional[str] = Field(None, description="Parent folder ID (null for root)")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = Field(None, description="User who created the folder")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "folder-abc123",
                "name": "Contracts 2026",
                "group_id": "group-123",
                "parent_folder_id": None,
                "created_by": "user-456"
            }
        }
