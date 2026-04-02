import { Outlet, Link, useLocation } from "react-router";
import { BarChart3, TrendingUp, AlertTriangle, Users, Upload } from "lucide-react";
import { cn } from "./ui/utils";

const navItems = [
  { path: "/overview", label: "Overview", icon: BarChart3 },
  { path: "/predictions", label: "Predictions", icon: TrendingUp },
  { path: "/anomalies", label: "Anomalies", icon: AlertTriangle },
  { path: "/segmentation", label: "Segmentation", icon: Users },
];

export function Layout() {
  const location = useLocation();
  const isUploadPage = location.pathname === "/";

  return (
    <div className="flex h-screen bg-background overflow-hidden">
      {/* Fixed Sidebar */}
      <aside className="w-60 bg-sidebar border-r border-border flex flex-col">
        {/* Logo/Brand */}
        <Link to="/" className="block hover:opacity-80 transition-opacity">
          <div className="p-6 border-b border-border">
            <h1 className="text-xl font-sans text-primary tracking-tight">
              FinSight
            </h1>
            <p className="text-xs text-muted-foreground mt-1 font-mono">
              ANALYTICS TERMINAL
            </p>
          </div>
        </Link>

        {/* Navigation */}
        <nav className="flex-1 p-4 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = location.pathname === item.path;

            return (
              <Link
                key={item.path}
                to={item.path}
                className={cn(
                  "flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 text-sm",
                  "border-l-2 -ml-4 pl-4",
                  isActive
                    ? "border-primary bg-secondary/50 text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground hover:bg-secondary/30"
                )}
              >
                <Icon className="w-4 h-4" />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        {/* Upload Status at Bottom */}
        <div className="p-4 border-t border-border">
          <div className="bg-secondary rounded-lg p-3">
            <div className="flex items-center gap-2 mb-2">
              <Upload className="w-4 h-4 text-muted-foreground" />
              <span className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                Status
              </span>
            </div>
            <div className="flex items-center gap-2">
              <div className={cn(
                "w-2 h-2 rounded-full",
                isUploadPage ? "bg-muted-foreground" : "bg-primary animate-pulse"
              )} />
              <span className="text-sm text-foreground font-mono">
                {isUploadPage ? "Idle" : "Ready"}
              </span>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
