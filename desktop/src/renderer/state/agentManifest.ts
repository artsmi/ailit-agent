/**
 * `ailit_desktop_agent_manifest_v1` — презентационные метаданные агентов (G9.7.1).
 * Реестр runtime — источник live availability; manifest — defaults для UI.
 */

export type AgentManifestEntry = {
  readonly agentType: string;
  readonly displayName: string;
  readonly role: string;
  readonly icon: string;
  readonly color: string;
  readonly capabilities: readonly string[];
};

export type AgentManifestV1 = {
  readonly version: 1;
  readonly entries: readonly AgentManifestEntry[];
};

/** «Короткое» имя до двоеточия в `AgentWork:chat-a` → `AgentWork`. */
export function agentTypeFromRef(ref: string): string {
  const s: string = String(ref ?? "").trim();
  if (!s) {
    return "";
  }
  const i: number = s.indexOf(":");
  return i < 0 ? s : s.slice(0, i);
}

const FALLBACK: Readonly<Record<string, Readonly<Pick<AgentManifestEntry, "displayName" | "role" | "color" | "icon">>>> = {
  AgentWork: { displayName: "Work", role: "Агент исполнения задач", color: "#888888", icon: "terminal" },
  AgentMemory: { displayName: "Memory", role: "PAG / контекст", color: "#888888", icon: "account_tree" }
};

/**
 * Сид по умолчанию: MVP + тестовый `AgentDummy` (новый тип без новых веток роутов).
 */
export const DEFAULT_AGENT_MANIFEST_V1: AgentManifestV1 = {
  version: 1,
  entries: [
    {
      agentType: "AgentWork",
      displayName: "Work",
      role: "Исполняет задачу пользователя",
      icon: "terminal",
      color: "#e040a0",
      capabilities: ["work.handle_user_prompt"]
    },
    {
      agentType: "AgentMemory",
      displayName: "Memory",
      role: "Ищет контекст в PAG и выдаёт grants",
      icon: "account_tree",
      color: "#7c52aa",
      capabilities: ["memory.query_context"]
    },
    {
      agentType: "AgentDummy",
      displayName: "Dummy",
      role: "Тестовый агент (registry/manifest, без hardcoded ветвлений в роутер)",
      icon: "smart_toy",
      color: "#00a896",
      capabilities: ["demo.ping"]
    }
  ]
};

function entryMap(m: AgentManifestV1): ReadonlyMap<string, AgentManifestEntry> {
  return new Map(m.entries.map((e) => [e.agentType, e]));
}

export function getManifestEntry(
  m: AgentManifestV1,
  agentType: string
): AgentManifestEntry {
  const t: string = String(agentType ?? "").trim();
  const hit: AgentManifestEntry | undefined = entryMap(m).get(t);
  if (hit) {
    return hit;
  }
  const fb = FALLBACK[t] ?? { displayName: t, role: "Агент", color: "#6b6b6b", icon: "device_unknown" };
  return {
    agentType: t,
    displayName: fb.displayName,
    role: fb.role,
    color: fb.color,
    icon: fb.icon,
    capabilities: []
  };
}

export function displayLabelForRef(
  m: AgentManifestV1,
  ref: string
): { shortType: string; displayName: string; badge: string } {
  if (ref.startsWith("client:") || ref.startsWith("Client:")) {
    return { shortType: "Broker", displayName: "Broker", badge: ref };
  }
  const t: string = agentTypeFromRef(ref);
  const e: AgentManifestEntry = getManifestEntry(m, t);
  return { shortType: t, displayName: e.displayName, badge: ref };
}
