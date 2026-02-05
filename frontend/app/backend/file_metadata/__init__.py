"""
File Metadata Module

Dual-storage layer for files: ADLS Gen2 (blobs) + Cosmos DB (metadata with e-tags).
"""

from file_metadata.cosmos import (
    file_metadata_bp,
    FileMetadataService,
    FileMetadata,
    FileStatus,
    ETagMismatchError,
    FileLockError,
    CONFIG_FILE_METADATA_ENABLED,
    CONFIG_FILE_METADATA_CLIENT,
    CONFIG_FILE_METADATA_CONTAINER,
)

__all__ = [
    "file_metadata_bp",
    "FileMetadataService",
    "FileMetadata",
    "FileStatus",
    "ETagMismatchError",
    "FileLockError",
    "CONFIG_FILE_METADATA_ENABLED",
    "CONFIG_FILE_METADATA_CLIENT",
    "CONFIG_FILE_METADATA_CONTAINER",
]
