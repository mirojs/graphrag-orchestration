# Repository Backup to Azure Storage Account

This guide provides scripts and instructions for backing up your git repository to an Azure Storage Account using `git clone --mirror` for complete repository preservation.

## 🎯 Overview

The backup solution includes:
- **Complete repository mirror**: All branches, tags, and refs
- **Compressed archives**: Efficient storage with gzip compression
- **Azure Storage integration**: Secure cloud storage
- **Easy restoration**: Scripts for quick repository restoration
- **Automated cleanup**: Temporary file management

## 📋 Prerequisites

1. **Azure CLI** installed and configured
2. **Git** installed
3. **Azure Storage Account** (scripts can help create one)
4. **Appropriate permissions** to storage account

### Install Azure CLI (if needed)
```bash
# Ubuntu/Debian
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# Or using package manager
sudo apt-get update
sudo apt-get install azure-cli
```

### Login to Azure
```bash
az login
```

## 🚀 Quick Start

### 1. Configuration
Copy the environment template and fill in your values:
```bash
cp azure-backup.env.template .env
# Edit .env with your Azure Storage Account details
```

### 2. Quick Backup (Recommended)
For immediate backup with minimal configuration:
```bash
# Edit the storage account name in quick_backup.sh
./quick_backup.sh
```

### 3. Full Featured Backup
For advanced features and configuration:
```bash
# Set environment variables or edit the script
export AZURE_STORAGE_ACCOUNT_NAME="your-storage-account"
export AZURE_STORAGE_CONTAINER="repo-backups"

./backup_repo_to_azure.sh
```

## 📁 Files Included

| File | Purpose |
|------|---------|
| `backup_repo_to_azure.sh` | Main backup script with full features |
| `quick_backup.sh` | Simplified backup for immediate use |
| `restore_repo.sh` | Repository restoration script |
| `azure-backup.env.template` | Configuration template |
| `README-BACKUP.md` | This documentation |

## 🔧 Detailed Usage

### Main Backup Script
```bash
./backup_repo_to_azure.sh
```

**Features:**
- ✅ Prerequisites validation
- ✅ Git mirror creation
- ✅ Archive compression
- ✅ Azure Storage upload
- ✅ Upload verification
- ✅ Automatic cleanup
- ✅ Restore instructions

### Quick Backup Script
```bash
# Edit storage account name in the script first
./quick_backup.sh
```

**Features:**
- 🚀 Fast execution
- 📦 Single archive creation
- ☁️ Direct Azure upload
- 🧹 Automatic cleanup

### Repository Restoration
```bash
./restore_repo.sh <storage-account> [container] <backup-name> [restore-directory]
```

**Examples:**
```bash
# Restore with default container
./restore_repo.sh mystorageaccount repo-backups my-repo-20250823-143022

# Restore to specific directory
./restore_repo.sh mystorageaccount repo-backups my-repo-20250823-143022 ./my-project
```

## 🏗️ Azure Storage Setup

### Create Storage Account (if needed)
```bash
# Set variables
RESOURCE_GROUP="your-resource-group"
STORAGE_ACCOUNT="your-storage-account"
LOCATION="eastus"

# Create resource group
az group create --name $RESOURCE_GROUP --location $LOCATION

# Create storage account
az storage account create \
    --name $STORAGE_ACCOUNT \
    --resource-group $RESOURCE_GROUP \
    --location $LOCATION \
    --sku Standard_LRS \
    --kind StorageV2
```

### Create Container
```bash
az storage container create \
    --name repo-backups \
    --account-name your-storage-account \
    --auth-mode login
```

## 📊 Backup Format

The backup creates a complete mirror of your repository:

```
backup-archive.tar.gz
└── your-repo.git/
    ├── branches/
    ├── hooks/
    ├── info/
    ├── objects/
    ├── refs/
    ├── config
    ├── description
    ├── HEAD
    └── packed-refs
```

## 🔄 Restoration Process

