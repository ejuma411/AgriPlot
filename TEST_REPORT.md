# AgriPlot Connect – Test Report

Date: 2026-02-27
Environment: Local dev (127.0.0.1)

## Automated Tests
- Command: `python manage.py test`
- Result: **PASS**
- Summary: 7 tests, 0 failures

## Manual Test Cases (Detailed)
For each case, fill **Actual** and **Status**.

### 1) Public Site & Discovery
**PUB1 Home page loads and renders featured plots**
- Test Data: Existing plots
- Preconditions: Server running
- Steps: Open `/`
- Expected: Hero + plots visible, no errors
- Actual: 
- Status: 

**PUB2 Search/autocomplete returns results**
- Test Data: Known plot title
- Preconditions: Search index loaded
- Steps: Type known plot title in search
- Expected: Results list updates and includes plot
- Actual: 
- Status: 

**PUB3 Search no-results state is clear**
- Test Data: Random text
- Preconditions: Search active
- Steps: Search random string
- Expected: “No results” message shown
- Actual: 
- Status: 

**PUB4 Plot detail page loads**
- Test Data: Plot ID
- Preconditions: Plot exists
- Steps: Open `/plot/<id>/`
- Expected: Title, location, price, seller info
- Actual: 
- Status: 

**PUB5 Plot detail shows verification status**
- Test Data: Verified + unverified plots
- Preconditions: Plots exist
- Steps: Open both plots
- Expected: Status badge reflects verification
- Actual: 
- Status: 

**PUB6 Plot detail CTAs work**
- Test Data: Plot with contact info
- Preconditions: Plot exists
- Steps: Click contact/phone/whatsapp CTA
- Expected: Contact flow starts
- Actual: 
- Status: 

**PUB7 Contact agent form submits**
- Test Data: Message
- Preconditions: Logged in user
- Steps: Submit contact form
- Expected: Request logged and acknowledged
- Actual: 
- Status: 

### 2) Authentication & OTP
**A1 Register buyer → OTP → verify → welcome email**
- Test Data: New buyer email
- Preconditions: Email service enabled
- Steps: Register buyer, enter OTP
- Expected: OTP verified, welcome email sent
- Actual: 
- Status: 

**A2 Register landowner wizard → OTP → success**
- Test Data: New landowner email
- Preconditions: Wizard available
- Steps: Complete wizard, verify OTP
- Expected: Account created, success email
- Actual: 
- Status: 

**A3 Login/logout for all roles**
- Test Data: Buyer/Agent/Landowner accounts
- Preconditions: Accounts exist
- Steps: Login/logout for each role
- Expected: Session created/cleared correctly
- Actual: 
- Status: 

**A4 Wrong password shows error**
- Test Data: Invalid password
- Preconditions: Account exists
- Steps: Attempt login with wrong password
- Expected: Error message shown
- Actual: 
- Status: 

**A5 Password reset flow**
- Test Data: Existing email
- Preconditions: Email service enabled
- Steps: Request reset, use link
- Expected: Password updated
- Actual: 
- Status: 

**A6 OTP resend works**
- Test Data: User pending OTP
- Preconditions: OTP active
- Steps: Click resend
- Expected: New OTP issued
- Actual: 
- Status: 

**A7 OTP expires after 10 minutes**
- Test Data: OTP older than 10 min
- Preconditions: OTP issued
- Steps: Wait >10 min, submit OTP
- Expected: OTP rejected as expired
- Actual: 
- Status: 

**A8 OTP invalid shows error**
- Test Data: Wrong OTP
- Preconditions: OTP issued
- Steps: Submit wrong OTP
- Expected: Error shown
- Actual: 
- Status: 

### 3) Landowner Wizard
**L1 Step navigation works**
- Test Data: None
- Preconditions: Wizard accessible
- Steps: Use Next/Back
- Expected: Steps change correctly
- Actual: 
- Status: 

**L2 Required docs enforced**
- Test Data: Missing docs
- Preconditions: Docs step
- Steps: Try proceed without docs
- Expected: Inline errors
- Actual: 
- Status: 

**L3 File type/size checks**
- Test Data: Invalid file
- Preconditions: Docs step
- Steps: Upload invalid file
- Expected: Client-side block
- Actual: 
- Status: 

