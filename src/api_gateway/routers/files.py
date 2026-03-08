"""
File Operations Router

Provides endpoints for file upload, deletion, renaming, moving, copying, and listing.
Uses ADLS Gen2 blob storage via Azure identity credentials.
Replaces the Quart file operation endpoints.
"""

import logging
import mimetypes
import asyncio
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, UploadFile, File as FastAPIFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from src.api_gateway.middleware.auth import get_group_id, get_user_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["files"])


# ==================== Request Models ====================

class DeleteFileRequest(BaseModel):
    filename: str


class BulkDeleteRequest(BaseModel):
    filenames: List[str]


class RenameFileRequest(BaseModel):
    old_filename: str
    new_filename: str


class MoveFileRequest(BaseModel):
    filename: str
    source_folder: Optional[str] = None
    dest_folder: Optional[str] = None


class CopyFileRequest(BaseModel):
    filename: str
    dest_filename: str


# ==================== Lazy Service Access ====================


def _get_blob_manager(request: Request):
    """Get the ADLS blob manager from app state."""
    manager = getattr(request.app.state, "user_blob_manager", None)
    if not manager:
        raise HTTPException(status_code=400, detail="File upload is not enabled")
    return manager


def _get_global_blob_manager(request: Request):
    """Get the global blob manager from app state (read-only, for shared docs)."""
    return getattr(request.app.state, "global_blob_manager", None)


def _get_ingester(request: Request):
    """Get the file ingester from app state (optional, for search index updates)."""
    return getattr(request.app.state, "ingester", None)


def _get_doc_sync(request: Request):
    """Get the DocumentSyncService from app state (optional, for Neo4j sync)."""
    return getattr(request.app.state, "document_sync_service", None)


# ==================== Upload Validation ====================

MAX_UPLOAD_SIZE_MB = 50
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024

ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    ".txt", ".csv", ".md", ".html", ".htm",
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp",
    ".json", ".xml",
}


def _sanitize_filename(filename: str) -> str:
    """Strip path components and disallow dangerous characters."""
    import os
    import re
    name = os.path.basename(filename or "upload")
    # Remove any non-alphanumeric characters except .-_ and spaces
    name = re.sub(r'[^\w\s.\-]', '_', name)
    return name or "upload"


def _validate_upload(f: UploadFile) -> None:
    """Validate file extension and size before upload."""
    import os
    name = _sanitize_filename(f.filename or "")
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed. Supported: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    # Check Content-Length header if available (not reliable but fast reject)
    if f.size is not None and f.size > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({f.size / 1024 / 1024:.1f} MB). Maximum: {MAX_UPLOAD_SIZE_MB} MB"
        )


# ==================== Endpoints ====================

