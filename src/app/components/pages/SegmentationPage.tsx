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

// Cluster colors - FinSight palette
const clusterColors: Record<number, string> = {
  0: "#00D4C8", // Cyan
  1: "#58A6FF", // Blue
  2: "#A371F7", // Purple
  3: "#FFA657", // Orange
  4: "#F85149", // Red
};

const CustomDot = (props: any) => {
  const { cx, cy, payload } = props;
  const color = clusterColors[payload.cluster] || "#8B949E";
  return (
    <circle
      cx={cx}
      cy={cy}
      r={6}
      fill={color}
      opacity={0.8}
    />
  );
};

export function SegmentationPage() {
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

        // Fetch segmentation results
        const result = await getResult(uploadId, "segmentation");
        setData(result.data);
        setError(null);
        setLoading(false);
      } catch (err) {
        console.error(err);
        setError("Failed to load segmentation analysis.");
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
          CLUSTERING USER PROFILES...
        </p>
      </div>
    );
  }

  if (!uploadId || error) {
    return (
      <div className="h-full flex items-center justify-center p-8">
        <div className="bg-card border border-border rounded-lg p-8 max-w-md text-center">
          <AlertCircle className="w-12 h-12 text-destructive mx-auto mb-4" />
          <h2 className="text-xl font-sans mb-2">No Segmentation Data</h2>
          <p className="text-muted-foreground mb-6">
            {error || "Please upload your transaction data first to view segmentation."}
          </p>
          <a href="/" className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
            Go to Upload
          </a>
        </div>
      </div>
    );
  }

  const clusterData = data?.points || [];
  const clusterSummaries = data?.cluster_profiles || [];
  const uniqueClusters = Array.from(new Set(clusterData.map((d: any) => d.cluster))) as number[];
  return (
    <div className="p-8">
      {/* Page Header */}
      <div className="mb-8">
        <h2 className="text-2xl font-sans mb-2 text-foreground">
          User Segmentation
        </h2>
        <p className="text-muted-foreground text-sm">
          K-Means clustering analysis of spending patterns (PCA-reduced 2D space)
        </p>
      </div>

      {/* Cluster Scatter Plot */}
      <div className="bg-card border border-border rounded-lg p-6 mb-8">
        <h3 className="text-sm font-mono uppercase tracking-wider text-muted-foreground mb-6">
          K-Means Cluster Visualization
        </h3>
        <ResponsiveContainer width="100%" height={450}>
          <ScatterChart>
            <CartesianGrid strokeDasharray="3 3" stroke="#30363D" />
            <XAxis
              type="number"
              dataKey="x"
              name="Principal Component 1"
              stroke="#8B949E"
              style={{ fontSize: 12, fontFamily: "var(--font-mono)" }}
              label={{
                value: "Principal Component 1",
                position: "insideBottom",
                offset: -5,
                style: { fill: "#8B949E", fontSize: 11, fontFamily: "var(--font-mono)" },
              }}
            />
            <YAxis
              type="number"
              dataKey="y"
              name="Principal Component 2"
              stroke="#8B949E"
              style={{ fontSize: 12, fontFamily: "var(--font-mono)" }}
              label={{
                value: "Principal Component 2",
                angle: -90,
                position: "insideLeft",
                style: { fill: "#8B949E", fontSize: 11, fontFamily: "var(--font-mono)" },
              }}
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
              formatter={(value: number) => value.toFixed(2)}
            />
            {uniqueClusters.map((clusterId: number) => (
              <Scatter 
                key={clusterId}
                name={`Cluster ${clusterId}`} 
                data={clusterData.filter((d: any) => d.cluster === clusterId)} 
                shape={<CustomDot />} 
              />
            ))}
          </ScatterChart>
        </ResponsiveContainer>
        <div className="flex items-center gap-6 mt-4 text-xs text-muted-foreground font-mono flex-wrap">
          {clusterSummaries.map((cluster: any) => (
            <div key={cluster.cluster_id} className="flex items-center gap-2">
              <div
                className="w-3 h-3 rounded-full"
                style={{ backgroundColor: clusterColors[cluster.cluster_id] || "#8B949E" }}
              />
              <span>{cluster.label || `Cluster ${cluster.cluster_id}`}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Cluster Summary Cards */}
      <div>
        <h3 className="text-sm font-mono uppercase tracking-wider text-muted-foreground mb-4">
          Cluster Summary
        </h3>
        <div className="grid grid-cols-2 gap-4">
          {clusterSummaries.map((cluster: any) => {
            const color = clusterColors[cluster.cluster_id] || "#8B949E";
            return (
              <div
                key={cluster.cluster_id}
                className="bg-card border border-border rounded-lg p-6 shadow-[0_0_15px_rgba(0,212,200,0.08)]"
              >
                <div className="flex items-center gap-3 mb-4">
                  <div
                    className="w-4 h-4 rounded-full"
                    style={{ backgroundColor: color }}
                  />
                  <h4 className="font-sans text-foreground">
                    {cluster.label || `Cluster ${cluster.cluster_id}`}
                  </h4>
                </div>

                <div className="space-y-4">
                  <div>
                    <div className="text-[11px] font-mono uppercase tracking-[0.1em] text-muted-foreground mb-1">
                      Avg Monthly Spend
                    </div>
                    <div className="text-2xl font-mono text-foreground">
                      ${(cluster.avg_total_spending || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </div>
                  </div>

                  <div>
                    <div className="text-[11px] font-mono uppercase tracking-[0.1em] text-muted-foreground mb-2">
                      Dominant Categories
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {(cluster.top_categories || []).map((category: string) => (
                        <span
                          key={category}
                          className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-mono border"
                          style={{
                            backgroundColor: `${color}20`,
                            color: color,
                            borderColor: `${color}40`,
                          }}
                        >
                          {category}
                        </span>
                      ))}
                    </div>
                  </div>

                  <div className="pt-4 border-t border-border">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-muted-foreground font-mono uppercase tracking-wider">
                        Avg Transaction Size
                      </span>
                      <span className="text-lg font-mono text-foreground">
                        ${(cluster.avg_transaction_size || 0).toFixed(2)}
                      </span>
                    </div>
                  </div>

                  <p className="text-xs text-muted-foreground">
                    {cluster.description || `Customer segment with unique spending behaviors across ${cluster.num_months} months of history.`}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
