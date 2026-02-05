"""
Cosmos DB File Metadata Service

Provides file metadata storage with e-tag support for optimistic concurrency control.
This is the dual-storage layer: files in ADLS Gen2, metadata in Cosmos DB.

Key features:
- E-tag based optimistic concurrency for B2B multi-user scenarios
- File metadata with version tracking
- Lock mechanism for collaborative editing
- Change tracking for audit/sync
"""

import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum

from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.cosmos import exceptions as cosmos_exceptions
from azure.identity.aio import AzureDeveloperCliCredential, ManagedIdentityCredential
from quart import Blueprint, current_app, jsonify, request

from config import CONFIG_CREDENTIAL
from core.authentication import get_group_id
from decorators import authenticated
from error import error_response

import logging

logger = logging.getLogger(__name__)


# ==================== Configuration Constants ====================

CONFIG_FILE_METADATA_ENABLED = "file_metadata_enabled"
CONFIG_FILE_METADATA_CLIENT = "file_metadata_client"
CONFIG_FILE_METADATA_CONTAINER = "file_metadata_container"


# ==================== Data Models ====================

class FileStatus(str, Enum):
    """File lifecycle status."""
    ACTIVE = "active"
    PROCESSING = "processing"  # Being indexed
    DEPRECATED = "deprecated"  # Soft deleted
    LOCKED = "locked"  # Being edited


@dataclass
class FileMetadata:
    """File metadata stored in Cosmos DB."""
    id: str  # filename
    group_id: str  # B2B group or B2C user_oid
    user_oid: str  # Owner/uploader
    filename: str
    blob_url: str
    content_type: str
    size_bytes: int
    status: FileStatus = FileStatus.ACTIVE
    folder_id: Optional[str] = None
    
    # Versioning
    version: int = 1
    created_at: str = ""
    updated_at: str = ""
    created_by: str = ""
    updated_by: str = ""
    
    # Locking for collaborative editing
    locked_by: Optional[str] = None
    locked_at: Optional[str] = None
    lock_expires_at: Optional[str] = None
    
    # E-tag for optimistic concurrency (set by Cosmos DB)
    _etag: Optional[str] = None
    
    # Custom metadata
    tags: List[str] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to Cosmos DB document format."""
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
        """Create from Cosmos DB document."""
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


# ==================== Exceptions ====================

class ETagMismatchError(Exception):
    """Raised when e-tag doesn't match (concurrent modification detected)."""
    def __init__(self, message: str = "File was modified by another user"):
        self.message = message
        super().__init__(self.message)


class FileLockError(Exception):
    """Raised when file is locked by another user."""
    def __init__(self, locked_by: str, expires_at: str):
        self.locked_by = locked_by
        self.expires_at = expires_at
        self.message = f"File is locked by {locked_by} until {expires_at}"
        super().__init__(self.message)


