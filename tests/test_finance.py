import io

import pandas as pd
import pytest

from finance import analysis as A
from finance import loader as L
from finance import recommendations as R
from finance import schema as S


def _tx(rows):
    return pd.DataFrame(rows, columns=["date", "description", "amount", "account", "category"])


def test_bank_file_with_title_rows_and_debit_credit():
    csv = (
        "דוח תנועות בחשבון,,,,\n"
        "חשבון 12345,,,,\n"
        "תאריך,תיאור התנועה,חובה,זכות,יתרה\n"
        "01/10/2026,משכורת,,18500,20000\n"
        "02/10/2026,ישראכרט,\"4,120.50\",,15879.5\n"
    ).encode("utf-8-sig")
    df = L.read_transactions(io.BytesIO(csv), "bank.csv", S.ACCOUNT_BANK)
    assert df["amount"].tolist() == [18500, -4120.5]
    assert df["date"].tolist() == [pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-02")]
    assert (df["account"] == S.ACCOUNT_BANK).all()


def test_credit_file_positive_charges_become_expenses():
    csv = "תאריך עסקה,שם בית העסק,סכום חיוב\n05/10/2026,שופרסל,350\n06/10/2026,זיכוי זארה,-100\n"
    df = L.read_transactions(io.BytesIO(csv.encode()), "card.csv", S.ACCOUNT_CREDIT)
    assert df["amount"].tolist() == [-350, 100]


def test_cp1255_encoding():
    csv = "תאריך,תיאור,סכום\n01/10/2026,משכורת,100\n".encode("cp1255")
    df = L.read_transactions(io.BytesIO(csv), "x.csv", S.ACCOUNT_BANK)
    assert df["description"].iloc[0] == "משכורת"


def test_missing_columns_raises():
    with pytest.raises(ValueError):
        L.read_transactions(io.BytesIO(b"a,b\n1,2\n"), "x.csv", S.ACCOUNT_BANK)


def test_card_bill_not_double_counted_when_card_detail_present():
    df = A.prepare_transactions(_tx([
        ["2026-10-01", "משכורת", 10000, S.ACCOUNT_BANK, None],
        ["2026-10-02", "ישראכרט", -500, S.ACCOUNT_BANK, None],
        ["2026-10-05", "שופרסל", -500, S.ACCOUNT_CREDIT, None],
    ]))
    m = A.monthly_summary(df)
    assert m["expenses"].iloc[0] == 500


def test_card_bill_counted_without_card_detail():
    df = A.prepare_transactions(_tx([
        ["2026-10-01", "משכורת", 10000, S.ACCOUNT_BANK, None],
        ["2026-10-02", "ישראכרט", -500, S.ACCOUNT_BANK, None],
    ]))
    assert A.monthly_summary(df)["expenses"].iloc[0] == 500


def test_refund_reduces_expenses_and_savings_are_separate():
    df = A.prepare_transactions(_tx([
        ["2026-10-01", "משכורת", 10000, S.ACCOUNT_BANK, None],
        ["2026-10-03", "שופרסל", -600, S.ACCOUNT_CREDIT, None],
        ["2026-10-04", "שופרסל", 100, S.ACCOUNT_CREDIT, None],
        ["2026-10-05", "העברה להשקעות", -2000, S.ACCOUNT_BANK, None],
    ]))
    m = A.monthly_summary(df).iloc[0]
    assert m["income"] == 10000
    assert m["expenses"] == 500
    assert m["savings"] == 2000
    assert m["net"] == 7500
    assert m["savings_rate"] == pytest.approx(0.95)


def test_keyword_categories():
    assert A.guess_category("רמי לוי שיווק", -100) == "מזון וסופר"
    assert A.guess_category("ביטוח לאומי", 500) == S.CAT_OTHER_INCOME
    assert A.guess_category("ביט - העברה", 50) == S.CAT_OTHER_INCOME
    assert A.guess_category("משהו לא מוכר", -10) == S.CAT_OTHER


def test_iso_and_day_first_dates():
    out = L.to_date(pd.Series(["2027-03-01", "01/03/2027"]))
    assert (out == pd.Timestamp("2027-03-01")).all()


def test_net_worth_and_liquidity():
    assets = L.normalize_assets(pd.DataFrame([
        ["עו\"ש", S.ASSET_CHECKING, "", 10000, 0, 0, 0, 0, ""],
        ["השתלמות ישנה", S.ASSET_HISHTALMUT, "", 50000, 0, 0.5, 0, 5, "2020-01-01"],
        ["השתלמות חדשה", S.ASSET_HISHTALMUT, "", 20000, 0, 0.5, 0, 5, "2030-01-01"],
        ["פנסיה", S.ASSET_PENSION, "", 100000, 0, 0.2, 1, 5, ""],
        ["משכנתא", S.ASSET_LOAN, "", 30000, 0, 0, 0, 4, ""],
    ], columns=S.ASSET_COLUMNS))
    nw = A.net_worth(assets, pd.Timestamp("2026-10-27"))
    assert nw.assets == 180000
    assert nw.liabilities == 30000
    assert nw.net == 150000
    assert nw.liquid == 60000
    assert nw.cash == 10000


def test_projection_without_fees_matches_compound_growth():
    p = A.project_balance(1000, 0, 12, 0, 0, 2)
    assert p["balance"].iloc[-1] == pytest.approx(1000 * 1.12 ** 2)


def test_higher_fees_cost_money():
    row = pd.Series({"balance": 100000, "monthly_deposit": 2000, "annual_return_pct": 5,
                     "fee_balance_pct": 0.5, "fee_deposit_pct": 3})
    assert A.fee_impact(row, 20, 0.2, 1.0) > 0


def test_recommendations_on_sample_data_run():
    tx, assets = L.load_sample()
    df = A.prepare_transactions(tx)
    recs = R.build(df, assets, R.Settings(), pd.Timestamp("2026-10-27"))
    titles = [r.title for r in recs]
    assert "דמי ניהול מעל הסף שהגדרת" in titles
    assert [R.SEVERITY_ORDER[r.severity] for r in recs] == sorted(R.SEVERITY_ORDER[r.severity] for r in recs)


def test_overspending_is_critical():
    df = A.prepare_transactions(_tx([
        ["2026-09-01", "משכורת", 5000, S.ACCOUNT_BANK, None],
        ["2026-09-02", "שכר דירה", -6000, S.ACCOUNT_BANK, None],
    ]))
    recs = R.build(df, pd.DataFrame(columns=S.ASSET_COLUMNS), R.Settings(), pd.Timestamp("2026-10-27"))
    assert recs[0].severity == R.CRITICAL
