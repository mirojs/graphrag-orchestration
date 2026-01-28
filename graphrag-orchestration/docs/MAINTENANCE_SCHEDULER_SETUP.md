# Maintenance Job Scheduler Setup

This document describes how to configure automated maintenance jobs for the GraphRAG document lifecycle system.

## Overview

The maintenance system supports three tiers of operation:

| Tier | Operation | Trigger | Frequency |
|------|-----------|---------|-----------|
| 1 | Real-time deprecation | API call | On-demand |
| 2 | Async garbage collection | Scheduled | Hourly or after lifecycle events |
| 3 | GDS recompute | Scheduled | Daily or when stale |

## Azure Functions Timer Trigger (Recommended)

### 1. Create Azure Function App

```bash
# Create function app (if not exists)
az functionapp create \
  --resource-group $RESOURCE_GROUP \
  --consumption-plan-location $LOCATION \
  --runtime python \
  --runtime-version 3.11 \
  --functions-version 4 \
  --name graphrag-maintenance \
  --storage-account $STORAGE_ACCOUNT
```

### 2. Maintenance Function Code

Create `maintenance_timer/__init__.py`:

```python
import azure.functions as func
import httpx
import os
import logging

# GraphRAG API endpoint
API_BASE = os.environ.get("GRAPHRAG_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("GRAPHRAG_API_KEY", "")

async def main(timer: func.TimerRequest) -> None:
    """
    Timer-triggered maintenance job.
    
    Schedule: Every hour at minute 0 (0 * * * *)
    """
    logging.info("Starting scheduled maintenance job")
    
    headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}
    
    async with httpx.AsyncClient(timeout=300) as client:
        # Step 1: Get stale groups
        stale_resp = await client.get(
            f"{API_BASE}/maintenance/admin/groups/stale",
            headers=headers,
        )
        stale_groups = stale_resp.json().get("groups", [])
        
        for group in stale_groups:
            group_id = group["group_id"]
            logging.info(f"Processing stale group: {group_id}")
            
            # Step 2: Run all GC jobs for the group
            gc_resp = await client.post(
                f"{API_BASE}/maintenance/run-all-gc",
                headers={**headers, "X-Group-ID": group_id},
            )
            logging.info(f"GC result for {group_id}: {gc_resp.json()}")
            
            # Step 3: Trigger GDS recompute if needed
            if group.get("needs_gds_recompute"):
                gds_resp = await client.post(
                    f"{API_BASE}/maintenance/recompute-gds",
                    headers={**headers, "X-Group-ID": group_id},
                )
                logging.info(f"GDS recompute for {group_id}: {gds_resp.json()}")
    
    logging.info("Maintenance job completed")
```

### 3. Function Configuration

Create `maintenance_timer/function.json`:

```json
{
  "scriptFile": "__init__.py",
  "bindings": [
    {
      "name": "timer",
      "type": "timerTrigger",
      "direction": "in",
      "schedule": "0 0 * * * *"
    }
  ]
}
```

### 4. Schedule Options

| CRON Expression | Description |
|-----------------|-------------|
| `0 0 * * * *` | Every hour at minute 0 |
| `0 */15 * * * *` | Every 15 minutes |
| `0 0 */6 * * *` | Every 6 hours |
| `0 0 2 * * *` | Daily at 2 AM |
| `0 0 2 * * 0` | Weekly on Sunday at 2 AM |

## Kubernetes CronJob Alternative

For Kubernetes deployments:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: graphrag-maintenance
spec:
  schedule: "0 * * * *"  # Every hour
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: maintenance
            image: curlimages/curl:latest
            env:
            - name: API_URL
              valueFrom:
                configMapKeyRef:
                  name: graphrag-config
                  key: api_url
            - name: API_KEY
              valueFrom:
                secretKeyRef:
                  name: graphrag-secrets
                  key: api_key
            command:
            - /bin/sh
            - -c
            - |
              # Run maintenance for all stale groups
              curl -X POST "$API_URL/maintenance/run-all-gc" \
                -H "Authorization: Bearer $API_KEY" \
                -H "Content-Type: application/json"
          restartPolicy: OnFailure
```

## Celery Beat Alternative (Self-Hosted)

For Celery-based deployments:

```python
# celery_config.py
from celery import Celery
from celery.schedules import crontab

app = Celery('graphrag')
app.config_from_object('django.conf:settings', namespace='CELERY')

app.conf.beat_schedule = {
    'gc-orphan-entities': {
        'task': 'tasks.run_gc_job',
        'schedule': crontab(minute=0),  # Every hour
        'args': ('orphan_entities',),
    },
    'gc-stale-edges': {
        'task': 'tasks.run_gc_job',
        'schedule': crontab(minute=15),  # Every hour at :15
        'args': ('stale_edges',),
    },
    'gc-deprecated-vectors': {
        'task': 'tasks.run_gc_job',
        'schedule': crontab(minute=30),  # Every hour at :30
        'args': ('deprecated_vectors',),
    },
    'gds-recompute': {
        'task': 'tasks.recompute_gds_stale_groups',
        'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM
    },
}
```

## Manual Trigger via API

For ad-hoc maintenance:

```bash
# Run all GC jobs for a group
curl -X POST "https://your-api.com/maintenance/run-all-gc" \
  -H "X-Group-ID: your-group-id" \
  -H "Authorization: Bearer $API_KEY"

# Recompute GDS for a group
curl -X POST "https://your-api.com/maintenance/recompute-gds" \
  -H "X-Group-ID: your-group-id" \
  -H "Authorization: Bearer $API_KEY"

# Check group health
curl "https://your-api.com/maintenance/health" \
  -H "X-Group-ID: your-group-id" \
  -H "Authorization: Bearer $API_KEY"

# List all stale groups
curl "https://your-api.com/maintenance/admin/groups/stale" \
  -H "Authorization: Bearer $API_KEY"
```

## Monitoring & Alerts

### Recommended Alerts

1. **Stale Groups Threshold**: Alert if >10 groups have `gds_stale=true` for >24h
2. **GC Job Failures**: Alert on consecutive GC job failures
3. **Orphan Entity Growth**: Alert if orphan entity count grows >20% week-over-week

### Health Check Integration

```python
# Example: Azure Monitor custom metric
from azure.monitor.opentelemetry import configure_azure_monitor

configure_azure_monitor()

# In maintenance job:
from opentelemetry import metrics
meter = metrics.get_meter("graphrag.maintenance")
orphan_counter = meter.create_counter("orphan_entities_cleaned")
orphan_counter.add(result["deleted"], {"group_id": group_id})
```

## Best Practices

1. **Stagger GC jobs** - Don't run all GC types simultaneously to avoid Neo4j load spikes
2. **GDS recompute off-peak** - Schedule GDS recompute during low-traffic hours
3. **Batch processing** - Use bulk operations for groups with many documents
4. **Idempotency** - All maintenance jobs are idempotent; safe to retry on failure
5. **Logging** - Enable structured logging for maintenance jobs to track trends
