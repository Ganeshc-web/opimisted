# Financial Planning API

## Setup
1. git clone https://github.com/Ganeshc-web/flask.git
2. cd financial_api
3. python3.12 -m venv .venv
4. Windows: .venv\Scripts\activate
   Mac/Linux: source .venv/bin/activate
5. pip install -r requirements.txt
6. cp .env.example .env
7. flask db upgrade
8. flask seed-admin   ← copy the key printed, you need it for all requests
9. python run.py

## Swagger UI
http://127.0.0.1:5000/api/docs

## Auth
Add header to every request:
X-API-Key: YOUR_KEY_FROM_SEED_ADMIN

## Base URL
http://127.0.0.1:5000/api/v1/
