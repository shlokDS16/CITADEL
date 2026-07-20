"""
Indian bank-narration normalisation + curated merchant lexicon.

Why a lexicon and not a model: transaction strings are 3-6 tokens of
abbreviated, rail-prefixed noise ("UPI-SWIGGY-swiggy@ybl-INB",
"POS/BESCOM/BANGALORE"). The industry answer — Plaid's enrichment engine,
and every Indian SMS-parser app — is a merchant knowledge base matched
with fuzzy string logic, with ML only filling coverage gaps. A lexicon hit
is exact, explainable, sub-millisecond, and correctable by a human the
moment it is wrong. `categorize.py` layers the ML fallback on top.

Everything here is pure string work: no I/O, no model, no DB.
"""
from __future__ import annotations

import re

CATEGORIES: tuple[str, ...] = (
    "Food & Dining", "Groceries", "Transport", "Utilities", "Healthcare",
    "Shopping", "Education", "Entertainment", "Housing", "Insurance", "Other",
)

# --------------------------------------------------------------------------
# Narration normalisation
# --------------------------------------------------------------------------
# Payment rails / instrument prefixes Indian banks stamp onto the narration.
_RAILS = (
    "upi", "pos", "neft", "rtgs", "imps", "ach", "ecs", "nach", "atm", "chq",
    "tfr", "mmt", "inf", "bil", "vps", "mps", "eft", "cms", "onl", "int",
    "dr", "cr", "debit", "credit", "wdl", "txn", "ref", "rrn", "trf", "pmt",
)
# Corporate/geographic filler that never disambiguates a merchant.
_NOISE = (
    "ltd", "limited", "pvt", "private", "india", "indian", "in", "inb", "co",
    "company", "corp", "services", "service", "solutions", "technologies",
    "enterprises", "store", "stores", "retail", "payment", "payments", "pay",
    "online", "merchant", "purchase", "bangalore", "bengaluru", "mumbai",
    "delhi", "chennai", "hyderabad", "pune", "kolkata", "gurgaon", "noida",
)
_UPI_HANDLE = re.compile(r"@[a-z0-9.\-_]+")
_LONG_NUM = re.compile(r"\b\d{4,}\b")           # refs, account/card fragments
_DATEISH = re.compile(r"\b\d{1,2}[-/]\d{1,2}([-/]\d{2,4})?\b")
_NON_ALNUM = re.compile(r"[^a-z0-9\s&]+")
_WS = re.compile(r"\s+")


def normalize(raw: str) -> str:
    """Reduce a bank narration to a comparable merchant phrase.

    ``"UPI-SWIGGY-swiggy@ybl-INB"`` -> ``"swiggy"``
    ``"POS/BESCOM/BANGALORE"``      -> ``"bescom"``
    ``"NEFT DR ZOMATO LTD"``        -> ``"zomato"``
    """
    if not raw:
        return ""
    s = raw.lower()
    s = _UPI_HANDLE.sub(" ", s)          # drop @ybl / @okhdfcbank
    s = _DATEISH.sub(" ", s)
    s = _NON_ALNUM.sub(" ", s)           # separators -> space, keep '&'
    s = _LONG_NUM.sub(" ", s)
    toks = [t for t in _WS.split(s) if t]
    # Strip rails only while they lead; a rail word deeper in the string is
    # more likely part of the real name (e.g. "credit union").
    while toks and toks[0] in _RAILS:
        toks.pop(0)
    # A bare numeric token is a reference/branch code, never a merchant name.
    toks = [t for t in toks
            if t not in _RAILS and t not in _NOISE and len(t) > 1
            and not t.isdigit()]
    # Collapse repeats: a UPI narration usually names the merchant twice (once
    # plainly, once inside the VPA), so "SWIGGY ... swiggy@ybl" would otherwise
    # key as "swiggy swiggy" and miss the cache entry made by "SWIGGY LTD".
    seen: set[str] = set()
    uniq = [t for t in toks if not (t in seen or seen.add(t))]
    return " ".join(uniq).strip()


