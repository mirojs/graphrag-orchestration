# Streaming Implementation Plan

## Overview
Replace nginx proxy approach with FastAPI StreamingResponse for direct file access from Azure Blob Storage.

## Backend Changes (FastAPI)

### 1. Add Streaming Endpoint
```python
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
import io
import urllib.parse

@router.get("/extract-fields/stream/{process_id}")
async def stream_extracted_file(
    process_id: str,
    app_config: AppConfiguration = Depends(get_app_config)
):
    """
    Stream file directly from Azure Blob Storage
    """
    try:
        # Get file from blob storage
        blob_helper = StorageBlobHelper(
            account_url=app_config.app_storage_blob_url,
            container_name=app_config.app_cps_processes
        )
        
        file_bytes = blob_helper.download_blob(
            blob_name=f"{process_id}/extracted_file.json"
        )
        
        file_stream = io.BytesIO(file_bytes)
        
        # Set appropriate headers
        headers = {
            "Content-Disposition": f"inline; filename=extracted_{process_id}.json",
            "Content-Type": "application/json",
            "Cache-Control": "no-cache"
        }
        
        return StreamingResponse(
            file_stream,
            media_type="application/json",
            headers=headers
        )
        
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"File not found: {str(e)}")

@router.get("/hierarchical-analysis/stream/{process_id}")
async def stream_hierarchical_file(
    process_id: str,
    app_config: AppConfiguration = Depends(get_app_config)
):
    """
    Stream hierarchical analysis results directly from Azure Blob Storage
    """
    try:
        blob_helper = StorageBlobHelper(
            account_url=app_config.app_storage_blob_url,
            container_name=app_config.app_cps_processes
        )
        
        file_bytes = blob_helper.download_blob(
            blob_name=f"{process_id}/hierarchical_analysis.json"
        )
        
        file_stream = io.BytesIO(file_bytes)
        
        headers = {
            "Content-Disposition": f"inline; filename=hierarchical_{process_id}.json",
            "Content-Type": "application/json"
        }
        
        return StreamingResponse(
            file_stream,
            media_type="application/json",
            headers=headers
        )
        
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Analysis not found: {str(e)}")
```

### 2. Enhanced Storage Helper
```python
class StorageBlobHelper:
    def stream_blob(self, blob_name: str, container_name: str = None) -> bytes:
        """
        Stream blob data directly for FastAPI responses
        """
        container_client = self._get_container_client(container_name)
        blob_client = container_client.get_blob_client(blob_name)
        
        try:
            # Check if blob exists
            blob_properties = blob_client.get_blob_properties()
            if blob_properties.size == 0:
                raise ValueError(f"Blob '{blob_name}' is empty.")
                
            # Download and return bytes
            download_stream = blob_client.download_blob()
            return download_stream.readall()
            
        except ResourceNotFoundError:
            raise ValueError(f"Blob '{blob_name}' not found in container.")
```

## Frontend Changes (React/TypeScript)

### 1. Update API Calls
```typescript
// Update SchemaTab.tsx to use streaming endpoints
const performDeterministicExtraction = async () => {
    try {
        setExtractionStatus('Extracting fields using streaming...');
        
        // Use streaming endpoint instead of proxy
        const streamingEndpoint = `${apiUrl}/extract-fields/stream/${processId}`;
        
        const response = await fetch(streamingEndpoint, {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Accept': 'application/json'
            }
        });
        
        if (!response.ok) {
            throw new Error(`Streaming failed: ${response.status}`);
        }
        
        const extractedData = await response.json();
        setExtractionResults(extractedData);
        setExtractionStatus('Fields extracted successfully via streaming');
        
    } catch (error) {
        console.error('Streaming extraction failed:', error);
        setExtractionStatus(`Extraction failed: ${error.message}`);
    }
};
```

### 2. Remove Proxy Dependencies
```typescript
// Remove proxy-specific logic and use direct API calls
const detectWorkingEndpoint = async (): Promise<string> => {
    const streamingEndpoints = [
        '/extract-fields/stream',
        '/hierarchical-analysis/stream'
    ];
    
    for (const endpoint of streamingEndpoints) {
        try {
            const response = await fetch(`${apiUrl}${endpoint}/test`, {
                method: 'HEAD',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            
            if (response.ok) {
                return endpoint;
            }
        } catch (error) {
            console.log(`Endpoint ${endpoint} not available`);
        }
    }
    
    throw new Error('No streaming endpoints available');
};
```

## nginx Configuration Changes

### 1. Simplified nginx Config
```nginx
server {
    listen 80;
    server_name localhost;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Only proxy general API calls, not file streaming
    location /api/ {
        proxy_pass http://api:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Standard timeouts
        proxy_timeout 60s;
        proxy_read_timeout 60s;
        proxy_connect_timeout 10s;
        client_max_body_size 10M;
    }

    # Static file serving for React app
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }
}
```

## Benefits of Streaming Approach

### 1. **Performance**
- Direct blob access without proxy overhead
- Better memory management with streaming
- Reduced latency for file operations

### 2. **Security**
- Backend controls all authentication
- Centralized authorization logic
- Better audit trail for file access

### 3. **Maintenance**
- Simpler nginx configuration
- All logic in FastAPI backend
- Easier debugging and monitoring

### 4. **Scalability**
- Azure Blob Storage native streaming
- Better handling of large files
- Efficient memory usage

## Migration Steps

1. **Phase 1**: Add streaming endpoints to FastAPI backend
2. **Phase 2**: Update frontend to use streaming endpoints
3. **Phase 3**: Test streaming functionality
4. **Phase 4**: Remove proxy configuration from nginx
5. **Phase 5**: Deploy and verify

## Considerations

### 1. **Authentication**
- Ensure all streaming endpoints are properly authenticated
- Handle token expiration gracefully

### 2. **Error Handling**
- Provide meaningful error messages for missing files
- Handle blob storage connection issues

### 3. **Caching**
- Implement appropriate cache headers
- Consider CDN integration for static assets

### 4. **Monitoring**
- Add logging for streaming operations
- Monitor blob storage usage and performance

## Conclusion

Using streaming instead of nginx proxy provides a more Azure-native, maintainable solution that follows Microsoft's reference implementation patterns. This approach eliminates proxy complexity while providing better control over file access and security.