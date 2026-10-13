# Knowledge Hub — Phase 1: Application Foundation

**Status:** Planned  
**Architecture baseline:** Streamlit + Python + Supabase Auth/PostgreSQL/Storage + LangChain + pgvector + OpenAI  
**Development:** Local first  
**Deployment target:** Streamlit Community Cloud

## 1. Objective

Build a secure, modular Streamlit application foundation with authentication, role-based access control, basic user administration, and navigation. Subsequent phases will implement document ingestion, retrieval-augmented generation (RAG), and document analysis.

## 2. Scope

### In scope
- Streamlit application shell, login/logout, protected navigation and session handling.
- Supabase Auth integration and user profile/role persistence in PostgreSQL.
- Two roles: `admin` and `user`.
- Administrator functions to invite/provision users, list accounts, assign roles, and deactivate access.
- Role-based access checks for both pages and privileged operations.
- Placeholder pages for Chatbot, Document Analysis, Knowledge Management and User Management.
- Initial audit logging for administrative changes.
- Local configuration, environment/secrets management, automated tests and deployment-ready project structure.

### Out of scope
- Knowledge document upload, replacement, deletion, parsing and indexing.
- pgvector schema and semantic search.
- LangChain RAG chains, embeddings, LLM answers and citations.
- Actual user document summarisation and analysis.
- Enterprise SSO, enforced MFA and document-level access controls.

## 3. Roles and permissions

| Capability | Administrator | User |
|---|---|---|
| Sign in / sign out | Yes | Yes |
| Chatbot placeholder | Yes | Yes |
| Document Analysis placeholder | Yes | Yes |
| Knowledge Management placeholder | Yes | No |
| User Management | Yes | No |
| Invite/provision users | Yes | No |
| Assign roles and deactivate accounts | Yes | No |

Default new accounts to `user`; never permit self-assignment to `admin`. Disable public sign-up for the initial version. Bootstrap the first administrator using a controlled, documented administrative procedure.

## 4. Technology choices

| Concern | Technology |
|---|---|
| UI and app runtime | Streamlit, Python |
| Identity | Supabase Auth |
| User profiles, roles, audit records | Supabase PostgreSQL |
| Database security | Supabase Row Level Security (RLS) and tightly scoped privileged operations |
| Secrets | Local untracked `.streamlit/secrets.toml`; Streamlit Community Cloud secrets on deployment |
| Tests | pytest |
| Later-phase RAG | LangChain, Supabase pgvector, OpenAI |
| Later-phase documents | Supabase Storage (private buckets) |

## 5. Logical design

- **UI layer:** Streamlit pages and reusable interface components.
- **Authentication layer:** Supabase sign-in/sign-out, token validation and session state.
- **Authorisation layer:** Centralised role checks invoked by each protected page and privileged service.
- **User administration service:** Restricted provisioning, role changes and account deactivation.
- **Data access layer:** Supabase clients and database operations, isolated from UI code.
- **Audit service:** Records actor, action, target and timestamp for administrative changes; avoid secrets and unnecessary personal data.

Streamlit session state is a UI/session convenience, not an authoritative permission source. Validate identity and effective role server-side for protected actions. Use Supabase RLS where user-scoped access is possible. Keep any service-role credential strictly server-side; never expose it to browser code, logs or repository commits.

## 6. Initial database entities

### `auth.users`
Supabase-managed identities; do not manually replace this authentication system.

### `public.profiles`
Suggested fields: `user_id` (UUID, primary key and reference to `auth.users`), `display_name`, `role` (`admin` or `user`, default `user`), `is_active`, `created_at`, `updated_at`.

Only privileged administrative operations may modify `role` and `is_active`. Users may be allowed to read/update narrowly permitted profile fields, but never their own role or active status. Define and test RLS policies accordingly.

### `public.audit_logs`
Suggested fields: `id`, `actor_user_id`, `action`, `target_user_id`, `created_at`, `details` (limited JSON metadata). Restrict log reading and writing; do not store tokens or passwords.

Note: disabling an application profile must be checked during authorisation, and should be paired with an appropriate Supabase Auth account restriction/session-revocation strategy. Merely hiding UI controls does not revoke access.

## 7. Proposed source layout

```text
knowledge-hub/
├── app.py
├── pages/
│   ├── chatbot.py
│   ├── document_analysis.py
│   ├── knowledge_management.py
│   └── user_management.py
├── services/
│   ├── auth_service.py
│   ├── authorization_service.py
│   ├── user_service.py
│   └── audit_service.py
├── database/
│   ├── client.py
│   └── migrations/
├── config/
│   └── settings.py
├── tests/
├── docs/
│   └── plans/
│       └── PHASE_01_APPLICATION_FOUNDATION.md
├── .streamlit/
│   └── secrets.toml.example
├── .gitignore
├── requirements.txt
└── README.md
```

The file layout is a starting point and may be refined in the implementation chat. Do not commit real `secrets.toml` files.

## 8. Implementation sequence

1. Initialise Python project, dependencies, source layout, Git ignore rules and configuration loading.
2. Create Supabase project and initial schema/migrations; configure RLS.
3. Implement login/logout, session validation and first-admin bootstrap procedure.
4. Implement centralised authorisation and protected Streamlit navigation.
5. Implement admin user provisioning, listing, role assignment and deactivation.
6. Implement audit logging and placeholder feature pages.
7. Add automated tests, manual security checks and deployment documentation.

## 9. Acceptance criteria

- [ ] Admin and normal user can authenticate and log out.
- [ ] Anonymous visitors cannot access protected pages or operations.
- [ ] Normal users cannot access admin pages or invoke admin services, even by direct navigation or crafted calls.
- [ ] Admin can provision/invite users, list accounts, change roles and deactivate access.
- [ ] Deactivated accounts are denied application access; auth/session implications are handled and tested.
- [ ] A user cannot grant themselves admin privileges through profile updates or database APIs.
- [ ] Both roles can access Chatbot and Document Analysis placeholders.
- [ ] Only admins can access Knowledge Management and User Management placeholders.
- [ ] Administrative changes are logged without leaking secrets.
- [ ] Secrets are not committed to source control or exposed in the UI.
- [ ] Local startup, setup instructions and pytest tests work.
- [ ] Streamlit Community Cloud deployment requirements are documented.

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Streamlit session state mistaken for security boundary | Revalidate identity and permissions in privileged services and enforce RLS |
| Admin credential exposure | Keep privileged credentials server-side in secrets, limit usage, never log |
| Users modifying their own roles | Restrictive RLS and privileged role-change path |
| Account deactivation fails to block existing sessions | Check active status for every protected action and define Auth session handling |
| Cloud/local configuration divergence | Use environment-based configuration and documented secrets |
| Scope creep into RAG implementation | Keep Phase 1 pages as placeholders |

## 11. Phase handoff

At completion, return to the master planning chat with: implementation summary, repository layout, schema/policies, test results, outstanding issues and any proposed architecture changes. Do not silently change the agreed technology stack.
