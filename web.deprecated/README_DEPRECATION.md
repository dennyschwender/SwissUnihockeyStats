# Deprecated Next.js Frontend

## ⚠️ DEPRECATED - DO NOT USE

This directory contains the original Next.js frontend implementation that has been **deprecated** and **replaced** by the Python full-stack implementation.

## Deprecation Details

- **Deprecated Date**: 2025-01-16
- **Reason**: Replaced with Python full-stack (FastAPI + Jinja2 + htmx + Alpine.js)
- **New Frontend Location**: `backend/templates/` and `backend/static/`
- **Status**: Archived for reference only

## Why Was This Deprecated?

The original Next.js implementation (Week 1 of MODERN_WEB_APP_ROADMAP.md) was replaced because:

1. **Bundle Size**: 350 KB compressed (1.2 MB uncompressed) - too large
2. **Complexity**: Separate frontend/backend deployment complexity
3. **Performance**: Slower initial page load due to JS bundle
4. **Maintenance**: Two separate codebases (TypeScript + Python)

## New Architecture

The new Python full-stack implementation provides:

- **FastAPI backend** at `backend/app/main.py`
- **Jinja2 templates** at `backend/templates/` (server-side rendering)
- **htmx** for dynamic interactions (35 KB total with Alpine.js)
- **Alpine.js** for local state management
- **Single codebase** - Python only
- **Better performance** - server-side rendering with progressive enhancement

## What Was in This Directory?

```
web/
├── src/
│   ├── app/                 # Next.js App Router pages
│   │   ├── [locale]/        # Internationalized routes
│   │   ├── layout.tsx       # Root layout
│   │   └── page.tsx         # Home page
│   ├── components/          # React components
│   │   ├── Header.tsx
│   │   ├── LanguageSwitcher.tsx
│   │   └── ThemeProvider.tsx
│   ├── lib/                 # Utilities
│   │   └── i18n.ts          # Internationalization (replaced by backend/app/lib/i18n.py)
│   └── dictionaries/        # Translation files (replaced by backend/i18n/)
├── public/                  # Static assets
├── next.config.js           # Next.js configuration
├── tailwind.config.ts       # Tailwind CSS config
└── package.json             # Node.js dependencies
```

## Migration Notes

- **Translations**: Migrated from `web/src/dictionaries/*.json` to `backend/i18n/*.json`
- **Components**: Converted React components to Jinja2 templates
- **Routing**: App Router routes converted to FastAPI endpoints
- **State Management**: React state replaced with htmx + Alpine.js
- **Styling**: Tailwind CSS replaced with custom CSS (Swiss theme)

## Can I Still Use This?

**No.** This code is archived for reference only. It will not be maintained or updated.

If you need the modern web app, use the Python full-stack implementation:

```bash
cd backend
uvicorn app.main:app --reload
```

Then visit: http://localhost:8000/

## Documentation

See the following files for the new implementation:

- [PYTHON_FULL_STACK.md](../PYTHON_FULL_STACK.md) - Current implementation guide
- [MODERN_IMPLEMENTATION.md](../MODERN_IMPLEMENTATION.md) - Week 2/3 progress
- [MODERN_WEB_APP_ROADMAP.md](../MODERN_WEB_APP_ROADMAP.md) - Original plan (Week 1 deprecated)

## Need Help?

If you're looking to understand the current implementation:

1. Read `PYTHON_FULL_STACK.md` for architecture overview
2. Check `backend/app/main.py` for FastAPI routes
3. Look at `backend/templates/` for Jinja2 templates
4. See `tests/` for comprehensive test suite (113 tests)

---

**This directory is kept for historical reference only.**
**All new development happens in `backend/` directory.**
