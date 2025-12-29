# Microsoft Samples fileListPath Analysis and Implementation

## Key Findings from Microsoft Azure Content Understanding Sample Code

### 1. fileListPath Purpose
Based on analysis of the official Microsoft sample repository (`Azure-Samples/azure-ai-content-understanding-python`), the `fileListPath` parameter serves a specific purpose:

- **NOT a directory path** - It's a path to a specific JSONL file
- **Selective inclusion mechanism** - Allows choosing specific reference files for each analysis
- **Dynamic file listing** - Should be created at analysis time with selected files only

### 2. Microsoft Sample Implementation Pattern

From `python/content_understanding_client.py`:
```python
KNOWLEDGE_SOURCE_LIST_FILE_NAME: str = "sources.jsonl"

def _get_pro_mode_reference_docs_config(
    self, storage_container_sas_url: str, storage_container_path_prefix: str
) -> List[Dict[str, str]]:
    return [{
        "kind": "reference",
        "containerUrl": storage_container_sas_url,
        "prefix": storage_container_path_prefix,
        "fileListPath": self.KNOWLEDGE_SOURCE_LIST_FILE_NAME,  # Points to "sources.jsonl"
    }]
```

### 3. sources.jsonl File Format

The `sources.jsonl` file contains one JSON object per line:
```jsonl
{"file": "contract1.pdf", "resultFile": "contract1.pdf.result.json"}
{"file": "invoice_template.pdf", "resultFile": "invoice_template.pdf.result.json"}
{"file": "policy_doc.pdf", "resultFile": "policy_doc.pdf.result.json"}
```

### 4. Dynamic Generation Process

From Microsoft sample `generate_knowledge_base_on_blob()`:
```python
# For each reference document:
resources.append({"file": analyze_item.filename, "resultFile": analyze_item.result_file_name})

# Upload the JSONL file:
await self.upload_jsonl_to_blob(
    container_client, resources, storage_container_path_prefix + self.KNOWLEDGE_SOURCE_LIST_FILE_NAME)
```

## Implementation Requirements

### Current Issue
Our implementation hardcodes `"fileListPath": "sources.jsonl"` but doesn't create this file dynamically based on selected reference files.

### Required Changes

1. **Analysis Time File Selection**: Allow users to specify which reference files to use for each analysis
2. **Dynamic sources.jsonl Creation**: Generate the file listing only selected reference files
3. **Per-Analysis Isolation**: Each analysis should have its own `sources.jsonl` file

### Solution Architecture

```
Analysis Request → Select Reference Files → Generate sources.jsonl → Create Analyzer → Run Analysis
```

### Benefits of This Approach

1. **Selective Reference Usage**: Not all uploaded reference files are used in every analysis
2. **Performance Optimization**: Only relevant reference files are processed
3. **Analysis Specificity**: Each analysis can use different combinations of reference files
4. **Cost Efficiency**: Reduced processing overhead for irrelevant reference documents
5. **Microsoft Compliance**: Follows exact pattern from official Microsoft samples

## Next Steps

1. Modify analyzer creation to generate dynamic `sources.jsonl` based on selected files
2. Add endpoint parameter for specifying which reference files to include
3. Create unique file paths for each analysis to avoid conflicts
4. Update knowledge sources configuration to use the generated file listing

This approach aligns perfectly with Microsoft's official implementation and addresses the user's concern about selective reference file usage.
