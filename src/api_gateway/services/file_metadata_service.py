"""
File Metadata Service (Cosmos DB)

Extracted from the Quart file_metadata blueprint for use with FastAPI.
Provides file metadata storage with e-tag support for optimistic concurrency control.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from azure.cosmos.aio import ContainerProxy
from azure.cosmos import exceptions as cosmos_exceptions

logger = logging.getLogger(__name__)


class FileStatus(str, Enum):
    ACTIVE = "active"
    PROCESSING = "processing"
    DEPRECATED = "deprecated"
    LOCKED = "locked"


@dataclass
class FileMetadata:
    id: str
    group_id: str
    user_oid: str
    filename: str
    blob_url: str
    content_type: str
    size_bytes: int
    status: FileStatus = FileStatus.ACTIVE
    folder_id: Optional[str] = None
    version: int = 1
    created_at: str = ""
    updated_at: str = ""
    created_by: str = ""
    updated_by: str = ""
    locked_by: Optional[str] = None
    locked_at: Optional[str] = None
    lock_expires_at: Optional[str] = None
    _etag: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "group_id": self.group_id,
            "user_oid": self.user_oid,
            "filename": self.filename,
            "blob_url": self.blob_url,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "status": self.status.value if isinstance(self.status, FileStatus) else self.status,
            "folder_id": self.folder_id,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "locked_by": self.locked_by,
            "locked_at": self.locked_at,
            "lock_expires_at": self.lock_expires_at,
            "tags": self.tags,
            "properties": self.properties,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileMetadata":
        status = data.get("status", "active")
        if isinstance(status, str):
            try:
                status = FileStatus(status)
            except ValueError:
                status = FileStatus.ACTIVE
        metadata = cls(
            id=data["id"],
            group_id=data["group_id"],
            user_oid=data["user_oid"],
            filename=data["filename"],
            blob_url=data.get("blob_url", ""),
            content_type=data.get("content_type", "application/octet-stream"),
            size_bytes=data.get("size_bytes", 0),
            status=status,
            folder_id=data.get("folder_id"),
            version=data.get("version", 1),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            created_by=data.get("created_by", ""),
            updated_by=data.get("updated_by", ""),
            locked_by=data.get("locked_by"),
            locked_at=data.get("locked_at"),
            lock_expires_at=data.get("lock_expires_at"),
            tags=data.get("tags", []),
            properties=data.get("properties", {}),
        )
        metadata._etag = data.get("_etag")
        return metadata


class ETagMismatchError(Exception):
    def __init__(self, message="File was modified by another user"):
        self.message = message
        super().__init__(self.message)


class FileLockError(Exception):
    def __init__(self, locked_by: str, expires_at: str):
        self.locked_by = locked_by
        self.expires_at = expires_at
        self.message = f"File is locked by {locked_by} until {expires_at}"
        super().__init__(self.message)


class FileMetadataService:
    """
    Service for managing file metadata in Cosmos DB with e-tag concurrency control.
    Partition key: /group_id (for B2B multi-tenant isolation)
    """

    def __init__(self, container: ContainerProxy):
        self.container = container

    async def create_metadata(
        self,
        filename: str,
        group_id: str,
        user_oid: str,
        blob_url: str,
        content_type: str,
        size_bytes: int,
        folder_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        properties: Optional[Dict[str, Any]] = None,
    ) -> FileMetadata:
        now = datetime.utcnow().isoformat() + "Z"
        metadata = FileMetadata(
            id=f"{group_id}:{filename}",
            group_id=group_id,
            user_oid=user_oid,
            filename=filename,
            blob_url=blob_url,
            content_type=content_type,
            size_bytes=size_bytes,
            folder_id=folder_id,
            version=1,
            created_at=now,
            updated_at=now,
            created_by=user_oid,
            updated_by=user_oid,
            tags=tags or [],
            properties=properties or {},
        )
        try:
            result = await self.container.create_item(body=metadata.to_dict(), partition_key=group_id)
            metadata._etag = result.get("_etag")
            logger.info("Created file metadata: %s in group %s", filename, group_id)
            return metadata
        except cosmos_exceptions.CosmosResourceExistsError:
            raise FileExistsError(f"File metadata already exists: {filename}")

    async def get_metadata(self, filename: str, group_id: str) -> Optional[FileMetadata]:
        doc_id = f"{group_id}:{filename}"
        try:
            result = await self.container.read_item(item=doc_id, partition_key=group_id)
            return FileMetadata.from_dict(result)
        except cosmos_exceptions.CosmosResourceNotFoundError:
            return None

    async def update_metadata(
        self,
        metadata: FileMetadata,
        user_oid: str,
        expected_etag: Optional[str] = None,
    ) -> FileMetadata:
        etag = expected_etag or metadata._etag

        # Check if file is locked by another user
        if metadata.locked_by and metadata.locked_by != user_oid:
            if metadata.lock_expires_at:
                expires = datetime.fromisoformat(metadata.lock_expires_at.rstrip("Z"))
                if expires > datetime.utcnow():
                    raise FileLockError(metadata.locked_by, metadata.lock_expires_at)

        metadata.version += 1
        metadata.updated_at = datetime.utcnow().isoformat() + "Z"
        metadata.updated_by = user_oid

        try:
            access_condition = {"if_match": etag} if etag else {}
            result = await self.container.replace_item(
                item=metadata.id,
                body=metadata.to_dict(),
                partition_key=metadata.group_id,
                **access_condition,
            )
            metadata._etag = result.get("_etag")
            logger.info("Updated file metadata: %s v%d", metadata.filename, metadata.version)
            return metadata
        except cosmos_exceptions.CosmosAccessConditionFailedError:
            raise ETagMismatchError(
                f"File '{metadata.filename}' was modified by another user. "
                f"Please refresh and try again."
            )

    async def delete_metadata(
        self,
        filename: str,
        group_id: str,
        user_oid: str,
        expected_etag: Optional[str] = None,
        soft_delete: bool = True,
    ) -> bool:
        if soft_delete:
            metadata = await self.get_metadata(filename, group_id)
            if not metadata:
                return False
            metadata.status = FileStatus.DEPRECATED
            await self.update_metadata(metadata, user_oid, expected_etag)
            return True
        else:
            doc_id = f"{group_id}:{filename}"
            try:
                access_condition = {"if_match": expected_etag} if expected_etag else {}
                await self.container.delete_item(item=doc_id, partition_key=group_id, **access_condition)
                logger.info("Hard deleted file metadata: %s", filename)
                return True
            except cosmos_exceptions.CosmosResourceNotFoundError:
                return False
            except cosmos_exceptions.CosmosAccessConditionFailedError:
                raise ETagMismatchError()

    async def list_files(
        self,
        group_id: str,
        folder_id: Optional[str] = None,
        status: Optional[FileStatus] = None,
        limit: int = 100,
        continuation_token: Optional[str] = None,
    ) -> tuple:
        conditions = ["c.group_id = @group_id"]
        params = [{"name": "@group_id", "value": group_id}]

        if folder_id is not None:
            if folder_id == "":
                conditions.append("(c.folder_id = null OR NOT IS_DEFINED(c.folder_id))")
            else:
                conditions.append("c.folder_id = @folder_id")
                params.append({"name": "@folder_id", "value": folder_id})

        if status:
            conditions.append("c.status = @status")
            params.append({"name": "@status", "value": status.value})
        else:
            conditions.append("c.status != @deprecated")
            params.append({"name": "@deprecated", "value": FileStatus.DEPRECATED.value})

        query = f"SELECT * FROM c WHERE {' AND '.join(conditions)} ORDER BY c.updated_at DESC"

        items = []
        next_token = None
        query_iterable = self.container.query_items(
            query=query,
            parameters=params,
            partition_key=group_id,
            max_item_count=limit,
        )
        async for page in query_iterable.by_page(continuation_token=continuation_token):
            async for item in page:
                items.append(FileMetadata.from_dict(item))
            next_token = query_iterable.properties.get("continuation")
            break  # Only process one page

        return items, next_token

    async def acquire_lock(
        self,
        filename: str,
        group_id: str,
        user_oid: str,
        duration_seconds: int = 300,
        expected_etag: Optional[str] = None,
    ) -> FileMetadata:
        metadata = await self.get_metadata(filename, group_id)
        if not metadata:
            raise FileNotFoundError(f"File not found: {filename}")

        if metadata.locked_by and metadata.locked_by != user_oid:
            if metadata.lock_expires_at:
                expires = datetime.fromisoformat(metadata.lock_expires_at.rstrip("Z"))
                if expires > datetime.utcnow():
                    raise FileLockError(metadata.locked_by, metadata.lock_expires_at)

        now = datetime.utcnow()
        metadata.locked_by = user_oid
        metadata.locked_at = now.isoformat() + "Z"
        metadata.lock_expires_at = (now + timedelta(seconds=duration_seconds)).isoformat() + "Z"
        metadata.status = FileStatus.LOCKED

        return await self.update_metadata(metadata, user_oid, expected_etag or metadata._etag)

    async def release_lock(
        self,
        filename: str,
        group_id: str,
        user_oid: str,
    ) -> FileMetadata:
        metadata = await self.get_metadata(filename, group_id)
        if not metadata:
            raise FileNotFoundError(f"File not found: {filename}")

        if metadata.locked_by != user_oid:
            if metadata.lock_expires_at:
                expires = datetime.fromisoformat(metadata.lock_expires_at.rstrip("Z"))
                if expires > datetime.utcnow():
                    raise FileLockError(metadata.locked_by or "unknown", metadata.lock_expires_at)

        metadata.locked_by = None
        metadata.locked_at = None
        metadata.lock_expires_at = None
        metadata.status = FileStatus.ACTIVE

        return await self.update_metadata(metadata, user_oid)

    async def rename_metadata(
        self,
        old_filename: str,
        new_filename: str,
        group_id: str,
        user_oid: str,
        new_blob_url: str,
        expected_etag: Optional[str] = None,
    ) -> FileMetadata:
        old_metadata = await self.get_metadata(old_filename, group_id)
        if not old_metadata:
            raise FileNotFoundError(f"File not found: {old_filename}")
        if expected_etag and old_metadata._etag != expected_etag:
            raise ETagMismatchError()

        new_metadata = await self.create_metadata(
            filename=new_filename,
            group_id=group_id,
            user_oid=old_metadata.user_oid,
            blob_url=new_blob_url,
            content_type=old_metadata.content_type,
            size_bytes=old_metadata.size_bytes,
            folder_id=old_metadata.folder_id,
            tags=old_metadata.tags,
            properties=old_metadata.properties,
        )

        await self.delete_metadata(
            old_filename, group_id, user_oid,
            expected_etag=old_metadata._etag,
            soft_delete=False,
        )

        return new_metadata