**L4 Resume banner appears**
- Test Data: Incomplete wizard session
- Preconditions: Save & Resume used
- Steps: Logout, open home/login
- Expected: Resume banner visible
- Actual: 
- Status: 

**L5 Wizard session clears after OTP**
- Test Data: Completed wizard
- Preconditions: OTP verified
- Steps: Return to home/login
- Expected: No resume banner
- Actual: 
- Status: 

**L6 Duplicate phone field removed**
- Test Data: None
- Preconditions: Wizard step 1
- Steps: Inspect form fields
- Expected: Only one phone field
- Actual: 
- Status: 

**L7 Progress UI updates correctly**
- Test Data: None
- Preconditions: Wizard active
- Steps: Move through steps
- Expected: Progress bar updates
- Actual: 
- Status: 

**L8 Inline validation messages**
- Test Data: Missing required
- Preconditions: Form submit
- Steps: Submit empty required field
- Expected: Inline errors, no alert
- Actual: 
- Status: 

### 4) User Profiles & Role Upgrades
**U1 Profile saves personal info**
- Test Data: New phone/email
- Preconditions: Logged in user
- Steps: Update profile
- Expected: Data persists
- Actual: 
- Status: 

**U2 Role request created**
- Test Data: Agent/Extension/Surveyor request
- Preconditions: Logged in user
- Steps: Submit request
- Expected: Request listed
- Actual: 
- Status: 

**U3 Admin approves role**
- Test Data: Pending request
- Preconditions: Admin access
- Steps: Approve request
- Expected: User gains access
- Actual: 
- Status: 

**U4 Admin rejects role**
- Test Data: Pending request
- Preconditions: Admin access
- Steps: Reject request
- Expected: User notified
- Actual: 
- Status: 

**U5 Notifications inbox shows role status**
- Test Data: Approved/rejected request
- Preconditions: User logged in
- Steps: Open inbox
- Expected: Status notifications visible
- Actual: 
- Status: 

### 5) Plot Creation
**P1 Add plot minimal seller fields**
- Test Data: Required fields only
- Preconditions: Owner/agent account
- Steps: Submit add plot
- Expected: Plot saved
- Actual: 
- Status: 

**P2 Price validation enforced**
- Test Data: Missing price
- Preconditions: Sale listing
- Steps: Submit without price
- Expected: Validation error
- Actual: 
- Status: 

**P3 Required docs upload**
- Test Data: Title deed, ID, KRA PIN
- Preconditions: Form open
- Steps: Upload and save
- Expected: Files stored
- Actual: 
- Status: 

**P4 Plot triggers verification**
- Test Data: New plot
- Preconditions: Verification flow enabled
- Steps: Submit plot
- Expected: Verification status + tasks
- Actual: 
- Status: 

**P5 Edit plot allowed for owner**
- Test Data: Owned plot
- Preconditions: Owner logged in
- Steps: Edit plot
- Expected: Save success
- Actual: 
- Status: 

**P6 Edit plot denied for other user**
- Test Data: Plot owned by other user
- Preconditions: Different user logged in
- Steps: Try edit
- Expected: Access denied
- Actual: 
- Status: 

### 6) Pricing Guardrails
**PG1 Sale price inside band passes**
- Test Data: Price within band
- Preconditions: MarketPriceBand set
- Steps: Submit plot
- Expected: Allowed
- Actual: 
- Status: 

**PG2 Sale price outside band blocks/warns**
- Test Data: Price out of range
- Preconditions: Guardrails active
- Steps: Submit plot
- Expected: Warning/blocked
- Actual: 
- Status: 

**PG3 Price per acre auto-calculates**
- Test Data: Area + sale price
- Preconditions: Form open
- Steps: Enter price and area
- Expected: Price per acre computed
- Actual: 
- Status: 

**PG4 Lease pricing required**
- Test Data: Lease listing
- Preconditions: Lease selected
- Steps: Submit without lease price
- Expected: Validation error
- Actual: 
- Status: 

**PG5 Price basis required**
- Test Data: Missing price basis
- Preconditions: Price entered
- Steps: Submit form
- Expected: Validation error
- Actual: 
- Status: 

