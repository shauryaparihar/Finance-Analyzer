import { KPICard } from "../KPICard";
import {
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { ArrowUpDown, Loader2, AlertCircle } from "lucide-react";
import { useState, useEffect, useMemo, JSXElementConstructor, Key, ReactElement, ReactNode, ReactPortal } from "react";
import { getResult, getStatus } from "../../api";
import { useAppContext } from "../../context/AppContext";

type SortConfig = {
  key: string;
  direction: "asc" | "desc";
} | null;

export function OverviewPage() {
  const { uploadId } = useAppContext();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortConfig, setSortConfig] = useState<SortConfig>(null);

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
          setError("Data processing failed. Please try a different file.");
          setLoading(false);
          return;
        }

        // If completed or other state, try fetching results
        const result = await getResult(uploadId, "summary");
        setData(result.data);
        setError(null);
        setLoading(false);
      } catch (err) {
        console.error(err);
        setError("Failed to load dashboard data. Please ensure the backend is running.");
        setLoading(false);
      }
    }

    fetchData();
    return () => {
      if (pollInterval) clearTimeout(pollInterval);
    };
  }, [uploadId]);

  const transactions = data?.recent_transactions || [];

  const sortedTransactions = useMemo(() => {
    if (!sortConfig) return transactions;
    return [...transactions].sort((a: any, b: any) => {
      const aValue = a[sortConfig.key];
      const bValue = b[sortConfig.key];
      if (aValue < bValue) return sortConfig.direction === "asc" ? -1 : 1;
      if (aValue > bValue) return sortConfig.direction === "asc" ? 1 : -1;
      return 0;
    });
  }, [transactions, sortConfig]);

  const handleSort = (key: any) => {
    setSortConfig((current) => {
      if (!current || current.key !== key) return { key, direction: "asc" };
      if (current.direction === "asc") return { key, direction: "desc" };
      return null;
    });
  };

  if (loading) {
    return (
      <div className="h-full flex flex-col items-center justify-center space-y-4">
        <Loader2 className="w-8 h-8 text-primary animate-spin" />
        <p className="text-muted-foreground font-mono text-sm animate-pulse">
          ANALYZING TRANSACTION DATA...
        </p>
      </div>
    );
  }

  if (!uploadId || error) {
    return (
      <div className="h-full flex items-center justify-center p-8">
        <div className="bg-card border border-border rounded-lg p-8 max-w-md text-center">
          <AlertCircle className="w-12 h-12 text-destructive mx-auto mb-4" />
          <h2 className="text-xl font-sans mb-2">No Data Available</h2>
          <p className="text-muted-foreground mb-6">
            {error || "Please upload your transaction data first to view the dashboard."}
          </p>
          <a href="/" className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
            Go to Upload
          </a>
        </div>
      </div>
    );
  }

  // Predefined chart colors from FinSight palette
  const CHART_COLORS = ["#00D4C8", "#58A6FF", "#A371F7", "#FFA657", "#F85149"];

  const categoryData = data?.category_spending?.map((item: any, index: number) => ({
    name: item.category,
    value: item.amount,
    color: CHART_COLORS[index % CHART_COLORS.length]
  })) || [];

  const monthlyData = data?.monthly_spending?.map((item: any) => ({
    month: item.month,
    amount: item.amount
  })) || [];

  return (
    <div className="p-8">
      {/* Page Header */}
      <div className="mb-8">
        <h2 className="text-2xl font-sans mb-2 text-foreground">Dashboard Overview</h2>
        <p className="text-muted-foreground text-sm">
          Comprehensive analysis of your financial transactions
        </p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        <KPICard
          label="Total Transactions"
          value={data?.total_transactions?.toLocaleString() || "0"}
          trend={data?.total_transactions > 0 ? { direction: "up", percentage: "Live" } : undefined}
        />
        <KPICard
          label="Total Spend"
          value={`$${(data?.total_spending || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}`}
          trend={data?.total_spending > 0 ? { direction: "up", percentage: "Net" } : undefined}
        />
        <KPICard
          label="Avg Monthly Spend"
          value={`$${(data?.avg_monthly_spending || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}`}
          trend={data?.avg_monthly_spending > 0 ? { direction: "down", percentage: "Avg" } : undefined}
        />
        <KPICard
          label="Anomalies Detected"
          value={data?.num_anomalies?.toString() || "0"}
          trend={data?.num_anomalies > 0 ? { direction: "up", percentage: "Review" } : undefined}
          variant={data?.num_anomalies > 0 ? "warning" : "default"}
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-12 gap-4 mb-8">
        {/* Monthly Spend Bar Chart */}
        <div className="col-span-7 bg-card border border-border rounded-lg p-6">
          <h3 className="text-sm font-mono uppercase tracking-wider text-muted-foreground mb-6">
            Monthly Spend Breakdown
          </h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={monthlyData}>
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
                formatter={(value: number) => [`$${value.toLocaleString()}`, "Amount"]}
              />
              <Bar dataKey="amount" fill="#00D4C8" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Category Distribution Pie Chart */}
        <div className="col-span-5 bg-card border border-border rounded-lg p-6">
          <h3 className="text-sm font-mono uppercase tracking-wider text-muted-foreground mb-6">
            Category Distribution
          </h3>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={categoryData}
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={100}
                paddingAngle={2}
                dataKey="value"
              >
                {categoryData.map((entry: { color: string | undefined; }, index: any) => (
                  <Cell key={`cell-${index}`} fill={entry.color} />
                ))}
              </Pie>
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
                formatter={(value: number) => `$${value.toLocaleString()}`}
              />
              <Legend
                verticalAlign="bottom"
                height={36}
                iconType="circle"
                wrapperStyle={{
                  fontSize: 11,
                  fontFamily: "var(--font-mono)",
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Recent Transactions Table */}
      <div className="bg-card border border-border rounded-lg overflow-hidden">
        <div className="p-6 border-b border-border">
          <h3 className="text-sm font-mono uppercase tracking-wider text-muted-foreground">
            Recent Transactions
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-secondary sticky top-0">
              <tr>
                <th
                  className="px-6 py-3 text-left text-xs font-mono uppercase tracking-wider text-muted-foreground cursor-pointer hover:text-foreground transition-colors"
                  onClick={() => handleSort("date")}
                >
                  <div className="flex items-center gap-2">
                    Date
                    <ArrowUpDown className="w-3 h-3" />
                  </div>
                </th>
                <th
                  className="px-6 py-3 text-left text-xs font-mono uppercase tracking-wider text-muted-foreground cursor-pointer hover:text-foreground transition-colors"
                  onClick={() => handleSort("description")}
                >
                  <div className="flex items-center gap-2">
                    Description
                    <ArrowUpDown className="w-3 h-3" />
                  </div>
                </th>
                <th
                  className="px-6 py-3 text-right text-xs font-mono uppercase tracking-wider text-muted-foreground cursor-pointer hover:text-foreground transition-colors"
                  onClick={() => handleSort("amount")}
                >
                  <div className="flex items-center justify-end gap-2">
                    Amount
                    <ArrowUpDown className="w-3 h-3" />
                  </div>
                </th>
                <th
                  className="px-6 py-3 text-left text-xs font-mono uppercase tracking-wider text-muted-foreground cursor-pointer hover:text-foreground transition-colors"
                  onClick={() => handleSort("category")}
                >
                  <div className="flex items-center gap-2">
                    Category
                    <ArrowUpDown className="w-3 h-3" />
                  </div>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {sortedTransactions.map((transaction: { id: Key | null | undefined; date: string | number | bigint | boolean | ReactElement<unknown, string | JSXElementConstructor<any>> | Iterable<ReactNode> | ReactPortal | Promise<string | number | bigint | boolean | ReactPortal | ReactElement<unknown, string | JSXElementConstructor<any>> | Iterable<ReactNode> | null | undefined> | null | undefined; description: string | number | bigint | boolean | ReactElement<unknown, string | JSXElementConstructor<any>> | Iterable<ReactNode> | ReactPortal | Promise<string | number | bigint | boolean | ReactPortal | ReactElement<unknown, string | JSXElementConstructor<any>> | Iterable<ReactNode> | null | undefined> | null | undefined; amount: number; category: string | number | bigint | boolean | ReactElement<unknown, string | JSXElementConstructor<any>> | Iterable<ReactNode> | ReactPortal | Promise<string | number | bigint | boolean | ReactPortal | ReactElement<unknown, string | JSXElementConstructor<any>> | Iterable<ReactNode> | null | undefined> | null | undefined; }, index: number) => (
                <tr
                  key={transaction.id}
                  className={`hover:bg-secondary/30 transition-colors ${index % 2 === 0 ? "bg-background" : "bg-secondary/10"
                    }`}
                >
                  <td className="px-6 py-4 font-mono text-sm text-muted-foreground">
                    {transaction.date}
                  </td>
                  <td className="px-6 py-4 text-sm text-foreground">
                    {transaction.description}
                  </td>
                  <td className="px-6 py-4 text-right font-mono text-sm text-foreground">
                    ${transaction.amount.toFixed(2)}
                  </td>
                  <td className="px-6 py-4">
                    <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-mono bg-primary/10 text-primary border border-primary/20">
                      {transaction.category}
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
