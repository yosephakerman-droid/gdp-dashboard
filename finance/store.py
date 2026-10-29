"""The user's saved data: merging new uploads and (de)serializing to JSON."""

from __future__ import annotations

import json

import pandas as pd

from . import analysis as A
from . import loader as L
from . import schema as S

VERSION = 1
TX_KEY = ["date", "description", "amount", "account"]


def empty_transactions() -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.Series(dtype="datetime64[ns]"),
        "description": pd.Series(dtype=object),
        "amount": pd.Series(dtype=float),
        "account": pd.Series(dtype=object),
        "category": pd.Series(dtype=object),
    })


def empty_assets() -> pd.DataFrame:
    return L.normalize_assets(pd.DataFrame(columns=S.ASSET_COLUMNS))


def clean_transactions(tx: pd.DataFrame) -> pd.DataFrame:
    """Canonical columns and types; blank categories are auto-filled."""
    if tx is None or tx.empty:
        return empty_transactions()
    df = tx.reindex(columns=S.TX_COLUMNS).copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["description"] = df["description"].fillna("").astype(str).str.strip()
    df["account"] = df["account"].where(df["account"].isin([S.ACCOUNT_BANK, S.ACCOUNT_CREDIT]), S.ACCOUNT_BANK)
    df = df.dropna(subset=["date", "amount"])
    df = df[df["description"] != ""]
    if df.empty:
        return empty_transactions()
    df = A.prepare_transactions(df)[S.TX_COLUMNS]
    return df.sort_values("date", ascending=False, kind="stable").reset_index(drop=True)


def _with_occurrence(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["amount_r"] = df["amount"].round(2)
    df["occ"] = df.groupby(["date", "description", "amount_r", "account"]).cumcount()
    return df


def merge_transactions(existing: pd.DataFrame, new: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Add rows from `new` that aren't already saved. Returns (merged, added).

    Identical rows inside one file (two equal coffees on the same day) are kept;
    loading the same file twice adds nothing.
    """
    new = clean_transactions(new)
    if new.empty:
        return existing, 0
    if existing.empty:
        return new, len(new)
    key = ["date", "description", "amount_r", "account", "occ"]
    e, n = _with_occurrence(existing), _with_occurrence(new)
    fresh = n.merge(e[key], on=key, how="left", indicator=True)
    fresh = fresh[fresh["_merge"] == "left_only"][S.TX_COLUMNS]
    if fresh.empty:
        return existing, 0
    merged = pd.concat([existing, fresh], ignore_index=True)
    return merged.sort_values("date", ascending=False, kind="stable").reset_index(drop=True), len(fresh)


def clean_assets(assets: pd.DataFrame) -> pd.DataFrame:
    if assets is None or assets.empty:
        return empty_assets()
    a = L.normalize_assets(assets.copy())
    a["type"] = a["type"].where(a["type"].isin(S.ASSET_TYPES), S.ASSET_INVESTMENTS)
    return a


def merge_assets(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Rows in `new` replace saved rows with the same name; others are added."""
    new = clean_assets(new)
    if existing.empty:
        return new
    keep = existing[~existing["name"].isin(new["name"])]
    return pd.concat([keep, new], ignore_index=True)


def to_json(tx: pd.DataFrame, assets: pd.DataFrame, settings: dict | None = None) -> str:
    t = tx.copy()
    t["date"] = t["date"].dt.strftime("%Y-%m-%d")
    a = assets.copy()
    a["liquidity_date"] = a["liquidity_date"].dt.strftime("%Y-%m-%d")
    payload = {
        "version": VERSION,
        "transactions": t.astype(object).where(t.notna(), None).to_dict("records"),
        "assets": a.astype(object).where(a.notna(), None).to_dict("records"),
        "settings": settings or {},
    }
    return json.dumps(payload, ensure_ascii=False)


def from_json(text: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Parse saved data. Raises ValueError on anything that isn't ours."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError("קובץ הגיבוי אינו תקין.") from e
    if not isinstance(data, dict) or "transactions" not in data or "assets" not in data:
        raise ValueError("זה לא קובץ גיבוי של האפליקציה.")
    tx = pd.DataFrame(data["transactions"], columns=S.TX_COLUMNS)
    assets = pd.DataFrame(data["assets"], columns=S.ASSET_COLUMNS)
    settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    return clean_transactions(tx), clean_assets(assets), settings