**PG6 Valuation report required**
- Test Data: Basis=valuation
- Preconditions: No report
- Steps: Submit
- Expected: Validation error
- Actual: 
- Status: 

**PG7 Government proof required**
- Test Data: Basis=government
- Preconditions: No proof
- Steps: Submit
- Expected: Validation error
- Actual: 
- Status: 

**PG8 Surveyor can adjust unrealistic price**
- Test Data: Unrealistic price
- Preconditions: Surveyor review
- Steps: Adjust price in report
- Expected: Updated price saved
- Actual: 
- Status: 

### 7) Documents
**D1 Upload required docs**
- Test Data: Title deed, search, ID, KRA PIN
- Preconditions: Form open
- Steps: Upload docs
- Expected: Files saved
- Actual: 
- Status: 

**D2 Document checklist updates**
- Test Data: Missing doc
- Preconditions: Docs partially uploaded
- Steps: View checklist
- Expected: Missing shown
- Actual: 
- Status: 

**D3 Document verification linked to task**
- Test Data: Review task
- Preconditions: Admin review
- Steps: Open review page
- Expected: Docs linked to task
- Actual: 
- Status: 

### 8) Verification Workflow
**V1 API verification creates tasks**
- Test Data: New plot
- Preconditions: API mock enabled
- Steps: Submit plot
- Expected: Extension task created
- Actual: 
- Status: 

**V2 Extension review completes**
- Test Data: Assigned task
- Preconditions: Extension login
- Steps: Submit report
- Expected: Task completed
- Actual: 
- Status: 

**V3 Surveyor review completes**
- Test Data: Assigned task
- Preconditions: Surveyor login
- Steps: Submit report
- Expected: Task completed
- Actual: 
- Status: 

**V4 Admin approves plot**
- Test Data: Completed tasks
- Preconditions: Admin login
- Steps: Approve
- Expected: Plot published
- Actual: 
- Status: 

**V5 Admin rejects plot**
- Test Data: Completed tasks
- Preconditions: Admin login
- Steps: Reject
- Expected: Returned with reasons
- Actual: 
- Status: 

**V6 Verification timeline shows all steps**
- Test Data: Completed flow
- Preconditions: Admin view
- Steps: Open history
- Expected: Full log
- Actual: 
- Status: 

### 9) Admin Queue & Assignment
**Q1 Queue filters work**
- Test Data: Mixed status plots
- Preconditions: Admin login
- Steps: Filter All/Pending/Approved
- Expected: Correct list
- Actual: 
- Status: 

**Q2 Assign modal filters roles**
- Test Data: Pending tasks
- Preconditions: Admin login
- Steps: Open assign modal
- Expected: Only correct roles
- Actual: 
- Status: 

**Q3 Unassigned reason visible**
- Test Data: Pending task
- Preconditions: Admin login
- Steps: View pending list
- Expected: Reason displayed
- Actual: 
- Status: 

**Q4 Auto-escalation after 12h**
- Test Data: Unconfirmed task
- Preconditions: SLA job run
- Steps: Wait >12h, run SLA
- Expected: Admin notified
- Actual: 
- Status: 

### 10) Extension Dashboard
**E1 Only assigned tasks visible**
- Test Data: Assigned tasks
- Preconditions: Extension login
- Steps: Open dashboard
- Expected: Only own tasks
- Actual: 
- Status: 

**E2 Confirm task**
- Test Data: Assigned task
- Preconditions: Extension login
- Steps: Confirm
- Expected: Status in_progress
- Actual: 
- Status: 

**E3 Submit report**
- Test Data: Required fields
- Preconditions: Task confirmed
- Steps: Submit report
- Expected: Task completed
- Actual: 
- Status: 

### 11) Surveyor Dashboard
**S1 Only assigned tasks visible**
- Test Data: Assigned tasks
- Preconditions: Surveyor login
- Steps: Open dashboard
- Expected: Only own tasks
- Actual: 
- Status: 

**S2 Confirm task**
- Test Data: Assigned task
- Preconditions: Surveyor login
- Steps: Confirm
- Expected: Status in_progress
- Actual: 
- Status: 

**S3 Submit report**
- Test Data: Required fields
- Preconditions: Task confirmed
- Steps: Submit report
- Expected: Task completed
- Actual: 
- Status: 

