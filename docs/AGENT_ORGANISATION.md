# Agent organisation

All agents are read-only and advisory. None has a path to PLC/SCADA/DCS/historian writes, setpoints or control commands. Reports stay `draft_requires_human_review`; humans review and act per site procedures.

The live tree is served by `GET /api/agents/tree` (code: `apps/api/app/features/agents_tree/`, UI: `apps/web/src/features/agents_tree/`). It returns `{generated_at_utc, root, totals, disclaimer}`. Each node carries `id, name, kind, model, description, permissions, budget, may_call, stats, meta, children`.

## The tree

```
ThermoMind orchestrator (read-only; no control path)
|- Investigation agent (Muse Spark, tool loop)            llm_agent  muse-spark-1.3
|  |- get_sensor_window, get_baseline_comparison, evaluate_hypothesis,
|  |  get_data_quality, list_evidence, lookup_reference, recall_similar_cases   (tools, deterministic)
|  `- GPU second-opinion model (mlp_v1)                    model, second opinion only
|- Plant what-if aggregator                               llm_agent
|  |- simulate_change                                      tool
|  `- one agent per subsystem (5 today, from plant/subsystems.py)   llm_agent
|- Operations agents:  shift-handover drafter, grid-event drill agent      llm_agent
|- Deterministic screening engines (no LLM): evidence, instrument health, emissions watch,
|     thermal model, maintenance planner, grid readiness/contingency        engine
`- Validators & humans: report validator, unsafe-pattern scan, human review (demo personas)
```

Node kinds: `llm_agent` (blue), `tool` (gray), `engine` (green), `validator` (yellow), `human` (amber), `model` (purple), plus `group` for pure grouping nodes.

## Permissions and budgets

- Every node lists `permissions`, and every node includes `no plant control`. Others: `read-only data`, `draft only`, `second opinion only`, `synthetic overlay only`, `decides and acts per site procedures` (humans).
- Every `llm_agent` names its model (`muse-spark-1.3`) and a `budget` (`max_tokens` per call, `max_tool_rounds`, `time_budget_s` where one exists). Values are read from the same constants the agents use (`config.META_MAX_TOKENS`, `plant/whatif.py`, ...).

## Live stats

Computed per request from the SQLite file (`config.DB_PATH`) through a `query_only` connection. A missing file or table gives zeros.

| Node | Stats |
|---|---|
| Investigation agent | stored cases, live vs offline, median tool calls per live case |
| Each investigation tool | calls found in stored case events |
| What-if aggregator | sessions, live vs offline, needs review |
| Subsystem agents | runs and ok rate, from `whatif_sessions[].agents[]` |
| Handover drafter / grid drill agent | notes / drills, live vs offline (`handover_notes`, `grid_drills`) |
| Human review | cases with a stored review decision, by decision |

Engines, validators and persona nodes are stateless and show no counts.

## n+1: adding an agent

Append one dict to the registry (`build_registry()` in `agents_tree/registry.py`). The entry shape:

```python
{"id": "agent.whatif.my_area",            # unique, "<kind>.<slug>"
 "parent": "agent.whatif",                # parent node id (None only for the root)
 "name": "My area agent",
 "kind": "llm_agent",                     # llm_agent | tool | engine | validator | human | model | group
 "model": "muse-spark-1.3",               # required for llm_agent, None otherwise
 "description": "one sentence",
 "permissions": ["read-only data", "draft only", "no plant control"],   # must contain "no plant control"
 "budget": {"max_tokens": 3000, "max_tool_rounds": 1, "time_budget_s": 55},   # required for llm_agent
 "calls": ["tool.simulate_change"],       # optional extra may_call ids; children are added automatically
 "stats_key": "subsystem:my_area",        # optional, which live-stats block to show
 "meta": {"measurements": ["AFDP"], "owner_persona": "reliability_engineer"}}
```

Plant-area agents and personas are not edited here: appending to `SUBSYSTEM_REGISTRY` (`plant/subsystems.py`) or `PERSONAS` (`plant/personas.py`) adds a node automatically, and the what-if run starts one more parallel agent. The tests (`apps/api/tests/test_agents_tree.py`) fail if an LLM node lacks a model or budget, or if any node omits `no plant control`.