@router.post("/upload")
async def upload_files(
    request: Request,
    background_tasks: BackgroundTasks,
    file: List[UploadFile] = FastAPIFile(...),
    folder_id: Optional[str] = Form(None),
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """Upload one or more files. Supports multi-file upload.
    
    If folder_id is provided, documents are indexed into that folder's
    root folder partition (isolated knowledge graph). Blob storage path
    remains {auth_group_id}/{filename}.
    """
    from src.api_gateway.services.folder_resolver import resolve_neo4j_group_id

    blob_manager = _get_blob_manager(request)
    ingester = _get_ingester(request)
    doc_sync = _get_doc_sync(request)
    neo4j_gid = await resolve_neo4j_group_id(group_id, folder_id)

    results = []
    for f in file:
        try:
            _validate_upload(f)
            safe_filename = _sanitize_filename(f.filename)
            # Blob storage uses auth_group_id (security boundary)
            file_url = await blob_manager.upload_blob(f, safe_filename, group_id)
            if ingester:
                from prepdocslib.listfilestrategy import File as IngesterFile

                await ingester.add_file(
                    IngesterFile(content=f, url=file_url, acls={"oids": [user_id]}),
                    user_oid=group_id,
                )
            results.append({"filename": safe_filename, "status": "success", "url": file_url})
        except Exception as e:
            logger.error("Error uploading file %s: %s", f.filename, e)
            results.append({"filename": f.filename, "status": "failed", "error": str(e)})

    # Trigger background indexing with neo4j_gid (folder partition)
    indexing_queued = False
    if doc_sync:
        for r in results:
            if r["status"] == "success":
                background_tasks.add_task(
                    doc_sync.on_file_uploaded, neo4j_gid, r["filename"], r["url"], user_id
                )
                indexing_queued = True

    success_count = sum(1 for r in results if r["status"] == "success")
    if success_count == len(results):
        return JSONResponse({"message": f"{len(results)} file(s) uploaded successfully", "results": results, "indexing_queued": indexing_queued})
    elif success_count > 0:
        return JSONResponse(
            {"message": f"{success_count}/{len(results)} files uploaded", "results": results, "indexing_queued": indexing_queued},
            status_code=207,
        )
    else:
        return JSONResponse(
            {"message": "All files failed to upload", "results": results, "status": "failed"},
            status_code=500,
        )


@router.post("/delete_uploaded")
async def delete_uploaded(
    request: Request,
    body: DeleteFileRequest,
    background_tasks: BackgroundTasks,
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """Delete a single file by filename."""
    blob_manager = _get_blob_manager(request)
    ingester = _get_ingester(request)

    await blob_manager.remove_blob(body.filename, group_id)
    if ingester:
        await ingester.remove_file(body.filename, group_id)

    # Delete graph data in background
    doc_sync = _get_doc_sync(request)
    if doc_sync:
        background_tasks.add_task(doc_sync.on_file_deleted, group_id, body.filename)

    return {"message": f"File {body.filename} deleted successfully"}


@router.post("/delete_uploaded_bulk")
async def delete_uploaded_bulk(
    request: Request,
    body: BulkDeleteRequest,
    background_tasks: BackgroundTasks,
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """Delete multiple files by filename list."""
    if not body.filenames:
        raise HTTPException(status_code=400, detail="No filenames provided")

    blob_manager = _get_blob_manager(request)
    ingester = _get_ingester(request)

    results = []
    successful_filenames = []
    for filename in body.filenames:
        try:
            await blob_manager.remove_blob(filename, group_id)
            if ingester:
                await ingester.remove_file(filename, group_id)
            results.append({"filename": filename, "status": "success"})
            successful_filenames.append(filename)
        except Exception as e:
            logger.error("Error deleting file %s: %s", filename, e)
            results.append({"filename": filename, "status": "failed", "error": str(e)})

    # Delete graph data in background for successfully deleted files
    doc_sync = _get_doc_sync(request)
    if doc_sync and successful_filenames:
        background_tasks.add_task(
            doc_sync.on_file_deleted_bulk, group_id, successful_filenames
        )

    success_count = len(successful_filenames)
    if success_count == len(results):
        return JSONResponse({"message": f"{len(results)} file(s) deleted successfully", "results": results})
    elif success_count > 0:
        return JSONResponse(
            {"message": f"{success_count}/{len(results)} files deleted", "results": results},
            status_code=207,
        )
    else:
        return JSONResponse(
            {"message": "All files failed to delete", "results": results, "status": "failed"},
            status_code=500,
        )


@router.get("/list_uploaded")
async def list_uploaded(
    request: Request,
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """List the uploaded documents for the current group."""
    blob_manager = _get_blob_manager(request)
    try:
        async with asyncio.timeout(30):
            files = await blob_manager.list_blobs(group_id)
    except TimeoutError:
        logger.error("list_uploaded_timeout for group_id=%s", group_id)
        raise HTTPException(status_code=504, detail="File listing timed out")
    except Exception as e:
        logger.exception("Failed to list files for group %s: %s", group_id, e)
        raise HTTPException(status_code=502, detail=f"Storage error: {type(e).__name__}: {e}")
    return files


@router.get("/list_global")
async def list_global(request: Request):
    """List shared/public documents from the global blob container (read-only)."""
    global_blob_manager = _get_global_blob_manager(request)
    if global_blob_manager is None:
        return []
    try:
        async with asyncio.timeout(10):
            container_client = global_blob_manager.blob_service_client.get_container_client(
                global_blob_manager.container
            )
            files = []
            async for blob in container_client.list_blobs():
                # Only top-level files, skip subdirectories
                if "/" not in blob.name:
                    files.append(blob.name)
            return files
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Global file listing timed out")
    except Exception as e:
        # Gracefully handle missing container (e.g. B2C deployments without shared library)
        error_name = type(e).__name__
        if "ResourceNotFound" in error_name or "ContainerNotFound" in str(e):
            logger.info("Global blob container '%s' not found — shared library disabled", global_blob_manager.container)
            return []
        logger.exception("Failed to list global files: %s", e)
        raise HTTPException(status_code=502, detail=f"Storage error: {error_name}: {e}")


@router.post("/rename_uploaded")
async def rename_uploaded(
    request: Request,
    body: RenameFileRequest,
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """Rename a file and update Neo4j with alias mapping."""
    if body.old_filename == body.new_filename:
        raise HTTPException(status_code=400, detail="Old and new filenames are the same")

    blob_manager = _get_blob_manager(request)
    ingester = _get_ingester(request)
    doc_sync = _get_doc_sync(request)

    try:
        # Step 1: Rename in ADLS
        new_url = await blob_manager.rename_blob(body.old_filename, body.new_filename, group_id)

        # Step 2: Update search index (if available)
        if ingester:
            await ingester.remove_file(body.old_filename, group_id)

        # Step 3: Update Neo4j directly via DocumentSyncService
        rename_result = None
        if doc_sync:
            rename_result = await doc_sync.on_file_renamed(
                group_id, body.old_filename, body.new_filename, new_url
            )

        return {
            "message": f"File renamed from {body.old_filename} to {body.new_filename}",
            "new_url": new_url,
            "neo4j_updated": rename_result is not None and rename_result.get("success", False),
            "aliases": rename_result.get("aliases", []) if rename_result else [],
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {body.old_filename}")
    except FileExistsError:
        raise HTTPException(status_code=409, detail=f"Destination file already exists: {body.new_filename}")


@router.post("/move_uploaded")
async def move_uploaded(
    request: Request,
    body: MoveFileRequest,
    background_tasks: BackgroundTasks,
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """Move a file to a different folder."""
    blob_manager = _get_blob_manager(request)

    try:
        new_url = await blob_manager.move_blob(body.filename, body.source_folder, body.dest_folder, group_id)

        # Update Document.source in Neo4j in background
        doc_sync = _get_doc_sync(request)
        if doc_sync:
            background_tasks.add_task(
                doc_sync.on_file_moved, group_id, body.filename, new_url
            )

        return {
            "message": f"File {body.filename} moved to {body.dest_folder or 'root'}",
            "new_url": new_url,
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {body.filename}")
    except FileExistsError:
        raise HTTPException(status_code=409, detail="File already exists in destination")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/copy_uploaded")
async def copy_uploaded(
    request: Request,
    body: CopyFileRequest,
    background_tasks: BackgroundTasks,
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """Copy a file within the group's directory."""
    if body.filename == body.dest_filename:
        raise HTTPException(status_code=400, detail="Source and destination filenames are the same")

    blob_manager = _get_blob_manager(request)

    try:
        new_url = await blob_manager.copy_blob(body.filename, body.dest_filename, group_id)

        # Trigger indexing for the copied file in background
        doc_sync = _get_doc_sync(request)
        if doc_sync:
            background_tasks.add_task(
                doc_sync.on_file_copied, group_id, body.dest_filename, new_url
            )

        return {
            "message": f"File copied from {body.filename} to {body.dest_filename}",
            "new_url": new_url,
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {body.filename}")
    except FileExistsError:
        raise HTTPException(status_code=409, detail=f"Destination file already exists: {body.dest_filename}")


@router.get("/content/{path:path}")
async def content_file(
    request: Request,
    path: str,
    source: Optional[str] = None,
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """
    Serve content files (citations/PDFs) from blob storage.

    When ``source`` query param is provided (a full blob URL), proxy directly
    from that URL.  Otherwise fall back to user/global blob manager lookups.
    """
    filename = path.split("/")[-1]

    # --- Primary path: proxy from the original source blob URL ---
    if source:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(source)
            if parsed.hostname and parsed.hostname.endswith(".blob.core.windows.net"):
                import httpx
                async with httpx.AsyncClient() as client:
                    resp = await client.get(source, follow_redirects=True, timeout=30.0)
                    if resp.status_code == 200:
                        content_type = resp.headers.get("content-type") or mimetypes.guess_type(path)[0] or "application/octet-stream"
                        return StreamingResponse(
                            iter([resp.content]),
                            media_type=content_type,
                            headers={"Content-Disposition": f'inline; filename="{filename}"'},
                        )
                    logger.debug("Source URL returned %s for %s", resp.status_code, source)
            else:
                logger.warning("Rejected non-Azure source URL: %s", parsed.hostname)
        except Exception as e:
            logger.debug("Source URL proxy failed for %s: %s", source, e)

    # --- Fallback: blob manager lookups (user-uploaded files) ---
    global_blob_manager = getattr(request.app.state, "global_blob_manager", None)
    user_blob_manager = getattr(request.app.state, "user_blob_manager", None)

    # Try user storage first (files stored as {group_id}/{filename})
    if user_blob_manager is not None:
        try:
            blob_data = await user_blob_manager.download_blob(path, group_id)
            if blob_data:
                content_bytes, props = blob_data
                content_type = props.get("content_settings", {}).get("content_type") or mimetypes.guess_type(path)[0] or "application/octet-stream"
                return StreamingResponse(
                    iter([content_bytes]),
                    media_type=content_type,
                    headers={"Content-Disposition": f'inline; filename="{filename}"'},
                )
        except Exception as e:
            logger.debug("User blob manager failed for %s: %s", path, e)

    # Fall back to global storage (flat path, no group_id prefix)
    if global_blob_manager is not None:
        try:
            blob_data = await global_blob_manager.download_blob(path)
            if blob_data:
                content_bytes, props = blob_data
                ct = props.get("content_settings", {}).get("content_type") if isinstance(props, dict) else None
                content_type = ct or mimetypes.guess_type(path)[0] or "application/octet-stream"
                return StreamingResponse(
                    iter([content_bytes]),
                    media_type=content_type,
                    headers={"Content-Disposition": f'inline; filename="{filename}"'},
                )
        except Exception as e:
            logger.debug("Global blob manager failed for %s: %s", path, e)

    raise HTTPException(status_code=404, detail=f"Content not found: {path}")
