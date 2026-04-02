"""
Reusable Plotly chart components with consistent premium theming.
"""
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional

# FinSight theme color palette
COLORS = {
    "primary": "#00D4C8",       # Cyan
    "secondary": "#58A6FF",     # Blue
    "accent": "#A371F7",        # Purple
    "success": "#00D4C8",       # Cyan
    "warning": "#FFA657",       # Orange
    "danger": "#F85149",        # Red
    "info": "#58A6FF",          # Blue
    "background": "#0D1117",    # FinSight BG
    "card": "#161B22",          # FinSight Card
    "text": "#F0F6FC",          # FinSight Base Text
    "text_muted": "#8B949E",    # FinSight Muted Text
}

CATEGORY_COLORS = [
    "#00D4C8", "#58A6FF", "#A371F7", "#FFA657", "#F85149",
    "#00B3A6", "#408BE8", "#8957E5", "#E6893E", "#D94038",
]

CHART_TEMPLATE = {
    "layout": {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"color": COLORS["text"], "family": "DM Sans, -apple-system, sans-serif"},
        "xaxis": {
            "gridcolor": "#30363D",
            "zerolinecolor": "#30363D",
        },
        "yaxis": {
            "gridcolor": "#30363D",
            "zerolinecolor": "#30363D",
        },
        "margin": {"l": 32, "r": 24, "t": 48, "b": 32},
    }
}


def apply_theme(fig):
    """Apply consistent strict theme to any Plotly figure."""
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=COLORS["text"], family="DM Sans, -apple-system, sans-serif", size=12),
        margin=dict(l=32, r=24, t=48, b=32),
        legend=dict(
            bgcolor="#161B22",
            bordercolor="#30363D",
            borderwidth=1,
            font=dict(size=12),
        ),
    )
    fig.update_xaxes(
        gridcolor="#30363D",
        zerolinecolor="#30363D",
    )
    fig.update_yaxes(
        gridcolor="#30363D",
        zerolinecolor="#30363D",
    )
    return fig


def category_pie_chart(category_data: List[Dict], title: str = "Spending by Category") -> go.Figure:
    """Create a donut chart for category breakdown."""
    df = pd.DataFrame(category_data)
    fig = go.Figure(data=[go.Pie(
        labels=df["category"],
        values=df["total"],
        hole=0.55,
        marker=dict(colors=CATEGORY_COLORS[:len(df)]),
        textinfo="label+percent",
        textposition="outside",
        textfont=dict(size=11),
        hovertemplate="<b>%{label}</b><br>Total: $%{value:,.2f}<br>Share: %{percent}<extra></extra>",
    )])
    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        showlegend=False,
        height=400,
    )
    return apply_theme(fig)


def monthly_spending_chart(monthly_data: List[Dict], title: str = "Monthly Spending Trend") -> go.Figure:
    """Create a bar + line chart for monthly spending."""
    df = pd.DataFrame(monthly_data)
    fig = go.Figure()

    # Bar chart
    fig.add_trace(go.Bar(
        x=df["month"],
        y=df["total"],
        marker=dict(
            color=df["total"],
            colorscale=[[0, COLORS["primary"]], [1, COLORS["accent"]]],
            cornerradius=6,
        ),
        hovertemplate="<b>%{x}</b><br>Spending: $%{y:,.2f}<extra></extra>",
        name="Monthly Spending",
    ))

    # Trend line
    fig.add_trace(go.Scatter(
        x=df["month"],
        y=df["total"].rolling(window=3, min_periods=1).mean(),
        mode="lines",
        line=dict(color=COLORS["warning"], width=2, dash="dot"),
        name="3-Month Average",
        hovertemplate="<b>%{x}</b><br>Avg: $%{y:,.2f}<extra></extra>",
    ))

    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        xaxis_title="Month",
        yaxis_title="Total Spending ($)",
        barmode="overlay",
        height=400,
    )
    return apply_theme(fig)


