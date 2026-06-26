const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("overlay", {
  getDisplay: () => ipcRenderer.invoke("overlay:getDisplay"),
  setPosition: (x, y) => ipcRenderer.send("overlay:setPosition", x, y),
  setInteractive: (v) => ipcRenderer.send("overlay:setInteractive", v),
});
