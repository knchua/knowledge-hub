
This prevents someone reviewing the repository from mistaking placeholders for finished AI functionality.

---

## 6. Create deployment documentation

Create:

**`docs/DEPLOYMENT_STREAMLIT_COMMUNITY_CLOUD.md`**

with:

```markdown
# Knowledge Hub — Streamlit Community Cloud Deployment

## Prerequisites

Before deployment:

1. Phase 1 tests pass locally.
2. Source code is committed to GitHub.
3. `.streamlit/secrets.toml` is not committed.
4. Supabase project is available.
5. Custom SMTP is configured for Auth email flows.
6. Supabase Auth email templates support invite and recovery TokenHash links.

## Python

Knowledge Hub uses Python 3.12.

Select Python 3.12 in Streamlit Community Cloud Advanced Settings.

## Entrypoint

Use:

`app.py`

## Dependencies

Python dependencies are defined in:

`requirements.txt`

## Streamlit Cloud Secrets

In Streamlit Community Cloud Advanced Settings → Secrets, configure:

```toml
[supabase]
url = "https://YOUR_PROJECT.supabase.co"
publishable_key = "..."
secret_key = "..."

[app]
base_url = "https://YOUR-APP.streamlit.app"