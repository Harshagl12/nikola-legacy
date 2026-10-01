const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  minimize: () => ipcRenderer.send('window-minimize'),
  openWorkspace: () => ipcRenderer.send('open-workspace'),
  showBall: () => ipcRenderer.send('show-ball'),
  moveBall: (position) => ipcRenderer.send('move-ball', position),
  showBallMenu: () => ipcRenderer.send('ball-context-menu'),
  newChat: () => ipcRenderer.send('new-chat'),
  quit: () => ipcRenderer.send('window-quit'),
  getAppVersion: () => ipcRenderer.invoke('get-version'),
  chooseDocuments: () => ipcRenderer.invoke('choose-documents'),
  restartBackend: () => ipcRenderer.invoke('restart-backend'),
  toggleVoice: () => ipcRenderer.invoke('toggle-voice'),
  captureScreen: () => ipcRenderer.invoke('capture-screen'),
  updatePanelState: (isOpen, side) => ipcRenderer.send('update-panel-state', {isOpen, side}),
  onWindowMode: (callback) => ipcRenderer.on('window-mode', (_event, mode) => callback(mode)),
  onNewChat: (callback) => ipcRenderer.on('new-chat', callback),
  onRestartBackend: (callback) => ipcRenderer.on('restart-backend', (_event, result) => callback(result))
  ,onOpenView: (callback) => ipcRenderer.on('open-view', (_event, view) => callback(view))
});
