/**
 * Judge tour steps. Mirrors docs/DEMO_SCRIPT.md. Copy only states what the app shows.
 * `target` is resolved at runtime from the investigation list (see GuidedTour.tsx).
 */
export type TourTarget =
  | { kind: "route"; to: string }
  | { kind: "case"; scenario: "S02_INTAKE_RESTRICTION" | "S03_SENSOR_INCONSISTENCY"; fallback: string };

export interface TourStep {
  id: string;
  title: string;
  body: string;
  goLabel: string;
  target: TourTarget;
  /** Shown only when a `case` target cannot be resolved to a stored case. */
  missingNote?: string;
}

export const TOUR_STEPS: TourStep[] = [
  {
    id: "overview",
    title: "1. Overview",
    body:
      "ThermoMind is a read-only decision-support tool: it never writes to a control system, and every report is a draft that needs engineer review. " +
      "The legend on this page explains the badges: REAL PUBLIC DATA, MODEL-DERIVED, SYNTHETIC OVERLAY, HUMAN REVIEW REQUIRED.",
    goLabel: "Go to Overview",
    target: { kind: "route", to: "/" },
  },
  {
    id: "data",
    title: "2. Data Sources",
    body:
      "The dataset card shows the UCI Gas Turbine CO and NOx data (36,733 hourly rows, 2011-2015, CC BY 4.0). " +
      "It has no timestamps and no fault labels, so charts use sample indices such as 2014 • sample #1200 rather than dates.",
    goLabel: "Go to Data Sources",
    target: { kind: "route", to: "/data" },
  },
  {
    id: "scenario",
    title: "3. Choose scenario S02",
    body:
      "Select dataset ds_uci_551 and scenario S02_INTAKE_RESTRICTION. The preview lists the transformations and carries a SYNTHETIC OVERLAY badge: " +
      "a seeded pattern is applied to a copy of real rows, and the original rows are untouched. Then run the investigation.",
    goLabel: "Go to scenario picker",
    target: { kind: "route", to: "/" },
  },
  {
    id: "case-s02",
    title: "4. The S02 case",
    body:
      "A stored case shows its mode (meta_live or offline_preview), a draft status, the evidence ledger, the baseline comparison, " +
      "ranked hypotheses with supporting and contradicting evidence ids, and the agent trace of tool calls.",
    goLabel: "Open S02 case",
    target: { kind: "case", scenario: "S02_INTAKE_RESTRICTION", fallback: "/investigations" },
    missingNote: "No stored S02 case was found, so this opens the case list. Run S02 from the Overview first.",
  },
  {
    id: "drawer",
    title: "5. Evidence drawer",
    body:
      "On the case page, click an evidence id (for example an AFDP item) to open the drawer. It shows the sample range, the observed and comparison values, " +
      "the method and the exact computation string behind the number.",
    goLabel: "Open the same case",
    target: { kind: "case", scenario: "S02_INTAKE_RESTRICTION", fallback: "/investigations" },
    missingNote: "No stored case was found, so this opens the case list.",
  },
  {
    id: "case-s03",
    title: "6. The S03 case",
    body:
      "S03_SENSOR_INCONSISTENCY is a synthetic single-sensor pattern. Compare its evidence and hypothesis ranking with S02: " +
      "the case page shows which evidence supports or contradicts each hypothesis.",
    goLabel: "Open S03 case",
    target: { kind: "case", scenario: "S03_SENSOR_INCONSISTENCY", fallback: "/investigations" },
    missingNote: "No stored S03 case was found, so this opens the case list. Run S03 from the Overview first.",
  },
  {
    id: "evaluation",
    title: "7. Evaluation & Trust",
    body:
      "The model card shows the gradient-boosting baseline, the chronological train / validation / holdout split and the naive baselines next to it. " +
      "These metrics describe how well TEY is predicted; they are not fault-detection accuracy.",
    goLabel: "Go to Evaluation",
    target: { kind: "route", to: "/evaluation" },
  },
];