def merchant_key(raw: str) -> str:
    """Stable cache key for a merchant. Distinct narrations that mean the
    same merchant collapse to the same key, so an LLM lookup or a human
    correction is spent once per merchant, not once per transaction."""
    n = normalize(raw)
    return n[:64] if n else "unknown"


# --------------------------------------------------------------------------
# Curated lexicon — substring/token patterns -> category.
# Ordered most-specific-first within each category; `Groceries` is listed
# before `Food & Dining` at match time because quick-commerce names would
# otherwise be swallowed by generic food tokens.
# --------------------------------------------------------------------------
LEXICON: dict[str, tuple[str, ...]] = {
    "Groceries": (
        "bigbasket", "big basket", "blinkit", "grofers", "zepto", "instamart",
        "jiomart", "dmart", "d mart", "avenue supermart", "more retail",
        "reliance fresh", "reliance smart", "spencers", "nature basket",
        "star bazaar", "licious", "freshtohome", "country delight",
        "milkbasket", "amul", "mother dairy", "kirana", "supermarket",
        "provision", "vegetable", "grocery",
    ),
    "Food & Dining": (
        "swiggy", "zomato", "dominos", "domino", "pizza hut", "mcdonald",
        "kfc", "burger king", "starbucks", "cafe coffee day", "ccd",
        "barista", "chaayos", "third wave", "blue tokai", "subway",
        "taco bell", "wow momo", "haldiram", "bikanervala", "faasos",
        "behrouz", "ovenstory", "eatfit", "box8", "freshmenu", "biryani",
        "restaurant", "resto", "cafe", "coffee", "dhaba", "bakery",
        "sweets", "food", "eatery", "kitchen", "canteen", "juice",
    ),
    "Transport": (
        "uber", "ola cabs", "olacabs", "ola money", "rapido", "meru",
        "blusmart", "yulu", "bounce", "vogo", "namma metro", "dmrc",
        "metro rail", "bmtc", "ksrtc", "msrtc", "tsrtc", "apsrtc",
        "irctc", "indian railway", "redbus", "abhibus", "indigo",
        "spicejet", "air india", "vistara", "akasa", "goair", "petrol",
        "hp petro", "hpcl", "iocl", "indian oil", "bharat petroleum",
        "bpcl", "shell", "nayara", "fuel", "fastag", "toll", "parking",
        "cab", "taxi", "auto rickshaw",
    ),
    "Utilities": (
        "bescom", "mseb", "msedcl", "tneb", "tangedco", "kseb", "cesc",
        "adani electricity", "tata power", "torrent power", "bses",
        "electricity", "powergrid", "bwssb", "delhi jal", "jal board",
        "water board", "gail", "indane", "hp gas", "bharat gas", "lpg",
        "jio", "airtel", "vodafone", "vi recharge", "bsnl", "mtnl",
        "act fibernet", "hathway", "tikona", "excitel", "broadband",
        "tata sky", "tata play", "dish tv", "sun direct", "d2h",
        "recharge", "postpaid", "prepaid", "gas bill", "municipal tax",
    ),
    "Healthcare": (
        "apollo", "pharmeasy", "1mg", "tata 1mg", "netmeds", "medplus",
        "wellness forever", "practo", "fortis", "manipal", "narayana",
        "aster", "max healthcare", "medanta", "cloudnine", "lal path",
        "dr lal", "srl diagnostic", "metropolis", "thyrocare", "redcliffe",
        "pharmacy", "chemist", "hospital", "clinic", "diagnostic",
        "pathology", "medical", "dental", "optical", "doctor", "medicine",
    ),
    "Shopping": (
        "amazon", "flipkart", "myntra", "ajio", "nykaa", "meesho",
        "tata cliq", "snapdeal", "croma", "reliance digital", "vijay sales",
        "decathlon", "ikea", "pepperfry", "urban ladder", "wakefit",
        "lenskart", "titan", "tanishq", "caratlane", "westside",
        "lifestyle", "shoppers stop", "pantaloons", "max fashion", "zara",
        "uniqlo", "bata", "puma", "adidas", "nike", "skechers", "levis",
        "firstcry", "boat", "apple store", "samsung",
    ),
    "Education": (
        "byju", "unacademy", "vedantu", "coursera", "udemy", "upgrad",
        "simplilearn", "great learning", "whitehat", "cuemath", "scaler",
        "newton school", "physics wallah", "aakash", "allen career",
        "school fee", "college fee", "tuition", "university", "institute",
        "academy", "coaching", "exam fee", "admission",
    ),
    "Entertainment": (
        "netflix", "prime video", "hotstar", "disney", "sony liv", "zee5",
        "jiocinema", "jiohotstar", "spotify", "gaana", "wynk", "saavn",
        "youtube premium", "bookmyshow", "district", "pvr", "inox",
        "cinepolis", "carnival cinema", "steam games", "playstation",
        "xbox", "nintendo", "cinema", "multiplex", "movie", "concert",
        "gaming", "subscription",
    ),
    "Housing": (
        "rent", "house rent", "maintenance", "society", "apartment",
        "nobroker", "magicbricks", "99acres", "housing com", "urban company",
        "urbanclap", "home loan", "housing loan", "property tax",
        "packers", "movers", "interior", "carpenter", "plumber",
        "electrician", "housekeeping",
    ),
    "Insurance": (
        "lic ", "life insurance corp", "hdfc life", "icici prudential",
        "sbi life", "max life", "bajaj allianz", "tata aig", "star health",
        "care health", "niva bupa", "religare health", "acko", "go digit",
        "policybazaar", "insurance", "premium payment", "mediclaim",
    ),
}

