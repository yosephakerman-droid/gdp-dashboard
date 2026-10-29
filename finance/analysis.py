"""Categorization and the numbers behind every view in the app."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import schema as S

INCOME_CATEGORIES = {S.CAT_SALARY, S.CAT_OTHER_INCOME}
LIQUID_NOW_TYPES = [S.ASSET_CHECKING, S.ASSET_DEPOSIT, S.ASSET_INVESTMENTS]


# --- Categorization ----------------------------------------------------------

def guess_category(description: str, amount: float) -> str:
    text = f" {str(description).lower()} "
    for category, keywords in S.CATEGORY_KEYWORDS:
        if any(k.lower() in text for k in keywords):
            # An incoming transfer (bit, bank transfer) is income, not spend.
            # Other positive amounts in spend categories are refunds.
            if amount > 0 and category == "העברות":
                return S.CAT_OTHER_INCOME
            return category
    return S.CAT_OTHER_INCOME if amount > 0 else S.CAT_OTHER


def prepare_transactions(tx: pd.DataFrame) -> pd.DataFrame:
    """Fill missing categories, assign a kind, add a month column."""
    df = tx.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["amount"] = df["amount"].astype(float)
    df["category"] = df["category"].astype(object)
    missing = df["category"].isna() | (df["category"].astype(str).str.strip().isin(["", "nan", "None"]))
    df.loc[missing, "category"] = [
        guess_category(d, a) for d, a in zip(df.loc[missing, "description"], df.loc[missing, "amount"])
    ]
    df["month"] = df["date"].dt.to_period("M").dt.to_timestamp()
    return assign_kinds(df.sort_values("date", kind="stable").reset_index(drop=True))


def assign_kinds(df: pd.DataFrame) -> pd.DataFrame:
    """Set the kind column from category/account. Re-run after edits."""
    df = df.copy()
    month = df["date"].dt.to_period("M")
    card_months = set(month[df["account"] == S.ACCOUNT_CREDIT])

    def kind(row) -> str:
        if row["category"] == S.CAT_CARD_BILL and row["account"] != S.ACCOUNT_CREDIT:
            # A card bill in the bank duplicates the card's own line items, but
            # only in months whose card detail was uploaded.
            return S.KIND_INTERNAL if row["date"].to_period("M") in card_months else S.KIND_EXPENSE
        if row["category"] == S.CAT_SAVINGS:
            return S.KIND_SAVING
        if row["category"] in INCOME_CATEGORIES:
            return S.KIND_INCOME
        # Positive amounts in spend categories are refunds: they reduce expenses.
        return S.KIND_EXPENSE

    df["kind"] = df.apply(kind, axis=1) if len(df) else pd.Series(dtype=object)
    return df


# --- Cash flow ---------------------------------------------------------------

def monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    """One row per month: income, expenses, savings transfers, net."""
    if df.empty:
        return pd.DataFrame(columns=["month", "income", "expenses", "savings", "net", "savings_rate"])
    g = df.groupby(["month", "kind"])["amount"].sum().unstack(fill_value=0.0)
    for k in (S.KIND_INCOME, S.KIND_EXPENSE, S.KIND_SAVING):
        if k not in g.columns:
            g[k] = 0.0
    out = pd.DataFrame(
        {
            "income": g[S.KIND_INCOME],
            # Refunds are positive amounts inside expense kinds, so they
            # reduce this number.
            "expenses": -g[S.KIND_EXPENSE],
            "savings": -g[S.KIND_SAVING],
        }
    )
    out["net"] = out["income"] - out["expenses"] - out["savings"]
    out["savings_rate"] = np.where(
        out["income"] > 0, (out["income"] - out["expenses"]) / out["income"], np.nan
    )
    return out.reset_index()


def complete_months(df: pd.DataFrame) -> pd.DataFrame:
    """Drop a trailing partial month (data ends before day 20)."""
    if df.empty:
        return df
    last = df["date"].max()
    if last.day < 20:
        return df[df["month"] < last.to_period("M").to_timestamp()]
    return df


@dataclass
class Averages:
    months: int
    income: float
    expenses: float
    savings: float
    net: float
    savings_rate: float


def averages(df: pd.DataFrame) -> Averages:
    m = monthly_summary(complete_months(df))
    if m.empty:
        m = monthly_summary(df)
    if m.empty:
        return Averages(0, 0, 0, 0, 0, float("nan"))
    inc, exp = m["income"].mean(), m["expenses"].mean()
    return Averages(
        months=len(m),
        income=inc,
        expenses=exp,
        savings=m["savings"].mean(),
        net=m["net"].mean(),
        savings_rate=(inc - exp) / inc if inc > 0 else float("nan"),
    )


def expenses_only(df: pd.DataFrame) -> pd.DataFrame:
    e = df[(df["kind"] == S.KIND_EXPENSE)].copy()
    e["spend"] = -e["amount"]
    return e


def category_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    e = expenses_only(df)
    if e.empty:
        return pd.DataFrame(columns=["category", "spend", "share", "monthly_avg"])
    months = max(df["month"].nunique(), 1)
    out = e.groupby("category", as_index=False)["spend"].sum().sort_values("spend", ascending=False)
    out["share"] = out["spend"] / out["spend"].sum()
    out["monthly_avg"] = out["spend"] / months
    return out.reset_index(drop=True)


def category_by_month(df: pd.DataFrame) -> pd.DataFrame:
    e = expenses_only(df)
    return e.groupby(["month", "category"], as_index=False)["spend"].sum()


def top_merchants(df: pd.DataFrame, n: int = 15) -> pd.DataFrame:
    e = expenses_only(df)
    if e.empty:
        return pd.DataFrame(columns=["description", "category", "spend", "count"])
    return (
        e.groupby("description")
        .agg(category=("category", "first"), spend=("spend", "sum"), count=("spend", "size"))
        .sort_values("spend", ascending=False)
        .head(n)
        .reset_index()
    )


def recurring_expenses(df: pd.DataFrame, min_months: int = 3, max_cv: float = 0.2) -> pd.DataFrame:
    """Charges that repeat in >= min_months months with a stable amount."""
    e = expenses_only(df)
    if e.empty:
        return pd.DataFrame(columns=["description", "category", "months", "avg_amount", "yearly"])
    per_month = e.groupby(["description", "month"], as_index=False).agg(
        spend=("spend", "sum"), category=("category", "first")
    )
    g = per_month.groupby("description").agg(
        category=("category", "first"),
        months=("month", "nunique"),
        avg_amount=("spend", "mean"),
        std=("spend", "std"),
    )
    g["cv"] = (g["std"].fillna(0) / g["avg_amount"]).fillna(0)
    g = g[(g["months"] >= min_months) & (g["cv"] <= max_cv)]
    g["yearly"] = g["avg_amount"] * 12
    return g.drop(columns=["std", "cv"]).sort_values("yearly", ascending=False).reset_index()


def fixed_vs_variable(df: pd.DataFrame) -> tuple[float, float]:
    """Monthly average of recurring vs. all other expenses."""
    e = expenses_only(df)
    months = max(df["month"].nunique(), 1)
    rec = set(recurring_expenses(df)["description"])
    fixed = e[e["description"].isin(rec)]["spend"].sum() / months
    variable = e[~e["description"].isin(rec)]["spend"].sum() / months
    return fixed, variable


def category_spikes(df: pd.DataFrame, min_ratio: float = 1.3, min_diff: float = 200) -> pd.DataFrame:
    """Categories where the last full month is well above the earlier average."""
    d = complete_months(df)
    cbm = category_by_month(d)
    if cbm.empty or cbm["month"].nunique() < 3:
        return pd.DataFrame(columns=["category", "last", "avg", "diff", "ratio"])
    last_m = cbm["month"].max()
    pivot = cbm.pivot_table(index="month", columns="category", values="spend", fill_value=0)
    prev = pivot[pivot.index < last_m].mean()
    last = pivot.loc[last_m]
    out = pd.DataFrame({"last": last, "avg": prev})
    out["diff"] = out["last"] - out["avg"]
    out["ratio"] = out["last"] / out["avg"].replace(0, np.nan)
    out = out[(out["diff"] >= min_diff) & ((out["ratio"] >= min_ratio) | out["ratio"].isna())]
    out.index.name = "category"
    return out.sort_values("diff", ascending=False).reset_index()


# --- Assets ------------------------------------------------------------------

def is_liquid(row, today: pd.Timestamp) -> bool:
    if row["type"] in LIQUID_NOW_TYPES:
        return True
    if row["type"] == S.ASSET_HISHTALMUT:
        return pd.notna(row["liquidity_date"]) and row["liquidity_date"] <= today
    return False


@dataclass
class NetWorth:
    assets: float
    liabilities: float
    net: float
    liquid: float
    locked: float
    cash: float  # checking + deposits


def net_worth(assets: pd.DataFrame, today: pd.Timestamp | None = None) -> NetWorth:
    today = today or pd.Timestamp.today().normalize()
    if assets.empty:
        return NetWorth(0, 0, 0, 0, 0, 0)
    loans = assets[assets["type"] == S.ASSET_LOAN]
    pos = assets[assets["type"] != S.ASSET_LOAN]
    liquid_mask = pos.apply(lambda r: is_liquid(r, today), axis=1) if not pos.empty else []
    total = pos["balance"].sum()
    liab = loans["balance"].abs().sum()
    liquid = pos[liquid_mask]["balance"].sum() if len(pos) else 0.0
    cash = pos[pos["type"].isin([S.ASSET_CHECKING, S.ASSET_DEPOSIT])]["balance"].sum()
    return NetWorth(total, liab, total - liab, liquid, total - liquid, cash)


def annual_fees(assets: pd.DataFrame) -> pd.DataFrame:
    """Estimated yearly fee cost per product (balance fee + deposit fee)."""
    a = assets[assets["type"] != S.ASSET_LOAN].copy()
    a["fee_from_balance"] = a["balance"] * a["fee_balance_pct"] / 100
    a["fee_from_deposits"] = a["monthly_deposit"] * 12 * a["fee_deposit_pct"] / 100
    a["fee_total"] = a["fee_from_balance"] + a["fee_from_deposits"]
    return a[a["fee_total"] > 0].sort_values("fee_total", ascending=False).reset_index(drop=True)


def project_balance(
    balance: float,
    monthly_deposit: float,
    annual_return_pct: float,
    fee_balance_pct: float,
    fee_deposit_pct: float,
    years: int,
) -> pd.DataFrame:
    """Year-by-year balance with a constant return, net of both fees.

    This is a simplified model: constant return, constant deposits, no
    inflation, no tax. It is an estimate, not a forecast.
    """
    r_month = (1 + (annual_return_pct - fee_balance_pct) / 100) ** (1 / 12) - 1
    dep = monthly_deposit * (1 - fee_deposit_pct / 100)
    rows = [(0, balance)]
    b = balance
    for y in range(1, years + 1):
        for _ in range(12):
            b = b * (1 + r_month) + dep
        rows.append((y, b))
    return pd.DataFrame(rows, columns=["year", "balance"])


def fee_impact(row, years: int, bench_balance_pct: float, bench_deposit_pct: float) -> float:
    """Extra balance at the end if fees were at the benchmark instead."""
    if years <= 0:
        return 0.0
    mine = project_balance(row["balance"], row["monthly_deposit"], row["annual_return_pct"],
                           row["fee_balance_pct"], row["fee_deposit_pct"], years)["balance"].iloc[-1]
    bench = project_balance(row["balance"], row["monthly_deposit"], row["annual_return_pct"],
                            min(bench_balance_pct, row["fee_balance_pct"]),
                            min(bench_deposit_pct, row["fee_deposit_pct"]), years)["balance"].iloc[-1]
    return float(bench - mine)
