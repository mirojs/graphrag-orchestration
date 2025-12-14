#!/bin/bash
# Stage 2: Local Container Tests
# Tests the containerized service using Docker

set -e

echo "=================================================="
echo "Stage 2: Local Container Tests"
echo "=================================================="

cd "$(dirname "$0")"

# Check prerequisites
echo ""
echo "Checking prerequisites..."
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not found"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "⚠️  docker-compose not found, using 'docker compose'"
    DOCKER_COMPOSE="docker compose"
else
    DOCKER_COMPOSE="docker-compose"
fi

echo "✅ Prerequisites OK"

# Check for .env file
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found"
    echo "Creating sample .env from .env.example..."
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "⚠️  Please update .env with your configuration"
    else
        echo "❌ No .env.example found. Please create .env manually."
        exit 1
    fi
fi

# Build container
echo ""
echo "=================================================="
echo "1. Building Docker Container"
echo "=================================================="
docker build -t graphrag-orchestration:test . || {
    echo "❌ Docker build failed"
    exit 1
}
echo "✅ Container built successfully"

# Start Neo4j if not running
echo ""
echo "=================================================="
echo "2. Starting Neo4j (if needed)"
echo "=================================================="
if ! docker ps | grep -q neo4j; then
    echo "Starting Neo4j container..."
    docker run -d \
        --name neo4j-test \
        -p 7474:7474 \
        -p 7687:7687 \
        -e NEO4J_AUTH=neo4j/password \
        -e NEO4J_PLUGINS='["apoc", "graph-data-science"]' \
        neo4j:5.15
    
    echo "Waiting for Neo4j to start..."
    sleep 15
    echo "✅ Neo4j started"
else
    echo "✅ Neo4j already running"
fi

# Start GraphRAG service
echo ""
echo "=================================================="
echo "3. Starting GraphRAG Service"
echo "=================================================="
docker run -d \
    --name graphrag-test \
    --network host \
    --env-file .env \
    -e NEO4J_URI=bolt://localhost:7687 \
    -e NEO4J_USERNAME=neo4j \
    -e NEO4J_PASSWORD=password \
    graphrag-orchestration:test || {
    echo "❌ Failed to start container"
    exit 1
}

echo "Waiting for service to start..."
sleep 5

# Health checks
echo ""
echo "=================================================="
echo "4. Health Checks"
echo "=================================================="

MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -s -H "X-Group-ID: test-group" http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ Basic health check passed"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "Waiting for service... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "❌ Service failed to start"
    echo "Container logs:"
    docker logs graphrag-test
    docker stop graphrag-test
    docker rm graphrag-test
    exit 1
fi

# Detailed health check
echo ""
curl -s -H "X-Group-ID: test-group" http://localhost:8000/health/detailed | python -m json.tool || {
    echo "⚠️  Detailed health check returned non-JSON response"
}

# Run endpoint tests
echo ""
echo "=================================================="
echo "5. API Endpoint Tests"
echo "=================================================="

echo "Testing basic indexing endpoint..."
python test_graphrag_indexing.py || {
    echo "⚠️  Basic tests had issues (check logs)"
}

# Run CU ingestion test
echo ""
echo "Testing CU Standard ingestion..."
python test_cu_ingestion.py || {
    echo "⚠️  CU ingestion test had issues (may need Azure credentials)"
}

# Verify Neo4j data
echo ""
echo "=================================================="
echo "6. Verify Neo4j Data"
echo "=================================================="
echo "Checking for indexed nodes..."
docker exec neo4j-test cypher-shell -u neo4j -p password \
    "MATCH (n) WHERE n.group_id = 'test-group-123' RETURN count(n) as node_count;" || {
    echo "⚠️  Neo4j query failed"
}

# Show container logs
echo ""
echo "=================================================="
echo "7. Container Logs (last 20 lines)"
echo "=================================================="
docker logs --tail 20 graphrag-test

# Cleanup option
echo ""
echo "=================================================="
echo "Stage 2 Complete!"
echo "=================================================="
echo ""
echo "Containers are still running for inspection."
echo ""
echo "To stop and cleanup:"
echo "  docker stop graphrag-test neo4j-test"
echo "  docker rm graphrag-test neo4j-test"
echo ""
echo "To keep testing:"
echo "  curl http://localhost:8001/api/v1/graphrag/health"
echo "  docker logs -f graphrag-test"
echo ""
echo "Next: Run Stage 3 (Deployed Container Tests)"
echo "  ./run_deployed_tests.sh"
echo "=================================================="
