export type RuntimeSupervisorStatusOk = {
  readonly ok: true;
  readonly result: {
    readonly runtime_dir: string;
    readonly uptime_s: number;
    readonly broker_count: number;
    readonly brokers_failed: number;
  };
};

export type RuntimeSupervisorError = {
  readonly ok: false;
  readonly error: string | { readonly code: string; readonly message: string };
};

export type RuntimeSupervisorStatusResponse = RuntimeSupervisorStatusOk | RuntimeSupervisorError;

export type RuntimeSupervisorBrokerRecord = {
  readonly chat_id: string;
  readonly namespace: string;
  readonly project_root: string;
  readonly endpoint: string;
  readonly pid: number | null;
  readonly state: string;
  readonly created_at: number;
  readonly last_seen: number;
};

export type RuntimeSupervisorBrokersOk = {
  readonly ok: true;
  readonly result: {
    readonly brokers: readonly RuntimeSupervisorBrokerRecord[];
  };
};

export type RuntimeSupervisorBrokersResponse = RuntimeSupervisorBrokersOk | RuntimeSupervisorError;

export type RuntimeSupervisorCreateBrokerOk = {
  readonly ok: true;
  readonly result: RuntimeSupervisorBrokerRecord;
};

export type RuntimeSupervisorCreateBrokerResponse = RuntimeSupervisorCreateBrokerOk | RuntimeSupervisorError;

export type RuntimeSupervisorStopBrokerOk = {
  readonly ok: true;
  readonly result: RuntimeSupervisorBrokerRecord | null;
};

export type RuntimeSupervisorStopBrokerResponse = RuntimeSupervisorStopBrokerOk | RuntimeSupervisorError;

export type RuntimeRequestEnvelope = {
  readonly contract_version: string;
  readonly runtime_id: string;
  readonly chat_id: string;
  readonly broker_id: string;
  readonly trace_id: string;
  readonly message_id: string;
  readonly parent_message_id: string | null;
  readonly goal_id: string;
  readonly namespace: string;
  readonly from_agent: string;
  readonly to_agent: string | null;
  readonly created_at: string;
  readonly type: string;
  readonly payload: Record<string, unknown>;
};

export type RuntimeResponseEnvelope = {
  readonly contract_version: string;
  readonly runtime_id: string;
  readonly chat_id: string;
  readonly broker_id: string;
  readonly trace_id: string;
  readonly message_id: string;
  readonly parent_message_id: string | null;
  readonly goal_id: string;
  readonly namespace: string;
  readonly from_agent: string;
  readonly to_agent: string | null;
  readonly created_at: string;
  readonly type: string;
  readonly ok: boolean;
  readonly payload: Record<string, unknown>;
  readonly error: { readonly code: string; readonly message: string } | null;
};

export type BrokerRequestResult =
  | { readonly ok: true; readonly response: RuntimeResponseEnvelope }
  | { readonly ok: false; readonly error: string };

export type ProjectRegistryEntry = {
  readonly projectId: string;
  readonly namespace: string;
  readonly title: string;
  readonly path: string;
  readonly active: boolean;
};

export type ProjectRegistryResult =
  | {
      readonly ok: true;
      readonly registryFile: string;
      readonly entries: readonly ProjectRegistryEntry[];
      readonly activeProjectIds: readonly string[];
    }
  | { readonly ok: false; readonly error: string };

export type SaveFileResult = { readonly ok: true } | { readonly ok: false; readonly error: string };

export type PagGraphSliceResult =
  | {
      readonly ok: true;
      readonly kind: "ailit_pag_graph_slice_v1";
      readonly namespace: string;
      readonly db_path: string;
      readonly graph_rev?: number;
      readonly pag_state: string;
      readonly level_filter: string | null;
      readonly nodes: readonly Record<string, unknown>[];
      readonly edges: readonly Record<string, unknown>[];
      readonly limits: {
        readonly node_limit: number;
        readonly node_offset: number;
        readonly edge_limit: number;
        readonly edge_offset: number;
      };
      readonly has_more: { readonly nodes: boolean; readonly edges: boolean };
    }
  | { readonly ok: false; readonly kind: "ailit_pag_graph_slice_v1"; readonly error: string; readonly code?: string };

