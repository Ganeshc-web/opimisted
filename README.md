# Wealth Wisdom — Python Backend

REST API for financial goal assessments, calculations, and report data.

## Setup

1. Python 3.12+
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in values
4. `flask db upgrade`
5. `flask seed-admin`
6. `python run.py`

## API

- Docs: `http://127.0.0.1:5000/api/docs`
- Base path: `/api/v1/`
- Auth header: `X-API-Key: <key>`
