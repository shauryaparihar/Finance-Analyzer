"""
Generate a 50,000-row category-balanced dataset for pressure testing.
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
import os

CATEGORIES = {
    "Groceries": {"amount_range": (15, 200), "descriptions": ["Walmart", "Whole Foods", "Trader Joe's", "Costco"]},
    "Rent": {"amount_range": (800, 2500), "descriptions": ["Monthly Rent", "Housing Payment"], "monthly": True},
    "Utilities": {"amount_range": (30, 250), "descriptions": ["Electric Bill", "Water Utility", "Internet", "Phone"]},
    "Entertainment": {"amount_range": (10, 150), "descriptions": ["Movies", "Concert", "Video Games", "Museum"]},
    "Dining": {"amount_range": (5, 80), "descriptions": ["McDonald's", "Chipotle", "Starbucks", "Sushi", "Pizza"]},
    "Transportation": {"amount_range": (5, 100), "descriptions": ["Uber", "Lyft", "Gas Station", "Bus Pass"]},
    "Healthcare": {"amount_range": (15, 500), "descriptions": ["Doctor Visit", "Pharmacy", "Dental", "Eye Exam"]},
    "Shopping": {"amount_range": (10, 300), "descriptions": ["Amazon", "Nike", "Best Buy", "IKEA", "Zara"]},
    "Subscriptions": {"amount_range": (5, 50), "descriptions": ["Netflix", "Spotify", "Amazon Prime", "Gym"]},
    "Salary": {"amount_range": (2000, 6000), "descriptions": ["Salary Deposit", "Paycheck"], "is_income": True, "monthly": True}
}

def generate_balanced_data(total_rows=50000, months=24):
    np.random.seed(42)
    random.seed(42)
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=months * 30)
    
    records = []
    
    # 1. Calculate target per category
    categories_list = list(CATEGORIES.keys())
    target_per_cat = total_rows // len(categories_list)
    
    for cat_name in categories_list:
        cat_info = CATEGORIES[cat_name]
        
        for _ in range(target_per_cat):
            # Random date within range
            days_offset = random.randint(0, months * 30)
            txn_date = start_date + timedelta(days=days_offset)
            
            # Amount
            low, high = cat_info["amount_range"]
            amount = round(random.uniform(low, high), 2)
            if cat_info.get("is_income"):
                amount = -amount # income is credit
                
            records.append({
                "date": txn_date.strftime("%Y-%m-%d"),
                "amount": amount,
                "category": cat_name,
                "description": random.choice(cat_info["descriptions"])
            })

    # 2. Add remaining rows if any
    remaining = total_rows - len(records)
    if remaining > 0:
        for _ in range(remaining):
            cat_name = random.choice(categories_list)
            cat_info = CATEGORIES[cat_name]
            days_offset = random.randint(0, months * 30)
            txn_date = start_date + timedelta(days=days_offset)
            low, high = cat_info["amount_range"]
            amount = round(random.uniform(low, high), 2)
            if cat_info.get("is_income"):
                amount = -amount
            records.append({
                "date": txn_date.strftime("%Y-%m-%d"),
                "amount": amount,
                "category": cat_name,
                "description": random.choice(cat_info["descriptions"])
            })

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    
    return df

if __name__ == "__main__":
    output_dir = "data/uploads"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "large_transactions_balanced.csv")
    
    print(f"Generating {50000} balanced transactions...")
    df = generate_balanced_data(50000)
    df.to_csv(output_path, index=False)
    print(f"✅ Saved to {output_path}")
    print("\nDistribution:")
    print(df["category"].value_counts())
