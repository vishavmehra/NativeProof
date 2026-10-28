# Security

## Reporting a vulnerability

Please report security issues privately through GitHub's "Report a vulnerability" form on this repository
(Security tab). Do not open a public issue for a suspected vulnerability. Include the affected endpoint or file, the
steps to reproduce, and the impact you observed.

## How secrets are handled

- Provider keys (Qloo, Nebius, OpenRouter), the database URL and the Supabase secret key live only in the backend's
  environment. They are never sent to the browser, written into prompts, or stored in application tables.
- The frontend receives only the Supabase URL and the publishable key, which are designed for client use.
- Configured secret values and bearer tokens are redacted from every log line (`backend/app/core/logging.py`).
- `.env` files are ignored by git. The `.env.example` files list variable names with placeholder values only.

## Access control

- Every API request is authenticated with a Supabase JWT, verified against the project's JWKS.
- The API checks ownership on every resource and returns 404 for another user's data.
- Row Level Security is enabled on user-owned tables for the Supabase Data API. Uploaded files are stored in a
  private Storage bucket under the owner's folder.

The automated checks for these rules are in `backend/tests/security/`.
