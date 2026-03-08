"""
Folder Resolver Service

Resolves folder_id → root_folder_id for use as Neo4j partition key (group_id).

Architecture:
- auth_group_id (B2B group / B2C user_id) = security boundary
- root_folder_id = Neo4j partition key (one knowledge graph per root folder)
- Unfiled documents (folder_id=None) fall back to auth_group_id
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def resolve_neo4j_group_id(
    auth_group_id: str,
    folder_id: Optional[str] = None,
) -> str:
    """Resolve the Neo4j partition key from folder context.

    Args:
        auth_group_id: The authenticated user/group identity (security boundary).
        folder_id: Optional folder ID (root or subfolder). If a subfolder,
                   walks SUBFOLDER_OF edges to find the root folder.

    Returns:
        The root_folder_id to use as Neo4j group_id, or auth_group_id if
        no folder context is provided.

    Raises:
        ValueError: If the folder doesn't exist or doesn't belong to auth_group_id.
    """
    if not folder_id:
        return auth_group_id

    from src.worker.services import GraphService

    driver = GraphService().driver
    if not driver:
        raise ValueError("Neo4j driver not initialized")

    with driver.session() as session:
        # Walk SUBFOLDER_OF to root and verify ownership
        result = session.run(
            """
            MATCH (f:Folder {id: $folder_id, group_id: $auth_gid})
            OPTIONAL MATCH (f)-[:SUBFOLDER_OF*1..]->(root:Folder)
            WHERE NOT (root)-[:SUBFOLDER_OF]->(:Folder)
            WITH f, root
            RETURN COALESCE(root.id, f.id) AS root_folder_id
            """,
            folder_id=folder_id,
            auth_gid=auth_group_id,
        )
        record = result.single()

        if not record:
            raise ValueError(
                f"Folder '{folder_id}' not found or does not belong to group '{auth_group_id}'"
            )

        root_id = record["root_folder_id"]
        logger.info(
            "folder_resolved_to_neo4j_group",
            extra={
                "auth_group_id": auth_group_id,
                "folder_id": folder_id,
                "root_folder_id": root_id,
            },
        )
        return root_id


async def get_valid_partition_ids(auth_group_id: str) -> list:
    """Get all valid Neo4j partition IDs for a given auth_group_id.

    Returns auth_group_id (for unfiled docs) plus all root folder IDs.
    """
    from src.worker.services import GraphService

    driver = GraphService().driver
    if not driver:
        return [auth_group_id]

    with driver.session() as session:
        result = session.run(
            """
            MATCH (f:Folder {group_id: $auth_gid})
            WHERE NOT (f)-[:SUBFOLDER_OF]->(:Folder)
            RETURN f.id AS root_folder_id
            """,
            auth_gid=auth_group_id,
        )
        root_ids = [r["root_folder_id"] for r in result]

    return [auth_group_id] + root_ids
