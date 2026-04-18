# Test Plan

## 1. Purpose
This test plan defines how AgriPlot Connect should be validated across listing, verification, payment, routing, and documentation-stabilization concerns.

## 2. Test Objectives
- Confirm critical business workflows operate correctly.
- prevent regression of previously identified audit issues;
- verify role-based access and route ownership;
- confirm provider failure handling degrades safely;
- confirm public marketplace assets load from static files.

## 3. Scope
### In Scope
- Marketplace browsing and filter submission
- Verification routing and surveyor submission
- Transactional payment validation
- Payment provider timeout fallback behavior
- Legal workflow state preservation

### Out of Scope
- Full external provider certification
- Production load testing
- Native mobile testing

## 4. Test Levels
### Unit Tests
- Model validation for `PaymentRequest`
- Form validation for `PaymentRequestForm`
- Service-level provider handling where practical

### Integration Tests
- Create payment request flow
- Surveyor report submission flow
- Route resolution and redirect checks

### Manual Tests
- Browser verification of marketplace CSS/JS behavior
- Payment detail visibility after pending-provider-confirmation fallback
- Verification admin navigation and route sanity

## 5. Test Environment
- Django application running in the project virtual environment
- PostgreSQL-backed test database
- Local static assets
- Mocked provider calls for Daraja/SMS-sensitive cases

## 6. Entry Criteria
- Migrations are up to date.
- Required environment variables are present for app startup.
- Test database is accessible.

## 7. Exit Criteria
- Critical audit regressions are covered and passing.
- No blocker remains for broken surveyor image persistence.
- Transactional plot-link enforcement is verified.
- Canonical verification routing is verified.

## 8. Test Cases
### Functional Regression Cases
1. Create transactional payment without plot.
Expected result: form is invalid or request is rejected.

2. Create commitment or reservation payment with valid plot.
Expected result: payment is created and plot-linked workflow proceeds.

3. Simulate Daraja timeout during payment creation.
Expected result: payment remains pending, metadata records `pending_provider_confirmation`, and an event is logged.

4. Submit surveyor report with uploaded image.
Expected result: `SurveyorReport` is saved and `PlotImage` is created.

5. Visit legacy duplicate verification staff route.
Expected result: route is not exposed.

6. Visit canonical verification dashboard route.
Expected result: route resolves normally.

7. Load marketplace homepage.
Expected result: static CSS/JS assets are referenced and page behavior still works.

## 9. Executed Focused Regression Set
The following targeted automated tests were executed after the audit fixes:

- transactional payment form rejects missing plot;
- transactional payment model rejects missing plot;
- payment create view rejects missing plot;
- Daraja connection failure records pending provider confirmation;
- timeout fallback records provider confirmation pending event;
- duplicate staff verification namespace route returns 404;
- surveyor report upload persists `PlotImage`;
- legacy verification redirect still points to canonical dashboard.

## 10. Risks
- The broader repository test suite currently contains unrelated failures outside this audit scope.
- External provider behavior still depends on real network and credential conditions in live environments.

## 11. Recommended Ongoing Testing
- Add CI execution for targeted regression cases.
- Expand payment callback coverage for both Daraja and Paystack.
- Add browser-level smoke tests for marketplace interactions and payment detail status states.
