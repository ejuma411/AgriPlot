# AgriPlot Connect Project Proposal

## Project Title
AgriPlot Connect: Verified Agricultural Land Marketplace and Transaction Workflow

## Project Background
The project was conceived to address the fragmented process of discovering, verifying, and transacting agricultural land in Kenya. Conventional land transactions were often slowed by poor record visibility, weak verification trails, informal payment handling, and limited coordination between buyers, landowners, agents, extension officers, and surveyors.

## Problem Statement
The platform was proposed to solve the following problems:

- Agricultural land listings lacked trusted verification evidence.
- Buyers had limited visibility into due diligence, survey, and registry status.
- Agents and landowners had no unified workflow for listing, inquiry handling, and compliance.
- Payment commitments and legal closing steps were difficult to track transparently.
- Notifications, auditability, and role-based operational controls were inconsistent across manual processes.

## Proposed Solution
The system was proposed as a web-based platform that would:

- Publish agricultural land listings with structured agronomic and commercial data.
- Support role-based onboarding for buyers, agents, landowners, administrators, extension officers, and surveyors.
- Run a multi-stage verification workflow covering document review, extension review, surveyor inspection, and registry follow-up.
- Provide a payment workspace for commitment fees, reservation deposits, escrow-related steps, and legal closing milestones.
- Maintain audit trails, notification logs, and reporting outputs for governance and operational visibility.

## Objectives
The proposed system was intended to:

- increase trust in agricultural land listings through verified evidence;
- shorten the time needed to move from inquiry to due diligence;
- reduce manual ambiguity in milestone-based payment handling;
- improve accountability through audit logs and tracked notifications;
- support both purchase and lease journeys with clear workflow state transitions.

## Stakeholders
- Buyers and tenants
- Landowners
- Agents and brokers
- Verification administrators
- Extension officers
- Land surveyors
- Finance and support administrators

## Scope
### In Scope
- User registration, authentication, and role management
- Plot listing creation and editing
- Verification task assignment and reporting
- Buyer search, filtering, and saved plots
- Payment request creation and legal workflow tracking
- Notifications through in-app, email, and SMS channels
- Reporting and audit exports

### Out of Scope
- Direct government registry integration in production without separate regulatory onboarding
- Native mobile apps
- Offline-first workflows
- Fully autonomous payout settlement without human/legal review

## Feasibility Summary
The project was considered feasible because the required stack, workflows, and role boundaries mapped well to a Django-based web platform with PostgreSQL persistence, templated UI, and provider integrations for payment and SMS notifications.

## Expected Deliverables
- Deployed Django application
- Database-backed listing and verification modules
- Payment and legal workflow module
- Administrator dashboards and audit tools
- System documentation and user manual

## Success Criteria
- Verified plots could be published and browsed reliably.
- Surveyor and extension evidence could be uploaded and retained.
- Transactional payments could not be created without a linked plot.
- Legal closing steps could be tracked for both purchase and lease journeys.
- Staff and user actions could be traced through notifications and audit logs.
