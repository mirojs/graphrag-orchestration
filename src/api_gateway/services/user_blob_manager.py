"""Lightweight blob manager for user file uploads using standard Blob Storage."""

import logging
import os
import re
import time
from typing import IO, Optional, Tuple

from azure.core.credentials_async import AsyncTokenCredential
from azure.storage.blob.aio import BlobServiceClient

logger = logging.getLogger(__name__)

# In-memory TTL cache for blob stats: group_id → (timestamp, count, total_bytes)
_blob_stats_cache: dict[str, Tuple[float, int, int]] = {}
# In-memory TTL cache for blob file listings: cache_key → (timestamp, [filenames])
_blob_list_cache: dict[str, Tuple[float, list[str]]] = {}
_BLOB_CACHE_TTL = 60  # seconds

# Pattern for safe folder names: alphanumeric, spaces, hyphens, underscores, dots
_SAFE_FOLDER_RE = re.compile(r'^[\w\s.\-\u2014:]+$')  # includes em-dash and colon for analysis result timestamps


def sanitize_folder_name(folder: str | None) -> str | None:
    """Validate and sanitize a folder name or path to prevent path traversal.

    Accepts both single names ("input_docs") and hierarchical paths
    ("insurance_claims_review/input_docs") for ADLS Gen2 compatibility.
    """
    if not folder:
        return None
    folder = folder.strip().strip("/")
    if not folder:
        return None
    if ".." in folder or "\\" in folder:
        raise ValueError(f"Invalid folder name: {folder}")
    # Validate each segment individually
    for segment in folder.split("/"):
        segment = segment.strip()
        if not segment:
            raise ValueError(f"Folder path contains empty segment: {folder}")
        if not _SAFE_FOLDER_RE.match(segment):
            raise ValueError(f"Folder name contains invalid characters: {folder}")
    return folder


def _is_directory_blob(blob) -> bool:
    """Check if a blob entry is a directory marker (not a real file).

    Catches ADLS Gen2 directories (hdi_isfolder) AND plain 0-byte
    folder-placeholder blobs created by non-HNS storage accounts.
    """
    if getattr(blob, "is_directory", False):
        return True
    metadata = getattr(blob, "metadata", None)
    if metadata and metadata.get("hdi_isfolder") == "true":
        return True
    if (getattr(blob, "size", None) or 0) == 0:
        return True
    return False


