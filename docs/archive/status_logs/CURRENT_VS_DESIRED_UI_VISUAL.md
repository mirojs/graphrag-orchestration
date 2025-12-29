# Current vs Desired UI - Visual Comparison

## 📊 What Console Logs Tell Us

```json
AllInconsistencies: [
  {
    Category: "PaymentTerms",
    InconsistencyType: "Payment Total Mismatch",
    Documents: [{
      DocumentASourceDocument: "invoice.pdf",
      DocumentBSourceDocument: "purchase_contract.pdf",
      DocumentAValue: "$610.00",
      DocumentBValue: "$29,900.00"
    }]  ← Array with 1 item = 1 table row
  },
  {
    Category: "Items",
    InconsistencyType: "Item Description Mismatch",
    Documents: [{
      DocumentASourceDocument: "invoice.pdf",
      DocumentBSourceDocument: "purchase_contract.pdf",
      DocumentAValue: "Consulting Services",
      DocumentBValue: "Vertical Platform Lift"
    }]  ← Array with 1 item = 1 table row
  }
]
```

---

## 🎨 Current UI (Category Grouping)

```
╔═══════════════════════════════════════════════════════╗
║ 📋 PaymentTerms (1 inconsistency)                    ║
╠═══════════════════════════════════════════════════════╣
║                                                       ║
║ Payment Total Mismatch                    Critical   ║
║ Evidence: Invoice shows $610.00 but contract...      ║
║ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ║
║ ℹ️ Each row represents a document pair comparison    ║
║                                                       ║
║ ┌─┬──────┬─────────┬───────────┬──────┬─────────┬──┐║
║ │#│Invoice│Invoice │Invoice    │Contr.│Contract │ ││║
║ │ │Field  │Value   │Source     │Field │Value    │ ││║
║ ├─┼──────┼─────────┼───────────┼──────┼─────────┼──┤║
║ │1│Amount│$610.00  │invoice.pdf│Total │$29,900  │[C││║
║ │ │Due   │         │Page 1     │Price │         │om││║
║ └─┴──────┴─────────┴───────────┴──────┴─────────┴──┘║
║                                                       ║
╚═══════════════════════════════════════════════════════╝

╔═══════════════════════════════════════════════════════╗
║ 📋 Items (1 inconsistency)                           ║
╠═══════════════════════════════════════════════════════╣
║                                                       ║
║ Item Description Mismatch                 High       ║
║ Evidence: Invoice lists Consulting Services...       ║
║ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ║
║ ℹ️ Each row represents a document pair comparison    ║
║                                                       ║
║ ┌─┬──────┬─────────┬───────────┬──────┬─────────┬──┐║
║ │#│Invoice│Invoice │Invoice    │Contr.│Contract │ ││║
║ │ │Field  │Value   │Source     │Field │Value    │ ││║
║ ├─┼──────┼─────────┼───────────┼──────┼─────────┼──┤║
║ │1│Servic│Consult. │invoice.pdf│Scope │Vertical │[C││║
║ │ │es    │Services │Page 1     │Work  │Lift...  │om││║
║ └─┴──────┴─────────┴───────────┴──────┴─────────┴──┘║
║                                                       ║
╚═══════════════════════════════════════════════════════╝
```

**Characteristics:**
- ✅ Correct rendering (each inconsistency = 1 table)
- ✅ Each table has 1 row (because `Documents.length = 1`)
- ℹ️ **Grouped by Category** (PaymentTerms, Items)
- ℹ️ Issues for same document pair are **separated**

---

## 🎯 Desired UI (Document-Pair Grouping)

