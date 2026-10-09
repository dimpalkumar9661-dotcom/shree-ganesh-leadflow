# Shree Ganesh LeadFlow — cloud version

Public inquiry form and a token-protected lead dashboard, using Flask, Supabase and Render. AI coding assistance was used to prepare this version.

## Deploy

1. Extract this ZIP into a NEW folder. Upload app.py, index.html, dashboard.html, requirements.txt, supabase_setup.sql, README.md and .gitignore to the GitHub repository root. Do not upload SQLite databases or keys. Keep the existing local project and database intact.
2. In your existing Supabase project, run supabase_setup.sql in SQL Editor. It creates a separate leadflow_leads table and denies public database access. TeleCare's tables are not changed.
3. In Render create a Python 3 Web Service from shree-ganesh-leadflow, branch main, empty Root Directory. Select Free if available. Build Command: pip install -r requirements.txt
4. Start Command: gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 60 app:app
5. Health Check Path: /health
6. Set environment variables ONLY in Render:
   - SUPABASE_URL: your project base URL, e.g. https://your-project.supabase.co (without /rest/v1/)
   - SUPABASE_SECRET_KEY: server-only sb_secret_... key. Alternatively SUPABASE_SERVICE_ROLE_KEY with the legacy service_role key. Never use anon/publishable here.
   - ADMIN_TOKEN: a private ASCII password/token of at least 24 characters. Use a different token from your local demo.
7. Deploy. Public form: the assigned Render URL. Dashboard: append /dashboard. Enter ADMIN_TOKEN and click Load leads. Share the homepage URL; keep the token private.

## Verify before sharing

Submit a clearly marked fictional test inquiry from a second browser. Confirm success, log in to the dashboard, check the new row, change status and reload. Verify the row survives a Render restart. Without a token, /api/leads must return 403. The cloud database starts empty: your two old local entries stay in leads.sqlite3 and are not automatically copied online.

## Scope

Captures inquiries, lists the latest 500 leads, searches those displayed leads and saves status changes. No AI follow-up generation or email notifications are enabled in this cloud release. Homepage uses sample service pricing. Demo visitors should use fictional details. A real customer launch needs business-approved contact/privacy information, retention arrangements and stronger abuse controls.

The dashboard HTML is public but contains no records or secrets; only authenticated API calls return records. Token lives in the current tab's memory. Supabase secret stays on the server. No SQLite files are opened. No automatic retries of inquiry writes. If a network timeout occurs after saving, verify in the dashboard before submitting again.

Request limits are process-wide (30 submissions/minute, 120 admin API requests/minute), reset on restart, and configured for one worker. The health route reports process liveness, not database availability. Free hosting may sleep and take time to wake; provider plan limits apply. This is a portfolio prototype, not an unattended high-volume production service.
