/**
 * Supervisor create_or_get_broker JSON body (G8): primary + workspace extras.
 * Mirrors Python _MAX_WORKSPACE_EXTRAS in broker_workspace_config.py.
 */

import type { HighlightNamespacePolicy } from "./desktopConfigContract";
import type { ProjectRegistryEntry, SupervisorCreateOrGetBrokerParams } from "./ipc";

/** Дополнительные корни (не primary); не более четырёх. */
export const MAX_BROKER_WORKSPACE_EXTRAS: number = 4;

export type BrokerProjectRow = {
  readonly projectId: string;
  readonly namespace: string;
  readonly projectRoot: string;
};

export type BrokerHandshakeWire = {
  readonly chat_id: string;
  readonly primary_namespace: string;
  readonly primary_project_root: string;
  readonly workspace: readonly {
    readonly namespace: string;
    readonly project_root: string;
  }[];
};

/**
 * Упорядоченная цепочка проектов для broker (как в UI: selectedProjectIds, затем fallback).
 * D-CFG-1: при отсутствии UI для explicit primary effective = first_selected — primary = первый в цепочке.
 */
export function resolveRegistryProjectChain(
  registry: readonly ProjectRegistryEntry[],
  selectedProjectIds: readonly string[],
  _highlightNamespacePolicy: HighlightNamespacePolicy | null | undefined
): readonly BrokerProjectRow[] | null {
  void _highlightNamespacePolicy;
  const byId: Map<string, ProjectRegistryEntry> = new Map(registry.map((e) => [e.projectId, e]));
  const chain: string[] = selectedProjectIds.length ? [...selectedProjectIds] : [];
  if (chain.length === 0 && registry[0]) {
    chain.push(registry[0].projectId);
  }
  const rows: BrokerProjectRow[] = [];
  for (const id of chain) {
    const ro: ProjectRegistryEntry | undefined = byId.get(id);
    if (ro) {
      rows.push({
        projectId: ro.projectId,
        namespace: ro.namespace,
        projectRoot: ro.path
      });
    }
  }
  if (rows.length === 0) {
    return null;
  }
  return rows;
}

/**
 * Чистое построение полей supervisor JSON (без cmd).
 *
 * @throws Error если нет ни одного проекта
 */
export function brokerHandshakePayload(
  chatId: string,
  orderedProjects: readonly { readonly namespace: string; readonly projectRoot: string }[]
): BrokerHandshakeWire {
  if (orderedProjects.length === 0) {
    throw new Error("brokerHandshakePayload: orderedProjects must be non-empty");
  }
  const primary0 = orderedProjects[0];
  if (primary0 === undefined) {
    throw new Error("brokerHandshakePayload: orderedProjects[0] missing");
  }
  const primary: { readonly namespace: string; readonly projectRoot: string } = primary0;
  const extras: readonly { readonly namespace: string; readonly projectRoot: string }[] =
    orderedProjects.slice(1, 1 + MAX_BROKER_WORKSPACE_EXTRAS);
  return {
    chat_id: chatId,
    primary_namespace: primary.namespace,
    primary_project_root: primary.projectRoot,
    workspace: extras.map((e) => ({
      namespace: e.namespace,
      project_root: e.projectRoot
    }))
  };
}

/** IPC-параметры preload из упорядоченной цепочки registry (primary + workspace). */
export function supervisorCreateOrGetBrokerParamsFromChain(
  chatId: string,
  chain: readonly BrokerProjectRow[]
): SupervisorCreateOrGetBrokerParams {
  const w: BrokerHandshakeWire = brokerHandshakePayload(chatId, chain);
  return {
    chatId: w.chat_id,
    primaryNamespace: w.primary_namespace,
    primaryProjectRoot: w.primary_project_root,
    workspace: w.workspace.map((x) => ({
      namespace: x.namespace,
      projectRoot: x.project_root
    }))
  };
}
