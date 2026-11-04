import { Activity, BarChart3, Cable, ClipboardList, Database, Flame, GitCompare, Inbox, LayoutDashboard, MessageCircleQuestion, Radio, Search, ShieldCheck, Stethoscope, Wind, Wrench, Zap } from "lucide-react";
import GuidedTour from "../features/tour/GuidedTour";
import { NavLink, Outlet } from "react-router-dom";
import { useAsync } from "../hooks/useAsync";
import { getHealth } from "../api/client";
import { PersonaSwitcher } from "../plant";

type NavItem = { to: string; label: string; icon: typeof LayoutDashboard; end?: boolean };
const NAV_SECTIONS: { title: string; items: NavItem[] }[] = [
  {
    title: "Core",
    items: [
      { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
      { to: "/replay", label: "Replay", icon: Radio },
      { to: "/investigations", label: "Investigations", icon: Search },
      { to: "/compare", label: "Compare cases", icon: GitCompare },
      { to: "/data", label: "Data Sources", icon: Database },
      { to: "/evaluation", label: "Evaluation & Trust", icon: ShieldCheck },
    ],
  },
  {
    title: "Plant operations",
    items: [
      { to: "/inbox", label: "Inbox", icon: Inbox },
      { to: "/ask", label: "Ask the plant", icon: MessageCircleQuestion },
      { to: "/planner", label: "Maintenance planner", icon: Wrench },
      { to: "/instruments", label: "Instrument health", icon: Stethoscope },
      { to: "/emissions", label: "Emissions watch", icon: Wind },
      { to: "/thermal", label: "Thermal monitoring", icon: Flame },
      { to: "/grid", label: "Grid support", icon: Zap },
      { to: "/ops", label: "Shift ops", icon: ClipboardList },
      { to: "/connectors", label: "Plant connectors", icon: Cable },
    ],
  },
];

export function Layout() {
  const health = useAsync((s) => getHealth(s), []);
  const h = health.data;

  return (
    <div className="flex min-h-screen bg-ink-900">
      <aside className="sticky top-0 flex h-screen w-64 shrink-0 flex-col border-r border-ink-700 bg-ink-950">
        <div className="flex items-center gap-3 px-5 py-5">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-600 shadow-sm">
            <Activity size={22} className="text-white" />
          </div>
          <div>
            <div className="text-lg font-bold tracking-tight text-ink-50">ThermoMind</div>
            <div className="text-xs font-medium uppercase tracking-wider text-ink-400">Diagnostic Intelligence</div>
          </div>
        </div>
        <div className="px-3 pb-1">
          <PersonaSwitcher />
        </div>
        <nav className="mt-2 flex flex-1 flex-col gap-1 overflow-y-auto px-3">
          {NAV_SECTIONS.map((section) => (
            <div key={section.title} className="mb-1">
              <div className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-ink-500">{section.title}</div>
              {section.items.map(({ to, label, icon: Icon, end }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-lg px-3 py-2 text-[15px] font-medium transition ${
                      isActive ? "bg-blue-50 text-blue-800 ring-1 ring-blue-200" : "text-ink-300 hover:bg-ink-800 hover:text-ink-100"
                    }`
                  }
                >
                  <Icon size={18} strokeWidth={2} />
                  {label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="border-t border-ink-700 px-5 py-4 text-sm text-ink-400">
          <div className="flex items-center gap-2">
            <BarChart3 size={14} />
            <span className="font-semibold text-ink-300">Read-only decision support</span>
          </div>
          <p className="mt-1.5 leading-snug">No plant control actions are possible from this software.</p>
          <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-xs">
            {health.loading ? (
              <span className="text-ink-500">checking API…</span>
            ) : h ? (
              <>
                <span className={h.status === "ok" ? "text-green-800" : "text-amber-700"}>API {h.status}</span>
                <span>·</span>
                <span>v{h.version}</span>
                <span>·</span>
                <span className={h.data_ready ? "text-ink-300" : "text-amber-700"}>data {h.data_ready ? "ready" : "missing"}</span>
                <span>·</span>
                <span className={h.model_ready ? "text-ink-300" : "text-amber-700"}>model {h.model_ready ? "ready" : "missing"}</span>
                <span>·</span>
                <span className={h.meta_configured ? "text-blue-700" : "text-ink-400"}>
                  meta {h.meta_configured ? "configured" : "not configured"}
                </span>
              </>
            ) : (
              <span className="text-red-700">API unreachable (:8000)</span>
            )}
          </div>
        </div>
      </aside>
      <main className="min-w-0 flex-1">
        <div className="mx-auto max-w-[1400px] px-8 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-bold tracking-tight text-ink-50">{title}</h1>
        {subtitle ? <div className="mt-1 max-w-3xl text-base text-ink-300">{subtitle}</div> : null}
      </div>
      {right ? <div className="flex shrink-0 flex-wrap items-center gap-2">{right}</div> : null}
      <GuidedTour />
    </div>
  );
}
