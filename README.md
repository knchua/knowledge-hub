# Knowledge Hub

Knowledge Hub is a GenAI-powered application being developed as part of an
AI Bootcamp project.

The application will provide document-grounded knowledge retrieval,
document analysis and administrative knowledge management capabilities.

## Current Status

Phase 1 — Application Foundation complete.

## Current Development Phase

Phase 1 — Application Foundation

The current phase establishes:

- Streamlit application foundation
- Supabase connectivity
- Supabase authentication
- Administrator and User roles
- Role-based navigation
- User administration
- Audit logging
- Deployment-ready configuration

RAG, document ingestion, vector search and document analysis functionality
will be implemented in later phases.

## Technology Stack

- Python 3.12
- Streamlit
- Supabase Auth
- Supabase PostgreSQL
- Supabase Storage (future phases)
- Supabase pgvector (future phases)
- LangChain (future phases)
- OpenAI API (future phases)

## Phase 1 Features

- Supabase authentication
- Session validation
- Admin and User roles
- Active/inactive account enforcement
- Role-based navigation
- User invitation
- Role management
- Account activation/deactivation
- Password recovery
- User deletion
- Administrative audit logging
- Protected placeholder pages

## Python Version

Python 3.12

## Local Setup

...

## Supabase Setup

...

## First Administrator Bootstrap

See `docs/FIRST_ADMIN_BOOTSTRAP.md`.

## Security Model

- Streamlit session state is not an authorization boundary.
- Application roles come from `public.profiles`.
- Admin service methods require `require_admin()`.
- Privileged Supabase credentials remain server-side.
- PostgreSQL RLS protects user-scoped access.
- Audit records do not contain passwords or tokens.

## Testing

Run:

```bash
pytest

Create a virtual environment:

```bash
python3.12 -m venv .venv