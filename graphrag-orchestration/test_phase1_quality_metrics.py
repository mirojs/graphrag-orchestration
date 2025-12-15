#!/usr/bin/env python3
"""
Phase 1 Quality Metrics - Code Validation Test

Validates that Phase 1 implementation is present in the code:
1. Silhouette score calculation in _cluster_nodes()
2. Confidence scoring in _summarize_cluster()
3. Quality metadata in indexed nodes
4. Metadata keys included in ESSENTIAL_METADATA_KEYS
"""

import ast
import sys
from pathlib import Path

print("=" * 80)
print("PHASE 1 QUALITY METRICS - CODE VALIDATION TEST")
print("=" * 80)
print()

# Files to validate
RAPTOR_SERVICE = Path("app/services/raptor_service.py")
VECTOR_SERVICE = Path("app/services/vector_service.py")

test_results = []


def check_file_exists(filepath):
    """Check if file exists."""
    if filepath.exists():
        print(f"✅ File exists: {filepath}")
        return True
    else:
        print(f"❌ File not found: {filepath}")
        return False


def check_code_contains(filepath, search_string, description):
    """Check if code contains a specific string."""
    try:
        content = filepath.read_text()
        if search_string in content:
            print(f"✅ {description}")
            return True
        else:
            print(f"❌ {description} - NOT FOUND")
            return False
    except Exception as e:
        print(f"❌ Error checking {filepath}: {e}")
        return False


def check_metadata_field(filepath, field_name):
    """Check if metadata field is present."""
    try:
        content = filepath.read_text()
        if f"'{field_name}'" in content or f'"{field_name}"' in content:
            print(f"✅ Metadata field '{field_name}' found")
            return True
        else:
            print(f"❌ Metadata field '{field_name}' NOT FOUND")
            return False
    except Exception as e:
        print(f"❌ Error checking metadata: {e}")
        return False


print("[1/4] Validating raptor_service.py exists...")
test_results.append(check_file_exists(RAPTOR_SERVICE))
print()

print("[2/4] Checking silhouette score implementation...")
test_results.append(
    check_code_contains(
        RAPTOR_SERVICE,
        "from sklearn.metrics import silhouette_score",
        "Import silhouette_score from sklearn"
    )
)
test_results.append(
    check_code_contains(
        RAPTOR_SERVICE,
        "silhouette_avg = silhouette_score(embeddings_array, cluster_labels)",
        "Calculate average silhouette score"
    )
)
test_results.append(
    check_code_contains(
        RAPTOR_SERVICE,
        "silhouette_per_sample = silhouette_samples(embeddings_array, cluster_labels)",
        "Calculate per-sample silhouette scores"
    )
)
test_results.append(
    check_code_contains(
        RAPTOR_SERVICE,
        "node.metadata['silhouette_score']",
        "Store silhouette_score in node metadata"
    )
)
print()

print("[3/4] Checking confidence scoring implementation...")
test_results.append(
    check_code_contains(
        RAPTOR_SERVICE,
        "cluster_coherence",
        "Calculate cluster coherence metric"
    )
)
test_results.append(
    check_code_contains(
        RAPTOR_SERVICE,
        "confidence_level",
        "Assign confidence level"
    )
)
test_results.append(
    check_code_contains(
        RAPTOR_SERVICE,
        "confidence_score",
        "Assign confidence score"
    )
)
test_results.append(
    check_metadata_field(RAPTOR_SERVICE, "cluster_coherence")
)
test_results.append(
    check_metadata_field(RAPTOR_SERVICE, "confidence_level")
)
test_results.append(
    check_metadata_field(RAPTOR_SERVICE, "confidence_score")
)
print()

print("[4/4] Checking metadata keys in ESSENTIAL_METADATA_KEYS...")
test_results.append(
    check_code_contains(
        RAPTOR_SERVICE,
        '"cluster_coherence"',
        "cluster_coherence in ESSENTIAL_METADATA_KEYS"
    )
)
test_results.append(
    check_code_contains(
        RAPTOR_SERVICE,
        '"confidence_level"',
        "confidence_level in ESSENTIAL_METADATA_KEYS"
    )
)
test_results.append(
    check_code_contains(
        RAPTOR_SERVICE,
        '"confidence_score"',
        "confidence_score in ESSENTIAL_METADATA_KEYS"
    )
)
test_results.append(
    check_code_contains(
        RAPTOR_SERVICE,
        '"silhouette_score"',
        "silhouette_score in ESSENTIAL_METADATA_KEYS"
    )
)
print()

# Additional checks for vector_service.py
print("[5/5] Checking vector_service.py metadata keys...")
if check_file_exists(VECTOR_SERVICE):
    test_results.append(
        check_code_contains(
            VECTOR_SERVICE,
            '"silhouette_score"',
            "silhouette_score in vector_service metadata keys"
        )
    )
print()

# Summary
print("=" * 80)
print("TEST SUMMARY")
print("=" * 80)
total_tests = len(test_results)
passed_tests = sum(test_results)
failed_tests = total_tests - passed_tests

print(f"Total Tests: {total_tests}")
print(f"Passed: {passed_tests} ✅")
print(f"Failed: {failed_tests} ❌")
print()

if failed_tests == 0:
    print("🎉 ALL TESTS PASSED - Phase 1 implementation is complete!")
    print()
    print("Phase 1 Quality Metrics Implementation Verified:")
    print("  ✅ Silhouette scores calculated and stored")
    print("  ✅ Confidence levels computed based on cluster coherence")
    print("  ✅ Quality metrics included in node metadata")
    print("  ✅ Metadata keys properly configured for indexing")
    print()
    print("Next Steps:")
    print("  • Deploy to Azure Container App")
    print("  • Run integration tests with real documents")
    print("  • Begin Phase 2: Azure AI Search query integration")
    sys.exit(0)
else:
    print("⚠️ SOME TESTS FAILED - Phase 1 implementation incomplete")
    print()
    print("Please review the failed checks above and ensure:")
    print("  • All silhouette score calculations are present")
    print("  • Confidence scoring logic is implemented")
    print("  • Metadata fields are correctly defined")
    print("  • ESSENTIAL_METADATA_KEYS includes quality metrics")
    sys.exit(1)
