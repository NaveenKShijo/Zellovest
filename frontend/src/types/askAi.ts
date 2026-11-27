/**
 * Ask AI Conversational Workspace Types (PRD #23, #24, #25 & Module M8)
 */

export interface AskAICitation {
  source_type: string; // 'document' | 'database' | 'calculation'
  source_id: string;
  description: string;
  excerpt?: string | null;
}

export interface EvidenceItem {
  evidence_id: string;
  kind: 'document' | 'structured' | 'calculation' | 'external' | 'action';
  title: string;
  tool: string;
  server: string;
  source_id?: string | null;
  document_id?: string | null;
  chunk_id?: string | null;
  page?: number | null;
  section?: string | null;
  /** Bounding box coordinates: [x0, y0, x1, y1] */
  bbox?: number[] | null;
  excerpt?: string | null;
  as_of?: string | null;
  unavailable?: boolean;
}

export interface DataGap {
  tool?: string | null;
  server?: string | null;
  code: string;
  message: string;
  retryable?: boolean;
}

export interface AnswerSections {
  /** Grounded, verified facts observed in structured data or source passages */
  facts: string[];
  /** Deterministic calculations, aggregations, and variances */
  calculations: string[];
  /** Plausible explanations and probabilistic inferences */
  hypotheses: string[];
  /** Items, conflicts, or missing data requiring human review */
  needs_review: string[];
}

export interface ProposedAction {
  action_id: string;
  tool: string;
  server: string;
  risk_class: 'low_risk' | 'high_risk' | string;
  description: string;
  arguments: Record<string, unknown>;
  idempotency_key: string;
  requires_confirmation: boolean;
  dry_run_by_default?: boolean;
  executed: boolean;
  result?: Record<string, unknown> | null;
  preview?: Record<string, unknown> | null;
  error?: string | null;
}

export interface ToolCall {
  tool: string;
  arguments?: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  error?: string | null;
  server?: string | null;
  risk_class?: string | null;
  success: boolean;
  latency_ms?: number;
  attempts?: number;
  purpose?: string | null;
}

export interface AskAIResponse {
  answer: string;
  conversation_id: string;
  citations: AskAICitation[];
  tool_calls?: ToolCall[];
  confidence: number;
  processing_time_ms: number;
  evidence?: EvidenceItem[];
  proposed_actions?: ProposedAction[];
  data_gaps?: DataGap[];
  sections?: AnswerSections;
  intent?: string | null;
  plan_source?: string | null;
  trace_id?: string | null;
  generated_at?: string;
}

export interface ConversationMessage {
  message_id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  citations?: AskAICitation[];
  evidence?: EvidenceItem[];
  proposed_actions?: ProposedAction[];
  data_gaps?: DataGap[];
  tool_calls?: ToolCall[];
  sections?: AnswerSections;
  intent?: string | null;
  confidence?: number;
  processing_time_ms?: number;
  error?: boolean;
}

export interface ConversationHistory {
  conversation_id: string;
  question: string;
  answer: string;
  created_at: string;
  title: string;
  message_count: number;
  last_message_at?: string | null;
  messages: ConversationMessage[];
}

export interface ConversationListResponse {
  conversations: ConversationHistory[];
  total: number;
  page: number;
  page_size: number;
}

export interface ActionPreviewRequest {
  tool_name: string;
  arguments: Record<string, unknown>;
}

export interface ActionPreviewResponse {
  tool: string;
  server: string;
  risk_class: string;
  requires_confirmation: boolean;
  arguments: Record<string, unknown>;
  preview: {
    summary: string;
    impact: string;
    target_entity?: string;
    financial_impact?: number | string | null;
    reversible: boolean;
    parameters_diff?: Record<string, { before: unknown; after: unknown }>;
    warnings?: string[];
    [key: string]: unknown;
  };
}

export interface ActionConfirmRequest {
  tool_name: string;
  arguments: Record<string, unknown>;
  idempotency_key?: string;
  conversation_id?: string;
  confirmation_note?: string;
}

export interface ActionConfirmResponse {
  tool: string;
  server: string;
  risk_class: string;
  success: boolean;
  result?: Record<string, unknown> | null;
  error?: string | null;
  expires_at?: string | null;
  conversation_id?: string | null;
}

export type AskAIStreamEvent =
  | { type: 'start'; conversation_id: string; trace_id: string }
  | { type: 'plan'; intent: string; source: string; tools: string[]; needs_clarification?: boolean }
  | { type: 'tool'; tool: string; server: string; risk_class: string; success: boolean; error?: string | null }
  | { type: 'actions'; proposed_actions: ProposedAction[] }
  | { type: 'status'; stage: string }
  | { type: 'token'; content: string }
  | { type: 'gaps'; data_gaps: DataGap[] }
  | ({ type: 'complete'; conversation_id: string } & AskAIResponse)
  | { type: 'error'; code: string; message: string };
