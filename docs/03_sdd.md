# Software Design Document

## 1. Architectural Overview
AgriPlot Connect follows a modular Django architecture. The application is organized into feature-oriented apps that collaborate through Django models, forms, views, templates, services, and provider integrations.

## 2. Major Modules
### 2.1 `listings`
- Owns public marketplace pages, plot models, search/filtering, and listing management.
- Stores `Plot` and `PlotImage`.
- Exposes public listing routes and user-facing actions such as saved plots and waitlists.

### 2.2 `verification`
- Owns verification tasking, surveyor and extension workflows, verification dashboards, and audit-related views.
- Stores `VerificationTask`, `LandSurveyor`, `SurveyorReport`, and related verification state.
- Uses a single canonical root include path in the project URL configuration.

### 2.3 `payments`
- Owns `PaymentRequest`, legal closing steps, transaction state transitions, provider callbacks, and the payment workspace.
- Enforces plot-linked transactional payments.
- Handles Daraja retries and pending-provider-confirmation fallback metadata.

### 2.4 `notifications`
- Owns in-app notifications, email logging, and SMS provider dispatch.
- Uses service-layer integration so SMS failure does not terminate the main business flow.

### 2.5 `accounts`, `authentication`, `security`, `reports`
- Support profile management, login/2FA, security/audit helpers, and reporting outputs.

## 3. URL Design
### Canonical Routing
- Root project routes are defined in `agriplot/urls.py`.
- Verification routes are included once at root.
- Listings routes no longer include verification internally.
- Legacy `/staff/...` duplicate verification exposure has been removed.

### Removed/Deprecated Route
- The legacy `ajax/search/` endpoint was removed because the homepage now uses normal form submission.

## 4. Data Design
### Core Entities
- `Plot`: listing and market-state entity
- `PlotImage`: plot-linked uploaded image evidence
- `VerificationTask`: assigned verification work item
- `SurveyorReport`: survey inspection report tied to a task and plot
- `PaymentRequest`: payment and legal workflow anchor
- `PaymentClosingStep`: legal/operational milestones for purchase and lease
- `Notification`: in-app event record

### Key Relationships
- A `Plot` may have many `PlotImage` records.
- A `VerificationTask` belongs to one `Plot`.
- A `SurveyorReport` belongs to one `VerificationTask` and one `Plot`.
- A `PaymentRequest` may belong to one `Plot` and has many `PaymentClosingStep` records.

## 5. Payment Workflow Design
### Input Validation
- `PaymentRequestForm` validates direct-deal amounts and method requirements.
- Plot-required categories are enforced in the form layer and again in the `PaymentRequest` model layer.
- The create view adds a final defensive guard before save.

### Provider Start Reliability
- Daraja calls are wrapped in a retry helper.
- Timeout/connection failures record `provider_start_status = pending_provider_confirmation`.
- The payment remains pending and an event is written for manual/provider follow-up.

### Market-State Synchronization
- Payment state transitions call market-state synchronization logic.
- Purchase and lease flows preserve distinct closing behavior while using the same transaction backbone.

## 6. Verification Workflow Design
### Surveyor Flow
- Surveyor report submission persists the report first.
- Uploaded survey photos are stored as `listings.PlotImage`.
- GPS updates and pricing review logic are applied after report save.

### Admin Supervision
- Verification admins assign and monitor tasks through dedicated verification views.
- Completion actions update task state and visibility.

## 7. Frontend Design
- Public marketplace templates use server-rendered Django templates.
- Large marketplace CSS and JS blocks were extracted to:
  - `static/css/marketplace.css`
  - `static/js/marketplace.js`
- Templates remain responsible for structure and server-side data binding.

## 8. Error Handling Strategy
- Validation errors are shown in forms without partial invalid saves.
- Provider failures that are transient are treated as pending confirmation rather than immediate hard failure.
- SMS exceptions are logged and isolated from core request success.

## 9. Test Design
Focused regression coverage was added for:
- missing plot rejection in transactional payment creation;
- pending provider confirmation fallback metadata;
- surveyor report image persistence into `PlotImage`;
- duplicate verification route removal.
