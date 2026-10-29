"""Personal finance dashboard: cash flow, breakdowns, savings and suggestions."""

import hashlib
import json
from dataclasses import asdict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_js_eval import streamlit_js_eval

from finance import analysis as A
from finance import loader as L
from finance import recommendations as R
from finance import schema as S
from finance import store as STORE

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


# --- Saved data ----------------------------------------------------------------
# "My data" lives in session state and is mirrored to the browser's
# localStorage, so it survives a refresh and never leaves the viewer's device
# (Streamlit's server only holds it in memory while the page is open).

SAMPLE, MINE = "נתוני דוגמה (פיקטיביים)", "הנתונים שלי"
STORAGE_KEY = "personal-finance-dashboard"
ss = st.session_state
ss.setdefault("ingested", set())
ss.setdefault("upload_log", [])

SETTING_FIELDS = [  # field, label, min, max, step, kind
    ("age", "גיל", 18, 90, 1, "number"),
    ("retirement_age", "גיל פרישה מתוכנן", 50, 90, 1, "number"),
    ("emergency_months", "קרן חירום (חודשי הוצאה)", 1.0, 12.0, 0.5, "slider"),
    ("savings_rate_target", "יעד שיעור חיסכון", 0.0, 0.5, 0.01, "slider"),
    ("max_pension_fee_balance", "סף דמי ניהול פנסיה/גמל מצבירה %", 0.0, 2.0, 0.05, "number"),
    ("max_pension_fee_deposit", "סף דמי ניהול פנסיה מהפקדה %", 0.0, 6.0, 0.1, "number"),
    ("max_hishtalmut_fee", "סף דמי ניהול קרן השתלמות %", 0.0, 2.0, 0.05, "number"),
    ("max_investment_fee", "סף דמי ניהול תיק השקעות %", 0.0, 2.0, 0.05, "number"),
    ("expected_return", "תשואה שנתית צפויה לתחזיות %", 0.0, 15.0, 0.5, "number"),
]
for field, *_ in SETTING_FIELDS:
    ss.setdefault(f"cfg_{field}", getattr(R.Settings(), field))


def apply_settings(saved: dict):
    for field, _, lo, hi, _, _ in SETTING_FIELDS:
        v = saved.get(field)
        if isinstance(v, (int, float)) and lo <= v <= hi:
            ss[f"cfg_{field}"] = type(getattr(R.Settings(), field))(v)


def get_store(name: str) -> dict:
    if name not in ss:
        if name == SAMPLE:
            tx, a = L.load_sample()
            ss[name] = {"tx": STORE.clean_transactions(tx), "assets": STORE.clean_assets(a), "ver": 0}
        else:
            ss[name] = {"tx": STORE.empty_transactions(), "assets": STORE.empty_assets(), "ver": 0}
    return ss[name]


def load_from_browser(store: dict):
    """Read saved data once per session. The first call returns None while the
    browser answers; the component then reruns the script with the value."""
    if ss.get("browser_loaded"):
        return
    raw = streamlit_js_eval(js_expressions=f"localStorage.getItem('{STORAGE_KEY}') ?? ''", key="ls_load")
    if raw is None:
        st.caption("טוען נתונים שמורים מהדפדפן…")
        return
    ss.browser_loaded = True
    ss.saved_json = raw
    if raw:
        try:
            store["tx"], store["assets"], saved_cfg = STORE.from_json(raw)
            apply_settings(saved_cfg)
            store["ver"] += 1
        except ValueError:
            ss.upload_log = [("error", "הנתונים השמורים בדפדפן לא נקראו. אפשר לשחזר מקובץ גיבוי.")]


def save_to_browser(store: dict, cfg: R.Settings):
    if not ss.get("browser_loaded"):
        return  # never overwrite saved data before it was read
    payload = STORE.to_json(store["tx"], store["assets"], asdict(cfg))
    if payload == ss.get("saved_json"):
        return
    digest = hashlib.md5(payload.encode()).hexdigest()[:12]
    streamlit_js_eval(js_expressions=f"localStorage.setItem('{STORAGE_KEY}', {json.dumps(payload)}); true",
                      key=f"ls_save_{digest}")
    ss.saved_json = payload


