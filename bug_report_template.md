## Frontend Bug Report

```markdown
## [FE] <Short, descriptive title of the bug>

### Summary
<!-- One or two sentences describing the visual or interaction issue. What broke? What was expected? -->

### Environment
- **Browser**: <!-- e.g. Chrome 124, Safari 17, Firefox 125 -->
- **OS**: <!-- e.g. macOS 14, Windows 11, iOS 17 -->
- **Device**: <!-- e.g. Desktop, iPhone 15, iPad Pro -->
- **Screen Resolution**: <!-- e.g. 1440x900, 375x812 -->
- **App Version / Build**: <!-- e.g. v2.3.1, commit hash, staging/prod -->
- **User Role / Auth State**: <!-- e.g. logged-in admin, guest, free-tier user -->

### Steps to Reproduce
1. 
2. 
3. 

### Expected Behavior
<!-- What should have happened? -->

### Actual Behavior
<!-- What actually happened? Be specific — include any error messages, visual glitches, broken layouts. -->

### Visual Evidence
<!-- Attach screenshots, screen recordings, or Loom links if available -->
- [ ] Screenshot attached
- [ ] Screen recording attached
- [ ] Console errors captured

### Console / Network Errors
```
<!-- Paste any JS errors, failed network requests, or warnings from DevTools here -->
```

### Reproduction Rate
- [ ] Always (100%)
- [ ] Often (>50%)
- [ ] Sometimes (<50%)
- [ ] Rarely / One-time

### Affected Component(s)
<!-- e.g. Navbar, Login Modal, Dashboard Chart, Checkout Form -->

### Related Issues / PRs
<!-- Link any related tickets, PRs, or Notion pages -->

### Additional Context
<!-- Any other info: feature flags enabled, A/B test variant, recent deployments, user-reported? -->

---
**LLM Enhancement Notes** *(auto-filled by AI)*:
- **Root Cause Hypothesis**: 
- **Likely Affected Files**: 
- **Suggested Fix Direction**: 
- **Regression Risk**: 
- **Severity**: <!-- Critical / High / Medium / Low -->
- **Priority**: <!-- P0 / P1 / P2 / P3 -->
```

---

## ⚙️ Backend Bug Report

```markdown
## [BE] <Short, descriptive title of the bug>

### Summary
<!-- One or two sentences describing the issue. What failed? What was the expected system behavior? -->

### Environment
- **Service / Microservice**: <!-- e.g. auth-service, payments-api, notification-worker -->
- **Environment**: <!-- e.g. Production, Staging, Dev, Local -->
- **Version / Commit**: <!-- e.g. v1.4.2, commit hash -->
- **Runtime**: <!-- e.g. Node 20, Python 3.12, Go 1.22 -->
- **Cloud / Infrastructure**: <!-- e.g. AWS us-east-1, GCP, on-prem -->

### Steps to Reproduce
1. 
2. 
3. 

### Request Details
- **Endpoint**: <!-- e.g. POST /api/v2/orders -->
- **Method**: <!-- GET / POST / PUT / PATCH / DELETE -->
- **Auth**: <!-- e.g. Bearer token, API key, no auth -->
- **Request Payload**:
```json
{
  // Paste sanitized request body here
}
```
- **Response / Error**:
```json
{
  // Paste response body or error message here
}
```
- **HTTP Status Code**: <!-- e.g. 500, 400, 403, 404 -->

### Expected Behavior
<!-- What should the system have done? -->

### Actual Behavior
<!-- What did it do instead? Include error messages, unexpected states, or data anomalies. -->

### Logs
```
<!-- Paste relevant log lines here. Include timestamps. Sanitize PII. -->
```

### Stack Trace
```
<!-- Paste full stack trace if available -->
```

### Reproduction Rate
- [ ] Always (100%)
- [ ] Often (>50%)
- [ ] Sometimes (<50%)
- [ ] Rare / One-time

### Data / State Conditions
<!-- Does this only occur for specific users, IDs, data states, or race conditions? -->
- Affected User ID(s): 
- Affected Record ID(s): 
- Known triggering condition: 

### Monitoring / Alerting
- **Sentry / Error Tracker Link**: 
- **Datadog / Grafana Dashboard Link**: 
- **Alert that fired (if any)**: 

### Impact Assessment
- **Who is affected**: <!-- e.g. All users, enterprise tier only, users in EU region -->
- **Estimated affected count**: 
- **Business impact**: <!-- e.g. checkout blocked, data loss risk, degraded performance -->

### Related Issues / PRs
<!-- Link related tickets, PRs, runbooks, or post-mortems -->

### Recent Changes
<!-- Any recent deploys, migrations, config changes, or dependency bumps that may be related? -->

---
**LLM Enhancement Notes** *(auto-filled by AI)*:
- **Root Cause Hypothesis**: 
- **Likely Affected Files / Services**: 
- **Suggested Fix Direction**: 
- **Regression Risk**: 
- **Is a Hotfix Needed?**: <!-- Yes / No / TBD -->
- **Severity**: <!-- Critical / High / Medium / Low -->
- **Priority**: <!-- P0 / P1 / P2 / P3 -->
```