def daily_spending_chart(df: pd.DataFrame, title: str = "Daily Spending") -> go.Figure:
    """Create area chart for daily spending."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"],
        y=df["amount"] if "amount" in df.columns else df["total_spending"],
        fill="tozeroy",
        fillcolor="rgba(99, 102, 241, 0.2)",
        line=dict(color=COLORS["primary"], width=1.5),
        hovertemplate="<b>%{x}</b><br>Spending: $%{y:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        xaxis_title="Date",
        yaxis_title="Spending ($)",
        height=350,
    )
    return apply_theme(fig)


def prediction_chart(
    test_dates, test_actual, test_predicted,
    future_predictions,
    title: str = "Expense Predictions"
) -> go.Figure:
    """Chart showing actual vs predicted + future forecast."""
    fig = go.Figure()

    # Historical actual
    fig.add_trace(go.Scatter(
        x=test_dates,
        y=test_actual,
        mode="lines",
        line=dict(color=COLORS["primary"], width=2),
        name="Actual",
        hovertemplate="<b>%{x}</b><br>Actual: $%{y:,.2f}<extra></extra>",
    ))

    # Historical predicted
    fig.add_trace(go.Scatter(
        x=test_dates,
        y=test_predicted,
        mode="lines",
        line=dict(color=COLORS["success"], width=2, dash="dash"),
        name="Predicted",
        hovertemplate="<b>%{x}</b><br>Predicted: $%{y:,.2f}<extra></extra>",
    ))

    # Future predictions
    future_dates = [p["date"] for p in future_predictions]
    future_values = [p["predicted_spending"] for p in future_predictions]

    fig.add_trace(go.Scatter(
        x=future_dates,
        y=future_values,
        fill="tozeroy",
        fillcolor="rgba(236, 72, 153, 0.15)",
        line=dict(color=COLORS["accent"], width=2),
        name="Forecast (30 days)",
        hovertemplate="<b>%{x}</b><br>Forecast: $%{y:,.2f}<extra></extra>",
    ))

    # Vertical line separating past/future
    if test_dates and future_dates:
        fig.add_vline(
            # Pass millisecond epoch to strictly bypass Pandas/Plotly Timestamp addition conflicts
            x=pd.to_datetime(test_dates[-1]).timestamp() * 1000, line_dash="dash",
            line_color=COLORS["text_muted"],
            annotation_text="Today",
            annotation_font_color=COLORS["text_muted"],
        )

    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        xaxis_title="Date",
        yaxis_title="Daily Spending ($)",
        height=450,
    )
    return apply_theme(fig)


def anomaly_timeline_chart(transactions_df: pd.DataFrame, title: str = "Anomaly Detection") -> go.Figure:
    """Scatter chart highlighting anomalies on a timeline."""
    fig = go.Figure()

    normal = transactions_df[~transactions_df["is_anomaly"]]
    anomalies = transactions_df[transactions_df["is_anomaly"]]

    fig.add_trace(go.Scatter(
        x=normal["date"],
        y=normal["amount"],
        mode="markers",
        marker=dict(color=COLORS["primary"], size=5, opacity=0.5),
        name="Normal",
        hovertemplate="<b>%{x}</b><br>$%{y:,.2f}<extra></extra>",
    ))

    fig.add_trace(go.Scatter(
        x=anomalies["date"],
        y=anomalies["amount"],
        mode="markers",
        marker=dict(
            color=COLORS["danger"],
            size=12,
            symbol="diamond",
            line=dict(color="white", width=1),
        ),
        name="Anomaly",
        hovertemplate="<b>%{x}</b><br>$%{y:,.2f}<br>⚠ Anomaly<extra></extra>",
    ))

    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        xaxis_title="Date",
        yaxis_title="Amount ($)",
        height=400,
    )
    return apply_theme(fig)


def anomaly_score_distribution(scores: List[float], labels: List[int], title: str = "Anomaly Score Distribution") -> go.Figure:
    """Histogram of anomaly scores."""
    fig = go.Figure()

    normal_scores = [s for s, l in zip(scores, labels) if l == 1]
    anomaly_scores = [s for s, l in zip(scores, labels) if l == -1]

    fig.add_trace(go.Histogram(
        x=normal_scores, nbinsx=40,
        marker=dict(color=COLORS["primary"], opacity=0.7),
        name="Normal",
    ))
    fig.add_trace(go.Histogram(
        x=anomaly_scores, nbinsx=20,
        marker=dict(color=COLORS["danger"], opacity=0.8),
        name="Anomaly",
    ))

    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        xaxis_title="Anomaly Score",
        yaxis_title="Count",
        barmode="overlay",
        height=350,
    )
    return apply_theme(fig)


def cluster_scatter_chart(scatter_data: List[Dict], title: str = "Spending Segments") -> go.Figure:
    """PCA scatter plot of clusters."""
    df = pd.DataFrame(scatter_data)
    
    fig = px.scatter(
        df, x="pca_x", y="pca_y",
        color=df["cluster"].astype(str),
        size="total_spending",
        hover_data=["year_month", "total_spending"],
        color_discrete_sequence=CATEGORY_COLORS,
    )

    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        xaxis_title="Principal Component 1",
        yaxis_title="Principal Component 2",
        height=450,
        legend_title="Cluster",
    )
    return apply_theme(fig)


def elbow_chart(k_values, inertias, silhouettes, best_k: int, title: str = "Optimal Clusters") -> go.Figure:
    """Elbow + silhouette chart for K selection."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(go.Scatter(
        x=k_values, y=inertias,
        mode="lines+markers",
        line=dict(color=COLORS["primary"], width=2),
        marker=dict(size=8),
        name="Inertia",
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=k_values, y=silhouettes,
        mode="lines+markers",
        line=dict(color=COLORS["accent"], width=2),
        marker=dict(size=8),
        name="Silhouette Score",
    ), secondary_y=True)

    # Mark best k
    fig.add_vline(
        x=best_k, line_dash="dash",
        line_color=COLORS["success"],
        annotation_text=f"Best K={best_k}",
        annotation_font_color=COLORS["success"],
    )

    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        xaxis_title="Number of Clusters (K)",
        height=350,
    )
    fig.update_yaxes(title_text="Inertia", secondary_y=False)
    fig.update_yaxes(title_text="Silhouette Score", secondary_y=True)
    return apply_theme(fig)