def ingest_uploads(store: dict, bank_files, credit_files, assets_file, backup_file):
    """Add each uploaded file to the saved data once."""
    new_log = []
    for files, source in ((bank_files, S.ACCOUNT_BANK), (credit_files, S.ACCOUNT_CREDIT)):
        for f in files or []:
            if f.file_id in ss.ingested:
                continue
            ss.ingested.add(f.file_id)
            try:
                store["tx"], added = STORE.merge_transactions(store["tx"], L.read_transactions(f, f.name, source))
                new_log.append(("success", f"{f.name}: נוספו {added} תנועות"
                                + ("" if added else " (כולן כבר שמורות)")))
            except Exception as e:  # show the problem, keep going with other files
                new_log.append(("error", f"{f.name}: {e}"))
    if assets_file and assets_file.file_id not in ss.ingested:
        ss.ingested.add(assets_file.file_id)
        try:
            new_assets = L.read_assets(assets_file, assets_file.name)
            store["assets"] = STORE.merge_assets(store["assets"], new_assets)
            new_log.append(("success", f"{assets_file.name}: עודכנו {len(new_assets)} נכסים"))
        except Exception as e:
            new_log.append(("error", f"{assets_file.name}: {e}"))
    if backup_file and backup_file.file_id not in ss.ingested:
        ss.ingested.add(backup_file.file_id)
        try:
            store["tx"], store["assets"], saved_cfg = STORE.from_json(backup_file.getvalue().decode("utf-8"))
            apply_settings(saved_cfg)
            new_log.append(("success", "הגיבוי שוחזר"))
        except (ValueError, UnicodeDecodeError) as e:
            new_log.append(("error", f"{backup_file.name}: {e}"))
    if new_log:
        store["ver"] += 1
        ss.upload_log = new_log


def editor_changed(key: str) -> bool:
    state = ss.get(key) or {}
    return any(state.get(k) for k in ("edited_rows", "added_rows", "deleted_rows"))


# --- Sidebar: data and settings ---------------------------------------------

with st.sidebar:
    st.header("נתונים")
    mode = st.radio("מקור", [MINE, SAMPLE], label_visibility="collapsed", key="mode")
    store = get_store(mode)

    if mode == SAMPLE:
        st.caption("כל הנתונים במצב זה מומצאים, להמחשה בלבד. שינויים כאן אינם נשמרים.")
    else:
        load_from_browser(store)
        st.caption("הנתונים נשמרים בדפדפן במכשיר הזה בלבד ונשארים אחרי רענון. "
                   "קבצים חדשים מתווספים לשמורים; תנועה שכבר קיימת לא תיכנס פעמיים.")
        bank_files = st.file_uploader('קובצי עו"ש (CSV / Excel)', type=["csv", "xlsx", "xls"],
                                      accept_multiple_files=True)
        credit_files = st.file_uploader("קובצי כרטיסי אשראי", type=["csv", "xlsx", "xls"],
                                        accept_multiple_files=True,
                                        help="חיובים מופיעים בקובץ כמספר חיובי; המערכת הופכת אותם להוצאה.")
        assets_file = st.file_uploader("נכסים, חסכונות והלוואות", type=["csv", "xlsx", "xls"],
                                       help="נכס עם שם שכבר קיים יתעדכן; נכס חדש יתווסף.")
        with st.expander("גיבוי, שחזור ומחיקה", key="exp_backup"):
            st.caption("קובץ גיבוי מאפשר להעביר את הנתונים למכשיר או לדפדפן אחר.")
            backup_file = st.file_uploader("שחזור מקובץ גיבוי (מחליף את הנתונים השמורים)", type=["json"])
            ingest_uploads(store, bank_files, credit_files, assets_file, backup_file)
            st.download_button("הורדת קובץ גיבוי",
                               STORE.to_json(store["tx"], store["assets"],
                                             {f: ss[f"cfg_{f}"] for f, *_ in SETTING_FIELDS}).encode("utf-8"),
                               "finance_backup.json", "application/json", on_click="ignore")
            confirm = st.checkbox("אני רוצה למחוק את כל הנתונים השמורים")
            if st.button("מחיקת כל הנתונים", disabled=not confirm, type="primary"):
                store.update(tx=STORE.empty_transactions(), assets=STORE.empty_assets(), ver=store["ver"] + 1)
                ss.upload_log = [("success", "כל הנתונים נמחקו")]
        for level, msg in ss.upload_log:
            (st.success if level == "success" else st.error)(msg)
        c1, c2 = st.columns(2)
        c1.download_button("תבנית תנועות", L.template_transactions_csv(), "transactions_template.csv", "text/csv", on_click="ignore")
        c2.download_button("תבנית נכסים", L.template_assets_csv(), "assets_template.csv", "text/csv", on_click="ignore")

    st.header("הגדרות")
    with st.expander("פרופיל וספים להמלצות", key="exp_settings"):
        st.caption("ברירות המחדל הן כללי אצבע שבחרתי, לא נתון רשמי. שנה לפי שיקול דעתך.")
        for field, label, lo, hi, step, kind in SETTING_FIELDS:
            widget = st.slider if kind == "slider" else st.number_input
            widget(label, min_value=lo, max_value=hi, step=step, key=f"cfg_{field}")
        cfg = R.Settings(**{f: ss[f"cfg_{f}"] for f, *_ in SETTING_FIELDS})

