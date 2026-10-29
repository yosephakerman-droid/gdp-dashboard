"""Column names, account/asset types and categories used across the app."""

# --- Accounts (source of a transaction) -------------------------------------
ACCOUNT_BANK = 'עו"ש'
ACCOUNT_CREDIT = "אשראי"

# --- Asset / liability types -------------------------------------------------
ASSET_CHECKING = 'עו"ש'
ASSET_DEPOSIT = "פיקדון/חיסכון"
ASSET_INVESTMENTS = "השקעות"
ASSET_HISHTALMUT = "קרן השתלמות"
ASSET_PENSION = "פנסיה"
ASSET_GEMEL = "קופת גמל"
ASSET_POLICY = "פוליסת ביטוח/חיסכון"
ASSET_LOAN = "הלוואה"

ASSET_TYPES = [
    ASSET_CHECKING,
    ASSET_DEPOSIT,
    ASSET_INVESTMENTS,
    ASSET_HISHTALMUT,
    ASSET_PENSION,
    ASSET_GEMEL,
    ASSET_POLICY,
    ASSET_LOAN,
]

# Long-term savings products (pension-like).
LONG_TERM_TYPES = [ASSET_PENSION, ASSET_GEMEL, ASSET_POLICY, ASSET_HISHTALMUT]

# --- Transaction columns -----------------------------------------------------
TX_COLUMNS = ["date", "description", "amount", "account", "category"]

TX_LABELS = {
    "date": "תאריך",
    "description": "תיאור",
    "amount": "סכום",
    "account": "חשבון",
    "category": "קטגוריה",
    "kind": "סוג",
    "month": "חודש",
}

# --- Asset columns -----------------------------------------------------------
ASSET_COLUMNS = [
    "name",
    "type",
    "provider",
    "balance",
    "monthly_deposit",
    "fee_balance_pct",
    "fee_deposit_pct",
    "annual_return_pct",
    "liquidity_date",
]

ASSET_LABELS = {
    "name": "שם",
    "type": "סוג",
    "provider": "גוף מנהל",
    "balance": "יתרה",
    "monthly_deposit": "הפקדה חודשית",
    "fee_balance_pct": "דמי ניהול מצבירה %",
    "fee_deposit_pct": "דמי ניהול מהפקדה %",
    "annual_return_pct": "תשואה שנתית / ריבית %",
    "liquidity_date": "תאריך נזילות",
}

# --- Transaction kinds -------------------------------------------------------
KIND_INCOME = "הכנסה"
KIND_EXPENSE = "הוצאה"
KIND_SAVING = "חיסכון"
KIND_INTERNAL = "פנימי (לא נספר)"

# --- Categories --------------------------------------------------------------
CAT_SALARY = "משכורת"
CAT_OTHER_INCOME = "הכנסה אחרת"
CAT_SAVINGS = "חיסכון והשקעות"
CAT_CARD_BILL = "חיוב כרטיס אשראי"
CAT_BANK_FEES = "עמלות וריביות בנק"
CAT_SUBSCRIPTIONS = "מנויים"
CAT_CARD_UNITEMIZED = "אשראי לא מפורט"
CAT_DONATIONS = "תרומות"
CAT_HOME = "בית ושיפוץ"
CAT_TAXES = "מסים ואגרות"
CAT_OTHER = "אחר"

