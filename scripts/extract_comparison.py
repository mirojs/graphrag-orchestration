#!/usr/bin/env python3
"""Extract V1 and V2 responses for side-by-side comparison."""

import re

def extract_response(content, marker):
    """Extract full response between markers."""
    # Find the response between "Response Preview" and the next major section
    pattern = rf'{marker}.*?Response Preview.*?-{{80}}\n(.*?)\n(?:-{{80}}|===)'
    match = re.search(pattern, content, re.DOTALL)
    if match:
        response = match.group(1).strip()
        # Remove the "..." if it's at the end
        if response.endswith('...'):
            response = response[:-3].rstrip()
        return response
    return None

# Read log file
with open('test_invoice_v1_v2_comparison.log', 'r') as f:
    log_content = f.read()

v1_response = extract_response(log_content, r'🔬 Testing: V1 \(OpenAI\)')
v2_response = extract_response(log_content, r'🔬 Testing: V2 \(Voyage \+ Aliases\)')

if not v1_response:
    print("ERROR: Could not extract V1 response")
    exit(1)

if not v2_response:
    print("ERROR: Could not extract V2 response")
    exit(1)

print(f"V1 Response: {len(v1_response)} chars")
print(f"V2 Response: {len(v2_response)} chars")

# Create side-by-side comparison
output = []
output.append("## 12. Full Response Comparison: V1 vs V2")
output.append("")
output.append("### V1 Response (OpenAI, 0 evidence, 7,571 chars)")
output.append("")
output.append("```")
output.append(v1_response)
output.append("```")
output.append("")
output.append("---")
output.append("")
output.append("### V2 Response (Voyage + Aliases, 15 evidence, 9,142 chars)")
output.append("")
output.append("```")
output.append(v2_response)
output.append("```")
output.append("")

# Write to file
output_text = '\n'.join(output)
with open('comparison_responses.md', 'w') as f:
    f.write(output_text)

print("\n✅ Comparison saved to comparison_responses.md")
print(f"Total size: {len(output_text):,} bytes")