st.title("ניתוח פיננסי אישי")
tabs = st.tabs(["סקירה", "הכנסות מול הוצאות", "פילוחים", "נכסים וחיסכון", "המלצות", "נתונים ועריכה"])

# --- Data tab first, so edits apply to every other tab -----------------------

AUTO_CATEGORY = "סיווג אוטומטי"

with tabs[5]:
    st.subheader("תנועות")
    with st.expander("➕ הוספת תנועה", key="exp_add_tx"):
        with st.form("add_tx", clear_on_submit=True):
            c1, c2 = st.columns(2)
            f_date = c1.date_input("תאריך", value="today", format="DD/MM/YYYY")
            f_kind = c2.radio("סוג", ["הוצאה", "הכנסה"], horizontal=True)
            f_desc = st.text_input("תיאור", placeholder="למשל: שופרסל, משכורת")
            c1, c2 = st.columns(2)
            f_amount = c1.number_input("סכום (₪)", min_value=0.0, step=10.0, format="%.2f")
            f_account = c2.selectbox("חשבון", [S.ACCOUNT_BANK, S.ACCOUNT_CREDIT])
            f_cat = st.selectbox("קטגוריה", [AUTO_CATEGORY] + S.ALL_CATEGORIES)
            if st.form_submit_button("הוספה", type="primary"):
                if not f_desc.strip() or f_amount <= 0:
                    st.error("צריך תיאור וסכום גדול מאפס.")
                else:
                    row = pd.DataFrame([[pd.Timestamp(f_date), f_desc.strip(),
                                         -f_amount if f_kind == "הוצאה" else f_amount, f_account,
                                         None if f_cat == AUTO_CATEGORY else f_cat]], columns=S.TX_COLUMNS)
                    store.update(tx=STORE.clean_transactions(pd.concat([store["tx"], row], ignore_index=True)),
                                 ver=store["ver"] + 1)
                    st.toast("התנועה נוספה")
    st.caption("עריכה: לחיצה כפולה על תא. מחיקה: סימון השורה בצד ובסמל הפח. "
               "קטגוריה ריקה תסווג אוטומטית. בהוצאה הסכום שלילי.")
    tx_key = f"tx_editor-{mode}-{store['ver']}"
    tx_edit = st.data_editor(
        store["tx"],
        key=tx_key,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={
            "date": st.column_config.DateColumn(S.TX_LABELS["date"], format="DD/MM/YYYY", required=True),
            "description": st.column_config.TextColumn(S.TX_LABELS["description"], required=True),
            "amount": st.column_config.NumberColumn(S.TX_LABELS["amount"], format="localized", required=True),
            "account": st.column_config.SelectboxColumn(S.TX_LABELS["account"],
                                                        options=[S.ACCOUNT_BANK, S.ACCOUNT_CREDIT],
                                                        default=S.ACCOUNT_BANK),
            "category": st.column_config.SelectboxColumn(
                S.TX_LABELS["category"],
                options=sorted(set(S.ALL_CATEGORIES) | set(store["tx"]["category"].dropna())),
            ),
        },
    )
    if editor_changed(tx_key):
        incomplete = (tx_edit["date"].isna() | tx_edit["amount"].isna()
                      | tx_edit["description"].fillna("").astype(str).str.strip().eq(""))
        if incomplete.any():
            st.caption("השלם תאריך, תיאור וסכום בשורה כדי לשמור.")
        else:
            store.update(tx=STORE.clean_transactions(tx_edit), ver=store["ver"] + 1)
            st.rerun()

    st.subheader("נכסים, חסכונות והלוואות")
    with st.expander("➕ הוספת נכס או הלוואה", key="exp_add_asset"):
        with st.form("add_asset", clear_on_submit=True):
            c1, c2 = st.columns(2)
            a_name = c1.text_input("שם", placeholder="למשל: פנסיה מקיפה")
            a_type = c2.selectbox("סוג", S.ASSET_TYPES)
            a_provider = st.text_input("גוף מנהל (לא חובה)")
            c1, c2 = st.columns(2)
            a_balance = c1.number_input("יתרה (₪) – בהלוואה: יתרת החוב", min_value=0.0, step=1000.0)
            a_deposit = c2.number_input("הפקדה חודשית (₪)", min_value=0.0, step=100.0)
            c1, c2, c3 = st.columns(3)
            a_fee_bal = c1.number_input("דמי ניהול מצבירה %", min_value=0.0, max_value=5.0, step=0.05)
            a_fee_dep = c2.number_input("דמי ניהול מהפקדה %", min_value=0.0, max_value=10.0, step=0.1)
            a_return = c3.number_input("תשואה / ריבית %", min_value=0.0, max_value=30.0, step=0.5)
            a_liq = st.date_input("תאריך נזילות (לקרן השתלמות, לא חובה)", value=None, format="DD/MM/YYYY")
            if st.form_submit_button("הוספה", type="primary"):
                if not a_name.strip():
                    st.error("צריך שם.")
                else:
                    row = pd.DataFrame([[a_name.strip(), a_type, a_provider, a_balance, a_deposit, a_fee_bal,
                                         a_fee_dep, a_return, a_liq]], columns=S.ASSET_COLUMNS)
                    store.update(assets=STORE.merge_assets(store["assets"], row), ver=store["ver"] + 1)
                    st.toast("הנכס נשמר (נכס בשם זהה מתעדכן)")
    st.caption("עריכה: לחיצה כפולה על תא. מחיקה: סימון השורה בצד ובסמל הפח. "
               "בהלוואה: 'יתרה' = יתרת החוב, 'תשואה/ריבית' = ריבית ההלוואה.")
    assets_key = f"assets_editor-{mode}-{store['ver']}"
    assets_edit = st.data_editor(
        store["assets"],
        key=assets_key,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={
            "name": st.column_config.TextColumn(S.ASSET_LABELS["name"], required=True),
            "type": st.column_config.SelectboxColumn(S.ASSET_LABELS["type"], options=S.ASSET_TYPES, required=True),
            "provider": S.ASSET_LABELS["provider"],
            "balance": st.column_config.NumberColumn(S.ASSET_LABELS["balance"], format="localized", default=0),
            "monthly_deposit": st.column_config.NumberColumn(S.ASSET_LABELS["monthly_deposit"], format="localized",
                                                             default=0),
            "fee_balance_pct": st.column_config.NumberColumn(S.ASSET_LABELS["fee_balance_pct"], format="%.2f",
                                                             default=0),
            "fee_deposit_pct": st.column_config.NumberColumn(S.ASSET_LABELS["fee_deposit_pct"], format="%.2f",
                                                             default=0),
            "annual_return_pct": st.column_config.NumberColumn(S.ASSET_LABELS["annual_return_pct"], format="%.2f",
                                                               default=0),
            "liquidity_date": st.column_config.DateColumn(S.ASSET_LABELS["liquidity_date"], format="DD/MM/YYYY"),
        },
    )
    if editor_changed(assets_key):
        incomplete = assets_edit["name"].fillna("").astype(str).str.strip().eq("") | assets_edit["type"].isna()
        if incomplete.any():
            st.caption("השלם שם וסוג בשורה כדי לשמור.")
        else:
            store.update(assets=STORE.clean_assets(assets_edit), ver=store["ver"] + 1)
            st.rerun()

