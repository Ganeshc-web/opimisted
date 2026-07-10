from app.core.formulas import full_corpus_calc, nps_table, sa_table


def test_nps_zero_contribution():
    rows, corpus = nps_table(0, 0, 0, 10)
    assert corpus == 0.0
    assert rows == []


def test_nps_with_accumulation():
    rows, corpus = nps_table(0, 5000, 2000, 25)
    assert len(rows) == 25
    assert corpus > 0
    assert rows[0]["Contribution (₹)"] == 84000.0


def test_nps_contribution_grows_5pct():
    rows, _ = nps_table(0, 5000, 2000, 3)
    assert abs(rows[1]["Contribution (₹)"] - rows[0]["Contribution (₹)"] * 1.05) < 0.01


def test_sa_with_accumulation():
    rows, corpus = sa_table(700000, 6000, 14)
    assert len(rows) == 14
    assert corpus > 700000


def test_sa_contribution_grows_5pct():
    rows, _ = sa_table(0, 6000, 3)
    assert abs(rows[1]["Contribution (₹)"] - rows[0]["Contribution (₹)"] * 1.05) < 0.01


def test_full_corpus_includes_nps_and_sa():
    calc = full_corpus_calc(
        annual_ret_reqd=600000,
        current_age=44,
        retirement_age=58,
        epf_annual_total=13980 * 12,
        current_epf_accum=1560000,
        employer_nps_pm=0,
        self_nps_pm=0,
        current_nps_accum=0,
        sa_pm=6000,
        current_sa_accum=700000,
    )
    assert calc["sa_fv"] > 0
    assert calc["total_existing_provision"] == (
        calc["pf_fv"] + calc["nps_fv"] + calc["sa_fv"]
    )
    assert calc["net_corpus"] == calc["corpus"] - calc["total_existing_provision"]
