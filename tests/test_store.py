import pandas as pd
import pytest

from finance import loader as L
from finance import schema as S
from finance import store as STORE


def _tx(rows):
    return pd.DataFrame(rows, columns=S.TX_COLUMNS)


def test_loading_same_file_twice_adds_nothing():
    new = _tx([["2026-10-01", "משכורת", 10000, S.ACCOUNT_BANK, None],
               ["2026-10-03", "שופרסל", -200, S.ACCOUNT_CREDIT, None]])
    merged, added = STORE.merge_transactions(STORE.empty_transactions(), new)
    assert added == 2
    merged, added = STORE.merge_transactions(merged, new)
    assert added == 0 and len(merged) == 2


def test_identical_rows_in_one_file_are_kept():
    coffee = ["2026-10-03", "ארומה", -18, S.ACCOUNT_CREDIT, None]
    merged, added = STORE.merge_transactions(STORE.empty_transactions(), _tx([coffee, coffee]))
    assert added == 2
    # A later file with three such coffees adds just the third.
    merged, added = STORE.merge_transactions(merged, _tx([coffee, coffee, coffee]))
    assert added == 1 and len(merged) == 3


def test_overlapping_file_adds_only_new_rows():
    first = _tx([["2026-09-01", "משכורת", 10000, S.ACCOUNT_BANK, None]])
    second = _tx([["2026-09-01", "משכורת", 10000, S.ACCOUNT_BANK, None],
                  ["2026-10-01", "משכורת", 10000, S.ACCOUNT_BANK, None]])
    merged, _ = STORE.merge_transactions(STORE.empty_transactions(), first)
    merged, added = STORE.merge_transactions(merged, second)
    assert added == 1 and len(merged) == 2


def test_user_category_is_kept_and_blank_is_auto_filled():
    tx = STORE.clean_transactions(_tx([
        ["2026-10-03", "שופרסל", -200, S.ACCOUNT_CREDIT, "קניות"],
        ["2026-10-04", "שופרסל", -100, S.ACCOUNT_CREDIT, None],
    ]))
    assert sorted(tx["category"]) == ["מזון וסופר", "קניות"]


def test_incomplete_rows_are_dropped():
    tx = STORE.clean_transactions(_tx([["2026-10-03", "", -200, S.ACCOUNT_CREDIT, None],
                                       [None, "x", -1, S.ACCOUNT_BANK, None]]))
    assert tx.empty


def test_assets_with_same_name_are_replaced():
    a1 = L.normalize_assets(pd.DataFrame([["פנסיה", S.ASSET_PENSION, "", 100, 0, 0, 0, 0, ""]],
                                         columns=S.ASSET_COLUMNS))
    a2 = L.normalize_assets(pd.DataFrame([["פנסיה", S.ASSET_PENSION, "", 200, 0, 0, 0, 0, ""],
                                          ["קרן", S.ASSET_HISHTALMUT, "", 50, 0, 0, 0, 0, "2027-03-01"]],
                                         columns=S.ASSET_COLUMNS))
    merged = STORE.merge_assets(a1, a2)
    assert dict(zip(merged["name"], merged["balance"])) == {"פנסיה": 200, "קרן": 50}


def test_json_round_trip():
    tx, assets = L.load_sample()
    tx, assets = STORE.clean_transactions(tx), STORE.clean_assets(assets)
    text = STORE.to_json(tx, assets, {"age": 40})
    tx2, assets2, settings = STORE.from_json(text)
    pd.testing.assert_frame_equal(tx, tx2, check_dtype=False)
    pd.testing.assert_frame_equal(assets, assets2, check_dtype=False)
    assert settings == {"age": 40}


def test_json_round_trip_empty():
    tx, assets, settings = STORE.from_json(STORE.to_json(STORE.empty_transactions(), STORE.empty_assets()))
    assert tx.empty and assets.empty and settings == {}


@pytest.mark.parametrize("text", ["not json", "[]", '{"a": 1}'])
def test_bad_backup_raises(text):
    with pytest.raises(ValueError):
        STORE.from_json(text)
