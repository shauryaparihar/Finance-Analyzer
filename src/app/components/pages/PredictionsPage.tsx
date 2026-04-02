import { KPICard } from "../KPICard";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  ComposedChart,
  BarChart,
  Bar,
} from "recharts";
import { Loader2, AlertCircle } from "lucide-react";
import { useState, useEffect } from "react";
import { getResult, getStatus } from "../../api";
import { useAppContext } from "../../context/AppContext";

export function PredictionsPage() {
  const { uploadId } = useAppContext();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let pollInterval: NodeJS.Timeout;

    async function fetchData() {
      if (!uploadId) {
        setLoading(false);
        return;
      }
      try {
        setLoading(true);
        // First check the overall status
        const statusData = await getStatus(uploadId);
        
        if (statusData.status === 'processing') {
          // Keep polling if still processing
          pollInterval = setTimeout(fetchData, 3000);
          return;
        }

        if (statusData.status === 'failed') {
          setError("Data processing failed.");
          setLoading(false);
          return;
        }

        // Fetch prediction results
        const result = await getResult(uploadId, "prediction");
        setData(result.data);
        setError(null);
        setLoading(false);
      } catch (err) {
        console.error(err);
        setError("Failed to load prediction models. Ensure the backend is running.");
        setLoading(false);
      }
    }

    fetchData();
    return () => {
      if (pollInterval) clearTimeout(pollInterval);
    };
  }, [uploadId]);

  if (loading) {
    return (
      <div className="h-full flex flex-col items-center justify-center space-y-4">
        <Loader2 className="w-8 h-8 text-primary animate-spin" />
        <p className="text-muted-foreground font-mono text-sm animate-pulse">
          RUNNING FORECAST MODELS...
        </p>
      </div>
    );
  }

  if (!uploadId || error) {
    return (
      <div className="h-full flex items-center justify-center p-8">
        <div className="bg-card border border-border rounded-lg p-8 max-w-md text-center">
          <AlertCircle className="w-12 h-12 text-destructive mx-auto mb-4" />
          <h2 className="text-xl font-sans mb-2">No Forecast Data</h2>
          <p className="text-muted-foreground mb-6">
            {error || "Please upload your transaction data first to view predictions."}
          </p>
          <a href="/" className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
            Go to Upload
          </a>
        </div>
      </div>
    );
  }

  const forecastData = data?.plot_data?.map((item: any) => ({
    month: item.date,
    actual: item.type === "actual" ? item.amount : null,
    forecast: item.type === "forecast" ? item.amount : null,
    lower: item.lower,
    upper: item.upper
  })) || [];

  const modelComparison = data?.comparison || [];
  const metrics = data?.metrics || {};
  return (
    <div className="p-8">
      {/* Page Header */}
      <div className="mb-8">
        <h2 className="text-2xl font-sans mb-2 text-foreground">
          Spending Predictions
        </h2>
        <p className="text-muted-foreground text-sm">
          30-day forecast with confidence intervals using time series analysis
        </p>
      </div>

      {/* Forecast Chart */}
      <div className="bg-card border border-border rounded-lg p-6 mb-8">
        <h3 className="text-sm font-mono uppercase tracking-wider text-muted-foreground mb-6">
          Historical Spending & 30-Day Forecast
        </h3>
        <ResponsiveContainer width="100%" height={400}>
          <ComposedChart data={forecastData}>
            <defs>
              <linearGradient id="confidenceBand" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#00D4C8" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#00D4C8" stopOpacity={0.05} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#30363D" />
            <XAxis
              dataKey="month"
              stroke="#8B949E"
              style={{ fontSize: 12, fontFamily: "var(--font-mono)" }}
            />
            <YAxis
              stroke="#8B949E"
              style={{ fontSize: 12, fontFamily: "var(--font-mono)" }}
              tickFormatter={(value) => `$${value / 1000}k`}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#161B22",
                border: "1px solid #30363D",
                borderRadius: "8px",
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                color: "#ffffff",
                boxShadow: "0 4px 12px rgba(0,0,0,0.5)"
              }}
              itemStyle={{ color: "#ffffff" }}
              labelStyle={{ color: "#9ca3af", marginBottom: "4px" }}
              formatter={(value: number) => [`$${value?.toLocaleString()}`, "Amount"]}
            />
            <Area
              type="monotone"
              dataKey="upper"
              stroke="none"
              fill="url(#confidenceBand)"
              fillOpacity={1}
            />
            <Area
              type="monotone"
              dataKey="lower"
              stroke="none"
              fill="url(#confidenceBand)"
              fillOpacity={1}
            />
            <Line
              type="monotone"
              dataKey="actual"
              stroke="#00D4C8"
              strokeWidth={3}
              dot={{ fill: "#00D4C8", r: 4 }}
              name="Historical"
            />
            <Line
              type="monotone"
              dataKey="forecast"
              stroke="#00D4C8"
              strokeWidth={3}
              strokeDasharray="8 4"
              dot={{ fill: "#00D4C8", r: 4 }}
              name="Forecast"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        <KPICard 
          label="Predicted Next Month" 
          value={`$${(metrics.next_month_prediction || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}`} 
        />
        <KPICard 
          label="Highest Predicted Category" 
          value={metrics.top_predicted_category || "N/A"} 
        />
        <div className="bg-card border border-border rounded-lg p-6 shadow-[0_0_15px_rgba(0,212,200,0.08)]">
          <div className="text-[11px] font-mono uppercase tracking-[0.1em] text-muted-foreground mb-3">
            Model Used
          </div>
          <div className="text-[32px] font-mono leading-none text-foreground">
            {metrics.model_name || "N/A"}
          </div>
          <div className="mt-2 text-xs text-muted-foreground font-mono">
            {metrics.model_description || "Predictive analysis engine"}
          </div>
        </div>
      </div>

      {/* Model Comparison */}
      <div className="bg-card border border-border rounded-lg p-6">
        <h3 className="text-sm font-mono uppercase tracking-wider text-muted-foreground mb-6">
          Model Comparison (RMSE)
        </h3>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={modelComparison} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" stroke="#30363D" />
            <XAxis
              type="number"
              stroke="#8B949E"
              style={{ fontSize: 12, fontFamily: "var(--font-mono)" }}
            />
            <YAxis
              type="category"
              dataKey="model"
              stroke="#8B949E"
              style={{ fontSize: 12, fontFamily: "var(--font-mono)" }}
              width={150}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#161B22",
                border: "1px solid #30363D",
                borderRadius: "8px",
                fontFamily: "var(--font-mono)",
                fontSize: 12,
              }}
              formatter={(value: number) => [value, "RMSE"]}
            />
            <Bar dataKey="rmse" fill="#00D4C8" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
        <p className="mt-4 text-xs text-muted-foreground">
          Lower RMSE indicates better predictive accuracy. ARIMA demonstrates the lowest error rate.
        </p>
      </div>
    </div>
  );
}
