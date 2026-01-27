"""
Example: Using the Simplified Document Analysis Service

This script demonstrates how to use the new simplified document analysis
service as a drop-in replacement for Azure Content Understanding.
"""

import asyncio
import logging
import sys
import os

# Add parent directory to path to import app modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'graphrag-orchestration'))

from app.services.simple_document_analysis_service import (
    SimpleDocumentAnalysisService,
    DocumentAnalysisBackend,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def example_check_backend_info():
    """Example: Check available backends and configuration."""
    logger.info("Example: Checking backend configuration")
    
    service = SimpleDocumentAnalysisService()
    info = service.get_backend_info()
    
    logger.info(f"Available backends: {info['available_backends']}")
    logger.info(f"Selected backend: {info['selected_backend']}")
    logger.info(f"Configuration: {info['configuration']}")


async def main():
    """Run example."""
    logger.info("=" * 60)
    logger.info("Simplified Document Analysis Service - Example")
    logger.info("=" * 60)
    
    # Check configuration
    await example_check_backend_info()
    
    logger.info("=" * 60)
    logger.info("Example complete!")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
