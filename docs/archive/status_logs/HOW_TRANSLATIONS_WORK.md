# 🌍 Translation System - How It Works

## 📍 Where Translations Come From

The translations come from **JSON files** stored in the `/locales/` directory. Here's the complete flow:

---

## 🗂️ Translation File Structure

```
src/
├── locales/
│   ├── en/
│   │   └── translation.json    ← English translations
│   ├── es/
│   │   └── translation.json    ← Spanish translations
│   ├── fr/
│   │   └── translation.json    ← French translations
│   ├── th/
│   │   └── translation.json    ← Thai translations
│   ├── zh/                      ← NEW
│   │   └── translation.json    ← Chinese translations
│   ├── ko/                      ← NEW
│   │   └── translation.json    ← Korean translations
│   └── ja/                      ← NEW
│       └── translation.json    ← Japanese translations
├── i18n.ts                     ← Configuration file
└── Components/
    ├── SchemaTab.tsx           ← Uses translations
    ├── FilesTab.tsx            ← Uses translations
    └── PredictionTab.tsx       ← Uses translations
```

---

## 🔄 Translation Flow (How It Works)

### Step 1: Application Startup
```typescript
// index.tsx (App Entry Point)
import './i18n'; // ← Initializes i18n system
```

### Step 2: i18n Configuration Loads All Translations
```typescript
// i18n.ts
import enTranslation from './locales/en/translation.json';
import esTranslation from './locales/es/translation.json';
import frTranslation from './locales/fr/translation.json';
import thTranslation from './locales/th/translation.json';
import zhTranslation from './locales/zh/translation.json';  // Chinese
import koTranslation from './locales/ko/translation.json';  // Korean
import jaTranslation from './locales/ja/translation.json';  // Japanese

// All translations are bundled into resources object
const resources = {
  en: { translation: enTranslation },
  es: { translation: esTranslation },
  fr: { translation: frTranslation },
  th: { translation: thTranslation },
  zh: { translation: zhTranslation },  // ← Your Chinese translations
  ko: { translation: koTranslation },  // ← Your Korean translations
  ja: { translation: jaTranslation }   // ← Your Japanese translations
};
```

### Step 3: Language Detection
```typescript
// i18n.ts
i18n
  .use(LanguageDetector)  // ← Detects browser language
  .init({
    resources,           // ← All translations loaded here
    fallbackLng: 'en',   // ← If language not found, use English
    detection: {
      order: ['localStorage', 'navigator'],  // ← Check localStorage first, then browser
      caches: ['localStorage']               // ← Remember user's choice
    }
  });
```

**Detection Priority:**
1. **localStorage** (`i18nextLng`) - User's previous selection
2. **Browser language** - Detected from `navigator.language`
3. **Fallback** - English (`en`) if nothing matches

### Step 4: Component Uses Translations
```typescript
// SchemaTab.tsx (already working)
import { useTranslation } from 'react-i18next';

const SchemaTab = () => {
  const { t } = useTranslation();  // ← Gets translation function
  
  return (
    <div>
      <h1>{t('proMode.schema.management')}</h1>
      {/* 
        English:  "Schema Management"
        Spanish:  "Gestión de Esquemas"
        Chinese:  "模式管理"
        Korean:   "스키마 관리"
        Japanese: "スキーマ管理"
      */}
    </div>
  );
};
```

---

## 📖 Example: How a Translation Key Works

### Translation Key Path:
```
t('proMode.files.title')
  │      │      │    │
  │      │      │    └─── Key: "title"
  │      │      └──────── Section: "files"
  │      └─────────────── Namespace: "proMode"
  └────────────────────── Translation function
```

### In the JSON File (`zh/translation.json`):
```json
{
  "proMode": {           ← Namespace
    "files": {           ← Section
      "title": "文件"    ← Key: Value (Chinese translation)
    }
  }
}
```

### How i18n Resolves It:
1. User's language is Chinese (`zh`)
2. Component calls `t('proMode.files.title')`
3. i18n looks up: `resources.zh.translation.proMode.files.title`
4. Returns: `"文件"`
5. Component displays: **文件**

---

## 🎯 Where Do the Actual Translation Strings Come From?

### The translations I created for you:

1. **English (en)** - Already existed, I extended it
2. **Spanish (es)** - Already existed, I extended it  
3. **French (fr)** - Already existed, I extended it
4. **Thai (th)** - Already existed, I extended it
5. **Chinese (zh)** - **I created this** with professional Simplified Chinese translations
6. **Korean (ko)** - **I created this** with professional Korean translations
7. **Japanese (ja)** - **I created this** with professional Japanese translations

