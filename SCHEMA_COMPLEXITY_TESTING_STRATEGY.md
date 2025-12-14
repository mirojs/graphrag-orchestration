# Schema Complexity Testing Strategy for Azure InternalServerError

## 🎯 **Testing Hypothesis**
Azure Content Understanding API is failing with InternalServerError after ~7 minutes due to schema complexity, not knowledge sources.

## 📋 **Testing Approach**
Progressive complexity testing to isolate the root cause:

### **Phase 1: Knowledge Sources Elimination**
✅ **COMPLETED**: Empty knowledge sources still produce Azure InternalServerError
- **Conclusion**: Knowledge sources are NOT the root cause

### **Phase 2: Schema Complexity Testing**
🧪 **CURRENT FOCUS**: Test different schema complexity levels

#### **Test Levels:**

1. **Simple Schema** (`test_simple_schema=simple`)
   - Single string field only
   - No arrays, no objects, no nesting
   - Minimal Azure processing load

2. **Array Schema** (`test_simple_schema=array`) 
   - Single array of strings
   - Basic array processing
   - One level of structure

3. **Complex Schema** (`test_simple_schema=complex`)
   - Single array of objects with properties
   - Two levels of nesting
   - Moderate complexity

4. **Original Schema** (no test parameters)
   - Full production schema
   - 15+ fields across 3 nesting levels
   - Maximum complexity

## 🔧 **Testing Parameters**

### **Schema Complexity Control:**
- `test_simple_schema=simple|array|complex|""`
- Controls field structure complexity

### **Knowledge Sources Control:**
- `test_empty_knowledge_sources=true` - Force empty knowledge sources
- `max_reference_files=0-10` - Limit number of reference files

## 📊 **Expected Results**

| Test Level | Expected Outcome | Conclusion |
|------------|------------------|------------|
| Simple     | ✅ Success       | Schema complexity is the issue |
| Array      | ❌ Failure       | Array processing causes issue |
| Complex    | ❌ Failure       | Object nesting causes issue |
| Original   | ❌ Failure       | Full schema complexity confirmed issue |

## 🚀 **Test Execution**

### **HTTP Test Files:**
- `test_schema_complexity.http` - Progressive schema tests
- `test_knowledge_sources.http` - Knowledge sources tests

### **Shell Scripts:**
- `test_empty_knowledge_sources.sh` - Automated empty knowledge test

### **Test URLs:**
```bash
# Simple schema test
PUT /pro-mode/content-analyzers/test-simple?test_simple_schema=simple&test_empty_knowledge_sources=true

# Array schema test  
PUT /pro-mode/content-analyzers/test-array?test_simple_schema=array&test_empty_knowledge_sources=true

# Complex schema test
PUT /pro-mode/content-analyzers/test-complex?test_simple_schema=complex&test_empty_knowledge_sources=true

# Original schema test
PUT /pro-mode/content-analyzers/test-original?test_empty_knowledge_sources=true
```

## 🎯 **Success Criteria**
- Identify the exact complexity level that triggers Azure InternalServerError
- Provide actionable solution for schema optimization
- Enable successful pro mode analyzer creation

## 📝 **Implementation Details**

### **Code Modifications:**
- Added testing parameters to `create_or_replace_content_analyzer()` function
- Implemented conditional schema replacement logic  
- Added comprehensive testing and logging
- Production-safe: Only activates when testing parameters are explicitly set

### **Safety Features:**
- Testing only activates with explicit parameters
- Original functionality preserved
- Clear testing vs production logging
- Easy rollback capability

## 🔄 **Next Steps**
1. Execute progressive schema complexity tests
2. Identify failure point
3. Optimize schema structure
4. Validate solution
5. Clean up testing code
