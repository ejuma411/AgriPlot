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

Create `.env` (example values in `agriplot/.env`). Key variables:
- `DJANGO_SECRET_KEY`
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- `SITE_URL`

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

## System Construction Journal
- JSON data stored in `verification/data/system_construction_journal.json`.
- Superadmin-only export: PDF from the journal page.

## Notes
- SMS integration supports a mock mode (`USE_SMS_MOCK=True`) for local testing.
- Some admin templates exist in both `templates/listings/admin` and `templates/verification/admin` for backward compatibility.

