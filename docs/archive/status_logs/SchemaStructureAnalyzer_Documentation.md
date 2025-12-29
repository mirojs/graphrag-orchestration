# SchemaStructureAnalyzer Documentation

## Overview

The `SchemaStructureAnalyzer` is a custom meta-schema designed to automate the analysis and documentation of other JSON schemas. It leverages Azure Content Understanding's AI capabilities to generate hierarchical tables, field relationships, visualizations, and best practices for any schema structure.

---

## Purpose

- **Automated Schema Documentation**: Instantly generate professional, hierarchical documentation for any JSON schema.
- **Meta-Analysis**: Acts as a schema that analyzes other schemas, producing structured, editable, and visual outputs.
- **AI-Powered**: Uses Azure Content Understanding to extract, organize, and visualize schema details.

---

## Structure

### Top-Level Definition
```json
{
  "name": "SchemaStructureAnalyzer",
  "description": "Analyze JSON schema structures and generate hierarchical table representations",
  "fields": { ... }
}
```

### Main Analysis Categories

#### 1. SchemaOverview
- **Purpose**: High-level summary of the schema
- **Fields**:
  - `SchemaName`: Name of the schema
  - `TotalFields`: Total number of fields
  - `SchemaComplexity`: Complexity rating (Simple, Moderate, Complex)
  - `PrimaryPurpose`: Main use case

#### 2. HierarchicalStructure
- **Purpose**: Hierarchical table of all fields
- **Fields**:
  - `Level`: Hierarchy level (1, 2, 3, ...)
  - `FieldName`: Name of the field
  - `DataType`: Data type (object, array, string, etc.)
  - `Method`: Extraction method (generate, extract, ...)
  - `Description`: Field description
  - `ParentField`: Parent field name
  - `Required`: Whether the field is required

#### 3. FieldRelationships
- **Purpose**: Map relationships and dependencies between fields
- **Fields**:
  - `SourceField`: Source field in the relationship
  - `TargetField`: Target field
  - `RelationshipType`: Type (Contains, References, ...)
  - `Impact`: Effect on extraction

#### 4. SchemaVisualization
- **Purpose**: Visual representations of the schema
- **Fields**:
  - `TreeStructure`: ASCII tree of the schema
  - `TableFormat`: Pipe-separated table
  - `MarkdownTable`: Markdown-formatted table

#### 5. UsagePatterns
- **Purpose**: Best practices and usage patterns
- **Fields**:
  - `Pattern`: Pattern name
  - `Description`: Pattern description
  - `Benefits`: Benefits of the pattern
  - `Example`: Example usage

---

## Example Usage

1. **Upload a schema** to Azure Blob Storage.
2. **Run SchemaStructureAnalyzer** via Azure Content Understanding API.
3. **Receive output**:
   - Hierarchical table of fields
   - Visual tree and markdown documentation
   - Field relationships and best practices
4. **Edit and save** the extracted schema as needed.

---

## Benefits
- Eliminates manual schema documentation
- Produces clear, hierarchical, and visual outputs
- Enables schema versioning and best practice sharing
- Integrates with automated pipelines for continuous schema analysis

---

## Example Output (Markdown Table)

| Level | FieldName | DataType | Method | Description | ParentField | Required |
|-------|-----------|----------|--------|-------------|-------------|----------|
| 1     | Invoice   | object   | generate | Root object |             | Yes      |
| 2     | Amount    | number   | extract  | Invoice total| Invoice     | Yes      |
| 2     | Date      | string   | extract  | Invoice date | Invoice     | Yes      |

---

## Innovation

The `SchemaStructureAnalyzer` is a meta-schema that turns Azure Content Understanding into a schema documentation engine, enabling instant, professional, and editable documentation for any JSON schema structure.
