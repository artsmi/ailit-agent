import { contextBridge, ipcRenderer } from "electron";
import type {
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
  SaveFileResult,
  TraceChannelEvent
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
  }
};

contextBridge.exposeInMainWorld("ailitDesktop", api);
