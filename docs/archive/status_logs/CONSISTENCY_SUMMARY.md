# Consistency Summary (10x Multi-Input Runs)

This document consolidates the 10 repeatability runs for the Azure Content Understanding multi-input analysis. Each run used a fresh analyzer (unique analyzerId) and consistently returned 5 DocumentTypes. Minor type-label naming varied (e.g., "Contract" vs "Purchase Contract"), but titles remained stable.

- API version: 2025-05-01-preview
- Evidence doc: see `CLOUD_VS_TEST_INVESTIGATION_COMPLETE.md` → Test File Consistency (10 Runs)
- Result: 10/10 runs detected 5 DocumentTypes

## Per-run results and artifacts

| Run | analyzerId | Invoice | Warranty | Purchase Contract | Holding Tank Servicing Contract | Property Management Agreement | Artifact |
|---:|---|---|---|---|---|---|---|
| 1 | `multi-input-test-1758628887` | Contoso Lifts LLC Invoice #1256003 | BUILDERS LIMITED WARRANTY WITH ARBITRATION | PURCHASE CONTRACT | HOLDING TANK SERVICING CONTRACT | PROPERTY MANAGEMENT AGREEMENT (Short Term and/or Vacation/Holiday Rentals) | [result](./multi_input_results_1758628887/multi_document_analysis_result.json) |
| 2 | `multi-input-test-1758629096` | INVOICE #1256003 | BUILDERS LIMITED WARRANTY WITH ARBITRATION | PURCHASE CONTRACT | HOLDING TANK SERVICING CONTRACT | PROPERTY MANAGEMENT AGREEMENT | [result](./multi_input_results_1758629096/multi_document_analysis_result.json) |
| 3 | `multi-input-test-1758629273` | INVOICE # 1256003 | BUILDERS LIMITED WARRANTY WITH ARBITRATION | PURCHASE CONTRACT | HOLDING TANK SERVICING CONTRACT | PROPERTY MANAGEMENT AGREEMENT (Short Term and/or Vacation/Holiday Rentals) | [result](./multi_input_results_1758629273/multi_document_analysis_result.json) |
| 4 | `multi-input-test-1758629438` | Contoso Lifts LLC Invoice #1256003 | BUILDERS LIMITED WARRANTY WITH ARBITRATION | PURCHASE CONTRACT | HOLDING TANK SERVICING CONTRACT | PROPERTY MANAGEMENT AGREEMENT (Short Term and/or Vacation/Holiday Rentals) | [result](./multi_input_results_1758629438/multi_document_analysis_result.json) |
| 5 | `multi-input-test-1758629630` | Contoso Lifts LLC Invoice #1256003 | BUILDERS LIMITED WARRANTY WITH ARBITRATION | PURCHASE CONTRACT | HOLDING TANK SERVICING CONTRACT | PROPERTY MANAGEMENT AGREEMENT | [result](./multi_input_results_1758629630/multi_document_analysis_result.json) |
| 6 | `multi-input-test-1758629791` | INVOICE #1256003 (Contoso Lifts LLC Invoice) | BUILDERS LIMITED WARRANTY WITH ARBITRATION | PURCHASE CONTRACT | HOLDING TANK SERVICING CONTRACT | PROPERTY MANAGEMENT AGREEMENT (Short Term and/or Vacation/Holiday Rentals) | [result](./multi_input_results_1758629791/multi_document_analysis_result.json) |
| 7 | `multi-input-test-1758629986` | INVOICE # 1256003 | BUILDERS LIMITED WARRANTY WITH ARBITRATION | PURCHASE CONTRACT | HOLDING TANK SERVICING CONTRACT | PROPERTY MANAGEMENT AGREEMENT | [result](./multi_input_results_1758629986/multi_document_analysis_result.json) |
| 8 | `multi-input-test-1758630152` | Invoice #1256003 | BUILDERS LIMITED WARRANTY WITH ARBITRATION | PURCHASE CONTRACT | HOLDING TANK SERVICING CONTRACT | PROPERTY MANAGEMENT AGREEMENT (Short Term and/or Vacation/Holiday Rentals) | [result](./multi_input_results_1758630152/multi_document_analysis_result.json) |
| 9 | `multi-input-test-1758630361` | Contoso Lifts LLC Invoice #1256003 | BUILDERS LIMITED WARRANTY WITH ARBITRATION | PURCHASE CONTRACT | HOLDING TANK SERVICING CONTRACT | PROPERTY MANAGEMENT AGREEMENT (Short Term and/or Vacation/Holiday Rentals) | [result](./multi_input_results_1758630361/multi_document_analysis_result.json) |
| 10 | `multi-input-test-1758630524` | Invoice # 1256003 | BUILDERS LIMITED WARRANTY WITH ARBITRATION | PURCHASE CONTRACT | HOLDING TANK SERVICING CONTRACT | PROPERTY MANAGEMENT AGREEMENT | [result](./multi_input_results_1758630524/multi_document_analysis_result.json) |

## Notes
- The taxonomy label for "type" can vary (e.g., Agreement vs Property Management Agreement), but the document titles are consistent and unambiguous.
- Cross-document comparisons consistently flagged the same categories of inconsistencies (e.g., payment terms and party naming), further supporting repeatability.
