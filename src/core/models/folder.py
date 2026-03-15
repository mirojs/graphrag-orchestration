"""Folder hierarchy models.

Supports two folder types:
- "user": Standard user file management folders (unlimited depth).
- "analysis_result": Auto-created folders holding analysis run metadata.

Analysis-related fields (analysis_status, analysis_group_id, etc.) are only
meaningful for user folders that have been submitted for analysis.
"""

from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
import uuid


# Valid folder types
FolderType = Literal["user", "analysis_result"]

# Analysis lifecycle states
AnalysisStatus = Literal[
    "not_analyzed",  # Default — never analyzed
    "analyzing",     # Analysis in progress
    "analyzed",      # Analysis complete and up-to-date
    "stale",         # Files changed since last analysis
]


class FolderCreate(BaseModel):
    """Request model for creating a folder."""

    name: str = Field(..., description="Folder name")
    parent_folder_id: Optional[str] = Field(None, description="Parent folder ID (null for root)")
    folder_type: FolderType = Field("user", description="Folder type: 'user' or 'analysis_result'")


class FolderUpdate(BaseModel):
    """Request model for updating a folder."""

    name: Optional[str] = Field(None, description="New folder name")
    parent_folder_id: Optional[str] = Field(None, description="New parent folder ID")


class Folder(BaseModel):
    """Folder for organizing documents in hierarchical structure.

    User folders support unlimited nesting depth.  When a user folder is
    analyzed, analysis_status transitions through not_analyzed → analyzing →
    analyzed.  File mutations in an analyzed folder mark it 'stale'.

    Analysis-result folders are auto-created under a special "Analysis Results"
    root and link back to the Neo4j group via analysis_group_id.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., description="Folder name")
    group_id: str = Field(..., description="Group/partition ID")
    parent_folder_id: Optional[str] = Field(None, description="Parent folder ID (null for root)")
    folder_type: FolderType = Field("user", description="Folder type")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = Field(None, description="User who created the folder")

    # Analysis fields (only meaningful for folder_type="user" or "analysis_result")
    analysis_status: Optional[AnalysisStatus] = Field(None, description="Analysis lifecycle state")
    analysis_group_id: Optional[str] = Field(None, description="Neo4j group_id for this analysis")
    source_folder_id: Optional[str] = Field(None, description="Source user folder that was analyzed (for result folders)")
    analyzed_at: Optional[datetime] = Field(None, description="When analysis was last completed")
    file_count: Optional[int] = Field(None, description="Number of files in the analysis")
    entity_count: Optional[int] = Field(None, description="Number of entities extracted")
    community_count: Optional[int] = Field(None, description="Number of communities detected")

    # Progress tracking (populated during analysis)
    analysis_files_total: Optional[int] = Field(None, description="Total files to process in current analysis")
    analysis_files_processed: Optional[int] = Field(None, description="Files processed so far in current analysis")

    # Richer stats (populated on analysis completion)
    section_count: Optional[int] = Field(None, description="Number of sections extracted")
    sentence_count: Optional[int] = Field(None, description="Number of sentences extracted")
    relationship_count: Optional[int] = Field(None, description="Number of relationships extracted")

    # Error tracking
    analysis_error: Optional[str] = Field(None, description="Error message if analysis failed")

    @field_validator("created_at", "updated_at", "analyzed_at", mode="before")
    @classmethod
    def coerce_neo4j_datetime(cls, v):
        """Convert neo4j.time.DateTime to Python datetime."""
        if v is None:
            return v
        if hasattr(v, "to_native"):
            return v.to_native()
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "id": "folder-abc123",
                "name": "Contracts 2026",
                "group_id": "group-123",
                "parent_folder_id": None,
                "folder_type": "user",
                "analysis_status": "analyzed",
                "analysis_group_id": "folder-abc123",
                "created_by": "user-456",
            }
        }
