"""Personal finance dashboard: cash flow, breakdowns, savings and suggestions."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from finance import analysis as A
from finance import loader as L
from finance import recommendations as R
from finance import schema as S

st.set_page_config(page_title="ניתוח פיננסי אישי", page_icon=":bar_chart:", layout="wide")

# Colors: fixed categorical order (income, expenses, savings) + status red.
C_INCOME, C_EXPENSE, C_SAVING, C_NEG = "#2a78d6", "#eb6834", "#1baf7a", "#e34948"

st.markdown(
    """
    <style>
      /* RTL on content only; the app shell (sidebar positioning) stays LTR. */
      [data-testid="stMainBlockContainer"], [data-testid="stSidebarUserContent"] {
        direction: rtl; text-align: right;
      }
      [data-testid="stMetricValue"], [data-testid="stMetricDelta"],
      .js-plotly-plot, [data-testid="stDataFrame"], [data-testid="stDataEditor"] { direction: ltr; }
      [data-testid="stMetricValue"] { text-align: right; }
      [data-testid="stMarkdownContainer"] ul { padding-right: 1.2rem; padding-left: 0; }
    </style>
    """,
    unsafe_allow_html=True,
)


def ils(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"₪{x:,.0f}" if x >= 0 else f"-₪{-x:,.0f}"


def pct(x) -> str:
    return "—" if x is None or pd.isna(x) else f"{x:.0%}"


def style_fig(fig: go.Figure, height: int = 360) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hoverlabel=dict(align="right"),
        bargap=0.25,
        bargroupgap=0.08,
    )
    fig.update_yaxes(tickprefix="₪", separatethousands=True, gridcolor="rgba(128,128,128,0.15)", zeroline=True,
                     zerolinecolor="rgba(128,128,128,0.4)")
    fig.update_xaxes(showgrid=False)
    return fig


def month_label(ts) -> str:
    return pd.Timestamp(ts).strftime("%m/%Y")


# --- Sidebar: data and settings ---------------------------------------------

with st.sidebar:
    st.header("נתונים")
    mode = st.radio("מקור", ["נתוני דוגמה (פיקטיביים)", "הקבצים שלי"], label_visibility="collapsed")

    tx_parts, assets = [], pd.DataFrame(columns=S.ASSET_COLUMNS)
    errors = []
    if mode.startswith("נתוני דוגמה"):
        sample_tx, assets = L.load_sample()
        tx_parts.append(sample_tx)
        st.caption("כל הנתונים במצב זה מומצאים, להמחשה בלבד.")
    else:
        bank_files = st.file_uploader('קובצי עו"ש (CSV / Excel)', type=["csv", "xlsx", "xls"],
                                      accept_multiple_files=True)
        credit_files = st.file_uploader("קובצי כרטיסי אשראי", type=["csv", "xlsx", "xls"],
                                        accept_multiple_files=True,
                                        help="חיובים מופיעים בקובץ כמספר חיובי; המערכת הופכת אותם להוצאה.")
        assets_file = st.file_uploader("נכסים, חסכונות והלוואות", type=["csv", "xlsx", "xls"],
                                       help="פנסיה, קרן השתלמות, גמל, תיק השקעות, פיקדונות, עו\"ש והלוואות.")
        for files, source in ((bank_files, S.ACCOUNT_BANK), (credit_files, S.ACCOUNT_CREDIT)):
            for f in files or []:
                try:
                    tx_parts.append(L.read_transactions(f, f.name, source))
                except Exception as e:  # show the problem, keep going with other files
                    errors.append(f"{f.name}: {e}")
        if assets_file:
            try:
                assets = L.read_assets(assets_file, assets_file.name)
            except Exception as e:
                errors.append(f"{assets_file.name}: {e}")
        c1, c2 = st.columns(2)
        c1.download_button("תבנית תנועות", L.template_transactions_csv(), "transactions_template.csv", "text/csv")
        c2.download_button("תבנית נכסים", L.template_assets_csv(), "assets_template.csv", "text/csv")
        st.caption("הקבצים מעובדים בזיכרון בזמן הריצה ואינם נשמרים בשרת.")
    for e in errors:
        st.error(e)

    st.header("הגדרות")
    with st.expander("פרופיל וספים להמלצות"):
        st.caption("ברירות המחדל הן כללי אצבע שבחרתי, לא נתון רשמי. שנה לפי שיקול דעתך.")
        cfg = R.Settings(
            age=st.number_input("גיל", 18, 90, 35),
            retirement_age=st.number_input("גיל פרישה מתוכנן", 50, 90, 67),
            emergency_months=st.slider("קרן חירום (חודשי הוצאה)", 1.0, 12.0, 6.0, 0.5),
            savings_rate_target=st.slider("יעד שיעור חיסכון", 0.0, 0.5, 0.15, 0.01, format="%.2f"),
            max_pension_fee_balance=st.number_input("סף דמי ניהול פנסיה/גמל מצבירה %", 0.0, 2.0, 0.3, 0.05),
            max_pension_fee_deposit=st.number_input("סף דמי ניהול פנסיה מהפקדה %", 0.0, 6.0, 2.0, 0.1),
            max_hishtalmut_fee=st.number_input("סף דמי ניהול קרן השתלמות %", 0.0, 2.0, 0.7, 0.05),
            max_investment_fee=st.number_input("סף דמי ניהול תיק השקעות %", 0.0, 2.0, 0.5, 0.05),
            expected_return=st.number_input("תשואה שנתית צפויה לתחזיות %", 0.0, 15.0, 5.0, 0.5),
        )

base_tx = pd.concat(tx_parts, ignore_index=True) if tx_parts else pd.DataFrame(columns=S.TX_COLUMNS)

st.title("ניתוח פיננסי אישי")
if base_tx.empty and assets.empty:
    st.info("העלה קובצי עו\"ש, אשראי ונכסים בסרגל הצדדי, או בחר 'נתוני דוגמה' כדי לראות את המערכת.")
    st.stop()

# Editor state is tied to the loaded data, so edits never apply to other files.
data_sig = f"{mode}-{len(base_tx)}-{pd.util.hash_pandas_object(base_tx.astype(str), index=False).sum() if len(base_tx) else 0}"
prepared = A.prepare_transactions(base_tx) if not base_tx.empty else base_tx.assign(kind=None, month=None)

tabs = st.tabs(["סקירה", "הכנסות מול הוצאות", "פילוחים", "נכסים וחיסכון", "המלצות", "נתונים ועריכה"])

# --- Data tab first, so edits apply to every other tab -----------------------

with tabs[5]:
    st.subheader("תנועות")
    st.caption("אפשר לשנות קטגוריה בכל שורה; השינוי מתעדכן בכל הלשוניות (עד רענון הדף).")
    view_cols = ["date", "description", "amount", "account", "category", "kind"]
    edited = st.data_editor(
        prepared[view_cols] if not prepared.empty else prepared,
        key=f"tx_editor-{data_sig}",
        hide_index=True,
        width="stretch",
        disabled=["date", "description", "amount", "account", "kind"],
        column_config={
            "date": st.column_config.DateColumn(S.TX_LABELS["date"], format="DD/MM/YYYY"),
            "description": S.TX_LABELS["description"],
            "amount": st.column_config.NumberColumn(S.TX_LABELS["amount"], format="localized"),
            "account": S.TX_LABELS["account"],
            "category": st.column_config.SelectboxColumn(
                S.TX_LABELS["category"],
                options=sorted(set(S.ALL_CATEGORIES) | set(prepared.get("category", pd.Series()).dropna())),
                required=True,
            ),
            "kind": S.TX_LABELS["kind"],
        },
    )
    st.subheader("נכסים, חסכונות והלוואות")
    st.caption("אפשר להוסיף, למחוק ולערוך שורות. בהלוואה: 'יתרה' = יתרת החוב, 'תשואה/ריבית' = ריבית ההלוואה.")
    assets = st.data_editor(
        assets,
        key=f"assets_editor-{data_sig}-{len(assets)}",
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={
            "name": S.ASSET_LABELS["name"],
            "type": st.column_config.SelectboxColumn(S.ASSET_LABELS["type"], options=S.ASSET_TYPES, required=True),
            "provider": S.ASSET_LABELS["provider"],
            "balance": st.column_config.NumberColumn(S.ASSET_LABELS["balance"], format="localized"),
            "monthly_deposit": st.column_config.NumberColumn(S.ASSET_LABELS["monthly_deposit"], format="localized"),
            "fee_balance_pct": st.column_config.NumberColumn(S.ASSET_LABELS["fee_balance_pct"], format="%.2f"),
            "fee_deposit_pct": st.column_config.NumberColumn(S.ASSET_LABELS["fee_deposit_pct"], format="%.2f"),
            "annual_return_pct": st.column_config.NumberColumn(S.ASSET_LABELS["annual_return_pct"], format="%.2f"),
            "liquidity_date": st.column_config.DateColumn(S.ASSET_LABELS["liquidity_date"], format="DD/MM/YYYY"),
        },
    )
    assets = L.normalize_assets(assets) if len(assets) else assets

all_tx = prepared.copy()
if not all_tx.empty:
    all_tx["category"] = edited["category"].values
    all_tx = A.assign_kinds(all_tx)
    export = all_tx[["date", "description", "amount", "account", "category", "kind"]].rename(columns=S.TX_LABELS)
    with tabs[5]:
        st.download_button("הורדת התנועות המסווגות (CSV)", export.to_csv(index=False).encode("utf-8-sig"),
                           "categorized_transactions.csv", "text/csv")

# --- Period filter ------------------------------------------------------------

df = all_tx
if not all_tx.empty:
    months = sorted(all_tx["month"].unique())
    if len(months) > 1:
        start, end = st.select_slider("תקופה", options=months, value=(months[0], months[-1]),
                                      format_func=month_label)
        df = all_tx[(all_tx["month"] >= start) & (all_tx["month"] <= end)]

today = pd.Timestamp.today().normalize()
avg = A.averages(df) if not df.empty else None
nw = A.net_worth(assets, today)
summary = A.monthly_summary(df) if not df.empty else pd.DataFrame()
recs = R.build(df, assets, cfg, today)

SEV_BOX = {R.CRITICAL: st.error, R.WARNING: st.warning, R.INFO: st.info, R.GOOD: st.success}
SEV_ICON = {R.CRITICAL: "🔴", R.WARNING: "🟠", R.INFO: "🔵", R.GOOD: "🟢"}


DETAIL_LABELS = {
    **S.ASSET_LABELS, "category": "קטגוריה", "description": "תיאור", "months": "חודשים",
    "avg_amount": "ממוצע לחודש", "yearly": "בשנה", "last": "חודש אחרון", "avg": "ממוצע קודם",
    "diff": "הפרש", "ratio": "יחס", "impact": "השפעה משוערת (₪)", "horizon": "שנים בחישוב",
}


def show_rec(rec: R.Rec, with_details: bool = True):
    text = f"**{rec.title}**  \n{rec.body}"
    if rec.impact:
        text += f"  \nהשפעה משוערת: **{ils(rec.impact)}**"
    SEV_BOX[rec.severity](text, icon=SEV_ICON[rec.severity])
    if with_details and rec.details is not None and not rec.details.empty:
        with st.expander("פירוט"):
            st.dataframe(rec.details.rename(columns=DETAIL_LABELS).round(2), hide_index=True,
                         width="stretch")


def cashflow_chart(m: pd.DataFrame) -> go.Figure:
    x = [month_label(v) for v in m["month"]]
    fig = go.Figure()
    fig.add_bar(x=x, y=m["income"], name="הכנסות", marker_color=C_INCOME, marker_cornerradius=4,
                hovertemplate="הכנסות: ₪%{y:,.0f}<extra></extra>")
    fig.add_bar(x=x, y=m["expenses"], name="הוצאות", marker_color=C_EXPENSE, marker_cornerradius=4,
                hovertemplate="הוצאות: ₪%{y:,.0f}<extra></extra>")
    fig.add_bar(x=x, y=m["savings"], name="העברות לחיסכון", marker_color=C_SAVING, marker_cornerradius=4,
                hovertemplate="לחיסכון: ₪%{y:,.0f}<extra></extra>")
    fig.update_layout(barmode="group", hovermode="x unified")
    return style_fig(fig)


# --- Overview -------------------------------------------------------------------

with tabs[0]:
    c = st.columns(5)
    c[0].metric("שווי נקי", ils(nw.net), help="נכסים פחות הלוואות, לפי טבלת הנכסים.")
    c[1].metric("נזיל כעת", ils(nw.liquid), help="עו\"ש, פיקדונות, השקעות וקרנות השתלמות שנפתחו.")
    if avg:
        c[2].metric("הכנסה חודשית ממוצעת", ils(avg.income))
        c[3].metric("הוצאה חודשית ממוצעת", ils(avg.expenses))
        c[4].metric("שיעור חיסכון", pct(avg.savings_rate),
                    help="(הכנסות − הוצאות) / הכנסות. העברות לחיסכון אינן נספרות כהוצאה.")
        st.caption(f"ממוצעים לפי {avg.months} חודשים מלאים בתקופה שנבחרה.")
    if not summary.empty:
        st.subheader("הכנסות מול הוצאות")
        st.plotly_chart(cashflow_chart(summary), width="stretch", theme="streamlit", key="chart_1")
    st.subheader("עיקר ההמלצות")
    top = [r for r in recs if r.severity in (R.CRITICAL, R.WARNING)][:3] or recs[:3]
    for r in top:
        show_rec(r, with_details=False)
    st.caption("ההמלצה המלאה בלשונית 'המלצות'.")

# --- Income vs expenses ------------------------------------------------------------

with tabs[1]:
    if summary.empty:
        st.info("אין תנועות להצגה.")
    else:
        st.plotly_chart(cashflow_chart(summary), width="stretch", theme="streamlit", key="chart_2")

        st.subheader("תזרים נטו לחודש")
        st.caption("הכנסות פחות הוצאות פחות העברות לחיסכון — מה שנשאר (או חסר) בעו\"ש.")
        x = [month_label(v) for v in summary["month"]]
        net_fig = go.Figure(go.Bar(
            x=x, y=summary["net"], marker_cornerradius=4,
            marker_color=[C_INCOME if v >= 0 else C_NEG for v in summary["net"]],
            hovertemplate="נטו: ₪%{y:,.0f}<extra></extra>",
        ))
        st.plotly_chart(style_fig(net_fig, 280), width="stretch", theme="streamlit", key="chart_3")

        st.subheader("נטו מצטבר")
        cum = go.Figure(go.Scatter(x=x, y=summary["net"].cumsum(), mode="lines+markers",
                                   line=dict(color=C_INCOME, width=2), marker=dict(size=8),
                                   hovertemplate="מצטבר: ₪%{y:,.0f}<extra></extra>"))
        st.plotly_chart(style_fig(cum, 260), width="stretch", theme="streamlit", key="chart_4")

        st.subheader("טבלה חודשית")
        tbl = summary.copy()
        tbl["month"] = tbl["month"].map(month_label)
        st.dataframe(
            tbl.rename(columns={"month": "חודש", "income": "הכנסות", "expenses": "הוצאות",
                                "savings": "לחיסכון", "net": "נטו", "savings_rate": "שיעור חיסכון"}),
            hide_index=True, width="stretch",
            column_config={k: st.column_config.NumberColumn(format="localized")
                           for k in ["הכנסות", "הוצאות", "לחיסכון", "נטו"]}
            | {"שיעור חיסכון": st.column_config.NumberColumn(format="percent")},
        )

        inc = df[df["kind"] == S.KIND_INCOME]
        if not inc.empty:
            st.subheader("מקורות הכנסה")
            src = inc.groupby("category", as_index=False)["amount"].sum().sort_values("amount", ascending=False)
            st.dataframe(src.rename(columns={"category": "קטגוריה", "amount": "סך הכל"}), hide_index=True,
                         column_config={"סך הכל": st.column_config.NumberColumn(format="localized")})

# --- Breakdowns ---------------------------------------------------------------------

with tabs[2]:
    cats = A.category_breakdown(df) if not df.empty else pd.DataFrame()
    if cats.empty:
        st.info("אין הוצאות להצגה.")
    else:
        st.subheader("הוצאה חודשית ממוצעת לפי קטגוריה")
        cs = cats.sort_values("monthly_avg")
        fig = go.Figure(go.Bar(
            y=cs["category"], x=cs["monthly_avg"], orientation="h", marker_color=C_EXPENSE,
            marker_cornerradius=4,
            text=[f"{s:.0%}" for s in cs["share"]], textposition="outside",
            customdata=cs[["spend", "share"]].values,
            hovertemplate="%{y}<br>ממוצע לחודש: ₪%{x:,.0f}<br>סך הכל: ₪%{customdata[0]:,.0f}"
                          "<br>חלק מההוצאות: %{customdata[1]:.0%}<extra></extra>",
        ))
        style_fig(fig, max(300, 28 * len(cs)))
        fig.update_xaxes(tickprefix="₪", separatethousands=True)
        fig.update_yaxes(tickprefix="", side="right")
        st.plotly_chart(fig, width="stretch", theme="streamlit", key="chart_5")

        st.subheader("מגמה לפי קטגוריה")
        pick = st.selectbox("קטגוריה", cats["category"].tolist())
        cbm = A.category_by_month(df)
        cbm = cbm[cbm["category"] == pick]
        trend = go.Figure(go.Bar(x=[month_label(v) for v in cbm["month"]], y=cbm["spend"],
                                 marker_color=C_EXPENSE, marker_cornerradius=4,
                                 hovertemplate="₪%{y:,.0f}<extra></extra>"))
        st.plotly_chart(style_fig(trend, 260), width="stretch", theme="streamlit", key="chart_6")

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("קבועות מול משתנות")
            fixed, variable = A.fixed_vs_variable(df)
            st.metric("הוצאות קבועות (חודשי)", ils(fixed),
                      help="חיובים שחוזרים ב-3 חודשים לפחות בסכום דומה.")
            st.metric("הוצאות משתנות (חודשי)", ils(variable))
        with c2:
            st.subheader("לפי חשבון")
            e = A.expenses_only(df)
            by_acc = e.groupby("account", as_index=False)["spend"].sum()
            by_acc["share"] = by_acc["spend"] / by_acc["spend"].sum()
            st.dataframe(by_acc.rename(columns={"account": "חשבון", "spend": "סך הוצאות", "share": "חלק"}),
                         hide_index=True, width="stretch",
                         column_config={"סך הוצאות": st.column_config.NumberColumn(format="localized"),
                                        "חלק": st.column_config.NumberColumn(format="percent")})

        st.subheader("חיובים חוזרים")
        rec_df = A.recurring_expenses(df)
        st.dataframe(rec_df.rename(columns={"description": "תיאור", "category": "קטגוריה", "months": "חודשים",
                                            "avg_amount": "ממוצע לחודש", "yearly": "בשנה"}),
                     hide_index=True, width="stretch",
                     column_config={"ממוצע לחודש": st.column_config.NumberColumn(format="localized"),
                                    "בשנה": st.column_config.NumberColumn(format="localized")})

        st.subheader("בתי העסק הגדולים")
        st.dataframe(A.top_merchants(df).rename(columns={"description": "תיאור", "category": "קטגוריה",
                                                         "spend": "סך הכל", "count": "מספר חיובים"}),
                     hide_index=True, width="stretch",
                     column_config={"סך הכל": st.column_config.NumberColumn(format="localized")})

# --- Assets ---------------------------------------------------------------------------

with tabs[3]:
    if assets.empty:
        st.info("לא הוזנו נכסים. אפשר להוסיף בלשונית 'נתונים ועריכה' או להעלות קובץ.")
    else:
        c = st.columns(4)
        c[0].metric("סך נכסים", ils(nw.assets))
        c[1].metric("הלוואות", ils(nw.liabilities))
        c[2].metric("נזיל כעת", ils(nw.liquid))
        c[3].metric("נעול לטווח ארוך", ils(nw.locked))

        st.subheader("פיזור לפי סוג")
        pos = assets[assets["type"] != S.ASSET_LOAN]
        by_type = pos.groupby("type", as_index=False)["balance"].sum().sort_values("balance")
        by_type["share"] = by_type["balance"] / by_type["balance"].sum()
        fig = go.Figure(go.Bar(y=by_type["type"], x=by_type["balance"], orientation="h",
                               marker_color=C_INCOME, marker_cornerradius=4,
                               text=[f"{s:.0%}" for s in by_type["share"]], textposition="outside",
                               hovertemplate="%{y}: ₪%{x:,.0f}<extra></extra>"))
        style_fig(fig, max(260, 40 * len(by_type)))
        fig.update_xaxes(tickprefix="₪", separatethousands=True)
        fig.update_yaxes(tickprefix="", side="right")
        st.plotly_chart(fig, width="stretch", theme="streamlit", key="chart_7")

        st.subheader("דמי ניהול שנתיים משוערים")
        fees = A.annual_fees(assets)
        if fees.empty:
            st.caption("לא הוזנו דמי ניהול.")
        else:
            st.metric("סך דמי ניהול בשנה", ils(fees["fee_total"].sum()))
            st.dataframe(
                fees[["name", "type", "balance", "fee_balance_pct", "fee_deposit_pct", "fee_total"]].rename(
                    columns={**S.ASSET_LABELS, "fee_total": "עלות שנתית"}),
                hide_index=True, width="stretch",
                column_config={"יתרה": st.column_config.NumberColumn(format="localized"),
                               "עלות שנתית": st.column_config.NumberColumn(format="localized")},
            )

        st.subheader("תחזית חיסכון לטווח ארוך")
        lt = assets[assets["type"].isin(S.LONG_TERM_TYPES + [S.ASSET_INVESTMENTS])]
        if lt.empty:
            st.caption("אין מוצרי חיסכון לטווח ארוך.")
        else:
            years = max(cfg.retirement_age - cfg.age, 1)
            chosen = st.multiselect("מוצרים", lt["name"].tolist(),
                                    default=lt[lt["type"].isin([S.ASSET_PENSION, S.ASSET_GEMEL])]["name"].tolist()
                                    or lt["name"].tolist()[:1])
            ret = st.slider("תשואה שנתית ברוטו להנחה %", 0.0, 12.0, float(cfg.expected_return), 0.5)
            sel = lt[lt["name"].isin(chosen)]
            if not sel.empty:
                mine = sum(A.project_balance(r.balance, r.monthly_deposit, ret, r.fee_balance_pct,
                                             r.fee_deposit_pct, years)["balance"] for r in sel.itertuples())
                nofee = sum(A.project_balance(r.balance, r.monthly_deposit, ret, 0, 0, years)["balance"]
                            for r in sel.itertuples())
                yrs = list(range(years + 1))
                pf = go.Figure()
                pf.add_scatter(x=[cfg.age + y for y in yrs], y=nofee, name="ללא דמי ניהול",
                               line=dict(color=C_SAVING, width=2, dash="dot"),
                               hovertemplate="גיל %{x}: ₪%{y:,.0f}<extra>ללא דמי ניהול</extra>")
                pf.add_scatter(x=[cfg.age + y for y in yrs], y=mine, name="עם דמי הניהול שלך",
                               line=dict(color=C_INCOME, width=2),
                               hovertemplate="גיל %{x}: ₪%{y:,.0f}<extra>עם דמי הניהול שלך</extra>")
                pf.update_layout(hovermode="x unified")
                pf.update_xaxes(title="גיל")
                st.plotly_chart(style_fig(pf), width="stretch", theme="streamlit", key="chart_8")
                c1, c2 = st.columns(2)
                c1.metric(f"צבירה משוערת בגיל {cfg.retirement_age}", ils(mine.iloc[-1]))
                c2.metric("עלות דמי הניהול לאורך התקופה", ils(nofee.iloc[-1] - mine.iloc[-1]))
                st.caption("הערכה בלבד: תשואה קבועה, הפקדות קבועות, ללא אינפלציה, מיסוי ושינויי שכר. "
                           "אינה תחזית ואינה מבטיחה דבר.")

        for r in assets[assets["type"] == S.ASSET_HISHTALMUT].itertuples():
            if pd.notna(r.liquidity_date):
                state = "נזילה" if r.liquidity_date <= today else f"נזילה ב-{r.liquidity_date:%d/%m/%Y}"
                st.caption(f"קרן השתלמות '{r.name}': {state}")

# --- Recommendations ------------------------------------------------------------------

with tabs[4]:
    st.warning("ההמלצות נוצרות אוטומטית מכללים פשוטים ומהנתונים שהוזנו. הן אינן ייעוץ השקעות, "
               "פנסיוני או מס, ואינן מחליפות בעל רישיון.", icon="⚠️")
    if not recs:
        st.info("אין המלצות כרגע.")
    for r in recs:
        show_rec(r)
