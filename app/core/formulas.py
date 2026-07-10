"""
formulas.py — Exact Python replicas of starter_product_template.xlsx formulas.

Excel RATE / FV / PV / PMT → numpy_financial (Newton-Raphson matches Excel).
Cell references noted in docstrings where applicable.
"""

from __future__ import annotations

import math
from datetime import date

import numpy_financial as npf
import pandas as pd

# Excel type: 0 = end of period, 1 = beginning (annuity-due)
END = 0
BEGIN = 1


def current_year() -> int:
    return date.today().year


def age_from_dob_year(dob_year: int) -> int:
    """Data Sheet B4 / B8: =YEAR(TODAY()) - birth year."""
    return current_year() - dob_year


# ── Excel wrappers ───────────────────────────────────────────────────────────


def excel_RATE(nper, pmt, pv, fv, when: int = END, guess: float = 0.1) -> float:
    """Excel RATE(nper, pmt, pv, [fv], [type]). Yogesh H7 / Data F6,F9,F10."""
    return float(npf.rate(nper, pmt, pv, fv, when))


def excel_FV(rate, nper, pmt, pv: float = 0, when: int = END) -> float:
    """Excel FV(rate, nper, pmt, [pv], [type]). Retirement B8; PF K10."""
    return float(npf.fv(rate, nper, pmt, pv, when))


def excel_PV(rate, nper, pmt, fv: float = 0, when: int = END) -> float:
    """Excel PV(rate, nper, pmt, [fv], [type]). Retirement B9; Insurance E."""
    return float(npf.pv(rate, nper, pmt, fv, when))


def excel_PMT(rate, nper, pv, fv: float = 0, when: int = END) -> float:
    """Excel PMT(rate, nper, pv, [fv], [type]). Retirement B10; Need H."""
    return float(npf.pmt(rate, nper, pv, fv, when))


# ── Data Sheet derived rates (F3–F10) ────────────────────────────────────────

# PF table & corpus utilization M7: =RATE(12,0,100,-108)
PF_MONTHLY_RATE = excel_RATE(12, 0, 100, -108)


def real_rate(roi_post: float, inflation_post: float) -> float:
    """Data Sheet F5: =(1+F4)/(1+F3)-1."""
    return (1 + roi_post) / (1 + inflation_post) - 1


def real_rate_monthly(rr: float) -> float:
    """Data Sheet F6: =RATE(12,0,-100,100*(1+F5))."""
    return excel_RATE(12, 0, -100, 100 * (1 + rr))


def monthly_effective_rate(roi_pre: float) -> float:
    """Data Sheet F9: =RATE(12,0,-100,100*(1+F8)). Need Analysis PMT rate."""
    return excel_RATE(12, 0, -100, 100 * (1 + roi_pre))


def monthly_eff_roi_post(roi_post: float) -> float:
    """Data Sheet F10: =RATE(12,0,-100,100*(1+F4))."""
    return excel_RATE(12, 0, -100, 100 * (1 + roi_post))


def display_amount(value: float) -> float:
    """Excel cash-flow signs → positive ₹ for UI."""
    return abs(value)


def safe_int(val, default: int = 0) -> int:
    """Parse data_editor cells (NaN / empty → default)."""
    if val is None:
        return default
    if isinstance(val, float) and math.isnan(val):
        return default
    if pd.isna(val):
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def safe_float(val, default: float = 0.0) -> float:
    if val is None:
        return default
    if isinstance(val, float) and math.isnan(val):
        return default
    if pd.isna(val):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    if pd.isna(val):
        return ""
    return str(val).strip()


def normalize_goals_df(df: pd.DataFrame) -> pd.DataFrame:
    """Clean goals table after data_editor — safe dtypes, no NaN."""
    if df is None or df.empty:
        return pd.DataFrame(
            columns=["Goal", "Target Year", "Current Cost (₹)", "Inflation"]
        )
    out = df.copy()
    for col in ("Goal", "Target Year", "Current Cost (₹)", "Inflation"):
        if col not in out.columns:
            out[col] = "" if col == "Goal" else 0
    out["Goal"] = out["Goal"].apply(safe_str)
    out["Target Year"] = out["Target Year"].apply(lambda x: safe_int(x, 0))
    out["Current Cost (₹)"] = out["Current Cost (₹)"].apply(lambda x: safe_float(x, 0))
    def _infl(x):
        if x is None or (isinstance(x, float) and math.isnan(x)) or pd.isna(x):
            return 0.06
        v = safe_float(x, 0.06)
        return v

    out["Inflation"] = out["Inflation"].apply(_infl)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# RETIREMENT SHEET (B4–B11, F4–F11)
