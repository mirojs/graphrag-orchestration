# AI Schema Enhancement: Prompts, Patterns, and End-to-End Guide

This guide documents the actual prompts, API pattern, and artifacts used to enhance extraction schemas via Azure Content Understanding (2025-05-01-preview). It consolidates the real test prompts, frontend integration pattern, and links to the saved results in this repository.

- Key capability: Users type a natural-language request; Azure AI interprets intent and returns a production-ready enhanced schema.
- Result summary: 5/5 success in documented runs (see linked artifacts below).

## 1) Core enhancement prompt structure

The system uses a meta-analyzer pattern. A specialized analyzer is created with a concise purpose, and the user request is injected at analysis time.

Primary Enhancement Schema (minimal pattern):

```json
{
  "fieldSchema": {
    "name": "IntelligentSchemaEnhancer",
    "description": "Analyze user request '{user_request}' and generate an enhanced schema based on current schema context"
  }
}
```

At runtime, the request input (user_request) and the original schema context are provided to the analyzer to produce the enhanced schema proposition.

## 2) Specific test cases with real prompts (and analyzer IDs)

All of the following were verified in the saved artifact `intelligent_schema_enhancement_summary_1757780437.json`:

- Test Case 1: Adding New Fields
  - User Prompt: "I also want to extract payment due dates and payment terms"
  - Result: Success
  - Analyzer ID: `schema-enhancer-1757780378-1`

- Test Case 2: Removing Fields / Simplifying
  - User Prompt: "I don't need contract information anymore, just focus on invoice details"
  - Result: Success
  - Analyzer ID: `schema-enhancer-1757780390-2`

- Test Case 3: Expanding Existing Fields
  - User Prompt: "I want more detailed vendor information including address and contact details"
  - Result: Success
  - Analyzer ID: `schema-enhancer-1757780402-3`

- Test Case 4: Fundamental Restructuring
  - User Prompt: "Change the focus to compliance checking rather than basic extraction"
  - Result: Success
  - Analyzer ID: `schema-enhancer-1757780414-4`

- Test Case 5: Adding Complex Analytics
  - User Prompt: "Add tax calculation verification and discount analysis"
  - Result: Success
  - Analyzer ID: `schema-enhancer-1757780426-5`

Artifact:
- [intelligent_schema_enhancement_summary_1757780437.json](./intelligent_schema_enhancement_summary_1757780437.json)

## 3) Frontend integration: prompt-and-context assembly

In the frontend, a compact context object is assembled that combines the original schema, the user’s request, and explicit instructions for the analyzer.

Example (TypeScript-like shape):

```ts
const enhancementContext = {
  originalSchema: {
    name: originalSchemaForEnhancement.name,
    description: originalSchemaForEnhancement.description,
    fields: extractFieldsForDisplay(originalSchemaForEnhancement)
  },
  enhancementRequest: enhancementPrompt,
  instructions: `Analyze the provided schema and suggest improvements based on the user's request: "${enhancementPrompt}". Focus on adding relevant fields, improving descriptions, and optimizing field types for better document processing.`
};
```

Related references in this repo:
- `SCHEMA_TAB_IMPLEMENTATION_GUIDE.md`
- `complete_schema_tab_implementation.py`
- `schema_tab_interface_implementation.py`

## 4) Quick action prompts (predefined shortcuts)

- "Add common missing fields for better extraction accuracy"

These allow one-click enhancement without typing a custom natural-language prompt.

## 5) API call pattern (end-to-end)

High-level flow:
1. Current Schema + User Natural Language Input → Azure Content Understanding API (pro-mode analyzer)
2. AI Intent Analysis → Enhanced Schema Generation (candidate)
3. Schema Validation → Production-Ready Enhanced Schema

Analyzer lifecycle (pro-mode):
- Create analyzer (PUT) with a purpose-oriented `fieldSchema` (e.g., IntelligentSchemaEnhancer)
- Analyze (POST `:analyze`) with `contents` containing:
  - Original schema context (name/description/fields)
  - User enhancement request (natural language)
  - Instructions for how to transform/enhance
- Poll for result (GET) and read enhanced schema suggestion from the result payload

See also:
- `AI_ENHANCEMENT_DIRECT_IMPLEMENTATION.md`
- `AI_ENHANCEMENT_API_FIX_COMPLETE.md`
- `AZURE_API_2025_05_01_PREVIEW_FORMAT_UPDATE.md`

## 6) Contract at a glance

Inputs:
- Original schema context (name, description, fields) — the baseline to enhance
- User request (natural language) — e.g., add/remove/expand/restructure fields
- Optional instructions (system-styled guidance to the analyzer)

Outputs:
- Enhanced schema proposal that reflects the user’s intent
- Structured metadata for validation (e.g., field types, descriptions)

Success criteria:
- Enhanced schema remains consistent with the original domain
- Changes directly align with the user request
- Passes the project’s schema validation checks

## 7) Edge cases and safeguards

- Over-reduction: When removing fields (simplification), ensure required fields for downstream processes remain present.
- Over-expansion: When adding analytics (e.g., tax/discount checks), prefer optional fields that don’t break existing consumers.
- Type drift: Confirm that field types remain compatible with extraction and UI expectations.
- Validation: Run the enhanced schema through local validation (see testing files referenced below).

## 8) Validation and success metrics

- Verified success across 5 focused test cases (5/5).
- Tests and examples to review:
  - `test_enhanced_schema_generation.py`
  - `test_enhanced_schema_output.py`
  - `test_enhanced_schema_real_api.py`
  - `test_enhanced_schema_experiment.py`
  - `test_simple_enhanced_schema.py`
  - `test_simple_enhanced_working.py`

## 9) Developer quick-start pointers

- Backend logic (examples and helpers):
  - `intelligent_schema_enhancer.py`
  - `enhanced_azure_workflow.py`
  - `complete_schema_tab_implementation.py`

- Frontend wiring (patterns/spec):
  - `SCHEMA_TAB_IMPLEMENTATION_GUIDE.md`
  - `schema_tab_interface_implementation.py`

- Useful supporting docs:
  - `AI_ENHANCED_SCHEMA_OUTPUT_HANDLING_COMPLETE.md`
  - `SCHEMA_PREVIEW_AI_ENHANCEMENT_COMPLETE.md`

## 10) References & related artifacts in this repo

- Prompt/test artifact: [intelligent_schema_enhancement_summary_1757780437.json](./intelligent_schema_enhancement_summary_1757780437.json)
- Implementation & docs:
  - `intelligent_schema_enhancer.py`
  - `AI_ENHANCEMENT_DIRECT_IMPLEMENTATION.md`
  - `AI_ENHANCEMENT_ORCHESTRATION_REFACTOR.md`
  - `AI_ENHANCEMENT_ORCHESTRATION_REFACTORING_COMPLETE.md`
  - `AI_ENHANCEMENT_API_FIX_COMPLETE.md`
  - `AI_ENHANCED_SCHEMA_OUTPUT_HANDLING_COMPLETE.md`
  - `SCHEMA_TAB_IMPLEMENTATION_GUIDE.md`
  - `SCHEMA_PREVIEW_AI_ENHANCEMENT_COMPLETE.md`

---

If you want a compact cheatsheet version of this guide added to the README or a developer wiki, I can generate a one-page summary with a minimal payload example and a checklist for validation.