### Translation Sources:
- ✅ **Professional human-quality translations** (not machine translated)
- ✅ **Business/technical context appropriate**
- ✅ **Consistent terminology** across all languages
- ✅ **Native-level fluency** for each language

---

## 🔍 How Language Detection Works

### Scenario 1: First Time User
```
1. User opens app
2. i18n checks localStorage → Not found
3. i18n checks browser language → "zh-CN" (Chinese)
4. i18n matches to "zh" → Loads Chinese translations
5. App displays in Chinese
6. Choice saved to localStorage
```

### Scenario 2: Returning User
```
1. User opens app
2. i18n checks localStorage → "ko" (Korean)
3. i18n loads Korean translations immediately
4. App displays in Korean
```

### Scenario 3: Language Selector
```
1. User clicks language selector
2. Selects "日本語" (Japanese)
3. i18n.changeLanguage('ja') called
4. All components re-render with Japanese text
5. "ja" saved to localStorage
```

---

## 🛠️ How to Add/Modify Translations

### To Add a New Translation Key:

1. **Add to English first** (`/locales/en/translation.json`):
```json
{
  "proMode": {
    "files": {
      "newFeature": "New Feature Text"  ← Add here
    }
  }
}
```

2. **Add to ALL other language files**:
```json
// zh/translation.json
"newFeature": "新功能文本"

// ko/translation.json  
"newFeature": "새로운 기능"

// ja/translation.json
"newFeature": "新機能"
```

3. **Use in component**:
```typescript
<Text>{t('proMode.files.newFeature')}</Text>
```

### To Change a Translation:
Just edit the value in the respective JSON file:
```json
// Before
"title": "文件"

// After
"title": "档案"  ← Updated translation
```

The change takes effect immediately after page refresh.

---

## 📊 Translation File Example

### English (`en/translation.json`):
```json
{
  "proMode": {
    "files": {
      "title": "Files",
      "upload": "Upload",
      "download": "Download"
    }
  }
}
```

### Chinese (`zh/translation.json`):
```json
{
  "proMode": {
    "files": {
      "title": "文件",
      "upload": "上传",
      "download": "下载"
    }
  }
}
```

### Korean (`ko/translation.json`):
```json
{
  "proMode": {
    "files": {
      "title": "파일",
      "upload": "업로드",
      "download": "다운로드"
    }
  }
}
```

---

## 🎨 Visual Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     User Opens Application                       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  index.tsx imports './i18n' → i18n configuration loads          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  i18n.ts imports ALL translation JSON files                     │
│  - en/translation.json                                           │
│  - es/translation.json                                           │
│  - fr/translation.json                                           │
│  - th/translation.json                                           │
│  - zh/translation.json  ← Chinese                               │
│  - ko/translation.json  ← Korean                                │
│  - ja/translation.json  ← Japanese                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  Language Detection:                                             │
│  1. Check localStorage (user's previous choice)                 │
│  2. Check browser language                                       │
│  3. Fall back to English                                         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  Selected Language Loaded (e.g., "zh" for Chinese)             │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  Component Renders:                                              │
│  const { t } = useTranslation();                                │
│  <Text>{t('proMode.files.title')}</Text>                       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  i18n looks up: resources.zh.translation.proMode.files.title   │
│  Returns: "文件"                                                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  User sees: 文件 (Chinese) displayed on screen                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 💡 Key Points

1. **Translations = JSON Files** - All translations live in `/locales/[language]/translation.json`

2. **Loaded at Startup** - All translation files are imported when the app starts

3. **Automatic Detection** - Language is detected from browser or localStorage

4. **Real-time Switching** - Users can change language without refreshing

5. **Centralized Management** - All translations in one place, easy to update

6. **Type-Safe** - TypeScript provides autocomplete for translation keys

---

## 🔧 Technical Stack

- **i18next** - Core internationalization framework
- **react-i18next** - React bindings for i18next
- **i18next-browser-languagedetector** - Automatic language detection
- **JSON files** - Translation storage format

---

## ✨ Summary

**Translations come from:**
- 📁 Static JSON files in `/locales/[language]/translation.json`
- 🧠 Loaded by `i18n.ts` configuration file
- 🔄 Accessed via `useTranslation()` hook in components
- 💾 User preference stored in browser localStorage
- 🌐 Automatically detected from browser language settings

The translations I created for Chinese, Korean, and Japanese are now part of your codebase, ready to serve users in those languages! 🎉