# ==================== Service Class ====================

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
        """
        Create file metadata entry.
        
        Args:
            filename: Name of the file (used as document id)
            group_id: B2B group ID or B2C user OID
            user_oid: User who uploaded the file
            blob_url: URL of the blob in ADLS
            content_type: MIME type
            size_bytes: File size
            folder_id: Optional folder assignment
            tags: Optional tags
            properties: Optional custom properties
            
        Returns:
            FileMetadata with e-tag set
        """
        now = datetime.utcnow().isoformat() + "Z"
        
        metadata = FileMetadata(
            id=f"{group_id}:{filename}",  # Composite ID for uniqueness
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
            result = await self.container.create_item(
                body=metadata.to_dict(),
                partition_key=group_id,
            )
            metadata._etag = result.get("_etag")
            logger.info(f"Created file metadata: {filename} in group {group_id}")
            return metadata
        except cosmos_exceptions.CosmosResourceExistsError:
            raise FileExistsError(f"File metadata already exists: {filename}")
    
    async def get_metadata(
        self,
        filename: str,
        group_id: str,
    ) -> Optional[FileMetadata]:
        """
        Get file metadata by filename.
        
        Args:
            filename: Name of the file
            group_id: B2B group ID or B2C user OID
            
        Returns:
            FileMetadata with current e-tag, or None if not found
        """
        doc_id = f"{group_id}:{filename}"
        try:
            result = await self.container.read_item(
                item=doc_id,
                partition_key=group_id,
            )
            return FileMetadata.from_dict(result)
        except cosmos_exceptions.CosmosResourceNotFoundError:
            return None
    
    async def update_metadata(
        self,
        metadata: FileMetadata,
        user_oid: str,
        expected_etag: Optional[str] = None,
    ) -> FileMetadata:
        """
        Update file metadata with optimistic concurrency control.
        
        Args:
            metadata: Updated metadata object
            user_oid: User making the update
            expected_etag: E-tag to match (if None, uses metadata._etag)
            
        Returns:
            Updated FileMetadata with new e-tag
            
        Raises:
            ETagMismatchError: If e-tag doesn't match (concurrent modification)
            FileLockError: If file is locked by another user
        """
        etag = expected_etag or metadata._etag
        
        # Check if file is locked by another user
        if metadata.locked_by and metadata.locked_by != user_oid:
            if metadata.lock_expires_at:
                expires = datetime.fromisoformat(metadata.lock_expires_at.rstrip("Z"))
                if expires > datetime.utcnow():
                    raise FileLockError(metadata.locked_by, metadata.lock_expires_at)
        
        # Update metadata
        metadata.version += 1
        metadata.updated_at = datetime.utcnow().isoformat() + "Z"
        metadata.updated_by = user_oid
        
        try:
            # Use if_match for optimistic concurrency
            access_condition = {"if_match": etag} if etag else {}
            
            result = await self.container.replace_item(
                item=metadata.id,
                body=metadata.to_dict(),
                partition_key=metadata.group_id,
                **access_condition,
            )
            metadata._etag = result.get("_etag")
            logger.info(f"Updated file metadata: {metadata.filename} v{metadata.version}")
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
        """
        Delete file metadata.
        
        Args:
            filename: Name of the file
            group_id: B2B group ID
            user_oid: User performing deletion
            expected_etag: E-tag to match for concurrency
            soft_delete: If True, mark as deprecated instead of hard delete
            
        Returns:
            True if deleted successfully
            
        Raises:
            ETagMismatchError: If e-tag doesn't match
        """
        doc_id = f"{group_id}:{filename}"
        
        if soft_delete:
            # Get current metadata
            metadata = await self.get_metadata(filename, group_id)
            if not metadata:
                return False
            
            metadata.status = FileStatus.DEPRECATED
            await self.update_metadata(metadata, user_oid, expected_etag)
            return True
        else:
            try:
                access_condition = {"if_match": expected_etag} if expected_etag else {}
                await self.container.delete_item(
                    item=doc_id,
                    partition_key=group_id,
                    **access_condition,
                )
                logger.info(f"Hard deleted file metadata: {filename}")
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
    ) -> tuple[List[FileMetadata], Optional[str]]:
        """
        List files in a group with optional filtering.
        
        Args:
            group_id: B2B group ID
            folder_id: Filter by folder (None = all, "" = root only)
            status: Filter by status (None = all non-deprecated)
            limit: Max results per page
            continuation_token: For pagination
            
        Returns:
            Tuple of (list of FileMetadata, next continuation token)
        """
        # Build query
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
            # Default: exclude deprecated
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
            # Get continuation token for next page
            next_token = query_iterable.properties.get("continuation")
            break  # Only process one page
        
        return items, next_token
    
    async def acquire_lock(
        self,
        filename: str,
        group_id: str,
        user_oid: str,
        duration_seconds: int = 300,  # 5 minutes default
        expected_etag: Optional[str] = None,
    ) -> FileMetadata:
        """
        Acquire an edit lock on a file.
        
        Args:
            filename: File to lock
            group_id: B2B group ID
            user_oid: User acquiring lock
            duration_seconds: Lock duration
            expected_etag: E-tag for concurrency
            
        Returns:
            Updated FileMetadata with lock info
            
        Raises:
            FileLockError: If already locked by another user
            ETagMismatchError: If concurrent modification
        """
        metadata = await self.get_metadata(filename, group_id)
        if not metadata:
            raise FileNotFoundError(f"File not found: {filename}")
        
        # Check existing lock
        if metadata.locked_by and metadata.locked_by != user_oid:
            if metadata.lock_expires_at:
                expires = datetime.fromisoformat(metadata.lock_expires_at.rstrip("Z"))
                if expires > datetime.utcnow():
                    raise FileLockError(metadata.locked_by, metadata.lock_expires_at)
        
        # Set lock
        now = datetime.utcnow()
        metadata.locked_by = user_oid
        metadata.locked_at = now.isoformat() + "Z"
        metadata.lock_expires_at = (now.replace(second=now.second + duration_seconds)).isoformat() + "Z"
        metadata.status = FileStatus.LOCKED
        
        return await self.update_metadata(metadata, user_oid, expected_etag or metadata._etag)
    
    async def release_lock(
        self,
        filename: str,
        group_id: str,
        user_oid: str,
    ) -> FileMetadata:
        """
        Release an edit lock on a file.
        
        Only the lock holder or after expiry can release.
        """
        metadata = await self.get_metadata(filename, group_id)
        if not metadata:
            raise FileNotFoundError(f"File not found: {filename}")
        
        if metadata.locked_by != user_oid:
            # Check if lock expired
            if metadata.lock_expires_at:
                expires = datetime.fromisoformat(metadata.lock_expires_at.rstrip("Z"))
                if expires > datetime.utcnow():
                    raise FileLockError(metadata.locked_by or "unknown", metadata.lock_expires_at)
        
        # Clear lock
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
        """
        Rename file metadata (creates new, deletes old).
        
        This is atomic via e-tag - if old file was modified, rename fails.
        """
        # Get old metadata
        old_metadata = await self.get_metadata(old_filename, group_id)
        if not old_metadata:
            raise FileNotFoundError(f"File not found: {old_filename}")
        
        # Check e-tag
        if expected_etag and old_metadata._etag != expected_etag:
            raise ETagMismatchError()
        
        # Create new metadata entry
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
        
        # Delete old entry
        await self.delete_metadata(
            old_filename, group_id, user_oid,
            expected_etag=old_metadata._etag,
            soft_delete=False,
        )
        
        return new_metadata


