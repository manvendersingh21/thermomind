# Safety

## Purpose and scope

ThermoMind is **read-only decision support** for performance and reliability engineers. It reads exported or public measurements, computes evidence, asks a language model to draft an investigation report, validates that draft, and waits for a human decision. It is not a monitoring system, not a protection system, not an alarm system and not a controller.

Concretely:

- **Zero write endpoints toward control systems.** The API has no code path that talks to a PLC, SCADA, DCS, historian, OPC server or any plant network. The only writes are to its own SQLite database (investigation records and review decisions).
- **No control language.** The report validator rejects drafts containing control instructions (setpoint changes, start/stop/trip commands, valve or load orders). Reports may list "engineer review checks" and "additional data needed"; they may not tell anyone to operate equipment.
- **Always a draft.** `DiagnosticReport.report_status` is the literal `draft_requires_human_review`; the engineer records `accepted`, `rejected` or `more_data_requested`. Nothing downstream consumes a report automatically.
- **Severity is a review priority, not an alarm.** `informational` / `review` / `urgent_review` rank how soon an engineer should look, not whether a plant is in danger.
- **Disclaimer in every report:** "Not a validated plant safety or control system."

## Threat model (prototype)

| Threat | Relevance to this prototype | Mitigation |
|---|---|---|
| Model hallucinates evidence or numbers | High: LLM drafts are the core output | Model may cite only evidence IDs returned by its tool calls; unknown IDs reject the draft; every evidence item carries the actual computation; one bounded rewrite then `needs_review` |
| Model fabricates dates for rows that have none | High: the data set has no timestamps | Rows are identified by `source_year` + `row_index` only; validator rejects date-like claims; UI shows `2014 • sample #1253` |
| Model emits operational instructions | High: an engineer might act on them | Validator rejects control instructions; UI copy reinforces HUMAN REVIEW REQUIRED |
| Synthetic data mistaken for real | High for a demo | `synthetic=true`, `scenario_label`, `is_synthetic`, `provenance_kind` at every layer; SYNTHETIC OVERLAY badges |
| Offline preview mistaken for Meta inference | Medium | `meta_used=false`, `mode="offline_preview"`, label "not a Meta inference" |
| API key leakage | Medium | Key read server-side from `.env`; never logged, never in exceptions (redaction regex), never returned by `/api/health`, `/api/demo/status` or `ping()`; `.env` git-ignored; Docker receives it by environment only |
| Prompt injection via uploaded CSV | Low–medium: cell contents reach the model only as numbers through tools | CSV validator enforces numeric columns; tool outputs are structured JSON built by the server, not free text from the file |
| Malicious upload (size, format) | Low | Size cap (`THERMOMIND_MAX_UPLOAD_BYTES`), header/schema validation, 400/413/422 responses, no execution of file content |
| Unauthorised access | High in production, accepted in prototype | No auth today; CORS allowlist for the dev origin; intended for localhost / single container; see below |
| Reasoning-model truncation producing empty content | Medium | `max_tokens` sized for reasoning tokens; `finish_reason="length"` handled as a failed turn, never as a report |

## What the prototype does not protect against

- It has no authentication, authorisation, audit trail of users, rate limiting or TLS termination. Do not expose it on a plant or corporate network as-is.
- It does not validate the physical correctness of hypotheses. The validator is about provenance and form.
- It does not know plant-specific limits, alarm settings or maintenance history.
- SQLite is single-writer; concurrent use is not supported.

## Future OT-security assessment (before any pilot)

1. **Deployment boundary.** ThermoMind runs in the IT zone (or an engineering workstation) on exported data; it never joins the OT network. Document the data export path (historian → CSV/parquet export → ThermoMind) and the review of that path by the plant's OT security owner.
2. **Identity and access.** SSO (OIDC), role-based access (viewer / reviewer / admin), per-case audit log with reviewer identity, retention policy.
3. **Secrets.** Key vault instead of `.env`; rotation; outbound allowlist for `api.meta.ai` only.
4. **Data governance.** Which measurements leave the site to the model provider, in what form (ThermoMind sends tool results: aggregated statistics and small windows, not whole historians), data-processing agreement, residency requirements.
5. **Model governance.** Pin model version; record model id, prompt hash, tool spec hash and `report_hash` per case; regression suite of frozen cases; human review rate monitored.
6. **Standards mapping.** Assess against IEC 62443 zone/conduit model, NIST SP 800-82 (OT security), and the owner's management-of-change procedure. The result should state explicitly that ThermoMind is a non-safety, non-control, advisory system with no path to actuation.
7. **Independent review.** External penetration test of the web/API surface and a design review of the validator before it is trusted with non-public plant data.
