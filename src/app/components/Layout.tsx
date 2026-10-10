import { Link, NavLink, Outlet } from "react-router";
import { AlertTriangle, BarChart3, LogOut, Tags, TrendingUp, Upload } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { CookieNotice } from "./common";
import { cn } from "./ui/utils";

const navItems = [
  { path: "/", label: "Upload", icon: Upload, end: true },
  { path: "/overview", label: "Overview & Budgets", icon: BarChart3, end: false },
  { path: "/forecast", label: "Forecast", icon: TrendingUp, end: false },
  { path: "/unusual", label: "Unusual Transactions", icon: AlertTriangle, end: false },
  { path: "/categories", label: "Categories", icon: Tags, end: false },
];

function Brand() {
  return (
    <Link to="/" className="block transition-opacity hover:opacity-80">
      <h1 className="font-sans text-xl tracking-tight text-primary">FinSight</h1>
      <p className="mt-1 font-mono text-xs text-muted-foreground">BUDGET RISK &amp; TRANSACTION REVIEW</p>
    </Link>
  );
}

export function Layout() {
  const { user, logout, cookieWarning } = useAuth();

  return (
    <div className="flex min-h-screen flex-col bg-background md:h-screen md:flex-row md:overflow-hidden">
      {/* Wide screens: fixed sidebar */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-sidebar md:flex">
        <div className="border-b border-border p-6">
          <Brand />
        </div>
        <nav className="flex-1 space-y-1 p-4" aria-label="Main">
          {navItems.map(({ path, label, icon: Icon, end }) => (
            <NavLink
              key={path}
              to={path}
              end={end}
              className={({ isActive }) =>
                cn(
                  "-ml-4 flex items-center gap-3 rounded-lg border-l-2 py-2.5 pl-4 pr-3 text-sm transition-all duration-200",
                  isActive ? "border-primary bg-secondary/50 text-foreground" : "border-transparent text-muted-foreground hover:bg-secondary/30 hover:text-foreground",
                )
              }
            >
              <Icon className="h-4 w-4" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-border p-4">
          <div className="rounded-lg bg-secondary p-3">
            <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">Signed in as</p>
            <p className="mb-3 truncate text-sm text-foreground" title={user?.email}>{user?.email}</p>
            <button onClick={() => logout()} className="flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground">
              <LogOut className="h-4 w-4" /> Log out
            </button>
          </div>
        </div>
      </aside>

      {/* Narrow screens: top bar with a scrolling menu */}
      <header className="border-b border-border bg-sidebar md:hidden">
        <div className="flex items-center justify-between gap-3 px-4 py-3">
          <Brand />
          <button onClick={() => logout()} className="flex shrink-0 items-center gap-1 text-sm text-muted-foreground hover:text-foreground" aria-label="Log out">
            <LogOut className="h-4 w-4" /> Log out
          </button>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2" aria-label="Main">
          {navItems.map(({ path, label, icon: Icon, end }) => (
            <NavLink
              key={path}
              to={path}
              end={end}
              className={({ isActive }) =>
                cn(
                  "flex shrink-0 items-center gap-2 rounded-md px-3 py-2 text-sm",
                  isActive ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary/40",
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="min-w-0 flex-1 md:overflow-auto">
        {cookieWarning && <div className="px-4 pt-4 sm:px-8 sm:pt-6"><CookieNotice /></div>}
        <Outlet />
      </main>
    </div>
  );
}
