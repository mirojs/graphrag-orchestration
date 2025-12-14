# React JSON View Integration Guide

## Overview

This guide shows how to add JSON view capabilities to the existing Prediction Tab while keeping all current functionality intact.

## Recommended Library: react-json-view

### Installation

```bash
npm install react-json-view
npm install --save-dev @types/react-json-view
```

### Basic Integration

#### Step 1: Add View Toggle to PredictionTab.tsx

```tsx
import ReactJson from 'react-json-view';

// Add state for view mode
const [viewMode, setViewMode] = useState<'table' | 'json'>('table');

// Add toggle buttons in your UI
<div style={{ 
  display: 'flex', 
  gap: '8px', 
  marginBottom: '16px',
  alignItems: 'center' 
}}>
  <Text weight="semibold">View Mode:</Text>
  <Button
    appearance={viewMode === 'table' ? 'primary' : 'secondary'}
    onClick={() => setViewMode('table')}
    size="small"
  >
    Table View
  </Button>
  <Button
    appearance={viewMode === 'json' ? 'primary' : 'secondary'}
    onClick={() => setViewMode('json')}
    size="small"
  >
    JSON View
  </Button>
</div>
```

#### Step 2: Conditional Rendering

```tsx
{viewMode === 'table' ? (
  // Your existing DataRenderer component
  <DataRenderer
    fieldName={fieldName}
    fieldData={fieldData}
    onCompare={handleCompareFiles}
  />
) : (
  // New JSON view
  <ReactJson
    src={fieldData}
    name={fieldName}
    theme="rjv-default"  // or "monokai", "google", "ocean"
    collapsed={2}
    displayDataTypes={true}
    displayObjectSize={true}
    enableClipboard={true}
    quotesOnKeys={false}
    style={{
      padding: '12px',
      borderRadius: '4px',
      fontSize: '14px',
      backgroundColor: '#f8f9fa'
    }}
  />
)}
```

### Advanced: Field-Level JSON View

Add a "View JSON" button next to each field:

```tsx
<div style={{ 
  display: 'flex', 
  justifyContent: 'space-between',
  alignItems: 'center',
  marginBottom: '8px' 
}}>
  <div>
    <Text size={500} weight="semibold">{fieldName}</Text>
    <Text size={200} className={proModeStyles.mutedText}>
      ({fieldData.type})
    </Text>
  </div>
  
  <Button
    appearance="subtle"
    size="small"
    icon={<CodeBlock20Regular />}
    onClick={() => setShowJsonModal({ open: true, data: fieldData })}
  >
    View JSON
  </Button>
</div>

{/* JSON Modal */}
<Dialog 
  open={showJsonModal.open}
  onOpenChange={(_, data) => setShowJsonModal({ open: data.open, data: null })}
>
  <DialogSurface style={{ maxWidth: '800px' }}>
    <DialogBody>
      <DialogTitle>JSON Data - {fieldName}</DialogTitle>
      <DialogContent>
        <ReactJson
          src={showJsonModal.data || {}}
          theme="monokai"
          collapsed={false}
          enableClipboard={true}
          displayDataTypes={true}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setShowJsonModal({ open: false, data: null })}>
          Close
        </Button>
      </DialogActions>
    </DialogBody>
  </DialogSurface>
</Dialog>
```

## Alternative Libraries

### 1. @uiw/react-json-view (Lightweight)

```bash
npm install @uiw/react-json-view
```

```tsx
import JsonView from '@uiw/react-json-view';

<JsonView 
  value={data}
  displayDataTypes={false}
  style={{ 
    fontSize: 14,
    fontFamily: 'Monaco, monospace' 
  }}
/>
```

### 2. react-json-pretty (Simple)

```bash
npm install react-json-pretty
```

```tsx
import JSONPretty from 'react-json-pretty';

<JSONPretty 
  data={data}
  theme={{
    main: 'line-height:1.3;color:#66d9ef;background:#272822;overflow:auto;',
    error: 'line-height:1.3;color:#66d9ef;background:#272822;overflow:auto;',
    key: 'color:#f92672;',
    string: 'color:#fd971f;',
    value: 'color:#a6e22e;',
    boolean: 'color:#ac81fe;',
  }}
/>
```

## Hybrid Approach: Best of Both Worlds

### Component Structure

