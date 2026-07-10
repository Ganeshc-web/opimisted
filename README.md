# Financial Planning API

## Setup (local)
1. cd financial_api
2. python3.12 -m venv .venv
3. Windows: `.venv\Scripts\activate` — Mac/Linux: `source .venv/bin/activate`
4. pip install -r requirements.txt
5. cp .env.example .env
6. flask db upgrade
7. flask seed-admin
8. python run.py

## Swagger UI
http://127.0.0.1:5000/api/docs

## Auth
Header on every request: `X-API-Key: YOUR_KEY_FROM_SEED_ADMIN`

## Base URL (local)
http://127.0.0.1:5000/api/v1/

## Production (AWS Lightsail)
- Backend API runs on **Lightsail** (Gunicorn + Nginx + LibreOffice for PDF reports)
- Reports stored in **AWS S3**
- Admin frontend on **Vercel** — set Base URL to Lightsail API
- Full deploy steps: [deploy/lightsail/README.md](deploy/lightsail/README.md)
- Frontend handoff: [docs/DEVASHISH_HANDOFF.md](docs/DEVASHISH_HANDOFF.md)

## Interim (Vercel)
API may run on Vercel until Lightsail is live. Reports are DOCX-only there (no LibreOffice).
