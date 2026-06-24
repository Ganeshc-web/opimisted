# Financial Planning API

## Setup
1. cd financial_api
2. python3.12 -m venv .venv
3. Windows: .venv\Scripts\activate
   Mac/Linux: source .venv/bin/activate
4. pip install -r requirements.txt
5. cp .env.example .env
6. flask db upgrade
7. flask seed-admin   ← copy the key printed, you need it for all requests
8. python run.py

## Swagger UI
http://127.0.0.1:5000/api/docs

## Auth
Add header to every request:
X-API-Key: YOUR_KEY_FROM_SEED_ADMIN

## Base URL
http://127.0.0.1:5000/api/v1/
