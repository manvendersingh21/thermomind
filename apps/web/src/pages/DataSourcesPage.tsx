import { Check, Copy, ExternalLink, FileUp, Upload } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { getDataset, listDatasets, uploadDataset } from "../api/client";
import type { UploadResult } from "../api/types";
import { EmptyDataset, ErrorBanner, PanelSkeleton, Spinner, WarnBanner } from "../components/Feedback";
import { PageHeader } from "../components/Layout";
import { SourceBadge } from "../components/SourceBadge";
import { useAsync } from "../hooks/useAsync";
import { fmtBytes, fmtDateTime, fmtInt, fmtNum, truncateMiddle } from "../lib/format";

function CopyHash({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  }
  return (
    <span className="inline-flex max-w-full items-center gap-2 font-mono text-sm">
      <span title={value} className="break-all">{truncateMiddle(value, 12, 8)}</span>
      <button type="button" onClick={copy} className="rounded border border-ink-600 p-1 text-ink-300 hover:border-blue-400 hover:text-blue-700" title="Copy sha256" aria-label="Copy sha256">
        {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
      </button>
    </span>
  );
}

export function DataSourcesPage() {
  const datasets = useAsync((s) => listDatasets(s), []);
  const [selected, setSelected] = useState<string | null>(null);
  const selectedId = selected ?? datasets.data?.find((d) => d.dataset_id === "ds_uci_551")?.dataset_id ?? datasets.data?.[0]?.dataset_id ?? null;
  const detail = useAsync(async (s) => (selectedId ? getDataset(selectedId, s) : null), [selectedId]);

  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<unknown>(null);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);

  async function onUpload(file: File | undefined) {
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    setUploadResult(null);
    try {
      const res = await uploadDataset(file);
      setUploadResult(res);
      datasets.reload();
      setSelected(res.dataset_id);
    } catch (e) {
      setUploadError(e);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const d = detail.data;
  const datasetEmpty = !datasets.loading && !datasets.error && (datasets.data?.length ?? 0) === 0;
  const doi = useMemo(() => (d?.source_url && d.source_url.includes("doi.org") ? d.source_url : "https://doi.org/10.24432/C5WC95"), [d]);

  return (
    <div>
      <PageHeader
        title="Data Sources"
        subtitle="Provenance for every row ThermoMind reads. Rows are ordered hourly aggregates; the dataset has no row-level timestamps and no verified fault labels."
        right={<SourceBadge variant="real" label="REAL UCI TURBINE DATA · CC BY 4.0" />}
      />
      {datasets.error ? <ErrorBanner className="mb-5" title="Could not load datasets" error={datasets.error} onRetry={datasets.reload} /> : null}
      {datasetEmpty ? <EmptyDataset className="mb-5" /> : null}

      <div className="mb-5 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="panel min-w-0 overflow-hidden xl:col-span-2">
          <div className="panel-header">
            <div className="panel-title">Registered datasets</div>
          </div>
          {datasets.loading ? (
            <div className="p-5">
              <PanelSkeleton lines={3} />
            </div>
          ) : (
            <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Dataset</th>
                  <th>Source</th>
                  <th>Rows</th>
                  <th>Years</th>
                  <th>Timestamps</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {(datasets.data ?? []).map((ds) => (
                  <tr key={ds.dataset_id} className={`cursor-pointer hover:bg-ink-800/60 ${ds.dataset_id === selectedId ? "bg-blue-50/60" : ""}`} onClick={() => setSelected(ds.dataset_id)}>
                    <td className="break-all font-mono text-blue-700">{ds.dataset_id}</td>
                    <td>
                      <div className="flex items-center gap-2">
                        {ds.source === "UCI_GAS_TURBINE_551" ? <SourceBadge variant="real" size="sm" label="UCI 551" /> : <SourceBadge variant="offline" size="sm" label="USER UPLOAD" />}
                        <span className="text-sm text-ink-300">{ds.source_license ?? "license unspecified"}</span>
                      </div>
                    </td>
                    <td className="font-mono">{fmtInt(ds.row_count)}</td>
                    <td className="font-mono text-sm">{ds.years.join(", ")}</td>
                    <td className="text-sm text-ink-300">{ds.has_timestamps ? "row-level timestamps" : "No row-level timestamps (ordered hourly samples)"}</td>
                    <td className="whitespace-nowrap text-sm text-ink-300">{fmtDateTime(ds.created_at_utc)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </div>
        <div className="panel min-w-0">
          <div className="panel-header">
            <div className="panel-title flex items-center gap-2">
              <Upload size={18} className="text-ink-300" /> Upload CSV
            </div>
          </div>
          <div className="px-5 py-4 text-base">
            <p className="text-sm text-ink-300">
              Same column layout as the UCI files (AT, AP, AH, AFDP, GTEP, TIT, TAT, TEY, CDP, CO, NOX). Name the file like{" "}
              <code className="font-mono text-ink-100">gt_2016.csv</code> to infer the year. Uploads are labelled USER_UPLOAD and never mixed into the UCI dataset.
            </p>
            <input ref={fileRef} type="file" aria-label="Choose CSV file to upload" accept=".csv,text/csv" className="hidden" onChange={(e) => onUpload(e.target.files?.[0])} />
            <button type="button" className="btn-secondary mt-3 w-full" onClick={() => fileRef.current?.click()} disabled={uploading}>
              {uploading ? <Spinner /> : <FileUp size={18} />} {uploading ? "Validating…" : "Choose CSV file"}
            </button>
            {uploadError ? <ErrorBanner className="mt-3" title="Upload rejected" error={uploadError} /> : null}
            {uploadResult ? (
              <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50/60 px-3 py-2.5 text-sm">
                <div className="font-semibold text-blue-800">Registered {uploadResult.dataset_id}</div>
                <div className="mt-1 text-ink-200">
                  {fmtInt(uploadResult.rows)} rows · {uploadResult.columns.length} columns · sha256 <CopyHash value={uploadResult.sha256} />
                </div>
                {uploadResult.warnings.length > 0 ? (
                  <WarnBanner className="mt-2">
                    <ul className="list-disc pl-4">
                      {uploadResult.warnings.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </WarnBanner>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      </div>

      {detail.error ? <ErrorBanner className="mb-5" title="Could not load dataset detail" error={detail.error} onRetry={detail.reload} /> : null}
      {detail.loading && selectedId ? <PanelSkeleton lines={6} className="mb-5" /> : null}
      {d ? (
        <>
          <div className="mb-5 grid grid-cols-1 gap-4 xl:grid-cols-3">
            <div className="panel min-w-0 px-5 py-4 xl:col-span-2">
              <div className="label mb-2">Dataset detail</div>
              <dl className="grid grid-cols-1 gap-x-4 sm:grid-cols-[180px_minmax(0,1fr)] gap-y-2 text-base">
                <dt className="mt-2 text-ink-300 sm:mt-0">Dataset id</dt>
                <dd className="break-all font-mono">{d.dataset_id}</dd>
                <dt className="mt-2 text-ink-300 sm:mt-0">Source</dt>
                <dd className="break-all font-mono">{d.source}</dd>
                <dt className="mt-2 text-ink-300 sm:mt-0">License</dt>
                <dd>{d.source_license ?? "—"}</dd>
                <dt className="mt-2 text-ink-300 sm:mt-0">Citation</dt>
                <dd className="break-words text-ink-100">{d.citation ?? "—"}</dd>
                <dt className="mt-2 text-ink-300 sm:mt-0">DOI / URL</dt>
                <dd>
                  {d.source === "UCI_GAS_TURBINE_551" ? (
                    <a href={doi} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-blue-700 hover:underline">
                      10.24432/C5WC95 <ExternalLink size={14} />
                    </a>
                  ) : null}
                  {d.source_url ? (
                    <a href={d.source_url} target="_blank" rel="noreferrer" className="ml-3 inline-flex items-center gap-1 text-blue-700 hover:underline">
                      source page <ExternalLink size={14} />
                    </a>
                  ) : (
                    <span className="text-ink-400">—</span>
                  )}
                </dd>
                <dt className="mt-2 text-ink-300 sm:mt-0">Plant</dt>
                <dd>{d.plant ?? "—"}</dd>
                <dt className="mt-2 text-ink-300 sm:mt-0">Years</dt>
                <dd className="font-mono">{d.years.join(", ")}</dd>
                <dt className="mt-2 text-ink-300 sm:mt-0">Time axis</dt>
                <dd>
                  {d.has_timestamps ? "Row-level timestamps" : "No row-level timestamps (ordered hourly samples)"}{" "}
                  <span className="break-all font-mono text-sm text-ink-400">{d.time_axis_type}</span>
                </dd>
                <dt className="mt-2 text-ink-300 sm:mt-0">Rows</dt>
                <dd className="font-mono">{fmtInt(d.row_count)}</dd>
              </dl>
              {d.warnings.length > 0 ? (
                <WarnBanner className="mt-4">
                  <ul className="list-disc pl-4">
                    {d.warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </WarnBanner>
              ) : null}
            </div>
            <div className="panel min-w-0 px-5 py-4">
              <div className="label mb-2">Rows per year</div>
              <div className="overflow-x-auto">
              <table className="table-base">
                <tbody>
                  {Object.entries(d.rows_per_year)
                    .sort(([a], [b]) => a.localeCompare(b))
                    .map(([y, n]) => (
                      <tr key={y}>
                        <td className="font-mono">{y}</td>
                        <td className="text-right font-mono">{fmtInt(n)}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
              </div>
            </div>
          </div>

          <div className="panel mb-5 overflow-hidden">
            <div className="panel-header">
              <div>
                <div className="panel-title">Measurement catalog</div>
                <div className="mt-0.5 text-sm text-ink-300">
                  Units as published by the source. <span className="text-amber-800">CDP: “mbar” is as published and under validation — treat the unit with caution.</span>
                </div>
              </div>
            </div>
            <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Key</th>
                  <th>Name</th>
                  <th>Unit</th>
                  <th className="text-right">Count</th>
                  <th className="text-right">Missing</th>
                  <th className="text-right">Min</th>
                  <th className="text-right">Median</th>
                  <th className="text-right">Max</th>
                </tr>
              </thead>
              <tbody>
                {d.measurements.map((m) => (
                  <tr key={m.key}>
                    <td className="font-mono font-semibold text-blue-700">{m.key}</td>
                    <td>{m.name}</td>
                    <td className={m.key === "CDP" ? "text-amber-800" : "text-ink-200"}>{m.unit}</td>
                    <td className="text-right font-mono">{fmtInt(m.count)}</td>
                    <td className={`text-right font-mono ${m.missing > 0 ? "text-amber-800" : ""}`}>{fmtInt(m.missing)}</td>
                    <td className="text-right font-mono">{fmtNum(m.min, 2)}</td>
                    <td className="text-right font-mono">{fmtNum(m.median, 2)}</td>
                    <td className="text-right font-mono">{fmtNum(m.max, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </div>

          <div className="mb-5 grid grid-cols-1 gap-4 xl:grid-cols-2">
            <div className="panel min-w-0 overflow-hidden">
              <div className="panel-header">
                <div className="panel-title">Source files</div>
              </div>
              <div className="overflow-x-auto">
              <table className="table-base">
                <thead>
                  <tr>
                    <th>File</th>
                    <th>Year</th>
                    <th className="text-right">Rows</th>
                    <th className="text-right">Size</th>
                    <th>sha256</th>
                  </tr>
                </thead>
                <tbody>
                  {d.source_files.map((f) => (
                    <tr key={f.filename}>
                      <td className="break-all font-mono text-sm">{f.filename}</td>
                      <td className="font-mono">{f.source_year ?? "—"}</td>
                      <td className="text-right font-mono">{fmtInt(f.rows)}</td>
                      <td className="text-right font-mono text-sm">{fmtBytes(f.bytes)}</td>
                      <td>
                        <CopyHash value={f.sha256} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            </div>
            <div className="panel min-w-0">
              <div className="panel-header">
                <div className="panel-title">Provenance notes</div>
              </div>
              <div className="px-5 py-4">
                {d.provenance_notes.length === 0 ? (
                  <div className="text-base text-ink-400">No provenance notes.</div>
                ) : (
                  <ul className="list-disc space-y-2 break-words pl-5 text-base text-ink-100 [overflow-wrap:anywhere]">
                    {d.provenance_notes.map((n, i) => (
                      <li key={i}>{n}</li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