class UserBlobManager:
    """Manages user-uploaded files in Azure Blob Storage.

    Supports optional folder prefixes: blobs are stored at
    ``{group_id}/{filename}`` (root) or ``{group_id}/{folder}/{filename}``.
    On ADLS Gen2 (HNS) accounts, directory entries are filtered out of listings.
    """

    def __init__(self, endpoint: str, container: str, credential: AsyncTokenCredential):
        self.credential = credential
        self.container = container
        self.blob_service_client = BlobServiceClient(
            account_url=endpoint,
            credential=credential,
            max_single_put_size=4 * 1024 * 1024,
        )

    def _blob_path(self, group_id: str, filename: str, folder: str | None = None) -> str:
        """Build the full blob path, optionally scoped to a folder."""
        if folder:
            return f"{group_id}/{folder}/{filename}"
        return f"{group_id}/{filename}"

    async def list_blobs(self, group_id: str, folder: str | None = None) -> list[str]:
        """List blob filenames for a group, optionally scoped to a folder.

        Args:
            group_id: Tenant/user partition key.
            folder: If provided, list only blobs inside ``{group_id}/{folder}/``.
                    If None, list only root-level (un-foldered) blobs.

        Returns:
            Plain filenames (no folder prefix).
        """
        folder = sanitize_folder_name(folder)
        cache_key = f"{group_id}:{folder or ''}"
        now = time.monotonic()
        cached = _blob_list_cache.get(cache_key)
        if cached and (now - cached[0]) < _BLOB_CACHE_TTL:
            return list(cached[1])

        if folder:
            prefix = f"{group_id}/{folder}/"
        else:
            prefix = f"{group_id}/"
        container_client = self.blob_service_client.get_container_client(self.container)
        files = []
        async for blob in container_client.list_blobs(name_starts_with=prefix, include=["metadata"]):
            if _is_directory_blob(blob):
                continue
            name = blob.name[len(prefix):]
            # Only immediate children, skip deeper nesting
            if "/" in name:
                continue
            # Skip empty names (the directory marker itself)
            if not name:
                continue
            files.append(name)

        _blob_list_cache[cache_key] = (now, files)
        return list(files)

    async def list_blobs_recursive(self, group_id: str, folder: str) -> list[dict]:
        """List all blobs recursively under a folder prefix.

        Returns a list of dicts with 'name' (relative path) and 'url' (full blob URL).
        Unlike list_blobs(), this includes blobs in subdirectories.
        """
        folder = sanitize_folder_name(folder)
        prefix = f"{group_id}/{folder}/"
        container_client = self.blob_service_client.get_container_client(self.container)
        blobs = []
        async for blob in container_client.list_blobs(name_starts_with=prefix, include=["metadata"]):
            if _is_directory_blob(blob):
                continue
            rel = blob.name[len(prefix):]
            if not rel:
                continue
            blob_url = f"{container_client.url}/{blob.name}"
            blobs.append({"name": rel, "url": blob_url, "full_path": blob.name})
        return blobs

    async def get_blob_stats(self, group_id: str) -> Tuple[int, int]:
        """Single-pass: count blobs and sum all sizes, with TTL cache."""
        now = time.monotonic()
        cached = _blob_stats_cache.get(group_id)
        if cached and (now - cached[0]) < _BLOB_CACHE_TTL:
            return cached[1], cached[2]

        prefix = f"{group_id}/"
        container_client = self.blob_service_client.get_container_client(self.container)
        count = 0
        total_bytes = 0
        async for blob in container_client.list_blobs(name_starts_with=prefix, include=["metadata"]):
            if _is_directory_blob(blob):
                continue
            name = blob.name[len(prefix):]
            if not name or name.endswith(".result.json"):
                continue
            total_bytes += blob.size or 0
            count += 1

        _blob_stats_cache[group_id] = (now, count, total_bytes)
        return count, total_bytes

    def invalidate_blob_cache(self, group_id: str) -> None:
        """Invalidate cached stats and ALL per-folder file lists after mutations."""
        _blob_stats_cache.pop(group_id, None)
        # Clear all cache entries for this group (root + any folder)
        keys_to_remove = [k for k in _blob_list_cache if k.startswith(f"{group_id}:")]
        for k in keys_to_remove:
            del _blob_list_cache[k]

    async def count_blobs(self, group_id: str) -> int:
        """Count top-level blobs for a group (for dashboard document count)."""
        count, _ = await self.get_blob_stats(group_id)
        return count

    async def get_storage_used_bytes(self, group_id: str) -> int:
        """Sum blob sizes for a group (for dashboard storage metric)."""
        _, total_bytes = await self.get_blob_stats(group_id)
        return total_bytes

    async def upload_blob(self, file: IO, filename: str, group_id: str, folder: str | None = None) -> str:
        folder = sanitize_folder_name(folder)
        blob_name = self._blob_path(group_id, filename, folder)
        container_client = self.blob_service_client.get_container_client(self.container)
        blob_client = container_client.get_blob_client(blob_name)
        await blob_client.upload_blob(file, overwrite=True)
        self.invalidate_blob_cache(group_id)
        return blob_client.url

    async def remove_blob(self, filename: str, group_id: str, folder: str | None = None) -> None:
        folder = sanitize_folder_name(folder)
        blob_name = self._blob_path(group_id, filename, folder)
        container_client = self.blob_service_client.get_container_client(self.container)
        blob_client = container_client.get_blob_client(blob_name)
        await blob_client.delete_blob(delete_snapshots="include")
        self.invalidate_blob_cache(group_id)

    async def rename_blob(self, old_filename: str, new_filename: str, group_id: str, folder: str | None = None) -> str:
        folder = sanitize_folder_name(folder)
        old_blob = self._blob_path(group_id, old_filename, folder)
        new_blob = self._blob_path(group_id, new_filename, folder)
        container_client = self.blob_service_client.get_container_client(self.container)
        src_client = container_client.get_blob_client(old_blob)
        dst_client = container_client.get_blob_client(new_blob)
        await dst_client.start_copy_from_url(src_client.url)
        await src_client.delete_blob(delete_snapshots="include")
        self.invalidate_blob_cache(group_id)
        return dst_client.url

    async def move_blob(self, filename: str, source_folder: str, dest_folder: str, group_id: str) -> str:
        src = f"{group_id}/{source_folder}/{filename}" if source_folder else f"{group_id}/{filename}"
        dst = f"{group_id}/{dest_folder}/{filename}" if dest_folder else f"{group_id}/{filename}"
        container_client = self.blob_service_client.get_container_client(self.container)
        src_client = container_client.get_blob_client(src)
        dst_client = container_client.get_blob_client(dst)
        await dst_client.start_copy_from_url(src_client.url)
        await src_client.delete_blob(delete_snapshots="include")
        self.invalidate_blob_cache(group_id)
        return dst_client.url

    async def copy_blob(self, filename: str, dest_filename: str, group_id: str) -> str:
        src = f"{group_id}/{filename}"
        dst = f"{group_id}/{dest_filename}"
        container_client = self.blob_service_client.get_container_client(self.container)
        src_client = container_client.get_blob_client(src)
        dst_client = container_client.get_blob_client(dst)
        await dst_client.start_copy_from_url(src_client.url)
        self.invalidate_blob_cache(group_id)
        return dst_client.url

    async def download_blob(self, filename: str, group_id: str, folder: str | None = None) -> "tuple[bytes, dict] | None":
        """Download a blob. Returns (content, properties) or None."""
        folder = sanitize_folder_name(folder)
        blob_name = self._blob_path(group_id, filename, folder)
        container_client = self.blob_service_client.get_container_client(self.container)
        blob_client = container_client.get_blob_client(blob_name)
        try:
            download = await blob_client.download_blob()
            content = await download.readall()
            ct = "application/octet-stream"
            if (
                hasattr(download.properties, "content_settings")
                and download.properties.content_settings
                and hasattr(download.properties.content_settings, "content_type")
                and download.properties.content_settings.content_type
            ):
                ct = download.properties.content_settings.content_type
            return content, {"content_settings": {"content_type": ct}}
        except Exception:
            logger.debug("Blob not found in user storage: %s", blob_name)
            return None

    async def close(self):
        await self.blob_service_client.close()
