"""Read and normalize uploaded transaction and asset files."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from . import schema as S

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _read_raw(file, name: str) -> pd.DataFrame:
    """Read CSV/Excel without assuming where the header row is."""
    name = name.lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(file, header=None, dtype=str)
    raw = file.read() if hasattr(file, "read") else Path(file).read_bytes()
    for enc in ("utf-8-sig", "cp1255", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    return pd.read_csv(io.StringIO(text), header=None, dtype=str, sep=None, engine="python")


def _canonical(header: str) -> str | None:
    h = str(header).strip().lower()
    for canon, aliases in S.COLUMN_ALIASES.items():
        if h in aliases:
            return canon
    return None


def _find_header_row(raw: pd.DataFrame, required: set[str], max_scan: int = 20) -> int:
    """Bank exports often start with title rows; find the real header."""
    for i in range(min(max_scan, len(raw))):
        found = {_canonical(v) for v in raw.iloc[i].tolist()}
        if required <= found:
            return i
    raise ValueError(
        "לא נמצאה שורת כותרות. ודא שיש עמודות תאריך, תיאור וסכום "
        "(או חובה/זכות). אפשר להוריד קובץ תבנית מהסרגל הצדדי."
    )


def to_number(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace("₪", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.replace("‏", "", regex=False)
        .str.strip()
        .replace({"": None, "nan": None, "None": None, "-": None})
    )
    # "123-" (trailing minus) appears in some exports.
    cleaned = cleaned.str.replace(r"^(\d+(?:\.\d+)?)-$", r"-\1", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


def to_date(series: pd.Series) -> pd.Series:
    """ISO dates (2026-03-01) as-is; everything else day-first (01/03/2026)."""
    text = series.astype(str).str.strip()
    iso = text.str.match(r"^\d{4}-\d{1,2}-\d{1,2}")
    out = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    out[iso] = pd.to_datetime(text[iso].str[:10], format="%Y-%m-%d", errors="coerce")
    out[~iso] = pd.to_datetime(text[~iso], dayfirst=True, errors="coerce", format="mixed")
    return out


def normalize_transactions(raw: pd.DataFrame, source: str) -> pd.DataFrame:
    """Turn a table with a header row into the canonical transactions frame.

    source: S.ACCOUNT_BANK or S.ACCOUNT_CREDIT. Credit-card exports list charges
    as positive numbers, so for them the sign is flipped (expense = negative).
    """
    df = raw.rename(columns={c: _canonical(c) or c for c in raw.columns})
    df = df.loc[:, ~df.columns.duplicated()]

    if "amount" in df.columns:
        amount = to_number(df["amount"])
        if source == S.ACCOUNT_CREDIT:
            amount = -amount
    elif "debit" in df.columns or "credit" in df.columns:
        debit = to_number(df.get("debit", pd.Series(0, index=df.index))).fillna(0)
        credit = to_number(df.get("credit", pd.Series(0, index=df.index))).fillna(0)
        amount = credit - debit.abs()
    else:
        raise ValueError("לא נמצאה עמודת סכום (או חובה/זכות).")

    out = pd.DataFrame(
        {
            "date": to_date(df["date"]),
            "description": df["description"].astype(str).str.strip(),
            "amount": amount,
            "account": df["account"].astype(str) if "account" in df.columns else source,
            "category": df["category"] if "category" in df.columns else None,
        }
    )
    out = out.dropna(subset=["date", "amount"])
    out = out[out["amount"] != 0]
    out["category"] = out["category"].where(out["category"].notna(), None)
    return out.reset_index(drop=True)


def read_transactions(file, name: str, source: str) -> pd.DataFrame:
    raw = _read_raw(file, name)
    try:
        idx = _find_header_row(raw, {"date", "description", "amount"})
    except ValueError:
        idx = _find_header_row(raw, {"date", "description", "debit"})
    table = raw.iloc[idx + 1:].copy()
    table.columns = [str(v).strip() for v in raw.iloc[idx].tolist()]
    return normalize_transactions(table, source)


def normalize_assets(df: pd.DataFrame) -> pd.DataFrame:
    hebrew_to_key = {v: k for k, v in S.ASSET_LABELS.items()}
    df = df.rename(columns={c: hebrew_to_key.get(str(c).strip(), str(c).strip()) for c in df.columns})
    for col in S.ASSET_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[S.ASSET_COLUMNS].copy()
    for col in ["balance", "monthly_deposit", "fee_balance_pct", "fee_deposit_pct", "annual_return_pct"]:
        df[col] = to_number(df[col]).fillna(0.0)
    df["liquidity_date"] = to_date(df["liquidity_date"].fillna(""))
    df["name"] = df["name"].fillna("").astype(str)
    df["provider"] = df["provider"].fillna("").astype(str)
    df["type"] = df["type"].fillna(S.ASSET_INVESTMENTS).astype(str).str.strip()
    return df[df["name"].str.len() > 0].reset_index(drop=True)


def read_assets(file, name: str) -> pd.DataFrame:
    if name.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(file, dtype=str)
    else:
        raw = file.read() if hasattr(file, "read") else Path(file).read_bytes()
        df = pd.read_csv(io.BytesIO(raw), dtype=str, encoding="utf-8-sig")
    return normalize_assets(df)


def load_sample() -> tuple[pd.DataFrame, pd.DataFrame]:
    tx = pd.read_csv(DATA_DIR / "sample_transactions.csv", encoding="utf-8-sig")
    tx["date"] = pd.to_datetime(tx["date"])
    tx["category"] = tx["category"].where(tx["category"].notna(), None)
    assets = normalize_assets(pd.read_csv(DATA_DIR / "sample_assets.csv", dtype=str, encoding="utf-8-sig"))
    return tx, assets


def template_transactions_csv() -> bytes:
    df = pd.DataFrame(
        [
            ["01/10/2026", "משכורת", "18500", 'עו"ש', ""],
            ["03/10/2026", "שופרסל דיל", "-412.30", "אשראי", ""],
        ],
        columns=[S.TX_LABELS[c] for c in S.TX_COLUMNS],
    )
    return df.to_csv(index=False).encode("utf-8-sig")


def template_assets_csv() -> bytes:
    df = pd.DataFrame(
        [
            ["פנסיה מקיפה", S.ASSET_PENSION, "שם הקרן", "250000", "3200", "0.22", "1.5", "5", ""],
            ["קרן השתלמות", S.ASSET_HISHTALMUT, "שם הקרן", "90000", "1600", "0.6", "0", "5", "01/01/2028"],
        ],
        columns=[S.ASSET_LABELS[c] for c in S.ASSET_COLUMNS],
    )
    return df.to_csv(index=False).encode("utf-8-sig")
