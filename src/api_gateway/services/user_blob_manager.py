"""Lightweight blob manager for user file uploads using standard Blob Storage."""

import logging
import os
from typing import IO

from azure.core.credentials_async import AsyncTokenCredential
from azure.storage.blob.aio import BlobServiceClient

logger = logging.getLogger(__name__)

class UserBlobManager:
    """Manages user-uploaded files in Azure Blob Storage (no ADLS/HNS required)."""

    def __init__(self, endpoint: str, container: str, credential: AsyncTokenCredential):
        self.credential = credential
        self.container = container
        self.blob_service_client = BlobServiceClient(
            account_url=endpoint,
            credential=credential,
            max_single_put_size=4 * 1024 * 1024,
        )

    async def list_blobs(self, group_id: str) -> list[str]:
        prefix = f"{group_id}/"
        container_client = self.blob_service_client.get_container_client(self.container)
        files = []
        async for blob in container_client.list_blobs(name_starts_with=prefix):
            name = blob.name[len(prefix):]
            # Only top-level files, skip subdirectories
            if "/" in name:
                continue
            files.append(name)
        return files

    async def count_blobs(self, group_id: str) -> int:
        """Count top-level blobs for a group (for dashboard document count)."""
        prefix = f"{group_id}/"
        container_client = self.blob_service_client.get_container_client(self.container)
        count = 0
        async for blob in container_client.list_blobs(name_starts_with=prefix):
            name = blob.name[len(prefix):]
            if "/" not in name:
                count += 1
        return count

    async def get_storage_used_bytes(self, group_id: str) -> int:
        """Sum blob sizes for a group (for dashboard storage metric)."""
        prefix = f"{group_id}/"
        container_client = self.blob_service_client.get_container_client(self.container)
        total = 0
        async for blob in container_client.list_blobs(name_starts_with=prefix):
            total += blob.size or 0
        return total

    async def upload_blob(self, file: IO, filename: str, group_id: str) -> str:
        blob_name = f"{group_id}/{filename}"
        container_client = self.blob_service_client.get_container_client(self.container)
        blob_client = container_client.get_blob_client(blob_name)
        await blob_client.upload_blob(file, overwrite=True)
        return blob_client.url

    async def remove_blob(self, filename: str, group_id: str) -> None:
        blob_name = f"{group_id}/{filename}"
        container_client = self.blob_service_client.get_container_client(self.container)
        blob_client = container_client.get_blob_client(blob_name)
        await blob_client.delete_blob(delete_snapshots="include")

    async def rename_blob(self, old_filename: str, new_filename: str, group_id: str) -> str:
        old_blob = f"{group_id}/{old_filename}"
        new_blob = f"{group_id}/{new_filename}"
        container_client = self.blob_service_client.get_container_client(self.container)
        src_client = container_client.get_blob_client(old_blob)
        dst_client = container_client.get_blob_client(new_blob)
        await dst_client.start_copy_from_url(src_client.url)
        await src_client.delete_blob(delete_snapshots="include")
        return dst_client.url

    async def move_blob(self, filename: str, source_folder: str, dest_folder: str, group_id: str) -> str:
        src = f"{group_id}/{source_folder}/{filename}" if source_folder else f"{group_id}/{filename}"
        dst = f"{group_id}/{dest_folder}/{filename}" if dest_folder else f"{group_id}/{filename}"
        container_client = self.blob_service_client.get_container_client(self.container)
        src_client = container_client.get_blob_client(src)
        dst_client = container_client.get_blob_client(dst)
        await dst_client.start_copy_from_url(src_client.url)
        await src_client.delete_blob(delete_snapshots="include")
        return dst_client.url

    async def copy_blob(self, filename: str, dest_filename: str, group_id: str) -> str:
        src = f"{group_id}/{filename}"
        dst = f"{group_id}/{dest_filename}"
        container_client = self.blob_service_client.get_container_client(self.container)
        src_client = container_client.get_blob_client(src)
        dst_client = container_client.get_blob_client(dst)
        await dst_client.start_copy_from_url(src_client.url)
        return dst_client.url

    async def close(self):
        await self.blob_service_client.close()