# Longest patterns first so "pizza hut" wins over "pizza", and quick-commerce
# grocery names are tested before generic food tokens.
_CATEGORY_ORDER = (
    "Groceries", "Food & Dining", "Transport", "Utilities", "Healthcare",
    "Shopping", "Education", "Entertainment", "Housing", "Insurance",
)
_FLAT: list[tuple[str, str]] = sorted(
    ((pat, cat) for cat in _CATEGORY_ORDER for pat in LEXICON[cat]),
    key=lambda pc: -len(pc[0]),
)


def lexicon_lookup(narration: str) -> tuple[str, float] | None:
    """Exact/substring lexicon match on the normalised narration.

    Returns ``(category, confidence)`` or ``None``. Confidence reflects how
    much of the phrase the pattern explains — a whole-string match is far
    stronger evidence than a generic token buried in a long narration.
    """
    n = normalize(narration)
    if not n:
        return None
    padded = f" {n} "
    for pat, cat in _FLAT:
        if pat in padded or pat in n:
            if n == pat:
                return cat, 0.99
            # token-boundary hit scores higher than a raw substring
            conf = 0.95 if f" {pat} " in padded else 0.88
            return cat, conf
    return None


def fuzzy_lookup(narration: str, min_score: float = 88.0) -> tuple[str, float] | None:
    """Fuzzy lexicon match — catches typos/truncations the exact pass misses
    ("swiggyy", "zomato bangalor"). Uses rapidfuzz partial-ratio against the
    pattern list; deliberately strict so it doesn't invent matches."""
    n = normalize(narration)
    if not n or len(n) < 4:
        return None
    try:
        from rapidfuzz import fuzz, process
    except ImportError:  # pragma: no cover - dependency is declared
        return None
    pats = [p for p, _ in _FLAT]
    hit = process.extractOne(n, pats, scorer=fuzz.partial_ratio,
                             score_cutoff=min_score)
    if not hit:
        return None
    pat, score, idx = hit
    return _FLAT[idx][1], round(min(0.90, score / 100.0), 4)
