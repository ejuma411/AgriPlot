# AgriPlot Connect

AgriPlot Connect is a Django 5.2 application for listing, verifying, and managing agricultural plots. It includes role-based onboarding for agents, landowners, extension officers, and surveyors, with verification workflows, audit logging, notifications, and registry lookups.

## Highlights
- **Listings**: Create and manage agricultural plot listings with documents and pricing support.
- **Verification**: Multi-stage verification workflow (document review, extension review, surveyor inspection, registry search).
- **Security**: 2FA, OTP, audit logs, and role request approvals.
- **Notifications**: Email and SMS notifications with logging.
- **Admin**: Dedicated verification/admin views and analytics.
- **Registry Mock**: Local registry mock for testing title searches.

## Project Structure
- `accounts/` — User profiles and dashboards (agent, landowner, staff).
- `authentication/` — Login and password reset flows, 2FA setup.
- `listings/` — Core listing models, forms, public pages, and dashboards.
- `verification/` — Verification workflows, admin queue, analytics, and exports.
- `notifications/` — Email/SMS services and notification models.
- `security/` — 2FA, OTP, audit logs, and security models.
- `registry_mock/` — Mock registry data and services.
- `templates/` — Shared templates for public and admin views.
- `static/` / `media/` — Static assets and user uploads.

## Tech Stack
- **Django 5.2**
- **PostgreSQL**
- **Celery** (task queue)
- **WeasyPrint** (PDF export)
- **pytest + pytest-django** (tests)

## Prerequisites
- Python 3.11+ (project currently uses 3.13 in development)
- PostgreSQL
- `pip` and a virtual environment

## Setup
```bash
python -m venv env
source env/bin/activate
pip install -r requirements.txt
```

Create `.env` from `.env.example`. Key variables:
- `DJANGO_SECRET_KEY`
- `DATABASE_URL` for Supabase/hosted Postgres, or `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` for local Postgres
- `SITE_URL`

For Supabase, copy a Postgres connection string from the Supabase Dashboard's **Connect** panel. The session pooler string is a good default for a persistent Django server on IPv4 networks. Keep SSL enabled with either `?sslmode=require` in `DATABASE_URL` or `DB_SSL=True`/`DB_SSLMODE=require` when using the individual `DB_*` variables.

## Migrations
```bash
python manage.py makemigrations
python manage.py migrate
```

If you run into migration history issues (common when tables already exist), use:
```bash
python manage.py migrate --fake-initial
```

## Running the Server
```bash
python manage.py runserver
```

## Tests
```bash
pytest -q
```

If your PostgreSQL user lacks `CREATEDB`, tests may fail when creating a test DB. Grant permissions or use `--reuse-db` with a pre-created test DB.

## Admin / Verification Dashboard
- Verification admin routes live under the **verification** app.
- Superadmin-only tools include **Audit Logs** and **System Construction Journal** exports.

## Audit Logs
- Stored in `security.AuditLog`.
- Superadmin-only view: `/verify/audit-logs/`
- Exports: CSV/JSON via the audit logs page.

## UX, Accessibility & Analytics
- Global accessibility helpers: skip link, focus-visible styles, required-field indicators, and ARIA validation feedback.
- Consistent feedback via toasts (replacing browser `alert()` in key flows).
- Lightweight UX analytics endpoint: `POST /analytics/track/` (uses `sendBeacon` when available, honors Do Not Track).

## Authentication Alerts
- Login, 2FA verify/setup, and password reset templates now show inline validation errors and global alerts.

## System Construction Journal
- JSON data stored in `verification/data/system_construction_journal.json`.
- Superadmin-only export: PDF from the journal page.

## Security & HCI
### Security posture (implemented)
- **Access control**: Document access is restricted to owners or staff; non-owners cannot view unapproved listings.
- **Verification gates**: Feature flags enforce contact verification, 2FA, and document verification before listing.
- **Auditability**: Sensitive actions write to `security.AuditLog` for traceability.
- **Platform hardening**: Security headers, secure cookie flags, and HTTPS/HSTS settings are available via `settings.py`.

### HCI/UX focus (current + recommended upgrades)
Current UX focuses on guided flows and clear error messaging (e.g., prompts to verify email/phone or enable 2FA).
Recommended HCI upgrades:
- **Accessibility checks**: WCAG contrast, keyboard navigation, focus states, and ARIA labels.
- **Form usability**: Inline validation, progressive disclosure for complex forms, and clearer help text.
- **Feedback loops**: Success/error toast consistency and empty-state guidance.
- **Journey mapping**: Map agent/landowner/verification journeys and remove friction points.
- **UX analytics**: Lightweight event tracking (page funnel + drop-off points) with privacy controls.
- **Usability testing**: Short task-based tests for onboarding and document upload flows.

## Notes
- SMS integration supports a mock mode (`USE_SMS_MOCK=True`) for local testing.
- Some admin templates exist in both `templates/listings/admin` and `templates/verification/admin` for backward compatibility.