# ==================== Blueprint ====================

file_metadata_bp = Blueprint("file_metadata", __name__)


def _get_group_id(auth_claims: dict[str, Any]) -> str:
    """Wrapper for shared get_group_id from authentication module."""
    return get_group_id(auth_claims)



@file_metadata_bp.get("/file_metadata/<filename>")
@authenticated
async def get_file_metadata(auth_claims: dict[str, Any], filename: str):
    """Get file metadata with e-tag in response header."""
    if not current_app.config.get(CONFIG_FILE_METADATA_ENABLED):
        return jsonify({"error": "File metadata service not enabled"}), 400
    
    group_id = _get_group_id(auth_claims)
    service: FileMetadataService = current_app.config[CONFIG_FILE_METADATA_CONTAINER]
    
    metadata = await service.get_metadata(filename, group_id)
    if not metadata:
        return jsonify({"error": f"File not found: {filename}"}), 404
    
    response = jsonify(metadata.to_dict())
    if metadata._etag:
        response.headers["ETag"] = metadata._etag
    return response, 200


@file_metadata_bp.put("/file_metadata/<filename>")
@authenticated
async def update_file_metadata(auth_claims: dict[str, Any], filename: str):
    """
    Update file metadata with e-tag concurrency control.
    
    Send If-Match header with e-tag from previous GET.
    Returns 412 Precondition Failed if e-tag doesn't match.
    """
    if not current_app.config.get(CONFIG_FILE_METADATA_ENABLED):
        return jsonify({"error": "File metadata service not enabled"}), 400
    
    group_id = _get_group_id(auth_claims)
    user_oid = auth_claims["oid"]
    expected_etag = request.headers.get("If-Match")
    
    service: FileMetadataService = current_app.config[CONFIG_FILE_METADATA_CONTAINER]
    
    # Get current metadata
    metadata = await service.get_metadata(filename, group_id)
    if not metadata:
        return jsonify({"error": f"File not found: {filename}"}), 404
    
    # Apply updates from request
    request_json = await request.get_json()
    if "tags" in request_json:
        metadata.tags = request_json["tags"]
    if "properties" in request_json:
        metadata.properties = request_json["properties"]
    if "folder_id" in request_json:
        metadata.folder_id = request_json["folder_id"]
    
    try:
        updated = await service.update_metadata(metadata, user_oid, expected_etag)
        response = jsonify(updated.to_dict())
        response.headers["ETag"] = updated._etag
        return response, 200
    except ETagMismatchError as e:
        return jsonify({"error": e.message, "code": "ETAG_MISMATCH"}), 412
    except FileLockError as e:
        return jsonify({"error": e.message, "locked_by": e.locked_by}), 423


@file_metadata_bp.post("/file_metadata/<filename>/lock")
@authenticated
async def lock_file(auth_claims: dict[str, Any], filename: str):
    """Acquire an edit lock on a file."""
    if not current_app.config.get(CONFIG_FILE_METADATA_ENABLED):
        return jsonify({"error": "File metadata service not enabled"}), 400
    
    group_id = _get_group_id(auth_claims)
    user_oid = auth_claims["oid"]
    
    request_json = await request.get_json() or {}
    duration = request_json.get("duration_seconds", 300)
    expected_etag = request.headers.get("If-Match")
    
    service: FileMetadataService = current_app.config[CONFIG_FILE_METADATA_CONTAINER]
    
    try:
        metadata = await service.acquire_lock(filename, group_id, user_oid, duration, expected_etag)
        response = jsonify({
            "message": "Lock acquired",
            "locked_by": metadata.locked_by,
            "expires_at": metadata.lock_expires_at,
        })
        response.headers["ETag"] = metadata._etag
        return response, 200
    except FileLockError as e:
        return jsonify({"error": e.message, "locked_by": e.locked_by}), 423
    except FileNotFoundError:
        return jsonify({"error": f"File not found: {filename}"}), 404
    except ETagMismatchError as e:
        return jsonify({"error": e.message}), 412


