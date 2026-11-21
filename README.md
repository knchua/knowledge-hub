# Knowledge Hub

**Knowledge Hub** is a document-grounded Generative AI (GenAI) web application developed for an **AI Bootcamp final project**. It demonstrates administrator-managed knowledge ingestion, retrieval-augmented generation (RAG) with source citations, and temporary document analysis with summarisation, question answering, and selected OCR/multimodal processing.

The application is built using **Python, Streamlit, LangChain, OpenAI and Supabase** and deployed to **Streamlit Community Cloud**.

> **Project scope:** Knowledge Hub is an educational demonstration, not a production-certified knowledge-management or security system. AI-generated outputs require review against source documents; valid citations indicate provenance but do not independently guarantee factual accuracy.

## Features

### 1. Knowledge Management (administrators)

Administrators manage the shared knowledge repository:

- Upload supported **PDF, DOCX and TXT** documents.
- Validate files, extract text, split content with LangChain, generate OpenAI embeddings, and store searchable vectors in **Supabase PostgreSQL with pgvector**.
- Manage document versions, replacement, deletion, retries, and processing status through the authorised application workflow.
- Store original shared documents in **private Supabase Storage**.

Only authorised, active administrators can perform knowledge-management operations. The shared repository and the temporary document-analysis workflow are separate.

### 2. RAG Chatbot (administrators and users)

Authenticated, active users can ask questions about the shared repository. Knowledge Hub:

1. Generates a query embedding and retrieves eligible active-document chunks using pgvector similarity search.
2. Selects bounded supporting context for answer generation.
3. Generates a document-grounded answer and validates displayed source identifiers against retrieved evidence.
4. Shows source document references and excerpts; PDF page details are displayed where available.
5. Can decline to answer when relevant supporting evidence is insufficient.

Conversation history is session-scoped, and users can clear the current conversation.

### 3. Document Analysis (administrators and users)

Users can temporarily upload a **PDF, DOCX or TXT** for:

- **Concise, Detailed and Structured** summaries.
- Document-specific question answering with source evidence.
- Selective **OCR and AI visual interpretation** of supported scanned PDF pages and embedded document images, following the application's visual-processing disclosure and consent controls.

Temporary analysis content is held in application session state and **is not added to the shared knowledge repository, Supabase Storage, or persistent pgvector index**. Relevant document material is transmitted to OpenAI when AI processing is requested. Clearing application state does not guarantee physical memory erasure or provider-side deletion.

### 4. About Us and Methodology (final-submission enhancement)

Both pages are available to **authenticated, active administrators and regular users** under the **Information** navigation group:

- **About Us:** purpose, target users, core features, technology stack and AI Bootcamp scope.
- **Methodology:** architecture, ingestion, RAG, temporary analysis, OCR/multimodal processing, security, testing and limitations.

The pages are informational only and do not change the existing AI-processing or data-storage pipelines.

## Roles and navigation

| Navigation section | Page | Administrator | Regular user |
| --- | --- | :---: | :---: |
| Knowledge Hub | Chatbot | Yes | Yes |
| Knowledge Hub | Document Analysis | Yes | Yes |
| Information | About Us | Yes | Yes |
| Information | Methodology | Yes | Yes |
| Administration | Knowledge Management | Yes | No |
| Administration | User Management | Yes | No |

A restricted **Developer Tools** navigation group may be visible to an explicitly allowed developer administrator. This synthetic-only diagnostic capability is not a general user-facing feature. Unauthenticated and inactive accounts cannot access the authenticated navigation.

## Architecture

```text
                        Streamlit interface
                                |
                Python services + LangChain
                     /                    \
        Shared knowledge              Temporary analysis
        (administrator-managed)       (user session)
                     |                    |
       Supabase private Storage       Native text / selective
       + document extraction          OCR and AI vision
                     |                    |
          Text chunks + OpenAI        Source-grounded summary
               embeddings            and document Q&A
                     |
       PostgreSQL + pgvector
                     |
       Evidence retrieval -> RAG answers + source citations

       Supabase Auth + application authorisation guard access
```

