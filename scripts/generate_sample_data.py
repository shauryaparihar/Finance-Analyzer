"""
Generate a realistic sample CSV dataset for testing the finance analyzer.
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CATEGORIES = {
    "Groceries": {
        "descriptions": [
            "Walmart grocery purchase", "Whole Foods Market", "Trader Joe's groceries",
            "Costco bulk buy", "Aldi supermarket", "Kroger weekly shopping",
            "Fresh produce market", "Target grocery run", "Safeway essentials",
            "Local farmer's market"
        ],
        "amount_range": (15, 200),
        "frequency_weight": 8,
    },
    "Rent": {
        "descriptions": [
            "Monthly apartment rent", "Rent payment", "Housing lease payment",
            "Apartment rental fee"
        ],
        "amount_range": (800, 2500),
        "frequency_weight": 1,  # once per month
        "monthly": True,
    },
    "Utilities": {
        "descriptions": [
            "Electric bill payment", "Water utility bill", "Gas company payment",
            "Internet service bill", "Phone bill", "Electricity monthly charge",
            "Comcast internet", "AT&T phone plan"
        ],
        "amount_range": (30, 250),
        "frequency_weight": 2,
    },
    "Entertainment": {
        "descriptions": [
            "Movie theater tickets", "Concert admission", "Bowling alley",
            "Video game purchase", "Streaming movie rental", "Theme park tickets",
            "Escape room experience", "Comedy show tickets", "Arcade gaming",
            "Museum admission"
        ],
        "amount_range": (10, 150),
        "frequency_weight": 4,
    },
    "Dining": {
        "descriptions": [
            "McDonald's meal", "Chipotle lunch", "Starbucks coffee",
            "Pizza Hut delivery", "Olive Garden dinner", "Sushi restaurant",
            "Thai food takeout", "Burger King drive-thru", "Local cafe breakfast",
            "Panda Express", "Domino's pizza order", "Taco Bell late night"
        ],
        "amount_range": (5, 80),
        "frequency_weight": 10,
    },
    "Transportation": {
        "descriptions": [
            "Uber ride", "Lyft trip", "Gas station fill-up", "Bus pass monthly",
            "Parking garage fee", "Toll road charge", "Car wash service",
            "Oil change service", "Train ticket", "Subway fare"
        ],
        "amount_range": (5, 100),
        "frequency_weight": 6,
    },
    "Healthcare": {
        "descriptions": [
            "Doctor visit copay", "Pharmacy prescription", "Dental checkup",
            "Eye exam appointment", "Lab work fees", "Urgent care visit",
            "CVS pharmacy", "Walgreens prescription", "Health insurance copay"
        ],
        "amount_range": (15, 500),
        "frequency_weight": 2,
    },
    "Shopping": {
        "descriptions": [
            "Amazon order", "Nike online purchase", "Best Buy electronics",
            "Home Depot supplies", "IKEA furniture", "Zara clothing",
            "Nordstrom apparel", "Etsy handmade item", "Apple Store accessory",
            "Target household items"
        ],
        "amount_range": (10, 300),
        "frequency_weight": 5,
    },
    "Subscriptions": {
        "descriptions": [
            "Netflix monthly subscription", "Spotify premium", "Amazon Prime renewal",
            "Gym membership fee", "YouTube Premium", "Adobe Creative Cloud",
            "Microsoft 365 subscription", "Hulu streaming service", "Disney+ subscription",
            "iCloud storage plan"
        ],
        "amount_range": (5, 50),
        "frequency_weight": 3,
    },
    "Salary": {
        "descriptions": [
            "Monthly salary deposit", "Paycheck direct deposit",
            "Bi-weekly paycheck", "Salary payment"
        ],
        "amount_range": (2000, 6000),
        "frequency_weight": 1,
        "is_income": True,
        "monthly": True,
    },
}


def generate_sample_data(num_rows: int = 1200, months: int = 12, seed: int = 42) -> pd.DataFrame:
    """Generate realistic financial transaction data."""
    np.random.seed(seed)
    random.seed(seed)

    end_date = datetime.now()
    start_date = end_date - timedelta(days=months * 30)

    records = []

    # Generate monthly fixed transactions (Rent, Salary)
    for month_offset in range(months):
        current_month_start = start_date + timedelta(days=month_offset * 30)

        for cat_name, cat_info in CATEGORIES.items():
            if cat_info.get("monthly"):
                day = random.randint(1, 5) if cat_name == "Salary" else random.randint(1, 3)
                txn_date = current_month_start + timedelta(days=day)
                amount = round(random.uniform(*cat_info["amount_range"]), 2)
                if cat_info.get("is_income"):
                    amount = -amount  # income is negative (credit)
                records.append({
                    "date": txn_date.strftime("%Y-%m-%d"),
                    "amount": amount,
                    "category": cat_name,
                    "description": random.choice(cat_info["descriptions"]),
                })

    # Generate variable transactions
    remaining = num_rows - len(records)
    variable_categories = {k: v for k, v in CATEGORIES.items() if not v.get("monthly")}

    # Build weighted category list
    weighted_cats = []
    for cat_name, cat_info in variable_categories.items():
        weighted_cats.extend([cat_name] * cat_info["frequency_weight"])

    for _ in range(remaining):
        cat_name = random.choice(weighted_cats)
        cat_info = CATEGORIES[cat_name]

        # Random date within range
        days_offset = random.randint(0, months * 30)
        txn_date = start_date + timedelta(days=days_offset)

        # Amount with some natural variation
        base_low, base_high = cat_info["amount_range"]
        amount = round(np.random.lognormal(
            mean=np.log((base_low + base_high) / 2),
            sigma=0.4
        ), 2)
        amount = max(base_low, min(amount, base_high * 2))  # clip but allow some high outliers

        records.append({
            "date": txn_date.strftime("%Y-%m-%d"),
            "amount": round(amount, 2),
            "category": cat_name,
            "description": random.choice(cat_info["descriptions"]),
        })

    # Inject anomalies (10-15 unusually large transactions)
    num_anomalies = random.randint(10, 15)
    anomaly_indices = random.sample(range(len(records)), min(num_anomalies, len(records)))
    for idx in anomaly_indices:
        if records[idx]["amount"] > 0:  # only inflate expenses
            records[idx]["amount"] = round(records[idx]["amount"] * random.uniform(5, 15), 2)
            records[idx]["description"] = "UNUSUAL: " + records[idx]["description"]

    # Balance income with expenses so the financial math is realistic
    total_expenses = sum(r["amount"] for r in records if r["amount"] > 0)
    total_income_abs = sum(abs(r["amount"]) for r in records if r["amount"] < 0)
    
    if total_expenses > total_income_abs:
        # Give them a 15% margin
        target_income = total_expenses * 1.15
        deficit = target_income - total_income_abs
        
        salary_records = [r for r in records if r["category"] == "Salary"]
        if salary_records:
            boost_per_salary = deficit / len(salary_records)
            for r in salary_records:
                r["amount"] -= boost_per_salary  # minus because income is stored as negative

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    return df


if __name__ == "__main__":
    from backend.core.config import SAMPLE_DATA_PATH

    print("Generating sample transaction data...")
    df = generate_sample_data()
    df.to_csv(SAMPLE_DATA_PATH, index=False)
    print(f"✅ Generated {len(df)} transactions -> {SAMPLE_DATA_PATH}")
    print(f"\nCategory distribution:")
    print(df["category"].value_counts().to_string())
    print(f"\nDate range: {df['date'].min()} to {df['date'].max()}")
    print(f"Amount range: ${df['amount'].min():.2f} to ${df['amount'].max():.2f}")
