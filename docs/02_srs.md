# Software Requirements Specification

## 1. Introduction
AgriPlot Connect is a Django-based agricultural land marketplace and transaction support platform. The system enables verified plot listing, role-based operations, verification workflow management, payment request tracking, legal closing progression, and notification delivery.

## 2. Product Scope
The system supports the end-to-end operational journey from plot publication to verification, buyer inquiry, and milestone-based transaction progress for purchase and lease use cases.

## 3. User Classes
- Buyer: browses, saves, contacts, pays, and follows transaction progress.
- Landowner: owns plots, monitors listing and transaction progress.
- Agent: manages listings and buyer engagement on behalf of sellers.
- Verification admin: assigns tasks, reviews evidence, and supervises compliance.
- Extension officer: submits agronomic and field verification reports.
- Land surveyor: submits survey and boundary verification reports.
- Finance/admin staff: manage transaction state transitions and closing workflow.

## 4. Functional Requirements
### 4.1 Authentication and Access
- The system shall support user login and logout.
- The system shall support role-aware dashboards.
- The system shall enforce authorization on sensitive listing, verification, and payment routes.

### 4.2 Listings
- The system shall allow authorized users to create and update plots.
- The system shall store plot location, land type, pricing, agronomic metadata, and documents.
- The system shall display verified plots on the public marketplace.
- The system shall support search and filtering by county, sub-county, ward, listing type, soil type, price, size intent, water source, topography, and registry-related attributes.

### 4.3 Verification
- The system shall create and manage verification tasks.
- The system shall support document review, extension review, surveyor inspection, and registry-related admin review.
- The system shall allow surveyors to upload plot images that persist as plot-linked images.
- The system shall keep one canonical verification route map at the root application level.

### 4.4 Payments and Transaction Workflow
- The system shall support payment requests for commitment fee, reservation deposit, agreement deposit, escrow deposit, stamp duty, and completion balance.
- The system shall reject transactional payment creation when no plot is linked.
- The system shall compute direct-deal payment amounts from plot and transaction context.
- The system shall track legal closing steps for purchase and lease workflows.
- The system shall update plot market state based on payment and legal milestone outcomes.

### 4.5 Provider Reliability
- The system shall retry Daraja provider requests on transient timeout or connection failures.
- The system shall preserve payment requests as pending when provider initiation is delayed.
- The system shall record provider-start metadata and payment events for operator follow-up.
- The system shall isolate SMS failures from the main business flow so notifications do not crash transactions.

### 4.6 Notifications
- The system shall create in-app notifications for transaction and verification events.
- The system shall send email when recipient email addresses are available.
- The system shall attempt SMS delivery when enabled and a phone number is available.

### 4.7 Audit and Reporting
- The system shall maintain audit visibility for operational actions.
- The system shall expose payment, escrow, and executive reports.
- The system shall support system construction and audit-related admin views.

## 5. Non-Functional Requirements
### 5.1 Security
- Role-based authorization shall be enforced.
- Sensitive actions shall be auditable.
- Payment and verification routes shall not rely on duplicate or ambiguous URL exposure.

### 5.2 Reliability
- Provider timeouts shall degrade gracefully.
- Surveyor evidence uploads shall persist without silent failure.
- Transactional payment integrity shall be enforced at form and model levels.

### 5.3 Maintainability
- Dead routes shall be removed when deprecated.
- Homepage marketplace CSS and JS shall be stored in static assets rather than large inline blocks.
- Route ownership shall remain canonical and documented.

### 5.4 Performance
- Marketplace listing pages shall paginate results.
- Query-heavy views shall use selective relations where appropriate.

### 5.5 Usability
- The marketplace shall support responsive search and browsing.
- Payment and verification flows shall expose clear status and next-step context.

## 6. External Interface Requirements
### 6.1 Payment Provider
- Safaricom Daraja for M-Pesa STK push initiation and callback handling
- Optional Paystack integration for card-based gateway flow

### 6.2 SMS Provider
- OpenSMS and TextSMS through the notification service layer

### 6.3 Database
- PostgreSQL-backed persistence for operational records

## 7. Constraints
- Provider availability and network conditions can affect external confirmation timing.
- Legal and regulatory completion still requires human/legal evidence for final closure.

## 8. Acceptance Criteria
- Surveyor image upload succeeds and stores `PlotImage`.
- Transactional payments without a plot are rejected.
- Duplicate verification route exposure is removed.
- Legacy AJAX marketplace search route is removed.
- Homepage presentation logic is served from static CSS/JS files.
