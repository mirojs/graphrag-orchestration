"""Cloud/Deployed tests for GraphRAG Orchestration Service.

These tests validate the deployed Azure Container App against:
- All 4 routes (Vector, Local, Global, DRIFT)
- Question Bank from QUESTION_BANK_HYBRID_ROUTER_2025-12-29.md
- Multi-tenancy isolation
- Performance benchmarks

Prerequisites:
- GRAPHRAG_CLOUD_URL environment variable set
- TEST_GROUP_ID with indexed documents
- Documents indexed with text-embedding-3-large (3072 dims)

Run:
    pytest tests/cloud/ -v --cloud
"""
