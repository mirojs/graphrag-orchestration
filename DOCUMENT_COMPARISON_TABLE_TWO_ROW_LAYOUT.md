# Document Comparison Table Layout Improvement

## Change Summary
Redesigned the `DocumentsComparisonTable` to display each document pair as **two consecutive rows** instead of one wide row, making the table easier to read and compare.

## Problem
The previous layout displayed Invoice and Contract data side-by-side in a single row with 8 columns:

```
| # | Invoice Field | Invoice Value | Invoice Source | Contract Field | Contract Value | Contract Source | Actions |
```

This created very wide rows that were:
- **Hard to scan**: Eyes had to travel horizontally across many columns
- **Difficult to compare**: Values were far apart
- **Required scrolling**: Table was too wide for most screens
- **Visually cluttered**: Too much information in one row

## Solution
New layout uses **two rows per document pair** with only 6 columns:

```
| # | Document | Field      | Value    | Source          | Actions |
|---|----------|------------|----------|-----------------|---------|
| 1 | Invoice  | Total Amt  | $50,000  | invoice.pdf p.1 |    ↕    |
|   | Contract | Total Amt  | $60,000  | contract.pdf p.2|    ↕    |
```

### Layout Details:
- **Row 1 (Invoice)**: Blue background badge "📄 Invoice"
- **Row 2 (Contract)**: Green background badge "📋 Contract"
- **Document # column**: Spans both rows, centered vertically
- **Actions column**: Spans both rows with Compare button
- **Separator**: Thicker border between document pairs (2px vs 1px)

## Benefits

### ✅ **Improved Readability**
- Narrower table fits on screen without horizontal scroll
- Related information grouped vertically (easier eye movement)
- Clear visual distinction between Invoice (blue) and Contract (green)

### ✅ **Better Comparison**
- Values are aligned vertically for easy comparison
- Document pairs visually grouped with shared row number
- Thicker borders separate different document pairs

### ✅ **Cleaner UI**
- Reduced from 8 columns to 6 columns
- Minimum width reduced from 900px to 700px
- Less horizontal scrolling on smaller screens

### ✅ **Maintained Functionality**
- Compare button still spans both rows (one click per pair)
- All information preserved (no data loss)
- Page numbers still displayed with source documents

## Visual Structure

### Before (Single Row):
```
┌────┬───────────────┬───────────────┬───────────────┬───────────────┬───────────────┬───────────────┬─────────┐
│ #  │ Invoice Field │ Invoice Value │ Invoice Src   │ Contract Field│ Contract Value│ Contract Src  │ Actions │
├────┼───────────────┼───────────────┼───────────────┼───────────────┼───────────────┼───────────────┼─────────┤
│ 1  │ Total Amount  │ $50,000       │ inv.pdf p.1   │ Total Amount  │ $60,000       │ cont.pdf p.2  │ Compare │
└────┴───────────────┴───────────────┴───────────────┴───────────────┴───────────────┴───────────────┴─────────┘
                                     VERY WIDE - REQUIRES SCROLL →
```

### After (Two Rows):
```
┌────┬──────────┬──────────────┬─────────┬──────────────┬─────────┐
│ #  │ Document │ Field        │ Value   │ Source       │ Actions │
├────┼──────────┼──────────────┼─────────┼──────────────┼─────────┤
│    │ Invoice  │ Total Amount │ $50,000 │ inv.pdf p.1  │    ↕    │
│ 1  ├──────────┼──────────────┼─────────┼──────────────┤    ↕    │
│    │ Contract │ Total Amount │ $60,000 │ cont.pdf p.2 │    ↕    │
╞════╪══════════╪══════════════╪═════════╪══════════════╪═════════╡  ← Thicker separator
│    │ Invoice  │ Payment Terms│ Net-30  │ inv.pdf p.1  │    ↕    │
│ 2  ├──────────┼──────────────┼─────────┼──────────────┤    ↕    │
│    │ Contract │ Payment Terms│ Net-60  │ cont.pdf p.2 │    ↕    │
└────┴──────────┴──────────────┴─────────┴──────────────┴─────────┘
                      NARROWER - FITS ON SCREEN
```

## Technical Implementation

### Key Changes:
1. **Header columns reduced**: 8 → 6 columns
2. **Table minimum width**: 900px → 700px
3. **Row structure**: Used `rowSpan={2}` for Document # and Actions columns
4. **React.Fragment**: Wrapped two rows per document pair
5. **Color coding**: 
   - Invoice: `colorPaletteBlueForeground2` background
   - Contract: `colorPaletteGreenForeground2` background
6. **Border styling**:
   - 1px between Invoice/Contract rows of same pair
   - 2px between different document pairs
   - Last pair has no bottom border

### Code Structure:
```tsx
{documentsArray.map((doc, pairIndex) => (
  <React.Fragment key={`pair-${pairIndex}`}>
    {/* Invoice Row */}
    <tr>
      <td rowSpan={2}>#{pairIndex + 1}</td>
      <td>📄 Invoice</td>
      <td>{DocumentAField}</td>
      <td>{DocumentAValue}</td>
      <td>{DocumentASource}</td>
      <td rowSpan={2}><CompareButton /></td>
    </tr>
    
    {/* Contract Row */}
    <tr>
      <td>📋 Contract</td>
      <td>{DocumentBField}</td>
      <td>{DocumentBValue}</td>
      <td>{DocumentBSource}</td>
    </tr>
  </React.Fragment>
))}
```

## User Experience Impact

### For Analysis Tab Users:
- ✅ Faster scanning of inconsistencies
- ✅ Easier to spot value differences (vertical alignment)
- ✅ Less horizontal scrolling
- ✅ Clearer visual grouping of document pairs

### For Category View:
- ✅ More inconsistencies visible without scrolling
- ✅ Better use of vertical space
- ✅ Reduced cognitive load (fewer columns to process)

### For Document Pair View:
- ✅ Consistent layout across both grouping modes
- ✅ Document pair headers + two-row table = excellent clarity

## Accessibility Improvements

1. **Color + Icons**: Blue/Green backgrounds PLUS emoji icons (📄/📋) for color-blind users
2. **Semantic HTML**: Proper use of `rowSpan` for screen readers
3. **Clear labels**: "Invoice" and "Contract" explicitly labeled in each row
4. **Logical reading order**: Row-by-row reading makes sense (Invoice, then Contract)

## Files Changed
- ✅ `DocumentsComparisonTable.tsx` - Redesigned table layout with two-row structure

## Testing Recommendations

### Visual Tests:
1. Verify Invoice rows have blue background badges
2. Verify Contract rows have green background badges
3. Check Document # column spans both rows correctly
4. Confirm Actions button spans both rows and is vertically centered
5. Validate thicker borders between document pairs (2px vs 1px)

### Functional Tests:
1. Compare button works for each document pair
2. All data displays correctly (no missing fields)
3. Page numbers visible in source cells
4. Table doesn't require horizontal scroll on standard screens (1366px+)

### Edge Cases:
1. Single document pair (2 rows total)
2. Many document pairs (10+ pairs = 20+ rows)
3. Long field values (test word wrapping)
4. Missing page numbers (handle gracefully)

## Backward Compatibility
- ✅ No API changes
- ✅ Same props interface
- ✅ All data still displayed
- ✅ Compare functionality unchanged
- ✅ Only visual layout changed

## Related Work
This complements other recent improvements:
- Document-pair grouping as default mode
- Button order swap (Document Pair first)
- Theming with Fluent UI v9 tokens
