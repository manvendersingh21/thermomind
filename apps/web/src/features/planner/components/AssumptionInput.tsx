interface Props {
  id: string;
  label: string;
  unit: string;
  value: string;
  onChange: (v: string) => void;
  step?: number;
  min?: number;
  max?: number;
  hint?: string;
}

/** Numeric input with the yellow ASSUMPTION badge: every economic / planning input is user-owned. */
export function AssumptionInput({ id, label, unit, value, onChange, step, min, max, hint }: Props) {
  return (
    <label htmlFor={id} className="block">
      <span className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-ink-100">{label}</span>
        <span
          title="ASSUMPTION — edit for your plant"
          className="rounded border border-yellow-400 bg-yellow-100 px-1.5 py-px text-[11px] font-bold tracking-wide text-yellow-900"
        >
          ASSUMPTION
        </span>
      </span>
      <span className="mt-1 flex items-center gap-2">
        <input
          id={id}
          type="number"
          inputMode="decimal"
          className="input w-full font-mono"
          value={value}
          step={step}
          min={min}
          max={max}
          onChange={(e) => onChange(e.target.value)}
        />
        <span className="w-28 shrink-0 text-sm text-ink-300">{unit}</span>
      </span>
      {hint ? <span className="mt-0.5 block text-xs text-ink-400">{hint}</span> : null}
    </label>
  );
}
