#!/usr/bin/env python3
"""Test that the DRIFT markdown fence stripping works correctly."""

def test_markdown_stripping():
    """Test the markdown code fence stripping logic."""
    
    # Test case 1: JSON wrapped in ```json...```
    test1 = '''```json
{
  "intermediate_answer": "Test answer",
  "followup_queries": []
}
```'''
    
    # Apply the stripping logic from drift_adapter.py
    cleaned = test1.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]  # Remove ```json
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]  # Remove ```
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]  # Remove trailing ```
    cleaned = cleaned.strip()
    
    print("Test 1: JSON wrapped in ```json...```")
    print(f"Original length: {len(test1)}")
    print(f"Cleaned length: {len(cleaned)}")
    print(f"Starts with '{{': {cleaned.startswith('{')}")
    print(f"First 50 chars: {cleaned[:50]}")
    
    # Try to parse as JSON
    import json
    try:
        parsed = json.loads(cleaned)
        print(f"✅ JSON parsing successful!")
        print(f"   Keys: {list(parsed.keys())}")
    except json.JSONDecodeError as e:
        print(f"❌ JSON parsing failed: {e}")
        return False
    
    # Test case 2: JSON with just ```...```
    test2 = '''```
{
  "result": "Another test"
}
```'''
    
    cleaned2 = test2.strip()
    if cleaned2.startswith("```json"):
        cleaned2 = cleaned2[7:]
    elif cleaned2.startswith("```"):
        cleaned2 = cleaned2[3:]
    if cleaned2.endswith("```"):
        cleaned2 = cleaned2[:-3]
    cleaned2 = cleaned2.strip()
    
    print("\nTest 2: JSON wrapped in ```...```")
    try:
        parsed2 = json.loads(cleaned2)
        print(f"✅ JSON parsing successful!")
        print(f"   Keys: {list(parsed2.keys())}")
    except json.JSONDecodeError as e:
        print(f"❌ JSON parsing failed: {e}")
        return False
    
    # Test case 3: Plain JSON (no markdown)
    test3 = '{"plain": "json"}'
    
    cleaned3 = test3.strip()
    if cleaned3.startswith("```json"):
        cleaned3 = cleaned3[7:]
    elif cleaned3.startswith("```"):
        cleaned3 = cleaned3[3:]
    if cleaned3.endswith("```"):
        cleaned3 = cleaned3[:-3]
    cleaned3 = cleaned3.strip()
    
    print("\nTest 3: Plain JSON (no wrapping)")
    try:
        parsed3 = json.loads(cleaned3)
        print(f"✅ JSON parsing successful!")
        print(f"   Keys: {list(parsed3.keys())}")
    except json.JSONDecodeError as e:
        print(f"❌ JSON parsing failed: {e}")
        return False
    
    print("\n" + "="*50)
    print("✅ All markdown stripping tests passed!")
    print("="*50)
    return True

if __name__ == "__main__":
    import sys
    success = test_markdown_stripping()
    sys.exit(0 if success else 1)
