const { app, BrowserWindow, screen, ipcMain } = require("electron");
const path = require("node:path");

const DEV_URL = "http://localhost:5273";

let win = null;

ipcMain.handle("overlay:getDisplay", () => {
  const d = screen.getPrimaryDisplay();
  return { workArea: d.workArea, bounds: win && !win.isDestroyed() ? win.getBounds() : null };
});
ipcMain.on("overlay:setPosition", (_e, x, y) => {
  if (!win || win.isDestroyed()) return;
  win.setPosition(Math.round(x), Math.round(y));
});
ipcMain.on("overlay:setInteractive", (_e, interactive) => {
  if (!win || win.isDestroyed()) return;
  win.setIgnoreMouseEvents(!interactive, { forward: true });
});

function createWindow() {
  const wa = screen.getPrimaryDisplay().workAreaSize;
  const x = wa.width - 400 - 20;
  const y = wa.height - 600 - 20;
  win = new BrowserWindow({
    width: 400,
    height: 600,
    x,
    y,
    show: false,
    transparent: true,
    frame: false,
    resizable: false,
    hasShadow: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.setAlwaysOnTop(true, "screen-saver");
  win.setIgnoreMouseEvents(true, { forward: true }); // click-through (SP1 default)
  // dev は --dev フラグ(シェル非依存)で切替。OVERLAY_DEV=1 も後方互換で受ける。
  const isDev = process.argv.includes("--dev") || process.env.OVERLAY_DEV === "1";
  if (isDev) {
    win.loadURL(DEV_URL);
  } else {
    win.loadFile(path.join(__dirname, "dist", "index.html"));
  }
  win.once("ready-to-show", () => win.show());
}

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
