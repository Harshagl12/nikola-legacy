const { app, BrowserWindow, Menu, ipcMain, nativeImage, session, screen, shell, dialog, Tray } = require('electron');
app.disableHardwareAcceleration();
const path = require('path');
const fs = require('fs');
const httpx = require('http');

// Avoid GPU/cache crashes on machines where Chromium cannot write its default cache.
app.commandLine.appendSwitch('disable-gpu');
app.commandLine.appendSwitch('disable-gpu-compositing');
app.commandLine.appendSwitch('disable-software-rasterizer');
app.setPath('userData', path.join(app.getPath('appData'), 'Nikola'));
app.setPath('cache', path.join(app.getPath('userData'), 'Cache'));

let mainWindow;
let appVersion = '1.0.0';
let tray;
let isWorkspaceVisible = false;
let isQuitting = false;
const API_KEY = process.env.NIKOLA_API_KEY || "";
const defaultBallPosition = { x: 32, y: 32 };
let ballPosition = { ...defaultBallPosition };

function safeCoordinate(value, fallback) {
  if (value === null || value === undefined) return fallback;
  const numericValue = Number(value);
  return Number.isFinite(numericValue) ? Math.round(numericValue) : fallback;
}

function loadBallPosition() {
  try {
    const saved = JSON.parse(fs.readFileSync(path.join(app.getPath('userData'), 'ball-position.json'), 'utf8'));
    if (saved && typeof saved === 'object') {
      ballPosition = {
        x: safeCoordinate(saved.x, defaultBallPosition.x),
        y: safeCoordinate(saved.y, defaultBallPosition.y),
      };
    }
  } catch {
    ballPosition = { ...defaultBallPosition };
  }
}

function saveBallPosition() {
  try {
    const filePath = path.join(app.getPath('userData'), 'ball-position.json');
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, JSON.stringify(ballPosition), 'utf8');
  } catch {
    // Position persistence is best effort.
  }
}

// Ensure Chromium media APIs are available in Electron shell.
app.commandLine.appendSwitch('enable-features', 'MediaFoundationVideoCapture,WebRTCPipeWireCapturer');

// Create window function
function createWindow() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;
  mainWindow = new BrowserWindow({
    width: 1040,
    height: 720,
    minWidth: 760,
    minHeight: 540,
    x: Math.max(0, Math.floor((width - 1040) / 2)),
    y: Math.max(0, Math.floor((height - 720) / 2)),
    show: false,
    alwaysOnTop: true,
    frame: false,
    transparent: true,
    resizable: true,
    skipTaskbar: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      preload: path.join(__dirname, 'preload.js'),
      spellcheck: true
    }
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://')) shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.webContents.on('will-navigate', (event) => event.preventDefault());
  mainWindow.once('ready-to-show', () => showBall());

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
  mainWindow.on('close', event => {
    if (!isQuitting) {
      event.preventDefault();
      showBall();
    }
  });
}

function showBall() {
  if (!mainWindow) return;
  isWorkspaceVisible = false;
  mainWindow.setAlwaysOnTop(true, 'floating');
  mainWindow.setResizable(false);
  mainWindow.setMinimumSize(112, 112);
  mainWindow.setMaximumSize(112, 112);
  mainWindow.setSize(112, 112, true);
  const safeX = safeCoordinate(ballPosition.x, defaultBallPosition.x);
  const safeY = safeCoordinate(ballPosition.y, defaultBallPosition.y);
  ballPosition = { x: safeX, y: safeY };
  mainWindow.setPosition(safeX, safeY, true);
  mainWindow.showInactive();
  mainWindow.webContents.send('window-mode', 'ball');
}

function showWorkspace() {
  if (!mainWindow) return;
  isWorkspaceVisible = true;
  mainWindow.setAlwaysOnTop(false);
  mainWindow.setMinimumSize(900, 620);
  mainWindow.setMaximumSize(0, 0);
  mainWindow.setResizable(true);
  mainWindow.setSize(1040, 720, true);
  mainWindow.center();
  mainWindow.show();
  mainWindow.focus();
  mainWindow.webContents.send('window-mode', 'workspace');
}

// App ready
app.on('ready', () => {
  // Allow microphone permission requests only for the local application window.
  const ses = session.defaultSession;
  ses.webRequest.onBeforeSendHeaders(
    { urls: ['http://127.0.0.1:8000/*', 'http://localhost:8000/*'] },
    (details, callback) => {
      details.requestHeaders['X-API-Key'] = API_KEY;
      callback({ cancel: false, requestHeaders: details.requestHeaders });
    }
  );
  ses.setPermissionCheckHandler((webContents, permission) => {
    return Boolean(mainWindow && webContents === mainWindow.webContents && permission === 'media');
  });

  ses.setPermissionRequestHandler((webContents, permission, callback) => {
    callback(Boolean(mainWindow && webContents === mainWindow.webContents && permission === 'media'));
  });

  loadBallPosition();
  createWindow();
  createTrayMenu();
});

app.on('window-all-closed', () => {
  // Closing the workspace is a mode change, not an application exit.
  // The only supported termination path is Quit Nikola.
});

app.on('activate', () => {
  if (mainWindow === null) {
    createWindow();
  }
});

// IPC Handlers
ipcMain.on('window-minimize', () => {
  showBall();
});

