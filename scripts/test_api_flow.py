"""End-to-end API flow test against running Flask server."""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = "http://127.0.0.1:5000/api/v1"
API_KEY = "24e2a5fb9fe9ec308816743b3526bf869127a9e38a57e27e5d8eddef11c67948"


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": API_KEY,
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def main():
    print("1. POST /assessment")
    status, res = api("POST", "/assessment/")
    print(f"   status={status}")
    assert status == 200, res
    assessment_id = res["data"]["assessment_id"]
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
    status, res = api("POST", f"/assessment/{assessment_id}/flow1", flow1)
    print(f"   status={status}")
    assert status == 200, res

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
    status, res = api("POST", f"/assessment/{assessment_id}/flow2", flow2)
    print(f"   status={status}")
    assert status == 200, res
    print(f"   client_age={res['data']['client_age']}, spouse_age={res['data']['spouse_age']}")

    print("4. POST flow3")
    flow3 = {
        "number_of_children": 2,
        "children": [
            {
                "child_number": 1,
                "full_name": "Child One",
                "occupation": "Student",
                "financially_dependent": True,
                "date_of_birth": "01/06/2010",
            },
            {
                "child_number": 2,
                "full_name": "Child Two",
                "occupation": "Student",
                "financially_dependent": True,
                "date_of_birth": "15/03/2013",
            },
        ],
    }
    status, res = api("POST", f"/assessment/{assessment_id}/flow3", flow3)
    print(f"   status={status}")
    assert status == 200, res

    print("5. POST flow4")
    flow4 = {
        "goals": [
            {
                "category": "child_goal",
                "goal_type": "Child 1 Graduation",
                "target_year": 2040,
                "today_cost": 2500000,
                "inflation_rate": 0.08,
            },
            {
                "category": "child_goal",
                "goal_type": "Child 1 PG",
                "target_year": 2044,
                "today_cost": 3500000,
                "inflation_rate": 0.08,
            },
            {
                "category": "child_goal",
                "goal_type": "Child 1 Marriage",
                "target_year": 2042,
                "today_cost": 2000000,
                "inflation_rate": 0.06,
            },
            {
                "category": "lifestyle",
                "goal_type": "House Purchase",
                "target_year": 2035,
                "today_cost": 5000000,
                "inflation_rate": 0.06,
            },
        ]
    }
    status, res = api("POST", f"/assessment/{assessment_id}/flow4", flow4)
    print(f"   status={status}")
    assert status == 200, res
    print(f"   goals saved={len(res['data']['goals'])}")

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
    status, res = api("POST", f"/calculate/{assessment_id}", calc_body)
    print(f"   status={status}")
    if status != 200:
        print(json.dumps(res, indent=2))
        return
    data = res["data"]
    client = data["client"]
    print(f"   client corpus raw={client['corpus']['raw']:.2f}")
    print(f"   client net_corpus raw={client['net_corpus']['raw']:.2f}")
    print(f"   client monthly_sip raw={client['monthly_sip']['raw']:.2f}")
    print(f"   insurance total raw={data['insurance']['total_required']['raw']:.2f}")
    print(f"   goals total monthly raw={data['goals']['total_monthly_sip']['raw']:.2f}")

    # Cross-check against formulas.py directly
    from app.core.formulas import (
        END,
        build_insurance_rows,
        compute_all_goals,
        full_corpus_calc,
        monthly_effective_rate,
        real_rate,
    )

    from app.core.formulas import current_year, age_from_dob_year

    client_age = age_from_dob_year(1990)
    spouse_age = age_from_dob_year(1995)
    rates = {"inflation_post": 0.06, "roi_post": 0.08, "inflation_pre": 0.06, "roi_pre": 0.12}
    rr = real_rate(rates["roi_post"], rates["inflation_post"])
    mly = monthly_effective_rate(rates["roi_pre"])

    expected_client = full_corpus_calc(
        1500000, client_age, 62, 33600, 1039997,
        **rates, pmt_when=END,
    )
    expected_spouse = full_corpus_calc(
        1000000, spouse_age, 55, 7200, 0,
        **rates, pmt_when=END,
    )
    goal_input = [
        {"Goal": g["goal_type"], "Target Year": g["target_year"],
         "Current Cost (₹)": g["today_cost"], "Inflation": g["inflation_rate"]}
        for g in flow4["goals"]
    ]
    goal_results, goals_total = compute_all_goals(goal_input, mly)
    _, ins_total = build_insurance_rows(
        expected_client["years_to_retirement"],
        expected_spouse["years_to_retirement"],
        30000, 1500000, 1000000,
        goal_results, rr, rates["roi_post"],
    )

    def check(label, api_val, expected, tol=1.0):
        ok = abs(api_val - expected) <= tol
        mark = "OK" if ok else "MISMATCH"
        print(f"   [{mark}] {label}: api={api_val:.2f} expected={expected:.2f}")
        return ok

    checks = [
        check("client corpus", client["corpus"]["raw"], expected_client["corpus"]),
        check("client pf_corpus", client["pf_corpus"]["raw"], expected_client["pf_fv"]),
        check("client net_corpus", client["net_corpus"]["raw"], expected_client["net_corpus"]),
        check("client monthly_sip", client["monthly_sip"]["raw"], expected_client["monthly_investment"]),
        check("client lump_sum", client["lump_sum"]["raw"], expected_client["lump_sum"]),
        check("spouse corpus", data["spouse"]["corpus"]["raw"], expected_spouse["corpus"]),
        check("goals total", data["goals"]["total_monthly_sip"]["raw"], goals_total),
        check("insurance total", data["insurance"]["total_required"]["raw"], ins_total),
    ]

    print("7. GET /assessment")
    status, res = api("GET", f"/assessment/{assessment_id}")
    print(f"   status={status}")
    assert status == 200, res
    d = res["data"]
    assert d["flow1"] is not None
    assert d["flow2"] is not None
    assert d["flow3"] is not None
    assert d["flow4"] is not None
    print(f"   all 4 flows present: flow1={bool(d['flow1'])}, flow2={bool(d['flow2'])}, "
          f"flow3={bool(d['flow3'])}, flow4={bool(d['flow4'])}")

    print()
    if all(checks):
        print("ALL CHECKS PASSED")
    else:
        print("SOME CHECKS FAILED — review output above")


if __name__ == "__main__":
    main()
