import { contextBridge, ipcRenderer } from "electron";
import type {
  AppendSessionDiagnosticResult,
  AppendTraceRowResult,
  BrokerRequestResult,
  DesktopApi,
  DesktopTraceRowEvent,
  DurableTraceReadResult,
  ProjectRegistryResult,
  RuntimeRequestEnvelope,
  RuntimeSupervisorBrokersResponse,
  RuntimeSupervisorCreateBrokerResponse,
  RuntimeSupervisorStatusResponse,
  RuntimeSupervisorStopBrokerResponse,
  PagGraphSliceResult,
  SaveFileResult,
  TraceChannelEvent,
  MemoryJournalReadResult
} from "../shared/ipc";

const api: DesktopApi = {
  async ping(): Promise<string> {
    return String(await ipcRenderer.invoke("ailit:ping"));
  },
  async supervisorStatus(): Promise<RuntimeSupervisorStatusResponse> {
    return (await ipcRenderer.invoke("ailit:supervisorStatus")) as RuntimeSupervisorStatusResponse;
  },
  async supervisorBrokers(): Promise<RuntimeSupervisorBrokersResponse> {
    return (await ipcRenderer.invoke("ailit:supervisorBrokers")) as RuntimeSupervisorBrokersResponse;
  },
  async supervisorCreateOrGetBroker(params: {
    readonly chatId: string;
    readonly namespace: string;
    readonly projectRoot: string;
  }): Promise<RuntimeSupervisorCreateBrokerResponse> {
    return (await ipcRenderer.invoke("ailit:supervisorCreateOrGetBroker", params)) as RuntimeSupervisorCreateBrokerResponse;
  },
  async supervisorStopBroker(params: { readonly chatId: string }): Promise<RuntimeSupervisorStopBrokerResponse> {
    return (await ipcRenderer.invoke("ailit:supervisorStopBroker", params)) as RuntimeSupervisorStopBrokerResponse;
  },
  async brokerRequest(params: {
    readonly endpoint: string;
    readonly request: RuntimeRequestEnvelope;
  }): Promise<BrokerRequestResult> {
    return (await ipcRenderer.invoke("ailit:brokerRequest", params)) as BrokerRequestResult;
  },
  async traceReadDurable(params: { readonly runtimeDir: string; readonly chatId: string }): Promise<DurableTraceReadResult> {
    return (await ipcRenderer.invoke("ailit:traceReadDurable", params)) as DurableTraceReadResult;
  },
  async appendTraceRow(params: {
    readonly runtimeDir: string;
    readonly chatId: string;
    readonly row: Record<string, unknown>;
  }): Promise<AppendTraceRowResult> {
    return (await ipcRenderer.invoke("ailit:appendTraceRow", params)) as AppendTraceRowResult;
  },
  async traceSubscribe(params: { readonly chatId: string; readonly endpoint: string }): Promise<{ readonly ok: true } | { readonly ok: false; readonly error: string }> {
    return (await ipcRenderer.invoke("ailit:traceSubscribe", params)) as { readonly ok: true } | { readonly ok: false; readonly error: string };
  },
  async traceUnsubscribe(params: { readonly chatId: string }): Promise<{ readonly ok: true }> {
    await ipcRenderer.invoke("ailit:traceUnsubscribe", params);
    return { ok: true };
  },
  onTraceRow(handler: (evt: DesktopTraceRowEvent) => void): () => void {
    const fn = (_e: unknown, payload: DesktopTraceRowEvent): void => {
      handler(payload);
    };
    ipcRenderer.on("ailit:traceRow", fn);
    return () => {
      ipcRenderer.removeListener("ailit:traceRow", fn);
    };
  },
  onTraceChannel(handler: (evt: TraceChannelEvent) => void): () => void {
    const fn = (_e: unknown, payload: TraceChannelEvent): void => {
      handler(payload);
    };
    ipcRenderer.on("ailit:traceChannel", fn);
    return () => {
      ipcRenderer.removeListener("ailit:traceChannel", fn);
    };
  },
  async projectRegistryList(params: { readonly startPath?: string }): Promise<ProjectRegistryResult> {
    return (await ipcRenderer.invoke("ailit:projectRegistryList", params)) as ProjectRegistryResult;
  },
  async saveTextFile(params: { readonly suggestedName: string; readonly content: string }): Promise<SaveFileResult> {
    return (await ipcRenderer.invoke("ailit:saveTextFile", params)) as SaveFileResult;
  },
  async appendSessionDiagnostic(params: {
    readonly runtimeDir: string;
    readonly chatId: string;
    readonly lines: readonly string[];
  }): Promise<AppendSessionDiagnosticResult> {
    return (await ipcRenderer.invoke("ailit:appendSessionDiagnostic", params)) as AppendSessionDiagnosticResult;
  },
  async pagGraphSlice(params: {
    readonly namespace: string;
    readonly dbPath?: string;
    readonly level: string | null;
    readonly nodeLimit: number;
    readonly nodeOffset: number;
    readonly edgeLimit: number;
    readonly edgeOffset: number;
  }): Promise<PagGraphSliceResult> {
    return (await ipcRenderer.invoke("ailit:pagGraphSlice", params)) as PagGraphSliceResult;
  },
  async memoryJournalRead(params: {
    readonly chatId: string;
    readonly limit?: number;
  }): Promise<MemoryJournalReadResult> {
    return (await ipcRenderer.invoke("ailit:memoryJournalRead", params)) as MemoryJournalReadResult;
  },
  async homeDir(): Promise<string> {
    return String(await ipcRenderer.invoke("ailit:homeDir"));
  }
};

contextBridge.exposeInMainWorld("ailitDesktop", api);
