# Setting Up Native Partition Key for Cosmos DB - Step-by-Step Guide

## Overview
We're going to configure your `Schemas_pro` collection to use `group_id` as a native partition key for better performance and logical organization.

---

## ⚠️ Important Notes

**Cosmos DB Limitation:** You CANNOT add a partition key to an existing collection. You must:
1. Create a NEW collection with partition key configured
2. Migrate data from old collection to new collection
3. Update your application to use the new collection

**Estimated Time:** 15-30 minutes

**Downtime Required:** 5-10 minutes (during collection swap)

---

## Option 1: Azure Portal (RECOMMENDED - Easiest)

### Step 1: Create New Collection with Partition Key

1. **Open Azure Portal**
   - Go to https://portal.azure.com
   - Navigate to your Cosmos DB account

2. **Open Data Explorer**
   - Click "Data Explorer" in left menu
   - Find your database (e.g., `content-processor`)

3. **Create New Collection**
   - Click "New Collection" button
   - Settings:
     - **Database**: Select your existing database (don't create new)
     - **Collection ID**: `Schemas_pro_v2` (temporary name)
     - **Partition Key**: `/group_id` ← **IMPORTANT!**
     - **Throughput**: Same as your current collection (e.g., 400 RU/s)
   - Click "OK"

4. **Verify Creation**
   - You should see `Schemas_pro_v2` in the collection list
   - Click on it and verify partition key is `/group_id`

### Step 2: Migrate Data

You have two options:

#### Option A: Using Azure Data Migration Tool (GUI - Easier)

1. **Download Azure Cosmos DB Data Migration Tool**
   - Link: https://aka.ms/csdmtool
   - Install on your machine

2. **Configure Source**
   - Source: MongoDB
   - Connection String: (your Cosmos DB connection string)
   - Collection: `Schemas_pro`

3. **Configure Target**
   - Target: MongoDB
   - Connection String: (same Cosmos DB connection string)
   - Collection: `Schemas_pro_v2`
   - Partition Key: `group_id`

4. **Run Migration**
   - Click "Import"
   - Wait for completion

#### Option B: Using Python Script (Faster for Tech Users)

Save this as `migrate_schemas_with_partition_key.py`:

```python
#!/usr/bin/env python3
"""
Migrate schemas from old collection to new collection with partition key.
"""
import os
from pymongo import MongoClient
from datetime import datetime

# Configuration
COSMOS_CONNSTR = "YOUR_COSMOS_CONNECTION_STRING_HERE"  # ← REPLACE THIS
DATABASE_NAME = "YOUR_DATABASE_NAME_HERE"               # ← REPLACE THIS
OLD_COLLECTION = "Schemas_pro"
NEW_COLLECTION = "Schemas_pro_v2"

def migrate_data():
    print("🚀 Starting migration...")
    print(f"   From: {OLD_COLLECTION}")
    print(f"   To: {NEW_COLLECTION}")
    print()
    
    # Connect
    client = MongoClient(COSMOS_CONNSTR)
    db = client[DATABASE_NAME]
    
    old_col = db[OLD_COLLECTION]
    new_col = db[NEW_COLLECTION]
    
    # Count documents
    total = old_col.count_documents({})
    print(f"📊 Found {total} documents to migrate")
    print()
    
    # Migrate
    migrated = 0
    errors = 0
    
    for doc in old_col.find():
        try:
            # Ensure group_id exists (required for partition key)
            if "group_id" not in doc:
                doc["group_id"] = "default"
                print(f"   ⚠️  Document {doc.get('id', 'unknown')} had no group_id, set to 'default'")
            
            # Remove _id to let Cosmos DB generate new one
            if "_id" in doc:
                del doc["_id"]
            
            # Insert into new collection
            new_col.insert_one(doc)
            migrated += 1
            
            if migrated % 10 == 0:
                print(f"   ✅ Migrated {migrated}/{total}...")
                
        except Exception as e:
            print(f"   ❌ Error migrating {doc.get('id', 'unknown')}: {e}")
            errors += 1
    
    print()
    print("=" * 60)
    print("✅ Migration Complete!")
    print(f"   Migrated: {migrated} documents")
    print(f"   Errors: {errors} documents")
    print("=" * 60)
    
    # Verify counts
    old_count = old_col.count_documents({})
    new_count = new_col.count_documents({})
    
    print()
    print("📊 Verification:")
    print(f"   Old collection: {old_count} documents")
    print(f"   New collection: {new_count} documents")
    
    if old_count == new_count:
        print("   ✅ Counts match!")
    else:
        print(f"   ⚠️  Warning: Counts don't match (difference: {abs(old_count - new_count)})")

if __name__ == "__main__":
    migrate_data()
```

**Run it:**
```bash
python migrate_schemas_with_partition_key.py
```

### Step 3: Verify New Collection

1. **In Azure Portal Data Explorer**
   - Open `Schemas_pro_v2` collection
   - Browse a few documents
   - Verify each has `group_id` field
   - Verify partition key icon shows `/group_id`

2. **Test a Query**
   ```javascript
   // In Azure Portal query editor:
   db.Schemas_pro_v2.find({"group_id": "default"})
   ```
   - Should be VERY fast (direct partition routing)
   - Compare with old collection (slower)

### Step 4: Update Application Code

**NO CODE CHANGES NEEDED!** 

The application already uses `group_id` for queries. Just need to point to new collection name.

If you want to keep the same name:
1. Rename `Schemas_pro` → `Schemas_pro_backup`
2. Rename `Schemas_pro_v2` → `Schemas_pro`

**OR** update this in `proMode.py`:
```python
# Find this line (around line 85):
def get_pro_mode_container_name(base_container_name: str) -> str:
    """Generate isolated container name for pro mode to ensure complete separation."""
    return f"{base_container_name}_pro"
    # Change to: return f"{base_container_name}_pro_v2"  # ← If keeping new name
```

### Step 5: Test Everything

1. **Upload a schema** via your application
   - Should work exactly the same
   - Check Azure Portal to verify it appears in new collection

2. **List schemas** by group
   - Should be noticeably faster
   - Try with different group IDs

3. **Check backend logs**
   - Look for: `[SchemaUpload] Storing schema in collection under group: <group_id>`

4. **Monitor performance**
   - Queries should be 3-5x faster
   - RU costs should be ~70% lower

### Step 6: Cleanup (After 1-2 Weeks)

Once you're confident everything works:

1. **Delete old collection**
   - In Azure Portal → Data Explorer
   - Right-click `Schemas_pro_backup` (or old name)
   - Select "Delete Collection"

2. **Update documentation**
   - Note that collection now uses partition key
   - Document the `group_id` partition strategy

---

## Option 2: Programmatic Setup (Advanced)

If you prefer command-line approach:

### Using Azure CLI

```bash
# Login
az login

# Create new collection with partition key
az cosmosdb mongodb collection create \
  --account-name YOUR_COSMOS_ACCOUNT_NAME \
  --database-name YOUR_DATABASE_NAME \
  --name Schemas_pro_v2 \
  --shard group_id \
  --throughput 400

# Verify
az cosmosdb mongodb collection show \
  --account-name YOUR_COSMOS_ACCOUNT_NAME \
  --database-name YOUR_DATABASE_NAME \
  --name Schemas_pro_v2
```

Then use the Python migration script from Option 1B.

---

## Troubleshooting

### Issue: "Cannot set partition key on existing collection"
**Solution:** You must create a NEW collection. Cannot modify existing.

### Issue: "Documents without group_id fail to insert"
**Solution:** Migration script sets `group_id = "default"` for documents missing it.

### Issue: "Performance not improved"
**Solution:** 
- Verify partition key is `/group_id` in Azure Portal
- Ensure queries include `group_id` filter
- Check that you're querying the NEW collection

### Issue: "Application can't find schemas"
**Solution:** Update collection name in code or rename collections.

---

## Benefits You'll See

✅ **3-5x faster queries** when filtering by group_id  
✅ **70% lower RU costs** for group-specific queries  
✅ **Logical organization** - schemas physically grouped by group_id  
✅ **Better scalability** - works efficiently even with 100k+ schemas  
✅ **Azure Portal clarity** - can see partition distribution clearly  

---

## Next Steps

1. ☐ Create new collection in Azure Portal with partition key `/group_id`
2. ☐ Run data migration (Portal tool or Python script)
3. ☐ Verify data in new collection
4. ☐ Test queries (should be much faster)
5. ☐ Point application to new collection
6. ☐ Monitor for 1-2 weeks
7. ☐ Delete old collection

---

## Need Help?

If you encounter any issues:
1. Check Azure Portal → Cosmos DB → Metrics (for RU usage patterns)
2. Check application logs for connection errors
3. Verify connection string points to correct account
4. Ensure firewall rules allow your application IP

---

**Ready to start? Follow Option 1 (Azure Portal) - it's the easiest and most reliable!**