@file_metadata_bp.delete("/file_metadata/<filename>/lock")
@authenticated
async def unlock_file(auth_claims: dict[str, Any], filename: str):
    """Release an edit lock on a file."""
    if not current_app.config.get(CONFIG_FILE_METADATA_ENABLED):
        return jsonify({"error": "File metadata service not enabled"}), 400
    
    group_id = _get_group_id(auth_claims)
    user_oid = auth_claims["oid"]
    
    service: FileMetadataService = current_app.config[CONFIG_FILE_METADATA_CONTAINER]
    
    try:
        metadata = await service.release_lock(filename, group_id, user_oid)
        return jsonify({"message": "Lock released"}), 200
    except FileLockError as e:
        return jsonify({"error": e.message, "locked_by": e.locked_by}), 423
    except FileNotFoundError:
        return jsonify({"error": f"File not found: {filename}"}), 404


@file_metadata_bp.get("/file_metadata")
@authenticated
async def list_file_metadata(auth_claims: dict[str, Any]):
    """List files with metadata and e-tags."""
    if not current_app.config.get(CONFIG_FILE_METADATA_ENABLED):
        return jsonify({"error": "File metadata service not enabled"}), 400
    
    group_id = _get_group_id(auth_claims)
    folder_id = request.args.get("folder_id")
    limit = int(request.args.get("limit", 100))
    continuation = request.args.get("continuation")
    
    service: FileMetadataService = current_app.config[CONFIG_FILE_METADATA_CONTAINER]
    
    files, next_token = await service.list_files(
        group_id=group_id,
        folder_id=folder_id,
        limit=limit,
        continuation_token=continuation,
    )
    
    response = jsonify({
        "files": [f.to_dict() for f in files],
        "continuation_token": next_token,
    })
    return response, 200


# ==================== Setup ====================

@file_metadata_bp.before_app_serving
async def setup_file_metadata():
    """Initialize Cosmos DB file metadata container."""
    USE_FILE_METADATA = os.getenv("USE_FILE_METADATA", "").lower() == "true"
    AZURE_COSMOSDB_ACCOUNT = os.getenv("AZURE_COSMOSDB_ACCOUNT")
    AZURE_FILE_METADATA_DATABASE = os.getenv("AZURE_FILE_METADATA_DATABASE", "graphrag")
    AZURE_FILE_METADATA_CONTAINER = os.getenv("AZURE_FILE_METADATA_CONTAINER", "file_metadata")
    
    current_app.config[CONFIG_FILE_METADATA_ENABLED] = USE_FILE_METADATA
    
    if USE_FILE_METADATA:
        current_app.logger.info("USE_FILE_METADATA is true, setting up Cosmos DB client")
        
        if not AZURE_COSMOSDB_ACCOUNT:
            raise ValueError("AZURE_COSMOSDB_ACCOUNT must be set when USE_FILE_METADATA is true")
        
        azure_credential = current_app.config[CONFIG_CREDENTIAL]
        cosmos_client = CosmosClient(
            url=f"https://{AZURE_COSMOSDB_ACCOUNT}.documents.azure.com:443/",
            credential=azure_credential,
        )
        cosmos_db = cosmos_client.get_database_client(AZURE_FILE_METADATA_DATABASE)
        cosmos_container = cosmos_db.get_container_client(AZURE_FILE_METADATA_CONTAINER)
        
        current_app.config[CONFIG_FILE_METADATA_CLIENT] = cosmos_client
        current_app.config[CONFIG_FILE_METADATA_CONTAINER] = FileMetadataService(cosmos_container)
        
        current_app.logger.info(
            f"File metadata service initialized: {AZURE_COSMOSDB_ACCOUNT}/{AZURE_FILE_METADATA_DATABASE}/{AZURE_FILE_METADATA_CONTAINER}"
        )


@file_metadata_bp.after_app_serving
async def close_file_metadata():
    """Close Cosmos DB client."""
    if cosmos_client := current_app.config.get(CONFIG_FILE_METADATA_CLIENT):
        await cosmos_client.close()
