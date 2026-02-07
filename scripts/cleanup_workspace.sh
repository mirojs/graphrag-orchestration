#!/bin/bash
# Workspace Cleanup Script
# Cleans Docker cache, old images, and stale log files to free disk space
# Run periodically (weekly/bi-weekly) or when disk usage is high

set -e

echo "=========================================="
echo "Workspace Cleanup - $(date)"
echo "=========================================="
echo ""

# Check disk usage before cleanup
echo "=== Disk Usage BEFORE Cleanup ==="
df -h /afh | grep -v Filesystem
echo ""

echo "=== Docker Usage BEFORE Cleanup ==="
docker system df
echo ""

# 1. Clean Docker build cache
echo "=== Cleaning Docker Build Cache ==="
docker builder prune --all --force
echo ""

# 2. Clean old Docker images (keep images from last 72 hours = 3 days)
echo "=== Cleaning Old Docker Images (older than 72h) ==="
docker image prune -a --filter "until=72h" --force
echo ""

# 3. Clean dangling images
echo "=== Cleaning Dangling Images ==="
docker image prune --force
echo ""

# 4. Clean old log files (older than 7 days)
echo "=== Cleaning Old Log Files (older than 7 days) ==="
cd /afh/projects/graphrag-orchestration
OLD_LOGS=$(find . -name "*.log" -type f -mtime +7 | wc -l)
if [ "$OLD_LOGS" -gt 0 ]; then
    find . -name "*.log" -type f -mtime +7 -delete
    echo "Deleted $OLD_LOGS old log files"
else
    echo "No old log files found"
fi
echo ""

# 5. Clean Python cache files
echo "=== Cleaning Python Cache ==="
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true
find . -name "*.pyo" -delete 2>/dev/null || true
echo "Cleaned Python cache directories and .pyc files"
echo ""

# Check disk usage after cleanup
echo "=== Disk Usage AFTER Cleanup ==="
df -h /afh | grep -v Filesystem
echo ""

echo "=== Docker Usage AFTER Cleanup ==="
docker system df
echo ""

echo "=========================================="
echo "Cleanup Complete!"
echo "=========================================="
