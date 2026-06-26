const { app, BrowserWindow, screen } = require("electron");
const path = require("node:path");

const DEV_URL = "http://localhost:5273";

function createWindow() {
  const wa = screen.getPrimaryDisplay().workAreaSize;
  const x = wa.width - 400 - 20;
  const y = wa.height - 600 - 20;
  const win = new BrowserWindow({
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
  if (process.env.OVERLAY_DEV === "1") {
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
