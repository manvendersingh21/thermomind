/** Types for GET /api/agents/tree. */
export type NodeKind = "llm_agent" | "tool" | "engine" | "validator" | "human" | "model" | "group";

export type StatValue = number | string | null;

export interface AgentBudget {
  max_tokens?: number | null;
  max_tool_rounds?: number | null;
  time_budget_s?: number | null;
}

export interface AgentNode {
  id: string;
  name: string;
  kind: NodeKind;
  model: string | null;
  description: string;
  permissions: string[];
  budget: AgentBudget | null;
  may_call: string[];
  stats: Record<string, StatValue>;
  meta: Record<string, unknown>;
  children: AgentNode[];
}

export interface AgentTreeTotals {
  nodes: number;
  by_kind: Record<string, number>;
  llm_agents: number;
  deterministic_nodes: number;
  subsystem_agents: number;
  stored_investigations: number;
}

export interface AgentTree {
  generated_at_utc: string;
  root: AgentNode;
  totals: AgentTreeTotals;
  disclaimer: string;
}