def model_comparison_chart(model_data: Dict[str, Dict], metric: str = "accuracy", title: str = "Model Comparison") -> go.Figure:
    """Bar chart comparing model performance."""
    names = list(model_data.keys())
    values = [model_data[n].get(metric, 0) for n in names]

    fig = go.Figure(data=[go.Bar(
        x=names,
        y=values,
        marker=dict(
            color=CATEGORY_COLORS[:len(names)],
            cornerradius=8,
        ),
        text=[f"{v:.3f}" for v in values],
        textposition="outside",
        textfont=dict(size=13, color=COLORS["text"]),
    )])

    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        xaxis_title="Model",
        yaxis_title=metric.upper(),
        height=350,
    )
    return apply_theme(fig)


def confusion_matrix_chart(cm: List[List[int]], labels: List[str], title: str = "Confusion Matrix") -> go.Figure:
    """Heatmap for confusion matrix."""
    fig = go.Figure(data=go.Heatmap(
        z=cm,
        x=labels,
        y=labels,
        colorscale=[[0, "#1E293B"], [0.5, "#6366F1"], [1, "#EC4899"]],
        hovertemplate="True: %{y}<br>Predicted: %{x}<br>Count: %{z}<extra></extra>",
        text=cm,
        texttemplate="%{text}",
        textfont=dict(size=11),
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        xaxis_title="Predicted",
        yaxis_title="Actual",
        height=450,
    )
    return apply_theme(fig)
