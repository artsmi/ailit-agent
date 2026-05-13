export type MockProject = {
  readonly projectId: string;
  readonly namespace: string;
  readonly title: string;
  readonly path: string;
  readonly active: boolean;
};

export type MockAgent = {
  readonly agentType: string;
  readonly displayName: string;
  readonly role: string;
  readonly color: string;
};

export type MockAgentLink = {
  readonly fromAgentType: string;
  readonly toAgentType: string;
  readonly label: string;
};

export type MockChatMessage = {
  readonly id: string;
  readonly from: "user" | "assistant";
  readonly text: string;
  readonly atIso: string;
};

export type MockAgentDialogueRow = {
  readonly id: string;
  readonly fromAgent: string;
  readonly toAgent: string;
  readonly humanText: string;
  readonly technicalSummary: string;
  readonly severity: "info" | "warning" | "error";
  readonly atIso: string;
};

export type MockPagNode = {
  readonly id: string;
  readonly label: string;
  readonly level: "A" | "B" | "C";
};

export type MockPagEdge = {
  readonly id: string;
  readonly from: string;
  readonly to: string;
};

export type MockWorkspace = {
  readonly projects: readonly MockProject[];
  readonly agents: readonly MockAgent[];
  readonly agentLinks: readonly MockAgentLink[];
  readonly chat: readonly MockChatMessage[];
  readonly agentDialogue: readonly MockAgentDialogueRow[];
  readonly pag: {
    readonly nodes: readonly MockPagNode[];
    readonly edges: readonly MockPagEdge[];
  };
  readonly usage: {
    readonly tokensIn: number;
    readonly tokensOut: number;
    readonly costUsd: number;
  };
  readonly toolLogs: readonly string[];
};

export const mockWorkspace: MockWorkspace = {
  projects: [
    {
      projectId: "proj-a",
      namespace: "ailit-agent",
      title: "ailit-agent",
      path: "/home/artem/reps/ailit-agent",
      active: true
    },
    {
      projectId: "proj-b",
      namespace: "example",
      title: "example-repo",
      path: "/home/artem/reps/example-repo",
      active: true
    }
  ],
  agents: [
    {
      agentType: "AgentWork",
      displayName: "Work",
      role: "Исполняет задачу пользователя",
      color: "#e040a0"
    },
    {
      agentType: "AgentMemory",
      displayName: "Memory",
      role: "Ищет контекст в PAG и выдаёт grants",
      color: "#7c52aa"
    }
  ],
  agentLinks: [
    {
      fromAgentType: "AgentWork",
      toAgentType: "AgentMemory",
      label: "query_context"
    }
  ],
  chat: [
    {
      id: "m1",
      from: "user",
      text: "Покажи текущее состояние проекта и что происходит у агентов.",
      atIso: "2026-04-25T12:00:00Z"
    },
    {
      id: "m2",
      from: "assistant",
      text: "Ок. Я показываю чат, диалог агентов и PAG-подсветку на mock data. Runtime интеграция начнётся только после UX checkpoint (G9.2).",
      atIso: "2026-04-25T12:00:04Z"
    }
  ],
  agentDialogue: [
    {
      id: "d1",
      fromAgent: "AgentWork:chat-a",
      toAgent: "AgentMemory:chat-a",
      humanText: "Мне нужен контекст по точкам входа проекта. Проверь PAG и предложи релевантные файлы.",
      technicalSummary: "memory.query_context level=B top_k=12",
      severity: "info",
      atIso: "2026-04-25T12:00:06Z"
    },
    {
      id: "d2",
      fromAgent: "AgentMemory:chat-a",
      toAgent: "AgentWork:chat-a",
      humanText: "Нашёл `ailit/ailit_cli/cli.py` и `ailit/ailit_runtime/broker.py` как релевантные точки входа. Нужны grants на чтение.",
      technicalSummary: "memory.query_context result=top_files(2) grants=required",
      severity: "warning",
      atIso: "2026-04-25T12:00:08Z"
    }
  ],
  pag: {
    nodes: [
      { id: "A:root", label: "root", level: "A" },
      { id: "B:ailit/ailit_cli/cli.py", label: "ailit/ailit_cli/cli.py", level: "B" },
      { id: "B:ailit/ailit_runtime/broker.py", label: "ailit/ailit_runtime/broker.py", level: "B" },
      { id: "C:docs/INDEX.md", label: "docs/INDEX.md", level: "C" }
    ],
    edges: [
      { id: "e1", from: "A:root", to: "B:ailit/ailit_cli/cli.py" },
      { id: "e2", from: "A:root", to: "B:ailit/ailit_runtime/broker.py" },
      { id: "e3", from: "B:ailit/ailit_cli/cli.py", to: "C:docs/INDEX.md" }
    ]
  },
  usage: {
    tokensIn: 1234,
    tokensOut: 987,
    costUsd: 0.042
  },
  toolLogs: [
    "run_shell: git status --porcelain",
    "read: plan/9-ailit-ui.md",
    "note: mock-first UX checkpoint before runtime"
  ]
};

