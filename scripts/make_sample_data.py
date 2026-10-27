"""Generate the fictitious demo data in data/. Run: python scripts/make_sample_data.py"""

from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(7)
OUT = Path(__file__).resolve().parent.parent / "data"
BANK, CREDIT = 'עו"ש', "אשראי"

rows = []


def add(date, desc, amount, account):
    rows.append([pd.Timestamp(date).strftime("%Y-%m-%d"), desc, round(float(amount), 2), account, ""])


months = pd.period_range("2025-11", "2026-10", freq="M")
card_totals = {}

for i, p in enumerate(months):
    y, m = p.year, p.month
    d = lambda day: pd.Timestamp(year=y, month=m, day=min(day, p.days_in_month))

    def card(day, desc, amount):
        add(d(day), desc, amount, CREDIT)
        card_totals[p] = card_totals.get(p, 0.0) + amount

    # --- bank account ---
    add(d(10), "משכורת - חברת הדוגמה בע\"מ", 18500 + (1500 if m == 3 else 0), BANK)
    add(d(1), "שכר דירה - העברה", -5800, BANK)
    if m % 2 == 1:
        add(d(15), "ארנונה עירייה", -720, BANK)
        add(d(18), "חברת חשמל", -rng.uniform(380, 620), BANK)
        add(d(20), "תאגיד מים", -rng.uniform(140, 210), BANK)
    add(d(5), "העברה להשקעות - תיק השקעות", -2000, BANK)
    add(d(28), "עמלת פעולה בערוץ ישיר", -rng.choice([6, 12, 18]), BANK)
    if rng.random() < 0.5:
        add(d(rng.integers(3, 27)), "כספומט משיכת מזומן", -rng.choice([200, 300, 500]), BANK)
    if rng.random() < 0.4:
        add(d(rng.integers(3, 27)), "ביט - העברה מחבר", rng.choice([80, 150, 250]), BANK)
    if m == 2:
        add(d(12), "ריבית חובה", -48, BANK)

    # --- credit card ---
    for week in range(4):
        card(2 + week * 7, rng.choice(["שופרסל דיל", "רמי לוי", "ויקטורי"]), rng.uniform(320, 680))
    for _ in range(rng.integers(3, 6)):
        card(rng.integers(1, 28), rng.choice(["וולט", "ארומה תל אביב", "מסעדת השף", "פיצה האט"]),
             rng.uniform(45, 260) * (1.8 if p == months[-1] else 1))
    for _ in range(2):
        card(rng.integers(1, 28), rng.choice(["פז ", "סונול", "דור אלון"]) + " תחנת דלק", rng.uniform(250, 360))
    card(3, "NETFLIX.COM", 54.9)
    card(4, "SPOTIFY", 23.9)
    card(6, "APPLE.COM/BILL ICLOUD", 11.9)
    card(7, "חדר כושר הולמס פלייס", 199)
    card(8, "בזק בינלאומי", 99)
    card(9, "פרטנר תקשורת", 69)
    card(11, "ביטוח רכב - הראל", 310)
    card(12, "ביטוח בריאות - מגדל", 145)
    if rng.random() < 0.6:
        card(rng.integers(1, 28), "סופר-פארם", rng.uniform(60, 240))
    if rng.random() < 0.5:
        card(rng.integers(1, 28), rng.choice(["ZARA", "AMAZON", "KSP", "איקאה"]),
             rng.uniform(150, 900) * (2.2 if p == months[-1] else 1))
    if m in (8,):
        card(14, "BOOKING.COM מלון", 4200)
        card(14, "אל על טיסה", 3600)
    if m == 12:
        card(20, "מוסך המומחים טסט", 1450)

# Card bill on the 2nd of the next month, as it appears in the bank account.
for p, total in card_totals.items():
    nxt = (p + 1)
    if nxt <= months[-1]:
        add(pd.Timestamp(year=nxt.year, month=nxt.month, day=2), "ישראכרט - חיוב כרטיס", -total, BANK)

tx = pd.DataFrame(rows, columns=["date", "description", "amount", "account", "category"])
tx = tx[tx["date"] <= "2026-10-26"]
# Credit card exports are positive; store the signed form used internally.
tx.loc[tx["account"] == CREDIT, "amount"] *= -1
tx.sort_values("date").to_csv(OUT / "sample_transactions.csv", index=False, encoding="utf-8-sig")

assets = pd.DataFrame(
    [
        ["עו\"ש בנק", "עו\"ש", "בנק לדוגמה", 42000, 0, 0, 0, 0, ""],
        ["פיקדון שקלי", "פיקדון/חיסכון", "בנק לדוגמה", 30000, 0, 0, 0, 3.5, ""],
        ["תיק השקעות עצמאי", "השקעות", "בית השקעות לדוגמה", 120000, 2000, 0.4, 0, 6, ""],
        ["פנסיה מקיפה", "פנסיה", "קרן פנסיה לדוגמה", 310000, 3300, 0.35, 1.8, 5, ""],
        ["קרן השתלמות", "קרן השתלמות", "בית השקעות לדוגמה", 95000, 1850, 0.68, 0, 5.5, "2027-03-01"],
        ["קופת גמל להשקעה", "קופת גמל", "בית השקעות לדוגמה", 40000, 500, 0.6, 0, 5.5, ""],
        ["הלוואת רכב", "הלוואה", "בנק לדוגמה", 35000, 0, 0, 0, 6.5, ""],
    ],
    columns=["name", "type", "provider", "balance", "monthly_deposit", "fee_balance_pct",
             "fee_deposit_pct", "annual_return_pct", "liquidity_date"],
)
assets.to_csv(OUT / "sample_assets.csv", index=False, encoding="utf-8-sig")
print(len(tx), "transactions,", len(assets), "assets")