**Technology stack:** Python 3.12, Streamlit, Supabase Auth/PostgreSQL/Storage, pgvector, LangChain, OpenAI, PyMuPDF, python-docx and Pillow. Pinned runtime dependencies are listed in [`requirements.txt`](requirements.txt).

### Processing boundaries

- **Shared ingestion:** indexed, versioned administrator-managed content used by the RAG chatbot.
- **Temporary analysis:** session-scoped user-uploaded content; it does not create shared knowledge vectors or persistent shared documents.
- **Visual processing:** OCR/vision augments supported temporary document analysis. It does **not** automatically ingest image-derived content into the persistent shared repository.

## Security and responsible AI

- Supabase authentication and application-profile validation, including active-account checks.
- Server-side administrator authorisation for privileged operations; sidebar/navigation visibility is not an authorisation boundary.
- Private storage and restricted access paths for the shared knowledge repository.
- Source-label validation, evidence-based responses, and insufficient-evidence abstention.
- Uploaded/retrieved document content treated as untrusted input, with prompt-injection safeguards and controlled evaluations.
- Session-state cleanup for conversation and temporary document analysis, with documented privacy limits.
- Bounded document/model operations and additional consent/budget controls for supported visual processing.
- Secrets configured outside the tracked repository; do not commit API keys, tokens or `.streamlit/secrets.toml`.

These controls reduce risk but do not establish comprehensive prompt-injection immunity, production security certification or universal answer correctness.

## Testing and evaluation

**Latest locally reported S4 regression:** **2,949 passed** after the About Us and Methodology changes and the corresponding navigation-test update. This result was reported for the local development working tree; it **may include dormant offline experimental tests not contained in the grading release**. It must not be presented as the exact test count of the previously published grading commit `29c22b2`.

Other recorded evaluation evidence includes:

- **12/12** latest controlled prompt-injection scenarios passed (specific tested scenarios only).
- Successful CPF LIFE document summarisation and targeted Q&A evaluation, with some summary omissions noted.
- Image-based infographic document analysis, including **eight targeted Q&A checks** and an appropriate refusal of an unsupported claim.
- Previously verified Streamlit Community Cloud deployment and smoke tests; the **new informational pages still require post-release Cloud verification** after the approved release is pushed.

Run local regression tests from the project root:

```bash
python -m pytest -q
```

Review results from the **exact final release candidate** before reporting a final release test total.

## Local development

This repository targets **Python 3.12**. From the project root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

The app requires a configured Supabase project, applicable database migrations/policies, and Streamlit secrets. Use the repository's setup/deployment documentation and example secrets configuration; do not place real credentials in version control. Application uploads are configured with a **20 MB Streamlit limit**, with additional processing constraints for selected operations.

For administrator setup, see [`docs/FIRST_ADMIN_BOOTSTRAP.md`](docs/FIRST_ADMIN_BOOTSTRAP.md).

## Deployment and release status

- **Source repository:** https://github.com/knchua/knowledge-hub
- **Deployment platform:** Streamlit Community Cloud (`app.py` entry point)
- **Existing grading-release baseline:** commit `29c22b2` on `main`
- **Final-submission informational enhancements:** About Us and Methodology verified locally; **new Git release commit and post-release Cloud smoke test are pending owner approval**.

Do not assume that uncommitted local changes are already deployed. Existing release tags are preserved.

## Known limitations

Knowledge Hub remains a bootcamp-scale implementation. Source references are traceable but do not establish claim-level factual entailment. OCR and visual descriptions may omit or misread unclear content, including complex diagrams or charts. Session-only analysis does not imply guaranteed physical erasure or provider deletion. The reported regression and security scenarios do not substitute for independent production security, concurrency, performance and operational audits.

## Project context

Knowledge Hub was developed as an AI Bootcamp capstone to demonstrate practical integration of web application development, role-based administration, vector search, LLM-assisted RAG, document summarisation and multimodal understanding. The **About Us** and **Methodology** pages explain the user-facing purpose and technical implementation within the application.
