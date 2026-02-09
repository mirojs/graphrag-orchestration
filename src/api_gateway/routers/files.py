"""
File Operations Router

Provides endpoints for file upload, deletion, renaming, moving, copying, and listing.
Uses ADLS Gen2 blob storage via Azure identity credentials.
Replaces the Quart file operation endpoints.
"""

import logging
import mimetypes
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File as FastAPIFile
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


def _get_ingester(request: Request):
    """Get the file ingester from app state (optional, for search index updates)."""
    return getattr(request.app.state, "ingester", None)


def _get_graphrag_client(request: Request):
    """Get the GraphRAG client from app state (optional)."""
    return getattr(request.app.state, "graphrag_client", None)


# ==================== Endpoints ====================

@router.post("/upload")
async def upload_files(
    request: Request,
    file: List[UploadFile] = FastAPIFile(...),
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """Upload one or more files. Supports multi-file upload."""
    blob_manager = _get_blob_manager(request)
    ingester = _get_ingester(request)

    results = []
    for f in file:
        try:
            file_url = await blob_manager.upload_blob(f, f.filename, user_id)
            if ingester:
                from prepdocslib.listfilestrategy import File as IngesterFile

                await ingester.add_file(
                    IngesterFile(content=f, url=file_url, acls={"oids": [user_id]}),
                    user_oid=user_id,
                )
            results.append({"filename": f.filename, "status": "success"})
        except Exception as e:
            logger.error("Error uploading file %s: %s", f.filename, e)
            results.append({"filename": f.filename, "status": "failed", "error": str(e)})

    success_count = sum(1 for r in results if r["status"] == "success")
    if success_count == len(results):
        return JSONResponse({"message": f"{len(results)} file(s) uploaded successfully", "results": results})
    elif success_count > 0:
        return JSONResponse(
            {"message": f"{success_count}/{len(results)} files uploaded", "results": results},
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
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """Delete a single file by filename."""
    blob_manager = _get_blob_manager(request)
    ingester = _get_ingester(request)

    await blob_manager.remove_blob(body.filename, user_id)
    if ingester:
        await ingester.remove_file(body.filename, user_id)

    return {"message": f"File {body.filename} deleted successfully"}


@router.post("/delete_uploaded_bulk")
async def delete_uploaded_bulk(
    request: Request,
    body: BulkDeleteRequest,
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """Delete multiple files by filename list."""
    if not body.filenames:
        raise HTTPException(status_code=400, detail="No filenames provided")

    blob_manager = _get_blob_manager(request)
    ingester = _get_ingester(request)

    results = []
    for filename in body.filenames:
        try:
            await blob_manager.remove_blob(filename, user_id)
            if ingester:
                await ingester.remove_file(filename, user_id)
            results.append({"filename": filename, "status": "success"})
        except Exception as e:
            logger.error("Error deleting file %s: %s", filename, e)
            results.append({"filename": filename, "status": "failed", "error": str(e)})

    success_count = sum(1 for r in results if r["status"] == "success")
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
    """List the uploaded documents for the current user."""
    blob_manager = _get_blob_manager(request)
    files = await blob_manager.list_blobs(user_id)
    return files


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
    graphrag_client = _get_graphrag_client(request)

    try:
        # Step 1: Rename in ADLS
        new_url = await blob_manager.rename_blob(body.old_filename, body.new_filename, user_id)

        # Step 2: Update search index (if available)
        if ingester:
            await ingester.remove_file(body.old_filename, user_id)

        # Step 3: Update Neo4j via GraphRAG (if available)
        graphrag_result = None
        if graphrag_client:
            try:
                graphrag_result = await graphrag_client.rename_document(
                    group_id=group_id,
                    old_document_id=body.old_filename,
                    new_document_id=body.new_filename,
                    new_title=body.new_filename,
                    new_source=new_url,
                    keep_alias=True,
                )
            except Exception as e:
                logger.warning("Failed to update Neo4j on rename: %s", e)

        return {
            "message": f"File renamed from {body.old_filename} to {body.new_filename}",
            "new_url": new_url,
            "neo4j_updated": graphrag_result is not None and graphrag_result.get("success", False),
            "aliases": graphrag_result.get("aliases", []) if graphrag_result else [],
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {body.old_filename}")
    except FileExistsError:
        raise HTTPException(status_code=409, detail=f"Destination file already exists: {body.new_filename}")


@router.post("/move_uploaded")
async def move_uploaded(
    request: Request,
    body: MoveFileRequest,
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """Move a file to a different folder."""
    blob_manager = _get_blob_manager(request)

    try:
        new_url = await blob_manager.move_blob(body.filename, body.source_folder, body.dest_folder, user_id)
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
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """Copy a file within the user's directory."""
    if body.filename == body.dest_filename:
        raise HTTPException(status_code=400, detail="Source and destination filenames are the same")

    blob_manager = _get_blob_manager(request)

    try:
        new_url = await blob_manager.copy_blob(body.filename, body.dest_filename, user_id)
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
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """
    Serve content files (citations/PDFs) from blob storage.

    Streams the blob content back to the client.
    """
    global_blob_manager = getattr(request.app.state, "global_blob_manager", None)
    user_blob_manager = getattr(request.app.state, "user_blob_manager", None)

    # Try user storage first, then global
    for manager in [user_blob_manager, global_blob_manager]:
        if manager is None:
            continue
        try:
            blob_data = await manager.download_blob(path, user_id)
            if blob_data:
                content_type, _ = mimetypes.guess_type(path)
                return StreamingResponse(
                    iter([blob_data]),
                    media_type=content_type or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{path.split("/")[-1]}"'},
                )
        except Exception:
            continue

    raise HTTPException(status_code=404, detail=f"Content not found: {path}")