### 12) Notifications
**N1 OTP email delivered**
- Test Data: New registration
- Preconditions: Email enabled
- Steps: Register
- Expected: OTP email received
- Actual: 
- Status: 

**N2 OTP success email delivered**
- Test Data: OTP verified
- Preconditions: Email enabled
- Steps: Verify OTP
- Expected: Success email
- Actual: 
- Status: 

**N3 Role request email delivered**
- Test Data: Role request
- Preconditions: Email enabled
- Steps: Submit request
- Expected: Email received
- Actual: 
- Status: 

**N4 Task assignment email/SMS delivered**
- Test Data: Task assigned
- Preconditions: SMS enabled
- Steps: Assign task
- Expected: Email+SMS sent
- Actual: 
- Status: 

**N5 Plot status update email delivered**
- Test Data: Approval/rejection
- Preconditions: Email enabled
- Steps: Approve/reject
- Expected: Status email
- Actual: 
- Status: 

**N6 Failure logging**
- Test Data: Invalid sender/SMTP
- Preconditions: Error induced
- Steps: Send message
- Expected: Failure logged
- Actual: 
- Status: 

### 13) Analytics & SLA
**AN1 Analytics dashboard loads**
- Test Data: Existing data
- Preconditions: Admin login
- Steps: Open analytics
- Expected: Metrics + charts
- Actual: 
- Status: 

**AN2 CSV export downloads**
- Test Data: Data available
- Preconditions: Admin login
- Steps: Export CSV
- Expected: File downloaded
- Actual: 
- Status: 

**AN3 SLA metrics correct**
- Test Data: Overdue tasks
- Preconditions: Data seeded
- Steps: Open analytics
- Expected: Counts accurate
- Actual: 
- Status: 

### 14) Support Tickets
**ST1 Submit support ticket**
- Test Data: Message
- Preconditions: Email enabled
- Steps: Submit ticket
- Expected: Ticket created + email
- Actual: 
- Status: 

**ST2 Ticket appears in admin list**
- Test Data: Ticket exists
- Preconditions: Admin login
- Steps: Open admin list
- Expected: Ticket visible
- Actual: 
- Status: 

### 15) System Journal
**J1 Journal accessible to admin**
- Test Data: None
- Preconditions: Admin login
- Steps: Open journal
- Expected: Page loads
- Actual: 
- Status: 

**J2 Non-admin cannot access**
- Test Data: Non-admin user
- Preconditions: Login
- Steps: Open journal
- Expected: Access denied
- Actual: 
- Status: 

### 16) Permissions & Roles
**PR1 Superuser access all admin routes**
- Test Data: Admin account
- Preconditions: Login
- Steps: Open admin routes
- Expected: Access allowed
- Actual: 
- Status: 

**PR2 Extension/Supervisor restrictions**
- Test Data: Extension/Surveyor
- Preconditions: Login
- Steps: Attempt task assignment
- Expected: Access denied
- Actual: 
- Status: 

### 17) UI/UX & Responsiveness
**UI1 Admin verification queue fits on mobile**
- Test Data: Mobile viewport
- Preconditions: Admin login
- Steps: Open queue
- Expected: No horizontal scroll
- Actual: 
- Status: 

**UI2 Admin footer not covered**
- Test Data: Any admin page
- Preconditions: Desktop viewport
- Steps: Scroll footer
- Expected: Footer visible
- Actual: 
- Status: 

**UI3 Dashboard footer not covered**
- Test Data: User dashboard
- Preconditions: Desktop viewport
- Steps: Scroll footer
- Expected: Footer visible
- Actual: 
- Status: 

**UI4 Profile page responsive**
- Test Data: Mobile viewport
- Preconditions: Login
- Steps: Open profile
- Expected: Tabs/tables stack properly
- Actual: 
- Status: 

**UI5 Add Plot form responsive**
- Test Data: Mobile viewport
- Preconditions: Login
- Steps: Open add plot
- Expected: No overflow
- Actual: 
- Status: 

**UI6 Auth pages consistent layout**
- Test Data: Login/Register/Wizard
- Preconditions: None
- Steps: Open auth pages
- Expected: Same portal layout
- Actual: 
- Status: 
