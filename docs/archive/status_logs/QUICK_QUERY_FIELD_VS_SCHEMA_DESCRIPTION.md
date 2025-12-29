# Quick Query: Field Description vs Schema Description

**Date**: January 17, 2025  
**Status**: ✅ CLARIFIED  
**Impact**: Critical understanding - Which description does Azure Content Understanding use?

---

## The Key Insight

**Azure Content Understanding uses the FIELD description with `method: "generate"`, NOT the schema description!**

```json
{
  "id": "quick_query_master",
  "description": "Master schema for quick query feature",  // ← NOT used by AI
  "fieldSchema": {
    "fields": {
      "QueryResult": {
        "type": "string",
        "method": "generate",
        "description": "Summarize the 5 files"  // ← THIS is what the AI uses!
      }
    }
  }
}
```

---

## Why Update Both?

### Field Description (Primary - Used by AI)
```python
# THIS IS CRITICAL - Azure Content Understanding reads this
existing_complete_schema["fieldSchema"]["fields"]["QueryResult"]["description"] = prompt
```

**Purpose**: Tell Azure Content Understanding what to generate  
**Used by**: AI analysis engine  
**Example**: "Summarize the key financial metrics from the uploaded documents"

### Schema Description (Secondary - Used by UI)
```python
# This is for UI display - helps users see current query in schema list
existing_complete_schema["description"] = prompt
```

**Purpose**: Show users what the current query is  
**Used by**: UI schema list, schema details page  
**Example**: Same as field description for consistency

---

## Update Priority

```python
# ✅ CORRECT ORDER: Field description FIRST (most critical)
if "fieldSchema" in existing_complete_schema and \
   "fields" in existing_complete_schema["fieldSchema"] and \
   "QueryResult" in existing_complete_schema["fieldSchema"]["fields"]:
    # 1. Update field description (AI prompt) - CRITICAL
    existing_complete_schema["fieldSchema"]["fields"]["QueryResult"]["description"] = prompt
    print(f"[QuickQuery] Updated field description (AI prompt): {prompt[:100]}...")
else:
    raise Exception("Schema structure invalid - missing QueryResult field")

# 2. Update schema description (UI display) - Nice to have
existing_complete_schema["description"] = prompt
```

**Why this order?**
1. **Fail fast**: If field structure is invalid, we error immediately
2. **Priority clear**: Field description is critical, schema description is bonus
3. **Error handling**: If field update fails, schema description won't be updated

---

## What Happens in Azure Content Understanding

### When You Execute a Query

1. **Frontend** sends prompt: "Summarize the 5 files"
2. **Backend** updates field description in schema:
   ```json
   {
     "QueryResult": {
       "method": "generate",
       "description": "Summarize the 5 files"  // ← Updated
     }
   }
   ```

3. **Analysis orchestration** sends schema to Azure Content Understanding
4. **Azure AI** sees field with `method: "generate"`:
   - Reads the description: "Summarize the 5 files"
   - Analyzes the uploaded documents
   - Generates a summary based on that description

5. **Result** returns as `QueryResult` field value

### The Schema Description is NOT Sent to AI

Azure Content Understanding API receives:
```json
{
  "analyzerRequest": {
    "fields": {
      "QueryResult": {
        "method": "generate",
        "description": "Summarize the 5 files"  // ← Only this matters!
      }
    }
  }
}
```

The schema-level `description` field is metadata - it's never sent to the AI.

---

## Code Implementation

### File: `proMode.py` (update-prompt endpoint)

**Lines 12409-12420**:
```python
# 🔧 Update ONLY the field description (this is what Azure Content Understanding uses)
# The field with method: "generate" is the AI prompt
if "fieldSchema" in existing_complete_schema and \
   "fields" in existing_complete_schema["fieldSchema"] and \
   "QueryResult" in existing_complete_schema["fieldSchema"]["fields"]:
    # This is the CRITICAL update - Azure Content Understanding uses this field description
    existing_complete_schema["fieldSchema"]["fields"]["QueryResult"]["description"] = prompt
    print(f"[QuickQuery] Updated field description (AI prompt): {prompt[:100]}...")
else:
    raise Exception("Schema structure invalid - missing QueryResult field")

# Also update schema-level description for UI display purposes
# This helps users see the current query when viewing the schema list
existing_complete_schema["description"] = prompt
```

**Lines 12374-12381** (Cosmos DB metadata):
```python
# Update the description in metadata (Cosmos DB)
# This is for UI display - shows current query in schema list
update_result = collection.update_one(
    {"id": QUICK_QUERY_MASTER_SCHEMA_ID},
    {
        "$set": {
            "description": prompt  // ← For UI display
        }
    }
)
```

---

## Testing

### Verify Field Description is Used

**Test 1: Different prompts produce different results**
```python
# Query 1
prompt = "Summarize the financial data"
# Expected: Summary of financial information

# Query 2
prompt = "Extract all dates mentioned"
# Expected: List of dates

# Query 3
prompt = "Identify the main entities (people, companies, locations)"
# Expected: List of entities
```

If the AI generates different outputs based on the prompt, it confirms the field description is being used.

### Verify Schema Description is Display-Only

**Test 2: Schema description changes don't affect AI**
```python
# Update only schema description (not field description)
schema["description"] = "Something completely different"

# Execute query with original field description
# Expected: AI still uses field description, ignores schema description
```

---

## Common Mistakes

### ❌ WRONG: Only updating schema description
```python
# This does NOT affect the AI!
existing_complete_schema["description"] = prompt
# AI still uses old field description
```

### ❌ WRONG: Updating wrong field
```python
# Updating a field without method: "generate"
existing_complete_schema["fieldSchema"]["fields"]["OtherField"]["description"] = prompt
# AI won't use this for generation
```

### ✅ CORRECT: Update the generate field
```python
# Update the field with method: "generate"
existing_complete_schema["fieldSchema"]["fields"]["QueryResult"]["description"] = prompt
# AI uses this for generation
```

---

## Architecture Diagram

```
User Input: "Summarize the 5 files"
    ↓
Backend update-prompt endpoint
    ↓
┌─────────────────────────────────────┐
│ Update Field Description (CRITICAL) │
│ fieldSchema.fields.QueryResult      │
│   .description = prompt             │
│   .method = "generate"              │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ Update Schema Description (UI)      │
│ schema.description = prompt         │
└─────────────────────────────────────┘
    ↓
Save to Blob Storage
    ↓
Update Cosmos DB metadata
    ↓
┌─────────────────────────────────────┐
│ Analysis Orchestration              │
│ Reads schema from blob              │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ Azure Content Understanding         │
│ Reads QueryResult field:            │
│   - method: "generate"              │
│   - description: "Summarize..."     │
│ Generates response                  │
└─────────────────────────────────────┘
    ↓
Result: Summary of the 5 files
```

---

## Summary

1. **Field description** (`fieldSchema.fields.QueryResult.description`):
   - ✅ Used by Azure Content Understanding AI
   - ✅ CRITICAL - This is the actual prompt
   - ✅ Must have `method: "generate"`

2. **Schema description** (`schema.description`):
   - ℹ️ Used by UI for display
   - ℹ️ NOT sent to AI
   - ℹ️ Nice to have for UX

3. **Update order**: Field first (critical), schema second (bonus)

4. **Both updated**: For consistency and good UX

---

**Status**: ✅ **CLARIFIED**  
**Code**: Correct - Updates field description (AI) first, then schema description (UI)  
**Ready for deployment**: YES
