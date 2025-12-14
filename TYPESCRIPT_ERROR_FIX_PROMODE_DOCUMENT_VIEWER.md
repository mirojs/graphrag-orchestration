# TypeScript Error Fix - ProModeDocumentViewer isDarkMode Property

## 🐛 **Issue**
```
TS2322: Type '{ className: string; metadata: { mimeType: string; filename: string; }; urlWithSasToken: string; iframeKey: number; isDarkMode: boolean | undefined; }' is not assignable to type 'IntrinsicAttributes & IProModeDocumentViewerProps'.
Property 'isDarkMode' does not exist on type 'IntrinsicAttributes & IProModeDocumentViewerProps'.
```

The `isDarkMode` property was being passed to the `ProModeDocumentViewer` component but wasn't defined in the interface.

## ✅ **Fix Applied**

### **1. Updated Interface**
**File:** `src/ContentProcessorWeb/src/ProModeComponents/ProModeDocumentViewer.tsx`

```typescript
// Before
interface IProModeDocumentViewerProps {
    className?: string;
    metadata?: any;
    urlWithSasToken: string | undefined;
    iframeKey: number;
}

// After
interface IProModeDocumentViewerProps {
    className?: string;
    metadata?: any;
    urlWithSasToken: string | undefined;
    iframeKey: number;
    isDarkMode?: boolean;  // ✅ Added this property
}
```

### **2. Updated Component Function Signature**
```typescript
// Before
const ProModeDocumentViewer = ({ className, metadata, urlWithSasToken, iframeKey }: IProModeDocumentViewerProps) => {

// After  
const ProModeDocumentViewer = ({ className, metadata, urlWithSasToken, iframeKey, isDarkMode }: IProModeDocumentViewerProps) => {
```

## 📋 **Files Modified**
- ✅ `/src/ContentProcessorWeb/src/ProModeComponents/ProModeDocumentViewer.tsx`
- ✅ Verified other duplicate file already had the correct interface

## 🧪 **Verification**
- ✅ TypeScript compilation errors resolved
- ✅ Interface properly defines `isDarkMode?: boolean`
- ✅ Component function signature accepts the parameter
- ✅ FilesTab component correctly passes the property
- ✅ No breaking changes to existing functionality

## 🚀 **Result**
The Docker build should now complete successfully without TypeScript errors. The `isDarkMode` property is properly typed and can be used throughout the component for theme-aware styling.

---
*Fix completed - TypeScript error resolved*
