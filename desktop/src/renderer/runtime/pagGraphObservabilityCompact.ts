import { newMessageId } from "./uuid";

const DESKTOP_GOAL_ID: string = "g-desktop";

export type PagGraphRevReconciledReasonCode =
  | "post_slice"
  | "post_trace"
  | "post_refresh"
  | "user_refresh"
  | "debounce_merge"
  | "poll_retry";

export type PagSnapshotRefreshedReasonCode =
  | "user_refresh"
  | "poll_retry"
  | "post_refresh"
  | "initial_load";

function maxGraphRevForNamespaces(
  graphRevByNamespace: Readonly<Record<string, number>>,
  namespaces: readonly string[]
): number {
  let m: number = 0;
  for (const ns of namespaces) {
    const v: number = graphRevByNamespace[ns] ?? 0;
    if (v > m) {
      m = v;
    }
  }
  return m;
}

export function buildPagGraphRevReconciledTraceRow(p: {
  readonly chatId: string;
  readonly sessionId: string;
  readonly namespace: string;
  readonly graph_rev_before: number | null;
  readonly graph_rev_after: number;
  readonly reason_code: PagGraphRevReconciledReasonCode;
}): Record<string, unknown> {
  const traceId: string = newMessageId();
  const messageId: string = newMessageId();
  return {
    contract_version: "ailit_agent_runtime_v1",
    runtime_id: "ailit-desktop",
    chat_id: p.chatId,
    broker_id: `broker-${p.chatId}`,
    trace_id: traceId,
    message_id: messageId,
    parent_message_id: null,
    goal_id: DESKTOP_GOAL_ID,
    namespace: p.namespace,
    from_agent: "User:desktop",
    to_agent: `AgentWork:${p.chatId}`,
    created_at: new Date().toISOString(),
    type: "topic.publish",
    payload: {
      type: "topic.publish",
      topic: "chat",
      event_name: "pag_graph_rev_reconciled",
      payload: {
        session_id: p.sessionId,
        namespace: p.namespace,
        graph_rev_before: p.graph_rev_before,
        graph_rev_after: p.graph_rev_after,
        reason_code: p.reason_code
      }
    }
  };
}

export function buildPagSnapshotRefreshedTraceRow(p: {
  readonly chatId: string;
  readonly sessionId: string;
  readonly namespaces: readonly string[];
  readonly graphRevByNamespace: Readonly<Record<string, number>>;
  readonly reason_code: PagSnapshotRefreshedReasonCode;
}): Record<string, unknown> {
  const traceId: string = newMessageId();
  const messageId: string = newMessageId();
  const graph_rev_after: number = maxGraphRevForNamespaces(p.graphRevByNamespace, p.namespaces);
  const inner: Record<string, unknown> = {
    session_id: p.sessionId,
    graph_rev_after: graph_rev_after,
    reason_code: p.reason_code
  };
  if (p.namespaces.length === 1) {
    inner["namespace"] = p.namespaces[0] ?? "";
  } else {
    inner["namespaces"] = [...p.namespaces];
  }
  return {
    contract_version: "ailit_agent_runtime_v1",
    runtime_id: "ailit-desktop",
    chat_id: p.chatId,
    broker_id: `broker-${p.chatId}`,
    trace_id: traceId,
    message_id: messageId,
    parent_message_id: null,
    goal_id: DESKTOP_GOAL_ID,
    namespace: p.namespaces[0] ?? "",
    from_agent: "User:desktop",
    to_agent: `AgentWork:${p.chatId}`,
    created_at: new Date().toISOString(),
    type: "topic.publish",
    payload: {
      type: "topic.publish",
      topic: "chat",
      event_name: "pag_snapshot_refreshed",
      payload: inner
    }
  };
}

export function extractCompactPagEventPayload(
  row: Readonly<Record<string, unknown>>
): Readonly<Record<string, unknown>> | null {
  if (row["type"] !== "topic.publish") {
    return null;
  }
  const pl: unknown = row["payload"];
  if (!pl || typeof pl !== "object" || Array.isArray(pl)) {
    return null;
  }
  const p1: Record<string, unknown> = pl as Record<string, unknown>;
  const en: unknown = p1["event_name"];
  if (en !== "pag_graph_rev_reconciled" && en !== "pag_snapshot_refreshed") {
    return null;
  }
  const inner: unknown = p1["payload"];
  if (!inner || typeof inner !== "object" || Array.isArray(inner)) {
    return null;
  }
  return inner as Readonly<Record<string, unknown>>;
}
