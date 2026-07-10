# Devashish — Frontend integration handoff

## Hosting

| App | Host |
|-----|------|
| **Admin panel** | Vercel (`wealth-admin-seven.vercel.app`) |
| **Backend API** | **AWS Lightsail** (production) |
| **Interim API** | Vercel (`wealth-wisdom-six.vercel.app`) until Lightsail URL is ready |

**Admin Settings → Base URL**

- **Now (interim):** `https://api-goals.wealthswisdom.com/api/v1` (or `https://wealth-wisdom-six.vercel.app/api/v1`)
- **Production:** Lightsail URL when ready

Header on every admin call: `X-API-Key: <Admin key>` (not User key).

---

## 0. Admin View Details — assessment + calculation

```
GET /api/v1/assessment/{assessment_id}
```

Returns Flow 1–4 as before. When `/calculate` has been run, also returns:

- `calculation` — summary cards + client/spouse retirement block + goals + insurance total  
- `reports` — list of generated reports (`report_id`, `file_name`, `format`, `generated_at`)

If calculate not run: `calculation: null`. If no reports: `reports: []`.

**View Details mapping**

| UI | JSON path |
|----|-----------|
| Average Insurance Required | `calculation.summary.average_insurance_required` |
| Total Retirement Corpus | `calculation.summary.total_retirement_corpus_required` |
| Monthly Investment Required | `calculation.summary.monthly_investment_required` |
| Client SIP / corpus / PF / lump sum | `calculation.client.*` |
| Goals | `calculation.goals.items` |

Money fields use `{ display, raw, inr }` (same as calculate API).

---

## 1. Email & Marketing (admin)

**Send Campaign**

```
POST /api/v1/admin/marketing/campaign
multipart/form-data: subject, body, body_format (html|plain), optional recipients, optional attachments (max 12MB)
```

**Optional recipient list**

```
GET /api/v1/admin/marketing/recipients
```

Preview panel = frontend only.

---

## 2. Main website — Report on Download

```
POST /api/v1/report/{assessment_id}/download
```

Backend decides delivery (frontend does **not** track the 499 email limit).

| Response | Meaning |
|----------|---------|
| JSON — `"Report sent to your email."` | Email sent |
| File (PDF/DOCX) | Download locally — no consent, or daily cap (499) reached |

Check `Content-Type`: `application/json` vs file mime type.

On **Lightsail**, reports are **PDF** (LibreOffice). On interim Vercel they may be **DOCX**.

---

## 3. Testimonials

```
GET/POST   /api/v1/admin/testimonials
GET/PUT/DELETE /api/v1/admin/testimonials/{id}
```

Public: `GET /api/v1/testimonials/` (no auth, max 3 visible).

---

## 4. Reports download (admin)

Use report **ID** from API, not guessed filename:

```
GET /api/v1/admin/reports/{report_id}/download
```

Use `file_name` from list response.

---

## 5. Users / Leads / Assessments

```
GET /api/v1/admin/leads?page=1&per_page=100&from_date=&to_date=&search=
GET /api/v1/admin/users?...
GET /api/v1/admin/assessments?...
```

Show `error.message` on failures — not `[object Object]`.

---

## 7. API & Access Logs

```
GET    /api/v1/admin/api-keys?search=
POST   /api/v1/admin/api-keys
PUT    /api/v1/admin/api-keys/{key_id}/revoke
PUT    /api/v1/admin/api-keys/{key_id}/activate
```

- **Generate:** POST body `{ "client_name": "...", "role": "user"|"admin" }` — save `api_key_plaintext` from response (shown once)
- **List row fields:** `api_key_token`, `role_label`, `request_count`, `rate_limit`, `last_connection`, `status`
- **Revoked** → show Activate | **Expired** → no actions
- User keys rate-limited to **1,000/min**; admin unlimited

---

## 6. Rate config

`GET/PUT /api/v1/rates/` — admin key for save. Remove any `localStorage` fallback for `pf_growth`.

---

## No webhook needed

Report email + 499 cap: same API response handles email vs download. No webhook from frontend.