1. **Download** archive from Azure Storage
2. **Extract** the tar.gz file
3. **Clone** from the .git mirror
4. **Verify** repository integrity

```bash
# Manual restoration steps
az storage blob download \
    --name 'my-repo-20250823-143022.tar.gz' \
    --container-name 'repo-backups' \
    --account-name 'mystorageaccount' \
    --file 'backup.tar.gz' \
    --auth-mode login

tar -xzf backup.tar.gz
git clone my-repo.git restored-repo
cd restored-repo
git log --oneline -10  # Verify
```

## 🔐 Security Considerations

### Authentication Methods
1. **Interactive Login** (Default): `az login`
2. **Managed Identity**: For Azure VMs/App Services
3. **Service Principal**: For automation

### Permissions Required
- **Storage Blob Data Contributor** role on storage account
- **Reader** role on storage account (minimum)

### Best Practices
- Use dedicated storage account for backups
- Enable soft delete on storage account
- Configure lifecycle management for old backups
- Use private endpoints for sensitive repositories

## 📈 Automation Options

### Scheduled Backups with Cron
```bash
# Add to crontab (crontab -e)
# Daily backup at 2 AM
0 2 * * * /path/to/your/repo/backup_repo_to_azure.sh

# Weekly backup on Sundays at 1 AM
0 1 * * 0 /path/to/your/repo/backup_repo_to_azure.sh
```

### GitHub Actions Integration
```yaml
name: Backup Repository
on:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM
  workflow_dispatch:

jobs:
  backup:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
        with:
          fetch-depth: 0  # Full history
      
      - name: Azure CLI Login
        uses: azure/login@v1
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}
      
      - name: Run Backup
        run: ./backup_repo_to_azure.sh
        env:
          AZURE_STORAGE_ACCOUNT_NAME: ${{ secrets.STORAGE_ACCOUNT }}
```

## 🗂️ Backup Management

### List Available Backups
```bash
az storage blob list \
    --container-name repo-backups \
    --account-name your-storage-account \
    --auth-mode login \
    --query '[].{Name:name, Size:properties.contentLength, Modified:properties.lastModified}' \
    --output table
```

### Delete Old Backups
```bash
# Delete backups older than 30 days
az storage blob delete-batch \
    --source repo-backups \
    --account-name your-storage-account \
    --auth-mode login \
    --pattern '*.tar.gz' \
    --if-modified-since $(date -d '30 days ago' --iso-8601)
```

## 🆘 Troubleshooting

### Common Issues

1. **"Not logged into Azure CLI"**
   ```bash
   az login
   ```

2. **"Storage account not found"**
   ```bash
   # Verify storage account exists
   az storage account show --name your-storage-account
   ```

3. **"Permission denied"**
   ```bash
   # Check permissions
   az role assignment list --assignee $(az account show --query user.name -o tsv) --all
   ```

4. **"Git repository not found"**
   ```bash
   # Ensure you're in a git repository
   git status
   ```

### Debug Mode
Add `set -x` to any script for verbose output:
```bash
#!/bin/bash
set -x  # Enable debug mode
set -e  # Exit on error
```

## 💡 Tips and Best Practices

1. **Test restoration** regularly to ensure backups work
2. **Use descriptive names** with timestamps
3. **Monitor storage costs** with Azure Cost Management
4. **Set up alerts** for backup failures
5. **Document your backup strategy** for team members
6. **Consider geo-redundant storage** for critical repositories
7. **Implement backup retention policies** to manage costs

## 📞 Support

For issues related to:
- **Azure CLI**: [Azure CLI Documentation](https://docs.microsoft.com/en-us/cli/azure/)
- **Azure Storage**: [Azure Storage Documentation](https://docs.microsoft.com/en-us/azure/storage/)
- **Git**: [Git Documentation](https://git-scm.com/doc)

## 🔄 Version History

- **v1.0**: Initial backup and restore scripts
- **v1.1**: Added quick backup option
- **v1.2**: Enhanced error handling and verification
- **v1.3**: Added automation examples and documentation
