# SwissUnihockey Stats - Claude Code Guide

## Project Overview

SwissUnihockey Stats is a FastAPI-based web application that displays Swiss floorball (unihockey) statistics. It fetches data from the official Swiss Unihockey API and presents it as a multi-language, mobile-first PWA.

## Tech Stack

- **Backend**: Python 3.9+, FastAPI, Uvicorn/Gunicorn
- **Templating**: Jinja2
- **Database**: SQLite (via SQLAlchemy)
- **Frontend**: HTMX, Alpine.js, Chart.js, vanilla CSS
- **i18n**: Custom JSON locale files (de, en, fr, it)
- **Deployment**: Docker

## Project Structure

```
SwissUnihockeyStats/
├── CLAUDE.md                    # This file
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, all page routes
│   │   ├── config.py            # Pydantic settings (env-driven)
│   │   ├── api/v1/              # JSON API endpoints
│   │   ├── lib/i18n.py          # Translation loader
│   │   ├── models/db_models.py  # SQLAlchemy models
│   │   └── services/            # Business logic, caching, scheduler
│   ├── templates/               # Jinja2 HTML templates
│   ├── static/                  # CSS, JS, images
│   ├── locales/                 # Translation files (de/en/fr/it)
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── manage.py                # CLI management commands
│   └── .env.example             # Environment variable template
└── Dockerfile
```

## Common Commands

```bash
# Run the development server
cd backend
uvicorn app.main:app --reload --port 8000

# Run with gunicorn (production-like)
gunicorn -w 1 -k uvicorn.workers.UvicornWorker app.main:app

# Run tests
cd backend
pytest

# Index data (populate DB from SwissUnihockey API)
python manage.py index-clubs-path --season 2025
```

## Environment Configuration

Copy `backend/.env.example` to `backend/.env` and fill in the values. Key settings:

| Variable | Description |
|---|---|
| `ADMIN_PIN` | Admin dashboard PIN (required in production) |
| `SESSION_SECRET` | Secret key for session cookies (required in production) |
| `DEBUG` | Set `true` for development, `false` for production |
| `SMTP_HOST` | SMTP server hostname for contact form emails |
| `SMTP_PORT` | SMTP port (default: 587) |
| `SMTP_USER` | SMTP username / sender email |
| `SMTP_PASSWORD` | SMTP password |
| `CONTACT_EMAIL` | Email address that receives contact form submissions |

## Adding a New Page

1. Create the template in `backend/templates/<page>.html` extending `base.html`
2. Add the route in `backend/app/main.py` following the `/{locale}/<page>` pattern
3. Add translation keys to all four locale files in `backend/locales/*/messages.json`
4. If needed, add a footer or nav link in `backend/templates/base.html`

## i18n Conventions

All user-facing strings live in `backend/locales/{locale}/messages.json`.
Access in templates via `{{ t.section.key }}`.
Supported locales: `de`, `en`, `fr`, `it`.

## Code Conventions

- All page routes follow `/{locale}/{page}` URL pattern
- Template context always includes `locale` and `t` (translations)
- Use `get_translations(locale)` from `app.lib.i18n` to load translations
- Static files are served from `/static/` with cache-busting query strings
- Keep routes in `main.py`; business logic in `services/`
