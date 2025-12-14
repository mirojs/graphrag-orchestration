from typing import Literal, get_args
from enum import Enum
from pydantic import BaseModel, ValidationError

# Test 1: The broken implementation
my_list = ["A", "B"]
BrokenLiteral = Literal[tuple(my_list)]
print(f"BrokenLiteral args: {get_args(BrokenLiteral)}")

class BrokenModel(BaseModel):
    value: BrokenLiteral

try:
    print("Testing BrokenModel with 'A'...")
    BrokenModel(value="A")
    print("BrokenModel SUCCESS (Unexpected!)")
except ValidationError as e:
    print(f"Caught expected error: {e}")

# Test 2: Dynamic Enum
DynamicEnum = Enum('DynamicEnum', {item: item for item in my_list})
print(f"DynamicEnum members: {list(DynamicEnum)}")

class EnumModel(BaseModel):
    value: DynamicEnum

try:
    print("Testing EnumModel with 'A'...")
    m = EnumModel(value="A") # Pydantic allows string input for Enum fields
    print(f"Success! Value: {m.value}")
except ValidationError as e:
    print(f"Enum failed: {e}")

# Test 3: Trying to make a proper Literal dynamically (Hack)
# Literal accepts multiple arguments. Literal[tuple(list)] passes ONE argument (the tuple).
# We want Literal["A", "B"].
# In Python, we can't easily unpack into [] at runtime for types.
# But maybe we don't need Literal if Enum works.
