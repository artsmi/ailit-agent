import { app, BrowserWindow, dialog } from "electron";
import * as path from "node:path";

import { registerIpcHandlers } from "./registerIpc";

function getRendererUrl(): string {
  const devUrlRaw: string | undefined = process.env["AILIT_DESKTOP_DEV_URL"];
  if (typeof devUrlRaw === "string" && devUrlRaw.length > 0) {
    const devUrl: string = devUrlRaw;
    return devUrl;
  }
  const indexHtmlPath: string = path.join(app.getAppPath(), "dist", "renderer", "index.html");
  return `file://${indexHtmlPath}`;
}

function getPreloadPath(): string {
  return path.join(app.getAppPath(), "dist", "preload", "preload.js");
}

async function createWindow(): Promise<void> {
  const win: BrowserWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 980,
    minHeight: 640,
    backgroundColor: "#fff7fb",
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      preload: getPreloadPath()
    }
  });

  win.once("ready-to-show", () => win.show());

  const rendererUrl: string = getRendererUrl();
  try {
    await win.loadURL(rendererUrl);
  } catch (err: unknown) {
    await dialog.showMessageBox(win, {
      type: "error",
      title: "ailit desktop",
      message: "Не удалось загрузить renderer.",
      detail: String(err)
    });
  }
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.whenReady().then(async () => {
  registerIpcHandlers();
  await createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      void createWindow();
    }
  });
});

