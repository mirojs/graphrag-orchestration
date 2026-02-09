"""
File Metadata Router (Cosmos DB)

Provides file metadata CRUD with e-tag concurrency and file locking.
Replaces the Quart file_metadata_bp blueprint.

The service class (FileMetadataService) is initialized in lifespan,
stored on app.state.file_metadata_service.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.api_gateway.middleware.auth import get_group_id, get_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/file_metadata", tags=["file-metadata"])


# ==================== Request Models ====================

class UpdateMetadataRequest(BaseModel):
    tags: Optional[List[str]] = None
    properties: Optional[Dict[str, Any]] = None
    folder_id: Optional[str] = None


class LockRequest(BaseModel):
    duration_seconds: int = 300


# ==================== Service Access ====================

def _get_service(request: Request):
    """Get the FileMetadataService from app state."""
    service = getattr(request.app.state, "file_metadata_service", None)
    if not service:
        raise HTTPException(status_code=400, detail="File metadata service not enabled")
    return service


# ==================== Endpoints ====================

@router.get("")
async def list_file_metadata(
    request: Request,
    folder_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100),
    continuation: Optional[str] = Query(default=None),
    group_id: str = Depends(get_group_id),
):
    """List files with metadata and e-tags."""
    service = _get_service(request)
    files, next_token = await service.list_files(
        group_id=group_id,
        folder_id=folder_id,
        limit=limit,
        continuation_token=continuation,
    )
    return {
        "files": [f.to_dict() for f in files],
        "continuation_token": next_token,
    }


@router.get("/{filename}")
async def get_file_metadata(
    request: Request,
    filename: str,
    group_id: str = Depends(get_group_id),
):
    """Get file metadata with e-tag in response header."""
    service = _get_service(request)
    metadata = await service.get_metadata(filename, group_id)
    if not metadata:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    response = JSONResponse(content=metadata.to_dict())
    if metadata._etag:
        response.headers["ETag"] = metadata._etag
    return response


@router.put("/{filename}")
async def update_file_metadata(
    request: Request,
    filename: str,
    body: UpdateMetadataRequest,
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
    if_match: Optional[str] = Header(default=None),
):
    """
    Update file metadata with e-tag concurrency control.
    Send If-Match header with e-tag from previous GET.
    """
    service = _get_service(request)

    metadata = await service.get_metadata(filename, group_id)
    if not metadata:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    if body.tags is not None:
        metadata.tags = body.tags
    if body.properties is not None:
        metadata.properties = body.properties
    if body.folder_id is not None:
        metadata.folder_id = body.folder_id

    try:
        updated = await service.update_metadata(metadata, user_id, if_match)
        response = JSONResponse(content=updated.to_dict())
        if updated._etag:
            response.headers["ETag"] = updated._etag
        return response
    except Exception as e:
        error_name = type(e).__name__
        if "ETagMismatch" in error_name:
            raise HTTPException(status_code=412, detail=str(e))
        elif "FileLock" in error_name:
            raise HTTPException(status_code=423, detail=str(e))
        raise


@router.post("/{filename}/lock")
async def lock_file(
    request: Request,
    filename: str,
    body: LockRequest = LockRequest(),
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
    if_match: Optional[str] = Header(default=None),
):
    """Acquire an edit lock on a file."""
    service = _get_service(request)

    try:
        metadata = await service.acquire_lock(
            filename, group_id, user_id, body.duration_seconds, if_match
        )
        response = JSONResponse(content={
            "message": "Lock acquired",
            "locked_by": metadata.locked_by,
            "expires_at": metadata.lock_expires_at,
        })
        if metadata._etag:
            response.headers["ETag"] = metadata._etag
        return response
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    except Exception as e:
        error_name = type(e).__name__
        if "FileLock" in error_name:
            raise HTTPException(status_code=423, detail=str(e))
        elif "ETagMismatch" in error_name:
            raise HTTPException(status_code=412, detail=str(e))
        raise


@router.delete("/{filename}/lock")
async def unlock_file(
    request: Request,
    filename: str,
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """Release an edit lock on a file."""
    service = _get_service(request)

    try:
        await service.release_lock(filename, group_id, user_id)
        return {"message": "Lock released"}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    except Exception as e:
        if "FileLock" in type(e).__name__:
            raise HTTPException(status_code=423, detail=str(e))
        raise
