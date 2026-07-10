"""Run full assessment → calculate → report generate flow (Method 2)."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from run import create_app

BASE = "/api/v1"
# Fixed local-only key so the script can run without flask seed-user.
LOCAL_DEV_KEY = "local-report-flow-key"


def ensure_local_user_key():
    from app import db
    from app.middleware.auth import hash_key
    from app.models.api_key import APIKey

    key_hash = hash_key(LOCAL_DEV_KEY)
    row = APIKey.query.filter_by(key_hash=key_hash).first()
    if not row:
        db.session.add(
            APIKey(
                client_name="Local Report Flow",
                key_hash=key_hash,
                role="user",
                is_active=True,
            )
        )
        db.session.commit()
    elif not row.is_active:
        row.is_active = True
        db.session.commit()


def api(client, method, path, body=None, api_key=None):
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    data = json.dumps(body) if body is not None else None
    return client.open(
        f"{BASE}{path}",
        method=method,
        data=data,
        headers=headers,
    )


def main():
    app = create_app()
    with app.app_context():
        from app import db
        from app.middleware.auth import hash_key
        from app.models.api_key import APIKey
        from app.models.rate_config import RateConfig

        db.create_all()

        user_key = os.environ.get("TEST_USER_API_KEY")
        if not user_key:
            ensure_local_user_key()
            user_key = LOCAL_DEV_KEY
            print(f"Using local dev API key (set TEST_USER_API_KEY to override)")

        if not RateConfig.query.first():
            db.session.add(
                RateConfig(
                    inflation_post=0.06,
                    roi_post=0.08,
                    inflation_pre=0.06,
                    roi_pre=0.12,
                    pf_growth=0.05,
                    updated_by="script",
                )
            )
            db.session.commit()

    client = app.test_client()

    print("1. POST /assessment")
    res = api(client, "POST", "/assessment/", api_key=user_key)
    print(f"   status={res.status_code}")
    body = res.get_json()
    if res.status_code != 200:
        print(body)
        return 1
    assessment_id = body["data"]["assessment_id"]
    print(f"   assessment_id={assessment_id}")

    print("2. POST flow1")
    flow1 = {
        "mobile": "9876543210",
        "email": "client@example.com",
        "spouse_mobile": "9876543211",
        "spouse_email": "spouse@example.com",
        "residential_address": "123 Main St, Mumbai",
        "consent": True,
    }
    res = api(client, "POST", f"/assessment/{assessment_id}/flow1", flow1, user_key)
    print(f"   status={res.status_code}")
    if res.status_code != 200:
        print(res.get_json())
        return 1

    print("3. POST flow2")
    flow2 = {
        "client_name": "Yogesh Taori",
        "client_occupation": "Engineer",
        "client_designation": "Manager",
        "client_company": "Tech Corp",
        "client_dob": "01/01/1990",
        "client_retirement_age": 62,
        "spouse_name": "Spouse Name",
        "spouse_occupation": "Teacher",
        "spouse_designation": "Senior Teacher",
        "spouse_company": "School",
        "spouse_dob": "01/01/1995",
        "spouse_retirement_age": 55,
    }
    res = api(client, "POST", f"/assessment/{assessment_id}/flow2", flow2, user_key)
    print(f"   status={res.status_code}")
    if res.status_code != 200:
        print(res.get_json())
        return 1

    print("4. POST flow3")
    flow3 = {
        "number_of_children": 1,
        "children": [
            {
                "child_number": 1,
                "full_name": "Child One",
                "occupation": "Student",
                "financially_dependent": True,
                "date_of_birth": "01/06/2010",
            }
        ],
    }
    res = api(client, "POST", f"/assessment/{assessment_id}/flow3", flow3, user_key)
    print(f"   status={res.status_code}")
    if res.status_code != 200:
        print(res.get_json())
        return 1

    print("5. POST flow4")
    flow4 = {
        "goals": [
            {
                "category": "lifestyle",
                "goal_type": "Home Purchase",
                "target_year": 2035,
                "today_cost": 5000000,
                "inflation_rate": 0.06,
            }
        ]
    }
    res = api(client, "POST", f"/assessment/{assessment_id}/flow4", flow4, user_key)
    print(f"   status={res.status_code}")
    if res.status_code != 200:
        print(res.get_json())
        return 1

    print("6. POST /calculate")
    calc_body = {
        "client_epf_annual": 33600,
        "client_epf_accum": 1039997,
        "client_annual_ret_reqd": 1500000,
        "spouse_epf_annual": 7200,
        "spouse_epf_accum": 0,
        "spouse_annual_ret_reqd": 1000000,
        "household_monthly": 30000,
    }
    res = api(client, "POST", f"/calculate/{assessment_id}", calc_body, user_key)
    print(f"   status={res.status_code}")
    if res.status_code != 200:
        print(res.get_json())
        return 1

    print("7. POST /report/generate")
    res = api(client, "POST", f"/report/{assessment_id}/generate", api_key=user_key)
    print(f"   status={res.status_code}")
    print(f"   content-type={res.content_type}")

    if res.content_type and "json" in res.content_type:
        data = res.get_json()
        print(json.dumps(data, indent=2))
        if data.get("data", {}).get("message"):
            print("\nReport emailed (consent=true).")
    else:
        reports_dir = ROOT / "reports"
        ext = "pdf" if "pdf" in (res.content_type or "") else "bin"
        out = reports_dir / f"generated_{assessment_id[:8]}.{ext}"
        out.write_bytes(res.data)
        print(f"\nReport saved: {out}")
        print(f"   size={out.stat().st_size} bytes")

    # Also list reports folder for latest files
    reports_dir = ROOT / "reports"
    if reports_dir.exists():
        latest = sorted(
            reports_dir.glob("report_*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:3]
        if latest:
            print("\nLatest report files in reports/:")
            for p in latest:
                print(f"   {p.name} ({p.stat().st_size} bytes)")

    print("\nDONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
