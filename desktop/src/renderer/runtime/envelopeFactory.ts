import type { RuntimeRequestEnvelope } from "@shared/ipc";

import { newMessageId } from "./uuid";

const CONTRACT = "ailit_agent_runtime_v1";

export function buildUserPromptAction(params: {
  readonly chatId: string;
  readonly brokerId: string;
  readonly namespace: string;
  readonly goalId: string;
  readonly traceId: string;
  readonly prompt: string;
  readonly workspace: { readonly projectIds: readonly string[]; readonly projectRoots: readonly string[] };
}): { readonly envelope: RuntimeRequestEnvelope; readonly messageId: string } {
  const messageId: string = newMessageId();
  const now: string = new Date().toISOString();
  return {
    messageId,
    envelope: {
    contract_version: CONTRACT,
    runtime_id: "ailit-desktop",
    chat_id: params.chatId,
    broker_id: params.brokerId,
    trace_id: params.traceId,
    message_id: messageId,
    parent_message_id: null,
    goal_id: params.goalId,
    namespace: params.namespace,
    from_agent: "User:desktop",
    to_agent: null,
    created_at: now,
    type: "action.start",
    payload: {
      action: "work.handle_user_prompt",
      prompt: params.prompt,
      workspace: {
        project_ids: [...params.workspace.projectIds],
        project_roots: [...params.workspace.projectRoots]
      }
    }
  }
  };
}

/** Сервис в AgentWork: ответ на ``session.perm_mode.need_user_choice``. */
export function buildPermModeChoiceRequest(params: {
  readonly chatId: string;
  readonly brokerId: string;
  readonly namespace: string;
  readonly goalId: string;
  readonly traceId: string;
  readonly gateId: string;
  readonly mode: string;
  readonly rememberProject: boolean;
}): { readonly envelope: RuntimeRequestEnvelope; readonly messageId: string } {
  const messageId: string = newMessageId();
  const now: string = new Date().toISOString();
  return {
    messageId,
    envelope: {
      contract_version: CONTRACT,
      runtime_id: "ailit-desktop",
      chat_id: params.chatId,
      broker_id: params.brokerId,
      trace_id: params.traceId,
      message_id: messageId,
      parent_message_id: null,
      goal_id: params.goalId,
      namespace: params.namespace,
      from_agent: "User:desktop",
      to_agent: `AgentWork:${params.chatId}`,
      created_at: now,
      type: "service.request",
      payload: {
        action: "work.perm_mode_choice",
        gate_id: params.gateId,
        mode: params.mode,
        remember_project: params.rememberProject
      }
    }
  };
}

/** Сервис в AgentWork: ответ на ``session.waiting_approval`` (ASK на инструмент, напр. run_shell). */
export function buildToolApprovalResolveRequest(params: {
  readonly chatId: string;
  readonly brokerId: string;
  readonly namespace: string;
  readonly goalId: string;
  readonly traceId: string;
  readonly callId: string;
  readonly approved: boolean;
}): { readonly envelope: RuntimeRequestEnvelope; readonly messageId: string } {
  const messageId: string = newMessageId();
  const now: string = new Date().toISOString();
  return {
    messageId,
    envelope: {
      contract_version: CONTRACT,
      runtime_id: "ailit-desktop",
      chat_id: params.chatId,
      broker_id: params.brokerId,
      trace_id: params.traceId,
      message_id: messageId,
      parent_message_id: null,
      goal_id: params.goalId,
      namespace: params.namespace,
      from_agent: "User:desktop",
      to_agent: `AgentWork:${params.chatId}`,
      created_at: now,
      type: "service.request",
      payload: {
        action: "work.approval_resolve",
        call_id: params.callId,
        approved: params.approved
      }
    }
  };
}
