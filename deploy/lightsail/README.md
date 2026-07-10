# Deploy Flask API on AWS Lightsail

Production target for this backend. Admin frontend stays on Vercel; point it at the Lightsail API URL.

## Architecture

```
Main website  →  Lightsail (Flask + Gunicorn + Nginx + LibreOffice)
Admin panel   →  Vercel  →  Lightsail API (/api/v1)
Reports       →  AWS S3 (PDF/DOCX after generation)
Database      →  Lightsail managed PostgreSQL or Postgres on instance
Emails        →  SMTP (Gmail / Google Workspace)
```

## 1. Create Lightsail instance

- **OS:** Ubuntu 22.04 LTS
- **Plan:** at least **2 GB RAM** (LibreOffice PDF conversion)
- Attach a **static IP**
- Open ports **80**, **443**, **22**

## 2. Install dependencies (SSH into instance)

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip \
  libreoffice-writer nginx git \
  libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev

sudo mkdir -p /var/www/financial_api/reports
sudo chown -R $USER:$USER /var/www/financial_api
```

## 3. Deploy application

```bash
cd /var/www/financial_api
git clone <your-repo-url> .
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env — see Production env vars below
flask db upgrade
flask seed-admin
```

## 4. Production `.env` on Lightsail

```env
FLASK_ENV=production
SECRET_KEY=<strong-random-secret>
DATABASE_URL=postgresql://user:pass@host:5432/wealth_wisdom
REPORTS_FOLDER=/var/www/financial_api/reports

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=info@wealthswisdom.com
SMTP_PASSWORD=<app-password>
EMAIL_FROM=info@wealthswisdom.com

REPORT_EMAIL_DAILY_LIMIT=499
REPORT_EMAIL_QUOTA_TZ=Asia/Kolkata

AWS_S3_BUCKET=your-bucket
AWS_REGION=ap-south-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_S3_REPORT_PREFIX=reports
```

## 5. Gunicorn + systemd

Copy `gunicorn.service` to `/etc/systemd/system/financial-api.service`, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable financial-api
sudo systemctl start financial-api
sudo systemctl status financial-api
```

## 6. Nginx + HTTPS

- Copy `nginx.conf.example` to `/etc/nginx/sites-available/financial-api`
- Replace `api.yourdomain.com` with your domain
- `sudo ln -s /etc/nginx/sites-available/financial-api /etc/nginx/sites-enabled/`
- `sudo certbot --nginx -d api.yourdomain.com`

## 7. Verify

```bash
curl https://api.yourdomain.com/api/v1/health
```

Swagger: `https://api.yourdomain.com/api/docs`

## 8. Tell frontend (Devashish)

**Admin Settings → Base URL:**

```
https://api.yourdomain.com/api/v1
```

Use **Admin** and **User** API keys from `flask seed-admin`.

## Interim: Vercel

Until Lightsail is live, API may still run on Vercel (`wealth-wisdom-six.vercel.app`). Reports are DOCX-only there (no LibreOffice). Switch admin base URL when Lightsail is deployed.
