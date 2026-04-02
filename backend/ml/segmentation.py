"""
User/spending segmentation using K-Means clustering.
"""
import pandas as pd
import numpy as np
import joblib
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score
from sklearn.decomposition import PCA
from typing import Dict, Any

from backend.core.config import MODEL_DIR, RANDOM_STATE, MIN_CLUSTERS, MAX_CLUSTERS


def segment_spending(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Segment spending patterns using K-Means.
    Features per month: total_spending, avg_transaction, spending_variance,
    num_transactions, top_category_ratio.
    """
    expenses = df[df["amount"] > 0].copy()

    if len(expenses) < 20 or "date" not in expenses.columns:
        return {"error": "Not enough data for segmentation"}

    # Create monthly spending profiles
    expenses["year_month"] = expenses["date"].dt.to_period("M").astype(str)

    profiles = []
    for ym, group in expenses.groupby("year_month"):
        profile = {
            "year_month": ym,
            "total_spending": group["amount"].sum(),
            "avg_transaction": group["amount"].mean(),
            "spending_variance": group["amount"].var() if len(group) > 1 else 0,
            "num_transactions": len(group),
            "max_transaction": group["amount"].max(),
            "min_transaction": group["amount"].min(),
        }

        if "category" in group.columns:
            cat_counts = group["category"].value_counts()
            profile["top_category_ratio"] = cat_counts.iloc[0] / len(group) if len(cat_counts) > 0 else 0
            profile["num_categories"] = len(cat_counts)
        else:
            profile["top_category_ratio"] = 0
            profile["num_categories"] = 0

        profiles.append(profile)

    profiles_df = pd.DataFrame(profiles)

    if len(profiles_df) < MIN_CLUSTERS + 1:
        return {"error": f"Not enough monthly data points ({len(profiles_df)}) for clustering"}

    # Feature matrix
    feature_cols = [
        "total_spending", "avg_transaction", "spending_variance",
        "num_transactions", "top_category_ratio", "num_categories"
    ]
    X = profiles_df[feature_cols].values

    # Standardize
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Elbow method
    max_k = min(MAX_CLUSTERS, len(profiles_df) - 1)
    inertias = []
    silhouettes = []
    k_range = range(MIN_CLUSTERS, max_k + 1)

    for k in k_range:
        km = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=10)
        labels = km.fit_predict(X_scaled)
        inertias.append(float(km.inertia_))
        if k > 1 and k < len(X_scaled):
            sil = float(silhouette_score(X_scaled, labels))
        else:
            sil = 0.0
        silhouettes.append(sil)

    # Pick best k by silhouette
    best_k_idx = np.argmax(silhouettes)
    best_k = list(k_range)[best_k_idx]

    # Final model
    final_km = KMeans(n_clusters=best_k, random_state=RANDOM_STATE, n_init=10)
    cluster_labels = final_km.fit_predict(X_scaled)
    profiles_df["cluster"] = cluster_labels

    final_silhouette = float(silhouette_score(X_scaled, cluster_labels)) if best_k > 1 else 0.0

    # PCA for visualization
    pca = PCA(n_components=2)
    X_pca = pca.fit_transform(X_scaled)
    profiles_df["pca_x"] = X_pca[:, 0]
    profiles_df["pca_y"] = X_pca[:, 1]

    # Cluster profiles
    cluster_profiles = []
    for c in range(best_k):
        cluster_data = profiles_df[profiles_df["cluster"] == c]
        profile = {
            "cluster_id": int(c),
            "num_months": len(cluster_data),
            "avg_total_spending": float(cluster_data["total_spending"].mean()),
            "avg_transactions": float(cluster_data["num_transactions"].mean()),
            "avg_transaction_size": float(cluster_data["avg_transaction"].mean()),
            "spending_variability": float(cluster_data["spending_variance"].mean()),
        }

        # Label clusters
        if profile["avg_total_spending"] > profiles_df["total_spending"].quantile(0.75):
            profile["label"] = "High Spender"
        elif profile["avg_total_spending"] < profiles_df["total_spending"].quantile(0.25):
            profile["label"] = "Low Spender"
        else:
            profile["label"] = "Moderate Spender"

        cluster_profiles.append(profile)

    # Save model
    model_path = MODEL_DIR / "segmentation.pkl"
    joblib.dump({"model": final_km, "scaler": scaler, "pca": pca}, model_path)

    return {
        "best_k": int(best_k),
        "silhouette_score": final_silhouette,
        "elbow_data": {
            "k_values": list(k_range),
            "inertias": inertias,
            "silhouettes": silhouettes,
        },
        "cluster_profiles": cluster_profiles,
        "scatter_data": [
            {
                "year_month": row["year_month"],
                "pca_x": float(row["pca_x"]),
                "pca_y": float(row["pca_y"]),
                "cluster": int(row["cluster"]),
                "total_spending": float(row["total_spending"]),
            }
            for _, row in profiles_df.iterrows()
        ],
        "model_path": str(model_path),
    }
