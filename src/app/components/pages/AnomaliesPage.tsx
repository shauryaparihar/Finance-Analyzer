import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { Loader2, AlertCircle } from "lucide-react";
import { useState, useEffect } from "react";
import { getResult, getStatus } from "../../api";
import { useAppContext } from "../../context/AppContext";

export function AnomaliesPage() {
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

        // Fetch anomaly results
        const result = await getResult(uploadId, "anomaly");
        setData(result.data);
        setError(null);
        setLoading(false);
      } catch (err) {
        console.error(err);
        setError("Failed to load anomaly detection results.");
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
          SCANNING FOR IRREGULARITIES...
        </p>
      </div>
    );
  }

  if (!uploadId || error) {
    return (
      <div className="h-full flex items-center justify-center p-8">
        <div className="bg-card border border-border rounded-lg p-8 max-w-md text-center">
          <AlertCircle className="w-12 h-12 text-destructive mx-auto mb-4" />
          <h2 className="text-xl font-sans mb-2">No Anomaly Data</h2>
          <p className="text-muted-foreground mb-6">
            {error || "Please upload your transaction data first to detect anomalies."}
          </p>
          <a href="/" className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
            Go to Upload
          </a>
        </div>
      </div>
    );
  }

  const scatterData = data?.plot_data || [];
  const anomalies = data?.anomalies || [];
  return (
    <div className="p-8">
      {/* Page Header */}
      <div className="mb-8">
        <h2 className="text-2xl font-sans mb-2 text-foreground">
          Anomaly Detection
        </h2>
        <p className="text-muted-foreground text-sm">
          Unusual spending patterns identified using statistical analysis
        </p>
      </div>

      {/* Scatter Plot */}
      <div className="bg-card border border-border rounded-lg p-6 mb-8">
        <h3 className="text-sm font-mono uppercase tracking-wider text-muted-foreground mb-6">
          Transaction Anomaly Distribution
        </h3>
        <ResponsiveContainer width="100%" height={450}>
          <ScatterChart>
            <CartesianGrid strokeDasharray="3 3" stroke="#30363D" />
            <XAxis
              dataKey="date"
              stroke="#8B949E"
              style={{ fontSize: 10, fontFamily: "var(--font-mono)" }}
              tick={{ fill: "#8B949E" }}
              minTickGap={30}
            />
            <YAxis
              dataKey="amount"
              stroke="#8B949E"
              style={{ fontSize: 10, fontFamily: "var(--font-mono)" }}
              tickFormatter={(value) => `$${value}`}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#161B22",
                border: "1px solid #30363D",
                borderRadius: "8px",
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                boxShadow: "0 4px 12px rgba(0,0,0,0.5)",
                color: "#ffffff"
              }}
              itemStyle={{ color: "#ffffff" }}
              labelStyle={{ color: "#9ca3af", marginBottom: "4px" }}
              formatter={(value: number) => [`$${value.toLocaleString()}`, "Amount"]}
            />
            <Scatter data={scatterData} name="Transactions">
              {scatterData.map((entry: any, index: number) => (
                <Cell
                  key={`cell-${index}`}
                  fill={entry.type === "anomaly" ? "#00D4C8" : "#4A5568"}
                  fillOpacity={entry.type === "anomaly" ? 1 : 0.2}
                  stroke={entry.type === "anomaly" ? "#00D4C8" : "none"}
                  r={entry.type === "anomaly" ? 7 : 2}
                  className={entry.type === "anomaly" ? "animate-pulse" : ""}
                />
              ))}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
        <div className="flex items-center gap-6 mt-4 text-xs text-muted-foreground font-mono">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-[#30363D]" />
            <span>Normal Transactions</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-primary animate-pulse" />
            <span>Detected Anomalies</span>
          </div>
        </div>
      </div>

      {/* Flagged Transactions Table */}
      <div className="bg-card border border-border rounded-lg overflow-hidden">
        <div className="p-6 border-b border-border">
          <h3 className="text-sm font-mono uppercase tracking-wider text-muted-foreground">
            Flagged Transactions
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-secondary/30 sticky top-0">
              <tr>
                <th className="px-6 py-4 text-left text-sm font-sans font-medium tracking-tight text-muted-foreground">
                  Date
                </th>
                <th className="px-6 py-4 text-left text-sm font-sans font-medium tracking-tight text-muted-foreground">
                  Description
                </th>
                <th className="px-6 py-4 text-right text-sm font-sans font-medium tracking-tight text-muted-foreground">
                  Amount
                </th>
                <th className="px-6 py-4 text-center text-sm font-sans font-medium tracking-tight text-muted-foreground">
                  Score
                </th>
                <th className="px-6 py-4 text-center text-sm font-sans font-medium tracking-tight text-muted-foreground">
                  Severity
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {anomalies.map((anomaly: any, index: number) => (
                <tr
                  key={anomaly.id}
                  className={`hover:bg-secondary/30 transition-colors ${
                    index % 2 === 0 ? "bg-background" : "bg-secondary/10"
                  }`}
                >
                  <td className="px-6 py-4 font-mono text-sm text-muted-foreground">
                    {anomaly.date}
                  </td>
                  <td className="px-6 py-4 text-sm text-foreground">
                    {anomaly.description}
                  </td>
                  <td className="px-6 py-4 text-right font-mono text-sm text-foreground">
                    ${anomaly.amount.toLocaleString()}
                  </td>
                  <td className="px-6 py-4 text-center">
                    <span className="font-mono text-sm text-primary">
                      {anomaly.score.toFixed(2)}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-center">
                    <span
                      className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-mono ${
                        anomaly.severity === "High"
                          ? "bg-destructive/20 text-destructive border border-destructive/30"
                          : "bg-[#FFA657]/20 text-[#FFA657] border border-[#FFA657]/30"
                      }`}
                    >
                      {anomaly.severity}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