# Order matters: the first category whose keyword appears in the description
# wins. More specific keywords must come before generic ones.
CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    (CAT_SALARY, ["משכורת", "שכר עבודה", "salary"]),
    (CAT_OTHER_INCOME, ["ביטוח לאומי", "ריבית זכות", "החזר מס", "דיבידנד"]),
    (CAT_BANK_FEES, ["ריבית חובה", "עמלת", "עמלה", "דמי ניהול חשבון", "דמי כרטיס"]),
    (CAT_CARD_BILL, ["ישראכרט", "כאל", "מקס איט", "max", "לאומי קארד", "אמריקן אקספרס",
                     "דיינרס", "חיוב כרטיס", "ויזה", "כרטיסי אשראי לי", "פרימיום אקספרס"]),
    (CAT_SAVINGS, ["העברה להשקעות", "הפקדה לקרן", "הפקדה לפיקדון", "פיקדון",
                   "קופת גמל להשקעה", "תיק השקעות", "ברוקר", "interactive", "אינטראקטיב",
                   "אקסלנס", "הכשרה חב' לביטו"]),
    ("דיור", ["שכר דירה", "שכירות", "משכנתא", "ארנונה", "ועד בית", "מ.מ", "מועצה מקומית", "עירייה", "עיריית"]),
    ("חשבונות בית", ["חברת חשמל", "חשמל", "תאגיד מים", "מי ההר", "מקורות", "בזק", "פרטנר",
                     "סלקום", "הוט", "hot", "yes", "גולן טלקום", "פלאפון", "סופרגז", "אמישראגז"]),
    ("בריאות", ["מכבי", "כללית", "מאוחדת", "לאומית", "סופר-פארם", "סופר פארם",
                "בית מרקחת", "רופא", "שיניים"]),
    ("ביטוחים", ["ביטוח", "הראל", "מגדל", "הפניקס", "מנורה", "איילון", "כלל "]),
    ("מזון וסופר", ["שופרסל", "רמי לוי", "ויקטורי", "יוחננוף", "מגה", "טיב טעם", "אושר עד",
                    "חצי חינם", "סופר", "מכולת", "am:pm", "קרפור", "carrefour"]),
    ("מסעדות ובתי קפה", ["מסעדה", "מסעדת", "קפה", "ארומה", "וולט", "wolt", "תן ביס", "10bis",
                         "מקדונלד", "פיצה", "בורגר", "סושי"]),
    ("תחבורה ורכב", ["דלק", "סונול", "פז ", "דור אלון", "רב קו", "רב-קו", "רכבת", "gett",
                     "yango", "חניה", "פנגו", "סלופארק", "טסט", "מוסך", "כביש 6"]),
    (CAT_SUBSCRIPTIONS, ["netflix", "spotify", "apple.com", "icloud", "google", "disney",
                         "openai", "chatgpt", "youtube", "amazon prime", "חדר כושר"]),
    ("חינוך וילדים", ["גן ילדים", "צהרון", "בית ספר", "חוג", "אוניברסיטה", "מכללה", "ישיבה", "תלמוד תורה"]),
    ("קניות", ["amazon", "aliexpress", "זארה", "zara", "h&m", "קסטרו", "fox", "איקאה",
               "ikea", "ksp", "באג", "שיין", "shein", "עזריאלי"]),
    ("פנאי ונופש", ["סינמה", "קולנוע", "יס פלאנט", "הופעה", "טיסה", "אל על", "booking",
                    "airbnb", "מלון"]),
    (CAT_TAXES, ["מס הכנסה", "מע\"מ", "אגרה", "רשות המסים"]),
    (CAT_DONATIONS, ["עמותה", "(ע\"ר)", "(ע.ר)", "עגול לטובה", "עיגול לטובה", "תרומה"]),
    (CAT_HOME, ["קרמיקה", "שיפוץ", "אינסטלציה", "תאורה", "חומרי בניין", "רהיט"]),
    ("משיכת מזומן", ["כספומט", "משיכת מזומן", "משיכה מבנקט"]),
    ("העברות", ["bit", "ביט", "פייבוקס", "paybox", "העברה"]),
]

ALL_CATEGORIES = [c for c, _ in CATEGORY_KEYWORDS] + [CAT_CARD_UNITEMIZED, CAT_OTHER]

# --- Column aliases for uploaded files --------------------------------------
# Lower-cased header text -> canonical column. Covers common Hebrew export
# headers; anything else can be renamed to the template headers by hand.
COLUMN_ALIASES = {
    "date": ["date", "תאריך", "תאריך עסקה", "תאריך רכישה", "תאריך ערך", "תאריך התנועה",
             "תאריך פעולה"],
    "description": ["description", "תיאור", "שם בית העסק", "שם בית עסק", "בית עסק",
                    "פרטים", "תיאור התנועה", "תאור", "הפעולה"],
    "amount": ["amount", "סכום", "סכום חיוב", "סכום החיוב", "סכום עסקה", "סכום העסקה",
               "סכום בש\"ח", "סכום בשח"],
    "debit": ["debit", "חובה", "בחובה"],
    "credit": ["credit", "זכות", "בזכות"],
    "account": ["account", "חשבון", "מקור"],
    "category": ["category", "קטגוריה", "ענף"],
}
