# Pre-Deployment Testing Plan

## Testing Strategy Overview

Given the significant changes to file management and API error handling, we need thorough testing before deployment.

## 1. Unit Tests

### FilesTab Component Tests
- Test separate rendering of input and reference files
- Verify upload button functionality for each file type
- Test error handling and empty states
- Validate file filtering and selection

### Redux Store Tests
- Test `fetchFilesByTypeAsync` thunk with various responses
- Verify error handling in reducers
- Test state updates for input vs reference files
- Validate error state management

### API Service Tests
- Test `fetchFiles` function with different file types
- Verify error handling for 500, 404, CORS errors
- Test upload functionality for both file types
- Validate response processing

## 2. Integration Tests

### File Management Flow
- End-to-end file upload for input files
- End-to-end file upload for reference files
- File deletion across both types
- File download functionality

### Error Scenarios
- API endpoint failures
- Network connectivity issues
- CORS errors
- Server 500 errors

## 3. Manual Testing Checklist

### UI Functionality
- [ ] Input files section displays correctly
- [ ] Reference files section displays correctly
- [ ] File counts are accurate
- [ ] Upload buttons work for each type
- [ ] File selection works across sections
- [ ] Command bar actions work correctly

### Error Handling
- [ ] 500 errors don't crash the UI
- [ ] Network errors show appropriate messages
- [ ] Empty states display correctly
- [ ] Loading states work properly

### Performance
- [ ] File lists load efficiently
- [ ] Upload progress indicators work
- [ ] Large file handling
- [ ] Concurrent operations

## 4. API Testing

### Endpoint Verification
- [ ] `/pro-mode/input-files` GET/POST
- [ ] `/pro-mode/reference-files` GET/POST
- [ ] `/pro-mode/schemas` GET/POST
- [ ] Error response handling

### Authentication & CORS
- [ ] Proper headers sent
- [ ] CORS preflight requests
- [ ] Authentication tokens
- [ ] Rate limiting

## 5. Browser Compatibility

### Modern Browsers
- [ ] Chrome (latest)
- [ ] Firefox (latest)
- [ ] Safari (latest)
- [ ] Edge (latest)

### Features
- [ ] File upload functionality
- [ ] Drag and drop (if implemented)
- [ ] LocalStorage/SessionStorage
- [ ] Network request handling

## 6. Deployment Staging

### Pre-Deployment
1. Run automated test suite
2. Manual testing in staging environment
3. Performance testing
4. Error monitoring setup

### Post-Deployment
1. Smoke tests in production
2. Monitor error rates
3. User acceptance testing
4. Performance monitoring

## Test Environment Setup

### Requirements
- Staging environment matching production
- Test data for both file types
- Error simulation capabilities
- Performance monitoring tools

### Test Data
- Various file types (PDF, DOCX, TXT, images)
- Large files for performance testing
- Invalid file types for error testing
- Duplicate files for validation testing
