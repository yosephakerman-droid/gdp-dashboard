"""Rule-based suggestions. Every threshold comes from Settings so the user
can change it; the defaults are rules of thumb, not verified benchmarks."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import analysis as A
from . import schema as S

CRITICAL, WARNING, INFO, GOOD = "critical", "warning", "info", "good"
SEVERITY_ORDER = {CRITICAL: 0, WARNING: 1, INFO: 2, GOOD: 3}


@dataclass
class Settings:
    age: int = 35
    retirement_age: int = 67
    emergency_months: float = 6.0
    savings_rate_target: float = 0.15
    max_pension_fee_balance: float = 0.3
    max_pension_fee_deposit: float = 2.0
    max_hishtalmut_fee: float = 0.7
    max_investment_fee: float = 0.5
    expected_return: float = 5.0
    excess_cash_buffer_months: float = 2.0


@dataclass
class Rec:
    severity: str
    title: str
    body: str
    impact: float | None = None  # rough yearly / total ₪ effect, when computable
    details: pd.DataFrame | None = field(default=None, repr=False)


def ils(x: float) -> str:
    return f"₪{x:,.0f}"


def _with_return(row: pd.Series, fallback: float) -> pd.Series:
    """Use the product's own return when known, else the user's assumption."""
    if row["annual_return_pct"] > 0:
        return row
    row = row.copy()
    row["annual_return_pct"] = fallback
    return row


def build(df: pd.DataFrame, assets: pd.DataFrame, s: Settings,
          today: pd.Timestamp | None = None) -> list[Rec]:
    today = today or pd.Timestamp.today().normalize()
    recs: list[Rec] = []
    avg = A.averages(df) if not df.empty else None
    nw = A.net_worth(assets, today)

    # 1. Spending more than earning
    if avg and avg.months:
        if avg.expenses > avg.income and avg.one_off > 0 and avg.regular <= avg.income:
            recs.append(Rec(WARNING, "השיפוץ מכניס את התזרים למינוס",
                            f"בממוצע חודשי ההוצאות ({ils(avg.expenses)}) עולות על ההכנסות ({ils(avg.income)}), "
                            f"אבל {ils(avg.one_off)} מהן הן שיפוץ. בלי השיפוץ ההוצאות הרגילות הן {ils(avg.regular)}, "
                            f"כלומר נשארים כ-{ils(avg.income - avg.regular)} בחודש. כדאי לוודא שהשיפוץ ממומן "
                            "מחיסכון שיועד לו ולא מהעו\"ש השוטף.", impact=(avg.expenses - avg.income) * 12))
        elif avg.expenses > avg.income:
            gap = avg.expenses - avg.income
            extra = f" גם בלי השיפוץ ({ils(avg.one_off)} בחודש) ההוצאות הרגילות ({ils(avg.regular)}) גבוהות מההכנסות." \
                if avg.one_off > 0 else ""
            recs.append(Rec(CRITICAL, "ההוצאות גבוהות מההכנסות",
                            f"בממוצע חודשי ההוצאות ({ils(avg.expenses)}) עולות על ההכנסות "
                            f"({ils(avg.income)}) ב-{ils(gap)}.{extra} כדאי להתחיל מהקטגוריות הגדולות "
                            "ומההוצאות הקבועות בלשונית 'פילוחים'.", impact=gap * 12))
        elif avg.savings_rate < s.savings_rate_target:
            need = s.savings_rate_target * avg.income - (avg.income - avg.expenses)
            recs.append(Rec(WARNING, "שיעור החיסכון נמוך מהיעד",
                            f"נשאר בממוצע {avg.savings_rate:.0%} מההכנסה (יעד שהוגדר: "
                            f"{s.savings_rate_target:.0%}). להגעה ליעד צריך לצמצם כ-{ils(need)} בחודש.",
                            impact=need * 12))
        else:
            recs.append(Rec(GOOD, "שיעור חיסכון תקין",
                            f"נשאר בממוצע {avg.savings_rate:.0%} מההכנסה, מעל היעד "
                            f"({s.savings_rate_target:.0%}). כדאי לוודא שהעודף מופנה לחיסכון "
                            "ולא נשאר בעו\"ש."))

    # 2. Emergency fund
    monthly = (avg.regular or avg.expenses) if avg else 0
    if avg and monthly > 0 and not assets.empty:
        target = monthly * s.emergency_months
        if nw.cash < target:
            recs.append(Rec(WARNING if nw.cash >= monthly * 3 else CRITICAL,
                            "קרן חירום חסרה",
                            f"מזומן זמין (עו\"ש + פיקדונות): {ils(nw.cash)}, כ-"
                            f"{nw.cash / monthly:.1f} חודשי הוצאה רגילה. היעד שהוגדר: "
                            f"{s.emergency_months:g} חודשים ({ils(target)}). חסרים {ils(target - nw.cash)}.",
                            impact=target - nw.cash))
        else:
            excess = nw.cash - monthly * (s.emergency_months + s.excess_cash_buffer_months)
            if excess > 0:
                recs.append(Rec(INFO, "יותר מזומן ממה שנדרש לחירום",
                                f"יש כ-{ils(excess)} מעבר לקרן החירום ולמרווח ביטחון. "
                                "מזומן בעו\"ש לרוב לא נושא ריבית; כדאי לבדוק חלופות סולידיות "
                                "או השקעה לטווח ארוך לפי היעדים שלך.", impact=excess))
            else:
                recs.append(Rec(GOOD, "קרן חירום קיימת",
                                f"המזומן הזמין מכסה כ-{nw.cash / monthly:.1f} חודשי הוצאה."))

    # 3. Overdraft and bank fees
    checking = assets[assets["type"] == S.ASSET_CHECKING] if not assets.empty else assets
    if not checking.empty and (checking["balance"] < 0).any():
        recs.append(Rec(CRITICAL, "יתרת עו\"ש שלילית",
                        f"יתרה נוכחית: {ils(checking['balance'].sum())}. ריבית על מינוס היא בדרך "
                        "כלל מהיקרות; עדיף לסגור אותה לפני חיסכון או השקעה."))
    if not df.empty:
        fees = A.expenses_only(df)
        fees = fees[fees["category"] == S.CAT_BANK_FEES]
        if not fees.empty and fees["spend"].sum() > 0:
            yearly = fees["spend"].sum() / max(df["month"].nunique(), 1) * 12
            recs.append(Rec(INFO, "עמלות וריביות בנק",
                            f"שולמו {ils(fees['spend'].sum())} בעמלות/ריבית בתקופה (כ-{ils(yearly)} "
                            "בשנה). אפשר לבקש מהבנק מסלול עמלות או לבדוק בנק דיגיטלי.",
                            impact=yearly))

    # 4. Category spikes
    if not df.empty:
        spikes = A.category_spikes(df)
        if not spikes.empty:
            top = spikes.iloc[0]
            names = ", ".join(spikes["category"].head(3))
            recs.append(Rec(WARNING, "קפיצה בהוצאות בחודש האחרון",
                            f"עלייה חריגה ב: {names}. למשל '{top['category']}': {ils(top['last'])} "
                            f"לעומת ממוצע {ils(top['avg'])}.",
                            details=spikes))

    # 5. Recurring charges / subscriptions
    if not df.empty:
        rec = A.recurring_expenses(df)
        subs = rec[(rec["category"] == S.CAT_SUBSCRIPTIONS) | (rec["avg_amount"] < 150)]
        if not subs.empty:
            recs.append(Rec(INFO, "מנויים וחיובים קבועים קטנים",
                            f"זוהו {len(subs)} חיובים חוזרים קטנים בסך כ-{ils(subs['yearly'].sum())} "
                            "בשנה. כדאי לעבור ולבטל את מה שלא בשימוש.",
                            impact=subs["yearly"].sum(), details=subs))

    # 6. Management fees
    if not assets.empty:
        years = max(s.retirement_age - s.age, 0)
        rows = []
        for _, r in assets.iterrows():
            t = r["type"]
            if t in (S.ASSET_PENSION, S.ASSET_GEMEL, S.ASSET_POLICY):
                high = r["fee_balance_pct"] > s.max_pension_fee_balance or r["fee_deposit_pct"] > s.max_pension_fee_deposit
                bench = (s.max_pension_fee_balance, s.max_pension_fee_deposit)
            elif t == S.ASSET_HISHTALMUT:
                high = r["fee_balance_pct"] > s.max_hishtalmut_fee
                bench = (s.max_hishtalmut_fee, 0.0)
            elif t == S.ASSET_INVESTMENTS:
                high = r["fee_balance_pct"] > s.max_investment_fee
                bench = (s.max_investment_fee, 0.0)
            else:
                continue
            if high:
                horizon = years if t in (S.ASSET_PENSION, S.ASSET_GEMEL, S.ASSET_POLICY) else min(years, 10) or 10
                rows.append({
                    "name": r["name"], "type": t,
                    "fee_balance_pct": r["fee_balance_pct"], "fee_deposit_pct": r["fee_deposit_pct"],
                    "impact": A.fee_impact(_with_return(r, s.expected_return), horizon, *bench),
                    "horizon": horizon,
                })
        if rows:
            d = pd.DataFrame(rows)
            recs.append(Rec(WARNING, "דמי ניהול מעל הסף שהגדרת",
                            f"{len(d)} מוצרים עם דמי ניהול גבוהים מהסף. לפי הנחת תשואה קבועה, "
                            f"הורדה לסף שווה כ-{ils(d['impact'].sum())} לאורך התקופה. "
                            "אפשר להשוות דמי ניהול ותשואות באתר גמל-נט של רשות שוק ההון, "
                            "ולבקש הנחה מהגוף המנהל או לשקול מעבר.",
                            impact=d["impact"].sum(), details=d))

    # 7. Hishtalmut liquidity
    if not assets.empty:
        h = assets[assets["type"] == S.ASSET_HISHTALMUT]
        for _, r in h.iterrows():
            if pd.notna(r["liquidity_date"]):
                if r["liquidity_date"] <= today:
                    recs.append(Rec(INFO, f"קרן ההשתלמות '{r['name']}' נזילה",
                                    f"תאריך הנזילות ({r['liquidity_date']:%d/%m/%Y}) עבר. "
                                    "משיכה אינה חובה; לפני שמושכים כדאי לבדוק את ההשלכות "
                                    "המיסויות מול הגוף המנהל או יועץ."))
                elif (r["liquidity_date"] - today).days <= 365:
                    recs.append(Rec(INFO, f"קרן ההשתלמות '{r['name']}' נזילה בקרוב",
                                    f"תיפתח למשיכה ב-{r['liquidity_date']:%d/%m/%Y}."))
        if h.empty:
            recs.append(Rec(INFO, "אין קרן השתלמות ברשימה",
                            "אם אינה קיימת, כדאי לבדוק מול המעסיק או רואה חשבון אם אפשר "
                            "ומשתלם לפתוח אחת במצבך."))

    # 8. Expensive loans
    if not assets.empty:
        loans = assets[(assets["type"] == S.ASSET_LOAN) & (assets["annual_return_pct"] > s.expected_return)]
        for _, r in loans.iterrows():
            recs.append(Rec(WARNING, f"הלוואה יקרה: {r['name']}",
                            f"ריבית {r['annual_return_pct']:g}% גבוהה מהתשואה הצפויה שהגדרת "
                            f"({s.expected_return:g}%). אם יש מזומן מעבר לקרן החירום, פירעון מוקדם "
                            "עשוי להשתלם (בדוק עמלת פירעון מוקדם).",
                            impact=abs(r["balance"]) * r["annual_return_pct"] / 100))

    # 9. No long-term saving recorded
    if not assets.empty and not assets["type"].isin([S.ASSET_PENSION, S.ASSET_GEMEL]).any():
        if assets["type"].eq(S.ASSET_POLICY).any():
            recs.append(Rec(WARNING, "לא הוזנה קרן פנסיה",
                            "יש פוליסות ביטוח/חיסכון אבל לא קרן פנסיה או קופת גמל. כדאי לבדוק אם "
                            "הפוליסות הן החיסכון הפנסיוני שלך (למשל ביטוח מנהלים), ואם יש קרן פנסיה "
                            "דרך המעסיקים – להוסיף אותה."))
        else:
            recs.append(Rec(WARNING, "לא הוזן חיסכון פנסיוני",
                            "לא נמצאה קרן פנסיה או קופת גמל בנתונים. אם יש כזו, כדאי להוסיף אותה; "
                            "אם אין, זה נושא לבדיקה דחופה."))

    return sorted(recs, key=lambda r: SEVERITY_ORDER[r.severity])
