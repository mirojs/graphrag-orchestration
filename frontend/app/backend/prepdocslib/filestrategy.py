import logging
from typing import Optional

from .blobmanager import AdlsBlobManager, BaseBlobManager, BlobManager
from .embeddings import ImageEmbeddings, OpenAIEmbeddings
from .figureprocessor import (
    FigureProcessor,
    MediaDescriptionStrategy,
    process_page_image,
)
from .fileprocessor import FileProcessor
from .listfilestrategy import File, ListFileStrategy
from .mediadescriber import ContentUnderstandingDescriber
from .searchmanager import SearchManager, Section
from .strategy import DocumentAction, SearchInfo, Strategy
from .textprocessor import process_text

logger = logging.getLogger("scripts")


async def parse_file(
    file: File,
    file_processors: dict[str, FileProcessor],
    category: Optional[str] = None,
    blob_manager: Optional[BaseBlobManager] = None,
    image_embeddings_client: Optional[ImageEmbeddings] = None,
    figure_processor: Optional[FigureProcessor] = None,
    user_oid: Optional[str] = None,
) -> list[Section]:

    key = file.file_extension().lower()
    processor = file_processors.get(key)
    if processor is None:
        logger.info("Skipping '%s', no parser found.", file.filename())
        return []
    logger.info("Ingesting '%s'", file.filename())
    pages = [page async for page in processor.parser.parse(content=file.content)]
    for page in pages:
        for image in page.images:
            logger.info("Processing image '%s' on page %d", image.filename, page.page_num)
            await process_page_image(
                image=image,
                document_filename=file.filename(),
                blob_manager=blob_manager,
                image_embeddings_client=image_embeddings_client,
                figure_processor=figure_processor,
                user_oid=user_oid,
            )
    sections = process_text(pages, file, processor.splitter, category)
    return sections


class FileStrategy(Strategy):
    """
    Strategy for ingesting documents into a search service from files stored either locally or in a data lake storage account
    """

    def __init__(
        self,
        list_file_strategy: ListFileStrategy,
        blob_manager: BlobManager,
        search_info: SearchInfo,
        file_processors: dict[str, FileProcessor],
        document_action: DocumentAction = DocumentAction.Add,
        embeddings: Optional[OpenAIEmbeddings] = None,
        image_embeddings: Optional[ImageEmbeddings] = None,
        search_analyzer_name: Optional[str] = None,
        search_field_name_embedding: Optional[str] = None,
        use_acls: bool = False,
        category: Optional[str] = None,
        figure_processor: Optional[FigureProcessor] = None,
        enforce_access_control: bool = False,
        use_web_source: bool = False,
        use_sharepoint_source: bool = False,
    ):
        self.list_file_strategy = list_file_strategy
        self.blob_manager = blob_manager
        self.file_processors = file_processors
        self.document_action = document_action
        self.embeddings = embeddings
        self.image_embeddings = image_embeddings
        self.search_analyzer_name = search_analyzer_name
        self.search_field_name_embedding = search_field_name_embedding
        self.search_info = search_info
        self.use_acls = use_acls
        self.category = category
        self.figure_processor = figure_processor
        self.enforce_access_control = enforce_access_control
        self.use_web_source = use_web_source
        self.use_sharepoint_source = use_sharepoint_source

    def setup_search_manager(self):
        self.search_manager = SearchManager(
            self.search_info,
            self.search_analyzer_name,
            self.use_acls,
            False,  # use_parent_index_projection disabled for file-based ingestion
            self.embeddings,
            field_name_embedding=self.search_field_name_embedding,
            search_images=self.image_embeddings is not None,
            enforce_access_control=self.enforce_access_control,
            use_web_source=self.use_web_source,
            use_sharepoint_source=self.use_sharepoint_source,
        )

    async def setup(self):
        self.setup_search_manager()
        await self.search_manager.create_index()

        if (
            self.figure_processor is not None
            and self.figure_processor.strategy == MediaDescriptionStrategy.CONTENTUNDERSTANDING
        ):
            media_describer = await self.figure_processor.get_media_describer()
            if isinstance(media_describer, ContentUnderstandingDescriber):
                await media_describer.create_analyzer()
                self.figure_processor.mark_content_understanding_ready()

    async def run(self):
        self.setup_search_manager()
        if self.document_action == DocumentAction.Add:
            files = self.list_file_strategy.list()
            async for file in files:
                try:
                    blob_url = await self.blob_manager.upload_blob(file)
                    sections = await parse_file(
                        file,
                        self.file_processors,
                        self.category,
                        self.blob_manager,
                        self.image_embeddings,
                        figure_processor=self.figure_processor,
                    )
                    if sections:
                        await self.search_manager.update_content(sections, url=blob_url)
                finally:
                    if file:
                        file.close()
        elif self.document_action == DocumentAction.Remove:
            paths = self.list_file_strategy.list_paths()
            async for path in paths:
                await self.blob_manager.remove_blob(path)
                await self.search_manager.remove_content(path)
        elif self.document_action == DocumentAction.RemoveAll:
            await self.blob_manager.remove_blob()
            await self.search_manager.remove_content()


