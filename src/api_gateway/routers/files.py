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
    folder: Optional[str] = None
    folder_id: Optional[str] = None


class BulkDeleteRequest(BaseModel):
    filenames: List[str]
    folder: Optional[str] = None
    folder_id: Optional[str] = None


class RenameFileRequest(BaseModel):
    old_filename: str
    new_filename: str
    folder: Optional[str] = None
    folder_id: Optional[str] = None


class MoveFileRequest(BaseModel):
    filename: str
    source_folder: Optional[str] = None
    dest_folder: Optional[str] = None
    source_folder_id: Optional[str] = None
    dest_folder_id: Optional[str] = None


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
    # Azure DI native support
    ".pdf", ".docx", ".xlsx", ".xls", ".pptx", ".html", ".htm",
    # Images — Azure DI OCR
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp",
    # Converted at upload: .txt→.pdf, .csv→.xlsx, .htm→.html
    ".txt", ".csv",
    # Sidecars (.result.json for pre-analyzed DI content)
    ".json",
}

# Extensions that are converted to DI-compatible formats at upload time.
# The original file is replaced with the converted version in blob storage.
_UPLOAD_CONVERSIONS = {
    ".txt": ".pdf",
    ".csv": ".xlsx",
    ".htm": ".html",
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


# ==================== Upload-time Format Conversion ====================

def _convert_txt_to_pdf(raw_bytes: bytes, original_filename: str) -> bytes:
    """Convert plain text content to a PDF document."""
    from fpdf import FPDF

    text = raw_bytes.decode("utf-8", errors="replace")
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    # multi_cell moves x; reset to left margin for each line
    for line in text.split("\n"):
        if line.strip():
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(0, 5, line)
        else:
            pdf.ln(5)
    return bytes(pdf.output())


def _convert_csv_to_xlsx(raw_bytes: bytes, original_filename: str) -> bytes:
    """Convert CSV content to an Excel XLSX file."""
    import csv as csv_mod
    import io
    from openpyxl import Workbook

    text = raw_bytes.decode("utf-8", errors="replace")
    reader = csv_mod.reader(io.StringIO(text))

    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    for row in reader:
        ws.append(row)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _maybe_convert_upload(f: UploadFile) -> tuple:
    """Convert the upload if its extension requires conversion.

    Returns (new_filename, content_bytes, was_converted).
    If no conversion is needed, returns (original_filename, original_bytes, False).
    """
    import os
    safe_name = _sanitize_filename(f.filename)
    ext = os.path.splitext(safe_name)[1].lower()
    raw = await f.read()

    target_ext = _UPLOAD_CONVERSIONS.get(ext)
    if not target_ext:
        # Reset file position for downstream consumers
        await f.seek(0)
        return safe_name, raw, False

    base = os.path.splitext(safe_name)[0]
    new_name = base + target_ext

    if ext == ".txt":
        converted = _convert_txt_to_pdf(raw, safe_name)
    elif ext == ".csv":
        converted = _convert_csv_to_xlsx(raw, safe_name)
    elif ext == ".htm":
        # Same content, just rename extension
        converted = raw
    else:
        await f.seek(0)
        return safe_name, raw, False

    logger.info(
        "Converted upload %s → %s (%d → %d bytes)",
        safe_name, new_name, len(raw), len(converted),
    )
    return new_name, converted, True


# ==================== Folder Helpers ====================


async def _resolve_folder_name(group_id: str, folder_id: str) -> str | None:
    """Resolve a folder UUID to its display name via Neo4j.

    Returns the folder name, or None if the folder doesn't exist.
    Deprecated — prefer _resolve_folder_path for hierarchical blob storage.
    """
    try:
        from src.worker.services import GraphService
        graph_service = GraphService()
        if not graph_service.driver:
            logger.warning("Neo4j unavailable — cannot resolve folder name for %s", folder_id)
            return None
        with graph_service.driver.session() as session:
            result = session.run(
                "MATCH (f:Folder {id: $fid, group_id: $gid}) RETURN f.name AS name",
                fid=folder_id, gid=group_id,
            )
            record = result.single()
            return record["name"] if record else None
    except Exception as e:
        logger.warning("Failed to resolve folder name for %s: %s", folder_id, e)
        return None


async def _resolve_folder_path(group_id: str, folder_id: str) -> str | None:
    """Resolve a folder UUID to its full hierarchical path via Neo4j.

    Walks the SUBFOLDER_OF chain to build a path like
    "insurance_claims_review/input_docs" for ADLS Gen2 blob storage.
    """
    try:
        from src.worker.services import GraphService
        graph_service = GraphService()
        if not graph_service.driver:
            logger.warning("Neo4j unavailable — cannot resolve folder path for %s", folder_id)
            return None
        with graph_service.driver.session() as session:
            result = session.run(
                """
                MATCH (f:Folder {id: $fid, group_id: $gid})
                OPTIONAL MATCH path = (f)-[:SUBFOLDER_OF*0..]->(root:Folder)
                WHERE NOT (root)-[:SUBFOLDER_OF]->()
                WITH f, path
                ORDER BY length(path) DESC
                LIMIT 1
                WITH [n IN nodes(path) | n.name] AS names
                RETURN reduce(p = '', i IN reverse(names) |
                    CASE WHEN p = '' THEN i ELSE p + '/' + i END
                ) AS folder_path
                """,
                fid=folder_id, gid=group_id,
            )
            record = result.single()
            return record["folder_path"] if record else None
    except Exception as e:
        logger.warning("Failed to resolve folder path for %s: %s", folder_id, e)
        return None


async def _resolve_folder(group_id: str, folder: str | None, folder_id: str | None) -> str | None:
    """Resolve the blob storage folder path from folder_id (preferred) or folder name."""
    if folder_id:
        return await _resolve_folder_path(group_id, folder_id)
    return folder


async def _folder_is_analyzed(group_id: str, folder_id: str | None) -> bool:
    """Check whether a folder (or any of its ancestors) has been analyzed.

    If folder_id is None (root / unfiled upload), returns False so that
    uploads to the root area are never auto-indexed.
    """
    if not folder_id:
        return False
    try:
        from src.worker.services import GraphService
        driver = GraphService().driver
        if not driver:
            return False
        with driver.session() as session:
            # Walk up the folder tree looking for an analyzed ancestor
            result = session.run(
                """
                MATCH (f:Folder {id: $fid, group_id: $gid})
                OPTIONAL MATCH path = (f)-[:SUBFOLDER_OF*0..]->(ancestor:Folder)
                WHERE ancestor.analysis_status IN ['analyzed', 'stale']
                RETURN count(ancestor) > 0 AS has_analyzed
                """,
                fid=folder_id, gid=group_id,
            )
            record = result.single()
            return bool(record and record["has_analyzed"])
    except Exception as e:
        logger.warning("_folder_is_analyzed check failed for %s: %s", folder_id, e)
        return False


async def _mark_folder_stale(group_id: str, folder_id: str) -> None:
    """Mark a folder as 'stale' (files changed since last analysis)."""
    try:
        from src.worker.services import GraphService
        driver = GraphService().driver
        if not driver:
            return
        with driver.session() as session:
            session.run(
                """
                MATCH (f:Folder {id: $fid, group_id: $gid})
                WHERE f.analysis_status = 'analyzed'
                SET f.analysis_status = 'stale', f.updated_at = datetime()
                """,
                fid=folder_id, gid=group_id,
            )
    except Exception as e:
        logger.warning("_mark_folder_stale failed for %s: %s", folder_id, e)


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
    root folder partition (isolated knowledge graph) and stored under
    the folder's blob prefix: ``{group_id}/{folder_name}/{filename}``.
    """
    from src.api_gateway.services.folder_resolver import resolve_neo4j_group_id

    blob_manager = _get_blob_manager(request)
    ingester = _get_ingester(request)
    doc_sync = _get_doc_sync(request)
    neo4j_gid = await resolve_neo4j_group_id(group_id, folder_id)

    # Resolve folder path for blob storage (hierarchical, e.g. "parent/child")
    folder_name: str | None = None
    if folder_id:
        folder_name = await _resolve_folder_path(group_id, folder_id)
        if not folder_name:
            logger.warning("Could not resolve folder_id=%s — uploading to root", folder_id)

    results = []
    for f in file:
        try:
            _validate_upload(f)
            # Convert format if needed (.txt→.pdf, .csv→.xlsx, .htm→.html)
            converted_name, converted_bytes, was_converted = await _maybe_convert_upload(f)

            if was_converted:
                import io
                blob_file = io.BytesIO(converted_bytes)
                file_url = await blob_manager.upload_blob(blob_file, converted_name, group_id, folder=folder_name)
            else:
                file_url = await blob_manager.upload_blob(f, converted_name, group_id, folder=folder_name)

            if ingester:
                from prepdocslib.listfilestrategy import File as IngesterFile

                await ingester.add_file(
                    IngesterFile(content=f, url=file_url, acls={"oids": [user_id]}),
                    user_oid=group_id,
                )
            results.append({"filename": converted_name, "status": "success", "url": file_url})
        except Exception as e:
            logger.error("Error uploading file %s: %s", f.filename, e)
            results.append({"filename": f.filename, "status": "failed", "error": str(e)})

    # Trigger background indexing ONLY if the target folder is already analyzed.
    # For un-analyzed folders, files are just stored in blob — no graph indexing.
    indexing_queued = False
    if doc_sync:
        should_index = await _folder_is_analyzed(group_id, folder_id)
        if should_index:
            for r in results:
                if r["status"] == "success":
                    background_tasks.add_task(
                        doc_sync.on_file_uploaded, neo4j_gid, r["filename"], r["url"], user_id
                    )
                    indexing_queued = True
            # Mark folder stale since new files were added after analysis
            if indexing_queued and folder_id:
                background_tasks.add_task(_mark_folder_stale, group_id, folder_id)

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

    folder = await _resolve_folder(group_id, body.folder, body.folder_id)
    await blob_manager.remove_blob(body.filename, group_id, folder=folder)
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

    folder = await _resolve_folder(group_id, body.folder, body.folder_id)
    results = []
    successful_filenames = []
    for filename in body.filenames:
        try:
            await blob_manager.remove_blob(filename, group_id, folder=folder)
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
    folder: Optional[str] = None,
    folder_id: Optional[str] = None,
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """List uploaded documents, optionally scoped to a folder.
    
    Args:
        folder: Folder name/path to scope listing. If omitted, lists root-level files.
        folder_id: Folder UUID — resolved server-side to the full hierarchical path.
                   Takes precedence over ``folder`` when both are provided.
    """
    blob_manager = _get_blob_manager(request)
    resolved_folder = folder
    if folder_id:
        resolved_folder = await _resolve_folder_path(group_id, folder_id)
        if not resolved_folder:
            logger.warning("Could not resolve folder_id=%s for listing — falling back to folder param", folder_id)
            resolved_folder = folder
    try:
        async with asyncio.timeout(30):
            files = await blob_manager.list_blobs(group_id, folder=resolved_folder)
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
        folder = await _resolve_folder(group_id, body.folder, body.folder_id)
        new_url = await blob_manager.rename_blob(body.old_filename, body.new_filename, group_id, folder=folder)

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
        src_folder = await _resolve_folder(group_id, body.source_folder, body.source_folder_id)
        dst_folder = await _resolve_folder(group_id, body.dest_folder, body.dest_folder_id)
        new_url = await blob_manager.move_blob(body.filename, src_folder, dst_folder, group_id)

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
    folder: Optional[str] = None,
    folder_id: Optional[str] = None,
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """
    Serve content files (citations/PDFs) from blob storage.

    When ``source`` query param is provided (a full blob URL), proxy directly
    from that URL.  Otherwise fall back to user/global blob manager lookups.
    """
    filename = path.split("/")[-1]

    global_blob_manager = getattr(request.app.state, "global_blob_manager", None)
    user_blob_manager = getattr(request.app.state, "user_blob_manager", None)

    # --- Primary path: download from source blob URL via authenticated SDK ---
    if source:
        try:
            from urllib.parse import urlparse, unquote
            parsed = urlparse(source)
            if parsed.hostname and parsed.hostname.endswith(".blob.core.windows.net"):
                # Extract container and blob path from the URL
                # URL format: https://<account>.blob.core.windows.net/<container>/<blob_path>
                path_parts = parsed.path.lstrip("/").split("/", 1)
                if len(path_parts) == 2:
                    container_name, blob_name = path_parts[0], unquote(path_parts[1])
                    # Try user blob manager first (same storage account)
                    if user_blob_manager is not None:
                        try:
                            container_client = user_blob_manager.blob_service_client.get_container_client(container_name)
                            blob_client = container_client.get_blob_client(blob_name)
                            download = await blob_client.download_blob()
                            content_bytes = await download.readall()
                            ct = "application/octet-stream"
                            if (
                                hasattr(download.properties, "content_settings")
                                and download.properties.content_settings
                                and hasattr(download.properties.content_settings, "content_type")
                                and download.properties.content_settings.content_type
                            ):
                                ct = download.properties.content_settings.content_type
                            content_type = ct or mimetypes.guess_type(path)[0] or "application/octet-stream"
                            return StreamingResponse(
                                iter([content_bytes]),
                                media_type=content_type,
                                headers={"Content-Disposition": f'inline; filename="{filename}"'},
                            )
                        except Exception as e:
                            logger.debug("SDK download from source URL failed: %s", e)
            else:
                logger.warning("Rejected non-Azure source URL: %s", parsed.hostname)
        except Exception as e:
            logger.debug("Source URL proxy failed for %s: %s", source, e)

    # --- Fallback: blob manager lookups (user-uploaded files) ---

    # Try user storage first (files stored as {group_id}/{filename})
    if user_blob_manager is not None:
        try:
            resolved_folder = await _resolve_folder(group_id, folder, folder_id)
            blob_data = await user_blob_manager.download_blob(path, group_id, folder=resolved_folder)
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