ipcMain.on('open-workspace', showWorkspace);
ipcMain.on('show-ball', showBall);
ipcMain.on('move-ball', (event, position) => {
  if (!mainWindow || isWorkspaceVisible) return;
  const safeInput = {
    x: safeCoordinate(position?.x, defaultBallPosition.x),
    y: safeCoordinate(position?.y, defaultBallPosition.y),
  };
  const display = screen.getDisplayNearestPoint(safeInput);
  const area = display.workArea;
  const x = Math.max(area.x, Math.min(safeInput.x, area.x + area.width - 112));
  const y = Math.max(area.y, Math.min(safeInput.y, area.y + area.height - 112));
  ballPosition = { x, y };
  saveBallPosition();
  mainWindow.setPosition(safeCoordinate(x, defaultBallPosition.x), safeCoordinate(y, defaultBallPosition.y), true);
});
ipcMain.on('ball-context-menu', () => {
  if (!tray) return;
  const menu = Menu.buildFromTemplate([
    { label: 'Open Nikola', click: showWorkspace },
    { label: 'New Chat', click: () => { if (mainWindow) mainWindow.webContents.send('new-chat'); showWorkspace(); } },
    { label: 'Documents', click: () => { showWorkspace(); if (mainWindow) mainWindow.webContents.send('open-view', 'documents'); } },
    { label: 'Voice', click: () => { showWorkspace(); if (mainWindow) mainWindow.webContents.send('open-view', 'voice'); } },
    { label: 'Settings', click: () => { showWorkspace(); if (mainWindow) mainWindow.webContents.send('open-view', 'settings'); } },
    { label: 'Restart Backend', click: requestBackendRestart },
    { type: 'separator' },
    { label: 'Quit Nikola', click: quitNikola }
  ]);
  menu.popup({ window: mainWindow });
});
ipcMain.on('new-chat', () => {
  if (mainWindow) mainWindow.webContents.send('new-chat');
  showWorkspace();
});

ipcMain.on('window-quit', () => {
  quitNikola();
});

function quitNikola() {
  isQuitting = true;
  app.quit();
}

ipcMain.handle('get-version', () => {
  return app.getVersion() || appVersion;
});

ipcMain.handle('get-window-mode', () => isWorkspaceVisible ? 'workspace' : 'ball');

ipcMain.handle('choose-documents', async () => {
  if (!mainWindow) return [];
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Add documents to Nikola',
    properties: ['openFile', 'multiSelections'],
    filters: [{ name: 'Supported documents', extensions: ['pdf', 'txt', 'md', 'docx', 'py', 'js', 'ts', 'json', 'csv'] }]
  });
  return result.canceled ? [] : result.filePaths;
});

function requestBackendRestart() {
  const req = httpx.request({
    hostname: '127.0.0.1',
    port: 8000,
    path: '/system/restart',
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Content-Length': '2', 'X-API-Key': API_KEY },
    timeout: 4000
  }, (res) => {
    res.resume();
    if (mainWindow) mainWindow.webContents.send('restart-backend', { accepted: res.statusCode === 200 });
  });
  req.on('timeout', () => req.destroy());
  req.on('error', () => { if (mainWindow) mainWindow.webContents.send('restart-backend', { accepted: false }); });
  req.end('{}');
}

ipcMain.handle('restart-backend', () => requestBackendRestart());

ipcMain.handle('toggle-voice', async () => {
  try {
    const response = await new Promise((resolve, reject) => {
      const req = httpx.request({
        hostname: 'localhost',
        port: 8000,
        path: '/voice-speak',
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
        timeout: 5000
      }, (res) => {
        res.on('data', () => {});
        res.on('end', () => resolve(true));
      });
      
      req.on('error', () => reject(false));
      req.write(JSON.stringify({ text: 'Voice toggled' }));
      req.end();
    });
    return response;
  } catch {
    return false;
  }
});

ipcMain.on('update-panel-state', (event, { isOpen, side }) => {
  if (isOpen) showWorkspace(); else showBall();
});

// System Tray
function createTrayMenu() {
  const iconPath = path.join(__dirname, '..', 'nikola_launcher', 'nikola_icon.ico');
  let icon = nativeImage.createFromPath(iconPath);
  if (icon.isEmpty()) {
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect x="3" y="3" width="58" height="58" rx="20" fill="#151923" stroke="#7c5cff"/><circle cx="32" cy="27" r="13" fill="#6ee7f9" fill-opacity=".25"/><text x="32" y="39" text-anchor="middle" font-family="Arial" font-size="28" font-weight="700" fill="white">N</text></svg>';
    icon = nativeImage.createFromDataURL(`data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`);
  }
  tray = new Tray(icon);
  tray.setToolTip('Nikola — Private Local AI');
  const contextMenu = Menu.buildFromTemplate([
    {
      label: '✦ Nikola',
      enabled: false
    },
    { type: 'separator' },
    {
      label: 'Open Nikola', click: showWorkspace
    },
    { label: 'New Chat', click: () => { if (mainWindow) mainWindow.webContents.send('new-chat'); showWorkspace(); } },
    { label: 'Documents', click: () => { showWorkspace(); if (mainWindow) mainWindow.webContents.send('open-view', 'documents'); } },
    { label: 'Restart Backend', click: requestBackendRestart },
    { type: 'separator' },
    {
      label: 'Quit Nikola', click: quitNikola
    }
  ]);
  
  tray.setContextMenu(contextMenu);
  tray.on('click', showWorkspace);
}

module.exports = { app, mainWindow };
