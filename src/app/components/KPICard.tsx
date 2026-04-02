import { ArrowUp, ArrowDown } from "lucide-react";

interface KPICardProps {
  label: string;
  value: string;
  trend?: {
    direction: "up" | "down";
    percentage: string;
  };
  variant?: "default" | "warning";
}

export function KPICard({ label, value, trend, variant = "default" }: KPICardProps) {
  const isWarning = variant === "warning";
  
  return (
    <div className={`bg-card border rounded-lg p-6 transition-all duration-300 ${
      isWarning 
        ? "border-destructive/50 shadow-[0_0_20px_rgba(248,81,73,0.15)]" 
        : "border-border shadow-[0_0_15px_rgba(0,212,200,0.08)]"
    }`}>
      <div className="text-[11px] font-mono uppercase tracking-[0.1em] text-muted-foreground mb-3">
        {label}
      </div>
      <div className={`text-[32px] font-mono leading-none mb-2 ${
        isWarning ? "text-destructive" : "text-foreground"
      }`}>
        {value}
      </div>
      {trend && (
        <div className="flex items-center gap-1.5 font-mono text-xs">
          {trend.direction === "up" ? (
            <ArrowUp className={`w-3 h-3 ${isWarning ? "text-destructive" : "text-primary"}`} />
          ) : (
            <ArrowDown className="w-3 h-3 text-destructive" />
          )}
          <span
            className={
              trend.direction === "up" 
                ? (isWarning ? "text-destructive" : "text-primary") 
                : "text-destructive"
            }
          >
            {trend.percentage}
          </span>
        </div>
      )}
    </div>
  );
}