export type DesktopTraceRowEvent = {
  readonly chatId: string;
  readonly row: Record<string, unknown>;
};

export type TraceChannelEvent = {
  readonly chatId: string;
  readonly kind: "open" | "end" | "error";
  readonly detail?: string;
};

export type DurableTraceReadResult =
  | { readonly ok: true; readonly rows: readonly Record<string, unknown>[] }
  | { readonly ok: false; readonly error: string };

export type AppendSessionDiagnosticResult =
  | { readonly ok: true; readonly filePath: string }
  | { readonly ok: false; readonly error: string };

export type AppendTraceRowResult =
  | { readonly ok: true; readonly row: Record<string, unknown> }
  | { readonly ok: false; readonly error: string };

export type MemoryJournalReadResult =
  | { readonly ok: true; readonly path: string; readonly rows: readonly Record<string, unknown>[] }
  | { readonly ok: false; readonly error: string };

export type DesktopApi = {
  readonly ping: () => Promise<string>;
  readonly supervisorStatus: () => Promise<RuntimeSupervisorStatusResponse>;
  readonly supervisorBrokers: () => Promise<RuntimeSupervisorBrokersResponse>;
  readonly supervisorCreateOrGetBroker: (params: {
    readonly chatId: string;
    readonly namespace: string;
    readonly projectRoot: string;
  }) => Promise<RuntimeSupervisorCreateBrokerResponse>;
  readonly supervisorStopBroker: (params: { readonly chatId: string }) => Promise<RuntimeSupervisorStopBrokerResponse>;
  readonly brokerRequest: (params: { readonly endpoint: string; readonly request: RuntimeRequestEnvelope }) => Promise<BrokerRequestResult>;
  readonly traceReadDurable: (params: { readonly runtimeDir: string; readonly chatId: string }) => Promise<DurableTraceReadResult>;
  readonly appendTraceRow: (params: {
    readonly runtimeDir: string;
    readonly chatId: string;
    readonly row: Record<string, unknown>;
  }) => Promise<AppendTraceRowResult>;
  readonly traceSubscribe: (params: { readonly chatId: string; readonly endpoint: string }) => Promise<{ readonly ok: true } | { readonly ok: false; readonly error: string }>;
  readonly traceUnsubscribe: (params: { readonly chatId: string }) => Promise<{ readonly ok: true }>;
  readonly onTraceRow: (handler: (evt: DesktopTraceRowEvent) => void) => () => void;
  readonly onTraceChannel: (handler: (evt: TraceChannelEvent) => void) => () => void;
  readonly projectRegistryList: (params: { readonly startPath?: string }) => Promise<ProjectRegistryResult>;
  readonly saveTextFile: (params: { readonly suggestedName: string; readonly content: string }) => Promise<SaveFileResult>;
  /** Записать строки в `session/desk-diagnostic-<chat>.log` под runtime_dir (для аналитики/диагностики). */
  readonly appendSessionDiagnostic: (params: {
    readonly runtimeDir: string;
    readonly chatId: string;
    readonly lines: readonly string[];
  }) => Promise<AppendSessionDiagnosticResult>;
  readonly pagGraphSlice: (params: {
    readonly namespace: string;
    readonly dbPath?: string;
    readonly level: string | null;
    readonly nodeLimit: number;
    readonly nodeOffset: number;
    readonly edgeLimit: number;
    readonly edgeOffset: number;
  }) => Promise<PagGraphSliceResult>;
  readonly memoryJournalRead: (params: {
    readonly chatId: string;
    readonly limit?: number;
  }) => Promise<MemoryJournalReadResult>;
  /** Домашний каталог (для путей ~/.ailit/…, в т.ч. agent-memory chat_logs). */
  readonly homeDir: () => Promise<string>;
};