assets = store["assets"]
if store["tx"].empty:
    all_tx = STORE.empty_transactions().assign(kind=pd.Series(dtype=object), month=pd.Series(dtype="datetime64[ns]"))
else:
    all_tx = A.prepare_transactions(store["tx"])
    export = all_tx[["date", "description", "amount", "account", "category", "kind"]].rename(columns=S.TX_LABELS)
    with tabs[5]:
        st.download_button("הורדת התנועות המסווגות (CSV)", export.to_csv(index=False).encode("utf-8-sig"),
                           "categorized_transactions.csv", "text/csv", on_click="ignore")

if mode == MINE:
    save_to_browser(store, cfg)

if all_tx.empty and assets.empty:
    with tabs[0]:
        st.info("אין עדיין נתונים. אפשר להעלות קובצי עו\"ש, אשראי ונכסים בסרגל הצדדי, "
                "להוסיף ידנית בלשונית 'נתונים ועריכה', או לבחור 'נתוני דוגמה' כדי לראות את המערכת.")

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
        if avg.one_off > 0:
            st.caption(f"מתוך ההוצאה החודשית, {ils(avg.one_off)} הם שיפוץ (חד-פעמי). "
                       f"ההוצאה הרגילה: {ils(avg.regular)} בחודש.")
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
