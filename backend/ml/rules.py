"""
A transparent keyword baseline. The ML model has to beat this to justify its complexity.
Keywords were written from general knowledge of common merchants, not tuned on the test split.
"""
from backend.ml.text import DIRECTION_CREDIT

UNCATEGORIZED = "Uncategorized"

# Order matters: the first category with a matching keyword wins.
KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Income", ("payroll", "direct dep", "salary", "paycheck", "interest paid", "dividend")),
    ("Mortgage", ("mortgage", "mtg pmt", "home loan", "principal pmt")),
    ("Rent", ("rent", "apartment", "property mgmt", "leasing")),
    ("Insurance", ("insurance", "geico", "state farm", "allstate", "progressive", "mutual", "assurance")),
    ("Subscription", ("netflix", "spotify", "hulu", "disney", "apple tv", "subscription", "membership", "prime video", "youtube")),
    ("Utilities", ("electric", "water", "gas co", "utility", "utilities", "internet", "comcast", "verizon", "at t ", "mobile", "waste", "power")),
    ("Healthcare", ("pharmacy", "cvs", "walgreens", "dental", "dentist", "clinic", "hospital", "medical", "health", "doctor", "urgent care")),
    ("Education", ("tuition", "university", "college", "school", "course", "udemy", "coursera", "textbook", "learning")),
    ("Travel", ("airlines", "airline", "hotel", "airbnb", "delta", "united air", "marriott", "hilton", "expedia", "booking", "resort")),
    ("Transportation", ("uber", "lyft", "shell", "chevron", "exxon", "fuel", "parking", "transit", "metro", "toll", "taxi", "gas station")),
    ("Groceries", ("grocery", "supermarket", "kroger", "safeway", "whole foods", "trader joe", "aldi", "publix", "costco", "market")),
    ("Restaurants", ("restaurant", "cafe", "coffee", "starbucks", "mcdonald", "pizza", "burger", "grill", "diner", "bar ", "kitchen", "doordash", "grubhub")),
    ("Entertainment", ("cinema", "theater", "theatre", "movie", "concert", "ticket", "game", "bowling", "casino", "bet")),
    ("Personal Care", ("salon", "spa", "barber", "beauty", "sephora", "ulta", "cosmetic", "nail")),
    ("Fees", ("fee", "overdraft", "nsf", "service charge", "penalty", "atm")),
    ("Transfer", ("transfer", "zelle", "venmo", "cash app", "payment thank you", "xfer")),
    ("Shopping", ("amazon", "walmart", "target", "ebay", "store", "shop", "mall", "best buy", "apple store", "etsy")),
]


def classify_with_rules(normalized_text: str) -> str:
    """Return the first matching category for normalized text (see text.normalize_description)."""
    padded = f" {normalized_text} "
    if f"dir_{DIRECTION_CREDIT}" in normalized_text and any(k in padded for k in ("payroll", "direct dep", "salary")):
        return "Income"
    for category, words in KEYWORDS:
        if any(word in padded for word in words):
            return category
    return UNCATEGORIZED