class UploadUserFileStrategy:
    """
    Strategy for ingesting a file that has already been uploaded to a ADLS2 storage account
    """

    def __init__(
        self,
        search_info: SearchInfo,
        file_processors: dict[str, FileProcessor],
        blob_manager: AdlsBlobManager,
        search_field_name_embedding: Optional[str] = None,
        embeddings: Optional[OpenAIEmbeddings] = None,
        image_embeddings: Optional[ImageEmbeddings] = None,
        enforce_access_control: bool = False,
        figure_processor: Optional[FigureProcessor] = None,
        graphrag_client: Optional["GraphRAGClient"] = None,  # Optional GraphRAG integration
    ):
        self.file_processors = file_processors
        self.embeddings = embeddings
        self.image_embeddings = image_embeddings
        self.search_info = search_info
        self.blob_manager = blob_manager
        self.figure_processor = figure_processor
        self.graphrag_client = graphrag_client  # For Neo4j integration
        self.search_manager = SearchManager(
            search_info=self.search_info,
            search_analyzer_name=None,
            use_acls=True,
            use_parent_index_projection=False,
            embeddings=self.embeddings,
            field_name_embedding=search_field_name_embedding,
            search_images=image_embeddings is not None,
            enforce_access_control=enforce_access_control,
        )
        self.search_field_name_embedding = search_field_name_embedding

    async def add_file(self, file: File, user_oid: str, folder_id: Optional[str] = None):
        """
        Add a file to the search index and optionally notify GraphRAG.
        
        Args:
            file: File object with content and metadata
            user_oid: User OID for access control
            folder_id: Optional folder ID for GraphRAG organization
        """
        sections = await parse_file(
            file,
            self.file_processors,
            None,
            self.blob_manager,
            self.image_embeddings,
            figure_processor=self.figure_processor,
            user_oid=user_oid,
        )
        if sections:
            await self.search_manager.update_content(sections, url=file.url)
        
        # Notify GraphRAG backend if configured
        if self.graphrag_client:
            try:
                from graphrag.client import GraphRAGDocument
                doc = GraphRAGDocument(
                    id=file.filename(),
                    title=file.filename(),
                    source=file.url or "",
                    metadata={"user_oid": user_oid},
                )
                await self.graphrag_client.notify_document_uploaded(
                    group_id=user_oid,  # Use user OID as group_id for B2C
                    document=doc,
                    folder_id=folder_id,
                    trigger_indexing=True,
                )
                logger.info(f"Notified GraphRAG of document upload: {file.filename()}")
            except Exception as e:
                logger.warning(f"Failed to notify GraphRAG of upload: {e}")
                # Don't fail the upload if GraphRAG notification fails

    async def remove_file(self, filename: str, oid: str):
        """
        Remove a file from the search index and optionally from GraphRAG.
        
        Args:
            filename: Name of the file to remove
            oid: User OID
        """
        if filename is None or filename == "":
            logging.warning("Filename is required to remove a file")
            return
        await self.search_manager.remove_content(filename, oid)
        
        # Notify GraphRAG backend if configured
        if self.graphrag_client:
            try:
                await self.graphrag_client.delete_document(
                    group_id=oid,  # Use user OID as group_id for B2C
                    document_id=filename,
                    hard_delete=True,  # Permanently remove from Neo4j
                )
                logger.info(f"Deleted document from GraphRAG: {filename}")
            except Exception as e:
                logger.warning(f"Failed to delete document from GraphRAG: {e}")
                # Don't fail the removal if GraphRAG deletion fails


# Type hint for optional import
try:
    from graphrag.client import GraphRAGClient
except ImportError:
    GraphRAGClient = None  # type: ignore
