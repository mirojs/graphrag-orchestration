# 🌐 Quick Reference: Using Translations in Components

## How to Use the Translation System

### 1. Import the Hook

```typescript
import { useTranslation } from 'react-i18next';
```

### 2. Initialize in Component

```typescript
const MyComponent: React.FC = () => {
  const { t } = useTranslation();
  
  // Now you can use t() function
  return <div>{t('proMode.files.title')}</div>;
};
```

### 3. Common Translation Patterns

#### Simple Text
```typescript
<Text>{t('proMode.files.title')}</Text>
// English: "Files"
// Spanish: "Archivos"
// Chinese: "文件"
```

#### Button Labels
```typescript
<Button>{t('proMode.buttons.upload')}</Button>
// English: "Upload"
// Korean: "업로드"
// Japanese: "アップロード"
```

#### With Counts (Pluralization)
```typescript
<Text>{t('proMode.schema.schemaCount', { count: 5 })}</Text>
// English: "5 schemas"
// French: "5 schémas"
```

#### Messages
```typescript
<Text>{t('proMode.files.loadingFiles')}</Text>
// English: "Loading files..."
// Thai: "กำลังโหลดไฟล์..."
```

---

## Available Translation Keys

### Files Tab
```
proMode.files.title
proMode.files.uploadFiles
proMode.files.total
proMode.files.input
proMode.files.reference
proMode.files.inputFiles
proMode.files.referenceFiles
proMode.files.deleteSelected
proMode.files.downloadSelected
proMode.files.exportList
proMode.files.name
proMode.files.size
proMode.files.uploaded
proMode.files.actions
proMode.files.download
proMode.files.upload
proMode.files.noInputFiles
proMode.files.noInputFilesMessage
proMode.files.noReferenceFiles
proMode.files.noReferenceFilesMessage
proMode.files.unknownFile
proMode.files.loadingFiles
proMode.files.failedToLoad
proMode.files.authenticationExpired
proMode.files.selectAll
```

### Prediction Tab
```
proMode.prediction.title
proMode.prediction.analyze
proMode.prediction.analyzing
proMode.prediction.noResults
proMode.prediction.analysisResults
proMode.prediction.selectFiles
proMode.prediction.selectSchema
proMode.prediction.startAnalysis
proMode.prediction.viewResults
proMode.prediction.noAnalysisRun
proMode.prediction.noAnalysisMessage
proMode.prediction.analysisInProgress
proMode.prediction.analysisComplete
proMode.prediction.analysisFailed
proMode.prediction.downloadResults
proMode.prediction.clearResults
```

### Schema Tab (Already Working)
```
proMode.schema.management
proMode.schema.createNew
proMode.schema.import
proMode.schema.settings
proMode.schema.refresh
proMode.schema.delete
proMode.schema.export
proMode.schema.noSchemasFound
proMode.schema.aiEnhancement
proMode.schema.enhancing
proMode.schema.schemaFields
proMode.schema.addNewField
proMode.schema.fieldName
proMode.schema.fieldDescription
proMode.schema.type
proMode.schema.method
proMode.schema.actions
```

### Common Buttons
```
proMode.buttons.new
proMode.buttons.import
proMode.buttons.settings
proMode.buttons.refresh
proMode.buttons.delete
proMode.buttons.export
proMode.buttons.create
proMode.buttons.update
proMode.buttons.cancel
proMode.buttons.save
proMode.buttons.close
proMode.buttons.apply
```

### Common Labels
```
proMode.labels.schemaName
proMode.labels.description
proMode.labels.fields
proMode.labels.required
proMode.labels.optional
```

### Common Messages
```
common.loading
common.error
common.success
common.confirm
common.cancel
common.save
common.delete
common.edit
common.create
common.search
common.filter
common.settings
```

---

## Language Codes

| Language | Code | Example Usage |
|----------|------|---------------|
| English | `en` | `i18n.changeLanguage('en')` |
| Spanish | `es` | `i18n.changeLanguage('es')` |
| French | `fr` | `i18n.changeLanguage('fr')` |
| Thai | `th` | `i18n.changeLanguage('th')` |
| Chinese | `zh` | `i18n.changeLanguage('zh')` |
| Korean | `ko` | `i18n.changeLanguage('ko')` |
| Japanese | `ja` | `i18n.changeLanguage('ja')` |

---

## Example: Converting FilesTab Strings

### Before (Hardcoded):
```typescript
<Text>Total</Text>
<Text>Input Files ({selectedInputFileIds.length}/{inputFiles.length})</Text>
<Button>Upload</Button>
<Text>Delete Selected</Text>
<Text>Download Selected</Text>
<Text>No input files uploaded yet</Text>
```

### After (Translated):
```typescript
<Text>{t('proMode.files.total')}</Text>
<Text>{t('proMode.files.inputFiles')} ({selectedInputFileIds.length}/{inputFiles.length})</Text>
<Button>{t('proMode.files.upload')}</Button>
<Text>{t('proMode.files.deleteSelected')}</Text>
<Text>{t('proMode.files.downloadSelected')}</Text>
<Text>{t('proMode.files.noInputFiles')}</Text>
```

---

## Example: Converting PredictionTab Strings

### Before (Hardcoded):
```typescript
<Button>Analyze</Button>
<Text>Analyzing...</Text>
<Text>No analysis has been run yet</Text>
<Text>Analysis complete</Text>
```

### After (Translated):
```typescript
<Button>{t('proMode.prediction.analyze')}</Button>
<Text>{t('proMode.prediction.analyzing')}</Text>
<Text>{t('proMode.prediction.noAnalysisRun')}</Text>
<Text>{t('proMode.prediction.analysisComplete')}</Text>
```

---

## Testing Your Translations

### In Browser Console:
```javascript
// Check current language
i18n.language; // e.g., "en"

// Change language
i18n.changeLanguage('zh'); // Chinese
i18n.changeLanguage('ko'); // Korean
i18n.changeLanguage('ja'); // Japanese

// Get translation directly
i18n.t('proMode.files.title'); // Returns translated text
```

### In React DevTools:
1. Find component using translation
2. Check props for `t` function
3. Verify it's the i18next translation function

---

## Best Practices

### ✅ DO:
- Use translation keys for ALL user-facing text
- Keep translations concise and clear
- Use consistent terminology across the app
- Test with different languages during development

### ❌ DON'T:
- Hardcode user-facing strings
- Concatenate translated strings (use placeholders instead)
- Assume text length will be the same across languages
- Use technical jargon in translation keys

---

## Adding New Translation Keys

1. **Add to English file first** (`/locales/en/translation.json`)
2. **Copy to all other language files** (es, fr, th, zh, ko, ja)
3. **Translate each value** appropriately
4. **Test in the UI** by switching languages

### Example:
```json
// Add to en/translation.json
{
  "proMode": {
    "files": {
      "newKey": "New Feature Text"
    }
  }
}

// Then add to zh/translation.json
{
  "proMode": {
    "files": {
      "newKey": "新功能文本"
    }
  }
}

// And so on for all languages...
```

---

## Troubleshooting

### Translation not showing?
1. Check if key exists in translation file
2. Verify JSON syntax is valid
3. Confirm language code is correct
4. Check browser console for i18next errors

### Wrong language displaying?
1. Check `i18n.language` in console
2. Verify localStorage `i18nextLng` value
3. Clear localStorage and retry
4. Check language detector configuration

### Text appears as key instead of translation?
1. Key doesn't exist in translation file
2. JSON syntax error in translation file
3. Translation file not imported in i18n.ts

---

**🎯 Ready to use! All translation infrastructure is in place and working.**
