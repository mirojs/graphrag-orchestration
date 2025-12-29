# Multi-Language Support (i18n) - Implementation Guide

## Overview

Multi-language support has been successfully implemented using **react-i18next**, the industry standard for React internationalization. The system currently supports:
- 🇺🇸 English (en) - Default
- 🇪🇸 Spanish (es)
- 🇫🇷 French (fr)
- 🇹🇭 Thai (th)

## Files Created

### 1. **Core Configuration**
- `src/i18n.ts` - Main i18next configuration with language detection and initialization

### 2. **Translation Files**
- `src/locales/en/translation.json` - English translations
- `src/locales/es/translation.json` - Spanish translations  
- `src/locales/fr/translation.json` - French translations
- `src/locales/th/translation.json` - Thai translations

### 3. **Components**
- `src/Components/LanguageSwitcher/LanguageSwitcher.tsx` - Language selection dropdown in header

### 4. **Integration Points**
- `src/index.tsx` - i18n initialization (imports `./i18n`)
- `src/Components/Header/Header.tsx` - Language switcher added to header
- `src/ProModeComponents/SchemaTab.tsx` - Example conversion (proof of concept)

## How It Works

### 1. **Automatic Language Detection**
The system automatically detects user language preference in this order:
1. localStorage (if user previously selected a language)
2. Browser language settings

### 2. **Language Switching**
Users can switch languages using the flag icon 🌐 in the header toolbar (next to the theme toggle).

### 3. **Using Translations in Components**

```tsx
import { useTranslation } from 'react-i18next';

const MyComponent = () => {
  const { t } = useTranslation();
  
  return (
    <div>
      <h1>{t('proMode.schema.management')}</h1>
      <Button>{t('proMode.buttons.save')}</Button>
    </div>
  );
};
```

### 4. **Translation Keys Structure**

```json
{
  "proMode": {
    "schema": {
      "management": "Schema Management",
      "createNew": "Create New",
      ...
    },
    "buttons": {
      "save": "Save",
      "cancel": "Cancel",
      ...
    }
  },
  "common": {
    "loading": "Loading...",
    "error": "An error occurred",
    ...
  },
  "header": {
    "title": "AI Document Reasoning",
    ...
  }
}
```

## Current Implementation Status

### ✅ Completed
- [x] i18n infrastructure setup
- [x] Language detection and persistence
- [x] Translation files for 3 languages (EN, ES, FR)
- [x] Language switcher in header
- [x] SchemaTab partially converted (proof of concept)

### 🔄 Partially Complete
- SchemaTab: ~20% of strings converted
  - ✅ Main header and buttons
  - ✅ AI Enhancement section
  - ✅ No schemas message
  - ⏳ Dialog boxes
  - ⏳ Field table headers
  - ⏳ Error messages

### 📋 Remaining Work

#### High Priority
1. **Complete SchemaTab conversion** (~4-6 hours)
   - Convert all dialog titles and messages
   - Convert field table headers and labels
   - Convert error and success messages
   - Convert placeholder text

2. **Convert FilesTab** (~2-3 hours)
   - File upload interface
   - File list and actions
   - Error messages

3. **Convert PredictionTab** (~2-3 hours)
   - Analysis interface
   - Results display
   - Error handling

#### Medium Priority
4. **Add missing languages** (Optional)
   - German, Japanese, Chinese, etc.
   - ~30 minutes per language (translation time)

5. **TypeScript improvements**
   - Create type-safe translation key types
   - Add autocomplete for translation keys

#### Low Priority
6. **Date/Number formatting**
   - Locale-aware date formatting
   - Currency and number formatting

7. **RTL language support** (if needed)
   - CSS adjustments for Arabic/Hebrew
   - Direction-aware layouts

## How to Add a New Language

1. Create a new translation file:
   ```bash
   src/locales/de/translation.json  # German example
   ```

2. Copy the structure from `en/translation.json` and translate

3. Add to `src/i18n.ts`:
   ```typescript
   import deTranslation from './locales/de/translation.json';
   
   const resources = {
     en: { translation: enTranslation },
     es: { translation: esTranslation },
     fr: { translation: frTranslation },
     th: { translation: thTranslation },
     de: { translation: deTranslation },  // Add here
   };
   ```

4. Add to language switcher (`src/Components/LanguageSwitcher/LanguageSwitcher.tsx`):
   ```typescript
   const languages: Language[] = [
     { code: 'en', name: 'English', flag: '🇺🇸' },
     { code: 'es', name: 'Español', flag: '🇪🇸' },
     { code: 'fr', name: 'Français', flag: '🇫🇷' },
     { code: 'th', name: 'ไทย', flag: '🇹🇭' },
     { code: 'de', name: 'Deutsch', flag: '🇩🇪' },  // Add here
   ];
   ```

## How to Convert a Component

### Before:
```tsx
<Button>Create New</Button>
<Text>No schemas found.</Text>
```

### After:
```tsx
import { useTranslation } from 'react-i18next';

const MyComponent = () => {
  const { t } = useTranslation();
  
  return (
    <>
      <Button>{t('proMode.schema.createNew')}</Button>
      <Text>{t('proMode.schema.noSchemasFound')}</Text>
    </>
  );
};
```

## Testing

### Manual Testing
1. Build and run the app
2. Click the language switcher (flag icon) in the header
3. Select different languages
4. Verify:
   - Text changes in header buttons
   - SchemaTab strings change
   - Language persists on page reload

### Quick Test Commands
```bash
# From the workspace root
cd ./code/content-processing-solution-accelerator/infra/scripts
./docker-build.sh

# Or for quick dev testing
cd code/content-processing-solution-accelerator/src/ContentProcessorWeb
npm start
```

## Performance Considerations

✅ **No Performance Impact**
- Translations are bundled at build time (no runtime fetching)
- Small JSON files (~5-10KB per language)
- react-i18next is highly optimized
- No additional network requests

## Dependencies Added

```json
{
  "i18next": "^25.5.3",
  "i18next-browser-languagedetector": "^8.0.2",
  "react-i18next": "^12.3.1" (already existed via react-tiff)
}
```

## Best Practices

1. **Always use translation keys**, never hardcode strings
2. **Use meaningful key hierarchies**: `proMode.schema.createNew` not `button1`
3. **Keep translations short and clear**
4. **Use placeholders for dynamic content**:
   ```tsx
   t('proMode.schema.fieldCount', { count: 5 })
   // English: "5 fields"
   // Spanish: "5 campos"
   ```
5. **Provide context in translation files** with comments if needed

## Future Enhancements

- [ ] Add translation management UI for non-developers
- [ ] Integrate with translation services (Locize, Crowdin, etc.)
- [ ] Add missing translations warnings in dev mode
- [ ] Create translation extraction tool to find untranslated strings

## Support

For questions or issues:
1. Check the [react-i18next documentation](https://react.i18next.com/)
2. Review existing converted components (SchemaTab) for examples
3. Test changes using the language switcher in the header

---

**Status**: ✅ Infrastructure Complete | 🔄 Partial Implementation | 📋 Ready for Full Conversion
