"""
Write data/sample_descriptions_only.csv: synthetic transactions with ONLY date, amount and description, so the
categorizer has to do the work. It includes a few hard cases (blank text, gibberish, ambiguous transfers, one-off
big purchases) so the Category review and Unusual transactions screens have something to show.

    python scripts/generate_description_only_sample.py
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(7)
OUT = Path(__file__).resolve().parents[1] / "data" / "sample_descriptions_only.csv"

# description, typical amount
ORDINARY = {
    "groceries": ([("WHOLE FOODS MKT 10234 AUSTIN TX", 82), ("KROGER #4402 AUSTIN TX", 64), ("TRADER JOE'S #512", 47), ("SAFEWAY #1822", 71), ("COSTCO WHSE #0452", 143)], 0.30),
    "food": ([("STARBUCKS #4821 SEATTLE WA", 6), ("CHIPOTLE 2291 AUSTIN TX", 13), ("MCDONALD'S F3321", 9), ("DOORDASH*PIZZA PLACE", 28), ("SQ *GREEN MARKET CAFE #403", 15)], 0.30),
    "transport": ([("SHELL OIL 57444 DALLAS TX", 44), ("UBER *TRIP HELP.UBER.COM", 19), ("CHEVRON 0098", 39), ("LYFT *RIDE SAT", 24)], 0.14),
    "shopping": ([("AMAZON.COM*2K4LP", 36), ("TARGET 00012345", 58), ("WALMART #5421", 42)], 0.14),
    "health": ([("CVS/PHARMACY #1822", 22), ("WALGREENS #3321", 18)], 0.04),
    "entertainment": ([("AMC THEATRES 0831", 31), ("STEAM PURCHASE", 20)], 0.04),
}
SUBSCRIPTIONS = [("NETFLIX.COM", 15.49), ("SPOTIFY USA", 10.99), ("HULU 877-8244858", 17.99)]
UTILITIES = [("COMCAST CABLE COMM", 79.99), ("VERIZON WIRELESS", 65.0), ("PG&E WEB ONLINE", 118.0)]

start, days = date(2025, 6, 1), 122
rows = []
for offset in range(days):
    day = start + timedelta(days=offset)
    for _ in range(random.choice([1, 2, 2, 3])):
        group = random.choices(list(ORDINARY), weights=[w for _, w in ORDINARY.values()])[0]
        description, typical = random.choice(ORDINARY[group][0])
        rows.append((day, round(typical * random.lognormvariate(0, 0.25), 2), description))
    if day.day == 1:
        rows.append((day, 1500.00, "AIMCO RENT PMT PPD ID: 4273027363"))
    if day.day in (1, 15):
        rows.append((day, -2400.00, "ACME PAYROLL PPD ID: 123456789"))
    if day.day == 5:
        rows += [(day, price, name) for name, price in SUBSCRIPTIONS]
    if day.day == 20:
        rows += [(day, round(price * random.uniform(0.9, 1.1), 2), name) for name, price in UTILITIES]

# hard cases the model cannot reliably categorize, and one-off big purchases
def on(offset: int) -> date:
    return start + timedelta(days=offset)

rows += [(on(12), 14.20, ""), (on(40), 9.99, ""), (on(75), 23.10, ""), (on(101), 31.00, "")]  # no description
rows += [(on(20), 33.00, "ZXQJ 8841 KLM"), (on(55), 18.50, "ZXQJ 8841 KLM"), (on(90), 27.00, "QRT 9921 PLM")]  # gibberish
rows += [(on(25), 60.00, "ACME CORP 2291"), (on(60), 45.00, "ACME CORP 2291"), (on(95), 52.00, "ACME CORP 2291")]  # unknown merchant
rows += [(on(30), 120.00, "ZELLE PAYMENT TO J SMITH"), (on(70), 200.00, "ZELLE PAYMENT TO J SMITH"), (on(100), 85.00, "VENMO PAYMENT")]  # transfers
rows += [(on(48), 1299.00, "BEST BUY #512"), (on(80), 640.00, "WHOLE FOODS MKT 10234 AUSTIN TX"), (on(110), 2150.00, "DELTA AIR LINES ATLANTA")]  # unusual

rows.sort(key=lambda r: (r[0], r[2]))
with open(OUT, "w", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["date", "amount", "description"])
    for day, amount, description in rows:
        writer.writerow([day.isoformat(), f"{amount:.2f}", description])
print(f"wrote {len(rows)} rows to {OUT}")
