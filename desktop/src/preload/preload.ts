import { contextBridge } from "electron";
import type { DesktopApi } from "../shared/ipc";

const api: DesktopApi = {
  async ping(): Promise<string> {
    return "pong";
  }
};

contextBridge.exposeInMainWorld("ailitDesktop", api);

