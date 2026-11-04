import { Activity, BarChart3, Menu, X, Cable, Network, ClipboardList, Database, Flame, GitCompare, Inbox, LayoutDashboard, MessageCircleQuestion, Radio, Search, ShieldCheck, Stethoscope, Wind, Wrench, Zap } from "lucide-react";
import GuidedTour from "../features/tour/GuidedTour";
import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
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
      { to: "/agents", label: "Agent organisation", icon: Network },
    ],
  },
];

const DESKTOP_QUERY = "(min-width: 1024px)";

function useIsDesktop(): boolean {
  const get = () => (typeof window === "undefined" || !window.matchMedia ? true : window.matchMedia(DESKTOP_QUERY).matches);
  const [isDesktop, setIsDesktop] = useState(get);
  useEffect(() => {
    if (!window.matchMedia) return;
    const mq = window.matchMedia(DESKTOP_QUERY);
    const on = () => setIsDesktop(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return isDesktop;
}

const FOCUSABLE = 'a[href], button:not([disabled]), select:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function Layout() {
  const health = useAsync((s) => getHealth(s), []);
  const h = health.data;
  const isDesktop = useIsDesktop();
  const [menuOpen, setMenuOpen] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const location = useLocation();

  const offCanvas = !isDesktop;
  const drawerOpen = offCanvas && menuOpen;
  const drawerClosed = offCanvas && !menuOpen;
  const closeMenu = useCallback(() => setMenuOpen(false), []);

  // Leaving the off-canvas layout or navigating closes the menu.
  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname, isDesktop]);

  // Focus management, Escape and focus trap while the off-canvas sidebar is open.
  useEffect(() => {
    if (!drawerOpen) return;
    const sidebar = sidebarRef.current;
    const toRestore = menuButtonRef.current;
    const first = sidebar?.querySelector<HTMLElement>("[data-menu-close]");
    first?.focus();
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setMenuOpen(false);
        return;
      }
      if (e.key !== "Tab" || !sidebar) return;
      const items = Array.from(sidebar.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) return;
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === firstEl || !sidebar.contains(active))) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && (active === lastEl || !sidebar.contains(active))) {
        e.preventDefault();
        firstEl.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      toRestore?.focus();
    };
  }, [drawerOpen]);

  const hiddenProps = drawerClosed ? ({ "aria-hidden": true, inert: "" } as Record<string, unknown>) : {};
  const dialogProps = drawerOpen ? { role: "dialog", "aria-modal": true, "aria-label": "Main navigation" } : {};

  return (
    <div className="flex min-h-screen flex-col bg-ink-900 lg:flex-row">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[100] focus:rounded-lg focus:bg-blue-700 focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-white focus:shadow-lg"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-ink-700 bg-ink-950 px-4 py-3 lg:hidden">
        <button
          ref={menuButtonRef}
          type="button"
          className="btn-secondary h-10 w-10 px-0"
          aria-label="Open navigation menu"
          aria-expanded={drawerOpen}
          aria-controls="app-sidebar"
          onClick={() => setMenuOpen(true)}
        >
          <Menu size={20} aria-hidden="true" />
        </button>
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 shadow-sm">
            <Activity size={18} className="text-white" aria-hidden="true" />
          </div>
          <span className="text-base font-bold tracking-tight text-ink-50">ThermoMind</span>
        </div>
      </header>
      {drawerOpen ? <div className="fixed inset-0 z-40 bg-slate-900/40 lg:hidden" onClick={closeMenu} aria-hidden="true" /> : null}
      <aside
        id="app-sidebar"
        ref={sidebarRef}
        {...hiddenProps}
        {...dialogProps}
        className={`fixed inset-y-0 left-0 z-50 flex h-[100dvh] w-64 max-w-[85vw] shrink-0 flex-col border-r border-ink-700 bg-ink-950 shadow-2xl transition-transform duration-200 lg:sticky lg:top-0 lg:z-auto lg:h-screen lg:max-w-none lg:translate-x-0 lg:shadow-none ${
          drawerClosed ? "-translate-x-full" : "translate-x-0"
        }`}
      >
        <div className="flex items-center gap-3 px-5 py-5">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-600 shadow-sm">
            <Activity size={22} className="text-white" aria-hidden="true" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-lg font-bold tracking-tight text-ink-50">ThermoMind</div>
            <div className="text-xs font-medium uppercase tracking-wider text-ink-400">Diagnostic Intelligence</div>
          </div>
          <button type="button" data-menu-close className="btn-secondary h-9 w-9 px-0 lg:hidden" aria-label="Close navigation menu" onClick={closeMenu}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="px-3 pb-1">
          <PersonaSwitcher />
        </div>
        <nav className="mt-2 flex flex-1 flex-col gap-1 overflow-y-auto px-3">
          {NAV_SECTIONS.map((section) => (
            <div key={section.title} className="mb-1">
              <div className="px-3 pb-1 pt-2 text-xs font-semibold uppercase tracking-wider text-ink-500">{section.title}</div>
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
                  <Icon size={18} strokeWidth={2} aria-hidden="true" />
                  {label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="border-t border-ink-700 px-5 py-4 text-sm text-ink-400">
          <div className="flex items-center gap-2">
            <BarChart3 size={14} aria-hidden="true" />
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
      <main id="main" tabIndex={-1} className="min-w-0 flex-1 outline-none">
        <div className="mx-auto max-w-[1400px] px-4 py-6 sm:px-8 sm:py-8">
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
      {right ? <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2 sm:shrink-0">{right}</div> : null}
      <GuidedTour />
    </div>
  );
}