```
╔═══════════════════════════════════════════════════════╗
║ 📄 invoice.pdf  ⚡  📄 purchase_contract.pdf         ║
║                                                       ║
║ 2 issues  │  Severity: Critical                      ║
╠═══════════════════════════════════════════════════════╣
║                                                       ║
║ 1️⃣  Payment Total Mismatch           [PaymentTerms]  ║
║ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ║
║ Invoice shows $610.00 but contract specifies         ║
║ $29,900.00. This vast difference indicates that      ║
║ payment terms do not align.                          ║
║                                                       ║
║     ┌────────────────────┐    ≠    ┌──────────────┐ ║
║     │ Invoice            │         │ Contract     │ ║
║     ├────────────────────┤         ├──────────────┤ ║
║     │ Amount Due         │         │ Total Price  │ ║
║     │ $610.00            │         │ $29,900.00   │ ║
║     │                    │         │              │ ║
║     │ 📄 invoice.pdf     │         │ 📄 purchase_ │ ║
║     │ Page 1             │         │    contract  │ ║
║     │                    │         │ Page 1       │ ║
║     └────────────────────┘         └──────────────┘ ║
║                                          [Compare]   ║
║                                                       ║
║ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ║
║                                                       ║
║ 2️⃣  Item Description Mismatch               [Items]  ║
║ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ║
║ Invoice lists Consulting Services whereas contract   ║
║ describes Vertical Platform Lift equipment.          ║
║                                                       ║
║     ┌────────────────────┐    ≠    ┌──────────────┐ ║
║     │ Invoice            │         │ Contract     │ ║
║     ├────────────────────┤         ├──────────────┤ ║
║     │ Services           │         │ Scope of Work│ ║
║     │ Consulting Svcs    │         │ Vertical Lift│ ║
║     │ Document Fee       │         │ Power System │ ║
║     │ Printing Fee       │         │ Custom Cab   │ ║
║     │                    │         │              │ ║
║     │ 📄 invoice.pdf     │         │ 📄 purchase_ │ ║
║     │ Page 1             │         │    contract  │ ║
║     │                    │         │ Page 1       │ ║
║     └────────────────────┘         └──────────────┘ ║
║                                          [Compare]   ║
║                                                       ║
║ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ║
║                                                       ║
║ 📑 Summary                                            ║
║ Documents: invoice.pdf (Page 1) ⚡                    ║
║            purchase_contract.pdf (Page 1)            ║
║ Severity Breakdown: Critical: 1  High: 1             ║
║                                                       ║
╚═══════════════════════════════════════════════════════╝
```

**Characteristics:**
- ✅ **Both issues shown together** (same document pair)
- ✅ Numbered list (1, 2) for easy reference
- ✅ Category badges for context
- ✅ Side-by-side value comparison
- ✅ Individual Compare buttons per issue
- ✅ Summary footer with severity breakdown

---

## 🔀 With Toggle (MetaArrayRenderer)

```
╔═══════════════════════════════════════════════════════╗
║ AllInconsistencies                                    ║
║                                                       ║
║ View: [🏷️ Group by Category] [📄 Group by Doc Pair] ║
╠═══════════════════════════════════════════════════════╣
║                                                       ║
║ ... content changes based on selected view ...       ║
║                                                       ║
╚═══════════════════════════════════════════════════════╝
```

**Allows users to switch between:**
- **Category View** → See all PaymentTerms issues across all documents
- **Document-Pair View** → See all issues for specific document comparison

---

## 📊 Comparison Table

| Aspect | Current (Category) | Desired (Doc-Pair) |
|--------|-------------------|-------------------|
| **Grouping** | By category (PaymentTerms, Items) | By document pair (invoice ⚡ contract) |
| **Tables** | 2 separate tables | 1 combined card |
| **Rows per table** | 1 row each | 2 numbered issues |
| **Use case** | "Show me all payment issues" | "Show me everything wrong with this comparison" |
| **When useful** | Analyzing patterns across docs | Reviewing specific document pair |
| **Navigation** | Scroll between categories | All issues visible at once |

---

## 🎬 User Journey

### Scenario: Reviewer checking invoice vs contract

**With Category Grouping (Current):**
```
1. See "PaymentTerms (1 inconsistency)" 
   → Click table → See $610 vs $29,900
2. Scroll down
3. See "Items (1 inconsistency)"
   → Click table → See Consulting vs Vertical Lift
4. Mental connection: "Oh, both are for same documents"
```

**With Document-Pair Grouping (Desired):**
```
1. See "invoice.pdf ⚡ purchase_contract.pdf - 2 issues"
2. Issue #1: Payment mismatch
3. Issue #2: Item mismatch
4. Immediate understanding: "This comparison has 2 problems"
```

---

## 💡 Why This Happens

**Your data structure (CORRECT ✅):**
```
Each inconsistency = Separate array item
Each array item = 1 Documents array entry
```

**Result:**
- 2 inconsistencies → 2 tables
- Each has 1 document pair → Each shows 1 row

**Alternative structure (if you wanted multiple rows in single table):**
```
Single inconsistency with multiple doc pairs:
{
  InconsistencyType: "General Mismatch",
  Documents: [
    { invoice1 vs contract1 },
    { invoice2 vs contract2 },
    { invoice3 vs contract3 }
  ]
}
```
This would show 3 rows in one table, but loses semantic meaning (different issue types).

---

## 🎯 Recommended Solution

**Use DocumentPairGroup component** which takes multiple inconsistencies and groups them by document pair:

```tsx
<DocumentPairGroup
  inconsistencies={[
    paymentTermsIssue,
    itemsIssue
  ]}
  onCompare={handleCompare}
/>
```

**Or use MetaArrayRenderer** for toggle flexibility:

```tsx
<MetaArrayRenderer
  fieldName="AllInconsistencies"
  data={allInconsistenciesData}
  onCompare={handleCompare}
  initialMode="document-pair"
/>
```

Both components are already built and tested! 🎉