# ══════════════════════════════════════════════════════════════════════════════


def retirement_sheet(
    client_annual_ret_reqd: float,
    client_dob_year: int,
    client_ret_age: int,
    spouse_annual_ret_reqd: float,
    spouse_dob_year: int,
    spouse_ret_age: int,
    inflation_post: float = 0.06,
    roi_post: float = 0.08,
    inflation_pre: float = 0.06,
    roi_pre: float = 0.12,
) -> dict:
    """
    Retirement sheet — client column B, spouse column F.
    B8/F8: FV(F7 inflation_pre, yrs, 0, exp_today_pm)
    B9/F9: PV(F6 real_rate_monthly, 12*ret_period, exp_at_ret_pm, 0, 1)
    B10/F10: PMT(F9 monthly_eff_pre, yrs*12, 0, -corpus)
    B11/F11: PV(F8 roi_pre annual, yrs, 0, -corpus)
    """
    client_age = age_from_dob_year(client_dob_year)
    spouse_age = age_from_dob_year(spouse_dob_year)

    rr = real_rate(roi_post, inflation_post)
    rr_mly = real_rate_monthly(rr)
    mly_eff_pre = monthly_effective_rate(roi_pre)
    mly_eff_post = monthly_eff_roi_post(roi_post)

    def calc_person(annual_reqd: float, age: int, ret_age: int) -> dict:
        ret_period = 80 - ret_age
        exp_today_pm = annual_reqd / 12
        yrs_to_ret = ret_age - age
        ret_year = current_year() + yrs_to_ret

        exp_at_ret_pm = excel_FV(inflation_pre, yrs_to_ret, 0, exp_today_pm)
        corpus = excel_PV(rr_mly, 12 * ret_period, exp_at_ret_pm, 0, BEGIN)
        monthly_inv = excel_PMT(mly_eff_pre, yrs_to_ret * 12, 0, -corpus, END)
        lump_sum = excel_PV(roi_pre, yrs_to_ret, 0, -corpus, END)

        return {
            "age": age,
            "retirement_year": ret_year,
            "retirement_period": ret_period,
            "expenses_today_pm": exp_today_pm,
            "years_to_retirement": yrs_to_ret,
            "expenses_at_retirement_pm": exp_at_ret_pm,
            "corpus": corpus,
            "monthly_investment": monthly_inv,
            "lump_sum": lump_sum,
        }

    return {
        "client": calc_person(client_annual_ret_reqd, client_age, client_ret_age),
        "spouse": calc_person(spouse_annual_ret_reqd, spouse_age, spouse_ret_age),
        "rates": {
            "real_rate": rr,
            "real_rate_monthly": rr_mly,
            "monthly_eff_pre": mly_eff_pre,
            "monthly_eff_post": mly_eff_post,
            "pf_monthly_rate": PF_MONTHLY_RATE,
            "inflation_pre": inflation_pre,
            "inflation_post": inflation_post,
            "roi_pre": roi_pre,
            "roi_post": roi_post,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# PF TABLE (Yogesh H–K): annual contribution, FV 12 periods
# ══════════════════════════════════════════════════════════════════════════════


def pf_table(
    current_epf_accum: float,
    epf_annual_total: float,
    years_to_retirement: int,
    pf_growth: float = 0.05,
) -> tuple[list[dict], float]:
    """
    K10 = FV(H7, 12, -J10, -I10); J11 = J10*1.05; I11 = K10.
    J = annual EPF contribution (Data / Yogesh B6).
    """
    if years_to_retirement <= 0:
        return [], current_epf_accum

    rows: list[dict] = []
    opening = current_epf_accum
    contribution = epf_annual_total
    yr = current_year()

    for _ in range(int(years_to_retirement)):
        closing = excel_FV(PF_MONTHLY_RATE, 12, -contribution, -opening, END)
        rows.append(
            {
                "Year": yr,
                "Opening (₹)": opening,
                "Contribution (₹)": contribution,
                "Closing (₹)": closing,
            }
        )
        yr += 1
        opening = closing
        contribution = contribution * (1 + pf_growth)

    return rows, rows[-1]["Closing (₹)"] if rows else current_epf_accum


def nps_table(
    current_nps_accum: float,
    employer_nps_pm: float,
    self_nps_pm: float,
    years_to_retirement: int,
    pf_growth: float = 0.05,
) -> tuple[list[dict], float]:
    """
    NPS accumulation table — mirrors pf_table() logic exactly.
    - nps_annual_total = (employer_nps_pm + self_nps_pm) * 12
    - Same PF_MONTHLY_RATE, same FV formula, same 5% annual contribution growth.
    - Returns (rows, final_corpus).
    """
    if years_to_retirement <= 0:
        return [], current_nps_accum

    nps_annual_total = (employer_nps_pm + self_nps_pm) * 12

    if nps_annual_total <= 0 and current_nps_accum <= 0:
        return [], 0.0

    rows: list[dict] = []
    opening = current_nps_accum
    contribution = nps_annual_total
    yr = current_year()

    for _ in range(int(years_to_retirement)):
        closing = excel_FV(PF_MONTHLY_RATE, 12, -contribution, -opening, END)
        rows.append(
            {
                "Year": yr,
                "Opening (₹)": opening,
                "Contribution (₹)": contribution,
                "Closing (₹)": closing,
            }
        )
        yr += 1
        opening = closing
        contribution = contribution * (1 + pf_growth)

    return rows, rows[-1]["Closing (₹)"] if rows else current_nps_accum


def sa_table(
    current_sa_accum: float,
    sa_pm: float,
    years_to_retirement: int,
    pf_growth: float = 0.05,
) -> tuple[list[dict], float]:
    """
    Superannuation accumulation table — mirrors pf_table() logic exactly.
    - sa_annual_total = sa_pm * 12
    - Same PF_MONTHLY_RATE, same FV formula, same 5% annual contribution growth.
    - Returns (rows, final_corpus).
    """
    if years_to_retirement <= 0:
        return [], current_sa_accum

    sa_annual_total = sa_pm * 12

    if sa_annual_total <= 0 and current_sa_accum <= 0:
        return [], 0.0

    rows: list[dict] = []
    opening = current_sa_accum
    contribution = sa_annual_total
    yr = current_year()

    for _ in range(int(years_to_retirement)):
        closing = excel_FV(PF_MONTHLY_RATE, 12, -contribution, -opening, END)
        rows.append(
            {
                "Year": yr,
                "Opening (₹)": opening,
                "Contribution (₹)": contribution,
                "Closing (₹)": closing,
            }
        )
        yr += 1
        opening = closing
        contribution = contribution * (1 + pf_growth)

    return rows, rows[-1]["Closing (₹)"] if rows else current_sa_accum


# ══════════════════════════════════════════════════════════════════════════════
# YOGESH / NIKHIL E13–E26
# ══════════════════════════════════════════════════════════════════════════════


def full_corpus_calc(
    annual_ret_reqd: float,
    current_age: int,
    retirement_age: int,
    epf_annual_total: float,
    current_epf_accum: float,
    inflation_post: float = 0.06,
    roi_post: float = 0.08,
    inflation_pre: float = 0.06,
    roi_pre: float = 0.12,
    pmt_when: int = END,
    employer_nps_pm: float = 0.0,
    self_nps_pm: float = 0.0,
    current_nps_accum: float = 0.0,
    sa_pm: float = 0.0,
    current_sa_accum: float = 0.0,
    pf_growth: float = 0.05,
) -> dict:
    """
    E18 = FV(E20, E17, 0, E16); E19 = PV(E14, E15*12, E18, 0, 1)
    E21 = F29; E22 = E19-E21
    E25 = PMT(E24, E17*12, 0, E22) — Yogesh type=0; Nikhil may use type=1
    E26 = PV(E23, E17, 0, E22)
    """
    rr = real_rate(roi_post, inflation_post)
    rr_mly = real_rate_monthly(rr)
    ret_period = 80 - retirement_age
    exp_today_pm = annual_ret_reqd / 12
    yrs_to_ret = retirement_age - current_age

    exp_at_ret_pm = excel_FV(inflation_pre, yrs_to_ret, 0, exp_today_pm)
    corpus = excel_PV(rr_mly, ret_period * 12, exp_at_ret_pm, 0, BEGIN)

    pf_rows, pf_fv = pf_table(
        current_epf_accum, epf_annual_total, yrs_to_ret, pf_growth=pf_growth
    )
    nps_rows, nps_fv = nps_table(
        current_nps_accum, employer_nps_pm, self_nps_pm, yrs_to_ret, pf_growth=pf_growth
    )
    sa_rows, sa_fv = sa_table(
        current_sa_accum, sa_pm, yrs_to_ret, pf_growth=pf_growth
    )
    total_existing_provision = pf_fv + nps_fv + sa_fv
    net_corpus = corpus - total_existing_provision

    mly_eff_pre = monthly_effective_rate(roi_pre)
    monthly_inv = excel_PMT(mly_eff_pre, yrs_to_ret * 12, 0, net_corpus, pmt_when)
    lump_sum = excel_PV(roi_pre, yrs_to_ret, 0, net_corpus, END)

    return {
        "real_rate": rr,
        "real_rate_monthly": rr_mly,
        "retirement_period": ret_period,
        "expenses_today_pm": exp_today_pm,
        "years_to_retirement": yrs_to_ret,
        "expenses_at_retirement_pm": exp_at_ret_pm,
        "corpus": corpus,
        "pf_fv": pf_fv,
        "nps_fv": nps_fv,
        "sa_fv": sa_fv,
        "total_existing_provision": total_existing_provision,
        "net_corpus": net_corpus,
        "monthly_investment": monthly_inv,
        "lump_sum": lump_sum,
        "pf_table": pf_rows,
        "nps_table": nps_rows,
        "sa_table": sa_rows,
    }


# ══════════════════════════════════════════════════════════════════════════════
# CORPUS UTILIZATION (M–Q): rate = PF_MONTHLY_RATE, withdrawal × 1.06
# ══════════════════════════════════════════════════════════════════════════════


def corpus_utilization_table(
    corpus: float,
    exp_at_ret_pm: float,
    retirement_age: int,
    retirement_year: int,
    inflation_post: float = 0.06,
) -> list[dict]:
    """
    P10 = 12 * -E18 → annual withdrawal magnitude; Q10 = FV(M7, 12, 0, -(O-P), 1).
    Last row (age 80): P = O (full withdrawal).
    """
    rows: list[dict] = []
    balance = corpus
    annual_withdrawal = 12 * abs(exp_at_ret_pm)
    age = retirement_age + 1
    year = retirement_year + 1

    while age <= 80:
        is_last = age == 80
        if is_last:
            annual_withdrawal = balance

        closing = excel_FV(
            PF_MONTHLY_RATE, 12, 0, -(balance - annual_withdrawal), BEGIN
        )
        rows.append(
            {
                "Age": age,
                "Year": year,
                "Opening (₹)": balance,
                "Withdrawal (₹)": annual_withdrawal,
                "Closing (₹)": max(closing, 0),
            }
        )

        if is_last:
            break

        balance = max(closing, 0)
        annual_withdrawal = annual_withdrawal * (1 + inflation_post)
        age += 1
        year += 1

    return rows


# ══════════════════════════════════════════════════════════════════════════════
# NEED ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_GOALS = [
    ("Child 1 Graduation", 2040, 2_500_000, 0.08),
    ("Child 1 PG", 2044, 3_500_000, 0.08),
    ("Child 1 Marriage", 2042, 2_000_000, 0.06),
    ("Child 2 Graduation", 2043, 2_500_000, 0.08),
    ("Child 2 PG", 2047, 3_500_000, 0.08),
    ("Child 2 Marriage", 2045, 2_000_000, 0.06),
    ("House Purchase", 2035, 5_000_000, 0.06),
    ("Car Purchase", 2030, 1_200_000, 0.06),
    ("Home Renovation", 2033, 800_000, 0.06),
    ("Holiday Home", 2038, 3_000_000, 0.06),
    ("Foreign Tour", 2030, 500_000, 0.06),
    ("Family Gifting", 2032, 200_000, 0.06),
    ("Charity", 2035, 100_000, 0.06),
    ("Child Birth Expenses", 2028, 300_000, 0.06),
    ("Big Purchases", 2034, 400_000, 0.06),
    ("Others", 0, 0, 0.06),
]


def goal_calc(
    target_year: int,
    current_cost: float,
    inflation_rate: float,
    monthly_eff_pre_rate: float,
) -> dict:
    """D = C - YEAR(TODAY()); G = FV(F,D,0,-E); H = PMT(F9, D*12, 0, -G, 1)."""
    years_from_now = target_year - current_year()
    if years_from_now <= 0 or current_cost <= 0:
        return {"years_from_now": years_from_now, "future_cost": 0.0, "monthly_inv": 0.0}

    future_cost = excel_FV(inflation_rate, years_from_now, 0, -current_cost, END)
    monthly_inv = excel_PMT(
        monthly_eff_pre_rate, years_from_now * 12, 0, -future_cost, BEGIN
    )
    return {
        "years_from_now": years_from_now,
        "future_cost": future_cost,
        "monthly_inv": monthly_inv,
    }


def compute_all_goals(
    goals: list[dict], monthly_eff_pre_rate: float
) -> tuple[list[dict], float]:
    """Returns enriched rows + SUM(H7:H12,H14:H23)."""
    results = []
    total = 0.0
    for g in goals:
        name = safe_str(g.get("Goal", ""))
        ty = safe_int(g.get("Target Year", 0), 0)
        cost = safe_float(g.get("Current Cost (₹)", 0), 0)
        infl = safe_float(g.get("Inflation", 0), 0.06)
        if not name or cost <= 0 or ty <= 0:
            continue
        calc = goal_calc(ty, cost, infl, monthly_eff_pre_rate)
        row = {
            "Goal": name,
            "Target Year": ty,
            "Current Cost (₹)": cost,
            "Inflation": infl,
            "current_cost": cost,
            **calc,
        }
        results.append(row)
        total += display_amount(calc["monthly_inv"])
    return results, total


# ══════════════════════════════════════════════════════════════════════════════
# INSURANCE (E4–E11)
# ══════════════════════════════════════════════════════════════════════════════


def insurance_pv(
    years: int,
    amount: float,
    cost_type_str: str,
    real_rate_annual: float,
    roi_post: float,
) -> float:
    """
    Insurance: future → rate F4 (roi_post annual), fv=-C, pmt=0.
    today → rate F5 (real_rate annual), pmt=-C, fv=0.
    """
    if years <= 0 or amount <= 0:
        return 0.0

    is_future = "future" in cost_type_str.lower()
    if is_future:
        return excel_PV(roi_post, years, 0, -amount, END)
    return excel_PV(real_rate_annual, years, -amount, 0, END)


def build_insurance_rows(
    client_years_to_ret: int,
    spouse_years_to_ret: int,
    household_monthly: float,
    client_annual: float,
    spouse_annual: float,
    goal_results: list[dict],
    real_rate_annual: float,
    roi_post: float,
) -> tuple[list[dict], float]:
    """Insurance sheet rows 4–11 linked to Retirement & Need Analysis."""
    rows: list[dict] = []

    # Row 4: Household — today's value; years = client retirement year offset
    hh_years = client_years_to_ret
    hh_amount = household_monthly * 12
    rows.append(
        {
            "Need": "Household Expenses",
            "Years": hh_years,
            "Amount (₹)": hh_amount,
            "Type": "Today's Value",
            "PV (₹)": insurance_pv(
                hh_years, hh_amount, "today", real_rate_annual, roi_post
            ),
        }
    )

    goal_map = [
        ("Child 1 Graduation", "Child 1 Graduation"),
        ("Child 1 PG", "Child 1 PG"),
        ("Child 1 Marriage", "Child 1 Marriage"),
        ("Child 2 Graduation", "Child 2 Graduation"),
        ("Child 2 PG", "Child 2 PG"),
        ("Child 2 Marriage", "Child 2 Marriage"),
    ]
    for label, key in goal_map:
        match = next((g for g in goal_results if g.get("Goal") == key), None)
        if match:
            rows.append(
                {
                    "Need": label,
                    "Years": int(match["years_from_now"]),
                    "Amount (₹)": display_amount(match["future_cost"]),
                    "Type": "Future value",
                    "PV (₹)": insurance_pv(
                        int(match["years_from_now"]),
                        display_amount(match["future_cost"]),
                        "future",
                        real_rate_annual,
                        roi_post,
                    ),
                }
            )

    # Row 11: Retirement Income 50%
    ret_income_years = client_years_to_ret
    ret_income_amount = (client_annual + spouse_annual) / 2
    rows.append(
        {
            "Need": "Retirement Income (50%)",
            "Years": ret_income_years,
            "Amount (₹)": ret_income_amount,
            "Type": "Today's Value",
            "PV (₹)": insurance_pv(
                ret_income_years,
                ret_income_amount,
                "today",
                real_rate_annual,
                roi_post,
            ),
        }
    )

    total = sum(r["PV (₹)"] for r in rows)
    return rows, total