```tsx
interface ViewToggleProps {
  data: any;
  fieldName: string;
  defaultView?: 'table' | 'json';
  showCompareButton?: boolean;
  onCompare?: (evidence: string, fieldName: string, item: any, rowIndex?: number) => void;
}

const FlexibleDataView: React.FC<ViewToggleProps> = ({
  data,
  fieldName,
  defaultView = 'table',
  showCompareButton = true,
  onCompare
}) => {
  const [viewMode, setViewMode] = useState<'table' | 'json'>(defaultView);

  return (
    <Card>
      {/* View Toggle */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button
            appearance={viewMode === 'table' ? 'primary' : 'secondary'}
            onClick={() => setViewMode('table')}
            size="small"
            icon={<Table20Regular />}
          >
            Table
          </Button>
          <Button
            appearance={viewMode === 'json' ? 'primary' : 'secondary'}
            onClick={() => setViewMode('json')}
            size="small"
            icon={<CodeBlock20Regular />}
          >
            JSON
          </Button>
        </div>
        
        {viewMode === 'json' && (
          <Button
            appearance="subtle"
            size="small"
            icon={<Copy20Regular />}
            onClick={() => {
              navigator.clipboard.writeText(JSON.stringify(data, null, 2));
              toast.success('JSON copied to clipboard');
            }}
          >
            Copy JSON
          </Button>
        )}
      </div>

      {/* Content */}
      {viewMode === 'table' ? (
        showCompareButton && onCompare ? (
          <DataRenderer
            fieldName={fieldName}
            fieldData={data}
            onCompare={onCompare}
          />
        ) : (
          <DataTable fieldName={fieldName} data={data} onCompare={() => {}} />
        )
      ) : (
        <ReactJson
          src={data}
          name={fieldName}
          theme="rjv-default"
          collapsed={1}
          displayDataTypes={true}
          enableClipboard={true}
          style={{
            padding: '12px',
            borderRadius: '4px',
            fontSize: '14px'
          }}
        />
      )}
    </Card>
  );
};
```

### Usage

```tsx
// In PredictionTab.tsx
<FlexibleDataView
  data={fieldData}
  fieldName={fieldName}
  defaultView="table"
  showCompareButton={true}
  onCompare={handleCompareFiles}
/>
```

## Benefits of Hybrid Approach

1. **Table View** (Default):
   - ✅ Clean, readable format
   - ✅ Comparison buttons work
   - ✅ Optimized for Azure API structure
   - ✅ Better UX for non-technical users

2. **JSON View** (Toggle):
   - ✅ See raw data structure
   - ✅ Copy exact JSON for debugging
   - ✅ Explore nested objects easily
   - ✅ Better for developers/debugging

3. **User Choice**:
   - ✅ Users can switch based on their needs
   - ✅ Technical users get JSON
   - ✅ Business users get tables
   - ✅ No functionality lost

## Styling Themes for react-json-view

Available themes:
- `rjv-default` - Clean white background
- `monokai` - Dark theme (popular)
- `google` - Material-inspired
- `ocean` - Blue theme
- `bright:inverted` - Light on dark
- `summerfruit:inverted` - Colorful dark
- `apathy` - Grayscale
- `ashes` - Muted colors
- `bespin` - Brown/orange
- `brewer` - Scientific
- `chalk` - Colorful dark
- `codeschool` - Educational
- `colors` - Rainbow
- `eighties` - Retro
- `embers` - Warm colors
- `flat` - Modern flat
- `grayscale` - B&W
- `greenscreen` - Terminal style
- `harmonic` - Balanced
- `hopscotch` - Playful
- `isotope` - Technical
- `marrakesh` - Warm
- `mocha` - Coffee colors
- `paraiso` - Tropical
- `pop` - High contrast
- `railscasts` - Ruby
- `shapeshifter` - Dynamic
- `solarized` - Popular classic
- `threezerotwofour` - Unique
- `tomorrow` - Modern
- `tube` - London Underground
- `twilight` - Evening

## Recommendation

**Use the Hybrid Approach:**
1. Keep your current table view as default (it's great!)
2. Add a simple toggle to switch to JSON view
3. Users get the best of both worlds
4. No need to rebuild anything

**Don't replace your current system** - it works well and has features (like comparison buttons) that JSON libraries don't provide out of the box.

## Implementation Checklist

- [ ] Install `react-json-view` and types
- [ ] Add view mode state to PredictionTab
- [ ] Create toggle buttons for Table/JSON view
- [ ] Wrap existing DataRenderer in conditional
- [ ] Add ReactJson component for JSON mode
- [ ] Test both views with real data
- [ ] Add copy-to-clipboard for JSON view
- [ ] Document for users

## Notes

- Your current **DataRenderer** component is excellent for structured data display
- JSON view is complementary, not a replacement
- Users can choose the view that suits their workflow
- Developers can debug with raw JSON, users can work with clean tables
