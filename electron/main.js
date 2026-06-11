// KIS Auto Trader — Electron Main Process
//
// 개발 실행:
//   cd electron
//   npm install
//   npm start
//
// 배포 빌드:
//   npm run build
//   -> dist/ 폴더에 설치 파일 생성
//
// 구조:
//   electron/main.js  <- 이 파일
//   electron/package.json
//   assets/icon.ico   <- 선택 (없으면 기본 아이콘 사용)
//   app.py, *.py      <- Streamlit 앱

"use strict";

const { app, BrowserWindow, Menu, Tray, dialog, Notification, nativeImage } = require("electron");

// Windows 작업표시줄 아이콘 설정 (앱 시작 전에 호출해야 적용됨)
app.setAppUserModelId("com.kisautotrader.app");
const { spawn } = require("child_process");
const path = require("path");
const http = require("http");
const fs   = require("fs");

// ──────────────────────────────────────────
// 경로 설정
// ──────────────────────────────────────────

const IS_PACKAGED = app.isPackaged;

const PROJECT_ROOT = IS_PACKAGED
  ? path.join(process.resourcesPath)
  : path.join(__dirname, "..");

const VENV_ROOT = IS_PACKAGED
  ? path.join(process.resourcesPath, "venv")
  : path.join(PROJECT_ROOT, "venv");

const STREAMLIT_EXE  = path.join(VENV_ROOT, "Scripts", "streamlit.exe");
const APP_PY         = path.join(PROJECT_ROOT, "app.py");
const ICON_PATH      = path.join(__dirname, "..", "assets", "icon.ico");
const ICON_PNG_PATH  = path.join(__dirname, "..", "assets", "icon.png");
const STATE_PATH     = path.join(PROJECT_ROOT, ".cache", "trader_state.json");

const STREAMLIT_PORT = 8501;
const STREAMLIT_URL  = `http://localhost:${STREAMLIT_PORT}`;
const WAIT_TIMEOUT   = 30000;  // 30초
const POLL_INTERVAL  = 2000;   // 2초

// ──────────────────────────────────────────
// 전역 상태
// ──────────────────────────────────────────

let mainWindow    = null;
let splashWindow  = null;
let tray          = null;
let streamlitProc = null;
let isQuitting    = false;
let streamlitAlive = false;   // 트레이 상태 표시용

// ──────────────────────────────────────────
// 장중 여부 판별
// ──────────────────────────────────────────

function isMarketHours() {
  const now  = new Date();
  const hhmm = now.getHours() * 100 + now.getMinutes();
  return hhmm >= 900 && hhmm <= 1530;
}

// ──────────────────────────────────────────
// trading_state.json 확인 (비정상 종료 감지)
// ──────────────────────────────────────────

function checkAbnormalExit() {
  try {
    if (!fs.existsSync(STATE_PATH)) return;
    const state = JSON.parse(fs.readFileSync(STATE_PATH, "utf8"));
    if (state.running) {
      new Notification({
        title: "KIS Auto Trader",
        body:  "비정상 종료가 감지되었습니다. 텔레그램을 확인하세요.",
      }).show();
      console.log("[WatchDog] 비정상 종료 감지 — trading_state.json running=true");
    }
  } catch (e) {
    console.error("[WatchDog] state 파일 읽기 실패:", e.message);
  }
}

// ──────────────────────────────────────────
// 트레이 메뉴 갱신
// ──────────────────────────────────────────

function updateTrayMenu() {
  if (!tray) return;
  const statusLabel = streamlitAlive ? "🟢 서버 실행 중" : "🔴 서버 재시작 중...";

  const contextMenu = Menu.buildFromTemplate([
    { label: statusLabel, enabled: false },
    { type: "separator" },
    {
      label: "열기",
      click: () => showMainWindow(),
    },
    {
      label: "서버 재시작",
      click: () => {
        console.log("[WatchDog] 수동 재시작 요청");
        restartStreamlit();
      },
    },
    { type: "separator" },
    {
      label: "종료",
      click: () => quitApp(),
    },
  ]);

  tray.setContextMenu(contextMenu);
}

// ──────────────────────────────────────────
// Streamlit 종료 핸들러 (WatchDog 핵심)
// ──────────────────────────────────────────

function handleStreamlitClose(code) {
  streamlitAlive = false;
  updateTrayMenu();

  if (isQuitting) return;

  // 비정상 종료 감지
  checkAbnormalExit();

  const delay = isMarketHours() ? 10000 : 60000;
  console.log(`[WatchDog] Streamlit 종료 (code=${code}) — ${delay / 1000}초 후 재시작`);

  setTimeout(() => {
    if (!isQuitting) restartStreamlit();
  }, delay);
}

// ──────────────────────────────────────────
// Streamlit 재시작
// ──────────────────────────────────────────

function restartStreamlit() {
  // 기존 프로세스 정리
  if (streamlitProc && !streamlitProc.killed) {
    try {
      spawn("taskkill", ["/pid", String(streamlitProc.pid), "/f", "/t"]);
    } catch {
      streamlitProc.kill("SIGTERM");
    }
  }
  streamlitProc = null;
  startStreamlit();

  // 재시작 후 페이지 새로고침 (서버 준비되면)
  waitForStreamlit(WAIT_TIMEOUT).then(() => {
    if (mainWindow) mainWindow.webContents.reload();
  }).catch(() => {});
}

// ──────────────────────────────────────────
// Streamlit 프로세스 시작
// ──────────────────────────────────────────

function startStreamlit() {
  if (!fs.existsSync(STREAMLIT_EXE)) {
    dialog.showErrorBox(
      "venv 오류",
      `Streamlit 실행 파일을 찾을 수 없습니다.\n\n${STREAMLIT_EXE}\n\n` +
      `venv가 설치되어 있는지 확인하세요:\n` +
      `cd "${PROJECT_ROOT}" && python -m venv venv && venv\\Scripts\\pip install -r requirements.txt`
    );
    app.quit();
    return;
  }

  console.log(`[Electron] Streamlit 시작: ${STREAMLIT_EXE}`);

  streamlitProc = spawn(STREAMLIT_EXE, ["run", APP_PY, "--server.headless", "true"], {
    cwd: PROJECT_ROOT,
    env: {
      ...process.env,
      STREAMLIT_SERVER_HEADLESS:            "true",
      STREAMLIT_BROWSER_GATHER_USAGE_STATS: "false",
    },
    windowsHide: true,
  });

  streamlitAlive = true;
  updateTrayMenu();

  streamlitProc.stdout.on("data", (data) => {
    console.log(`[Streamlit] ${data.toString().trim()}`);
  });
  streamlitProc.stderr.on("data", (data) => {
    console.error(`[Streamlit ERR] ${data.toString().trim()}`);
  });
  streamlitProc.on("close", handleStreamlitClose);
}

// ──────────────────────────────────────────
// Streamlit 서버 준비 대기
// ──────────────────────────────────────────

function waitForStreamlit(timeout) {
  return new Promise((resolve, reject) => {
    const start    = Date.now();
    const interval = setInterval(() => {
      http.get(STREAMLIT_URL, () => {
        clearInterval(interval);
        resolve();
      }).on("error", () => {
        if (Date.now() - start > timeout) {
          clearInterval(interval);
          reject(new Error(`${timeout / 1000}초 내에 Streamlit 서버가 응답하지 않았습니다.`));
        }
      });
    }, POLL_INTERVAL);
  });
}

// ──────────────────────────────────────────
// 스플래시 화면
// ──────────────────────────────────────────

function createSplash() {
  splashWindow = new BrowserWindow({
    width:          400,
    height:         250,
    frame:          false,
    alwaysOnTop:    true,
    transparent:    true,
    resizable:      false,
    skipTaskbar:    true,
    webPreferences: { contextIsolation: true },
  });

  splashWindow.loadURL(`data:text/html;charset=utf-8,
    <html>
    <head><style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      body {
        background: #0a1628;
        color: #e0e0e0;
        font-family: 'Segoe UI', sans-serif;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        height: 100vh;
        border-radius: 12px;
        border: 1px solid #1e3a5f;
      }
      h1 { font-size: 22px; color: #4fc3f7; margin-bottom: 8px; }
      p  { font-size: 13px; color: #aaa; margin-bottom: 24px; }
      .dot { display: inline-block; width: 8px; height: 8px;
             border-radius: 50%; background: #4fc3f7;
             margin: 0 4px; animation: bounce 1.2s infinite; }
      .dot:nth-child(2) { animation-delay: 0.2s; }
      .dot:nth-child(3) { animation-delay: 0.4s; }
      @keyframes bounce {
        0%, 80%, 100% { transform: scale(0.7); opacity: 0.5; }
        40%           { transform: scale(1.1); opacity: 1;   }
      }
    </style></head>
    <body>
      <h1>🚀 KIS Auto Trader</h1>
      <p>시작 중입니다...</p>
      <div>
        <span class="dot"></span>
        <span class="dot"></span>
        <span class="dot"></span>
      </div>
    </body>
    </html>
  `);
}

// ──────────────────────────────────────────
// 메인 창
// ──────────────────────────────────────────

function showMainWindow() {
  if (!mainWindow) return;
  mainWindow.show();
  app.focus({ steal: true });
  mainWindow.setAlwaysOnTop(true);
  mainWindow.focus();
  setTimeout(() => mainWindow && mainWindow.setAlwaysOnTop(false), 500);
}

function createMainWindow() {
  const iconFile = fs.existsSync(ICON_PATH) ? ICON_PATH
                 : fs.existsSync(ICON_PNG_PATH) ? ICON_PNG_PATH
                 : null;

  mainWindow = new BrowserWindow({
    width:  1400,
    height: 900,
    title:  "KIS Auto Trader",
    show:   false,
    icon:   iconFile || undefined,
    titleBarStyle:   "overlay",
    titleBarOverlay: {
      color:       "#0a1628",   // 진한 곤색
      symbolColor: "#ffffff",
      height:      32,
    },
    webPreferences: {
      contextIsolation: true,
      nodeIntegration:  false,
    },
  });

  mainWindow.loadURL(STREAMLIT_URL);

  mainWindow.webContents.on("did-finish-load", () => {
    mainWindow.webContents.insertCSS(`
      [data-testid="stAppDeployButton"] { display: none !important; }
    `);
  });

  mainWindow.on("close", (e) => {
    if (!isQuitting) {
      e.preventDefault();
      mainWindow.hide();
      if (tray) {
        tray.displayBalloon({
          title:    "KIS Auto Trader",
          content:  "트레이에서 실행 중입니다.",
          iconType: "info",
        });
      }
    }
  });

  buildMenu();
}

// ──────────────────────────────────────────
// 메뉴바
// ──────────────────────────────────────────

function buildMenu() {
  const template = [
    {
      label: "파일",
      submenu: [
        { label: "종료", accelerator: "CmdOrCtrl+Q", click: () => quitApp() },
      ],
    },
    {
      label: "보기",
      submenu: [
        {
          label:       "새로고침",
          accelerator: "F5",
          click:       () => mainWindow && mainWindow.webContents.reload(),
        },
        ...(!IS_PACKAGED ? [
          { type: "separator" },
          {
            label:       "개발자 도구",
            accelerator: "F12",
            click:       () => mainWindow && mainWindow.webContents.toggleDevTools(),
          },
        ] : []),
      ],
    },
    {
      label: "도움말",
      submenu: [
        {
          label: "버전 정보",
          click: () => {
            dialog.showMessageBox(mainWindow, {
              type:    "info",
              title:   "버전 정보",
              message: "KIS Auto Trader",
              detail:  `버전: ${app.getVersion()}\nElectron: ${process.versions.electron}\nNode: ${process.versions.node}`,
              buttons: ["확인"],
            });
          },
        },
      ],
    },
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ──────────────────────────────────────────
// 시스템 트레이
// ──────────────────────────────────────────

function createTray() {
  const iconFile = fs.existsSync(ICON_PNG_PATH) ? ICON_PNG_PATH
                 : fs.existsSync(ICON_PATH)     ? ICON_PATH
                 : null;
  let trayIcon;
  try {
    trayIcon = iconFile ? nativeImage.createFromPath(iconFile) : nativeImage.createEmpty();
    if (trayIcon.isEmpty() && iconFile) throw new Error("empty");
  } catch {
    trayIcon = nativeImage.createEmpty();
  }

  tray = new Tray(trayIcon);
  tray.setToolTip("KIS Auto Trader");
  updateTrayMenu();

  tray.on("double-click", () => showMainWindow());
}

// ──────────────────────────────────────────
// 정리 및 종료
// ──────────────────────────────────────────

function clearTraderState() {
  // taskkill 전에 Python으로 running=false 기록 (atexit 미실행 대비)
  try {
    const pythonExe = path.join(VENV_ROOT, "Scripts", "python.exe");
    const code = `
import json, pathlib
p = pathlib.Path(r'${STATE_PATH.replace(/\\/g, "\\\\")}')
if p.exists():
    s = json.loads(p.read_text(encoding='utf-8'))
    s['running'] = False
    p.write_text(json.dumps(s, ensure_ascii=False), encoding='utf-8')
`.trim();
    const { spawnSync } = require("child_process");
    spawnSync(pythonExe, ["-c", code], { timeout: 2000 });
  } catch (e) {
    console.log("[Electron] clearTraderState 오류:", e.message);
  }
}

function killStreamlit() {
  if (streamlitProc) {
    console.log("[Electron] Streamlit 종료 중...");
    clearTraderState();
    try {
      spawn("taskkill", ["/pid", String(streamlitProc.pid), "/f", "/t"]);
    } catch {
      streamlitProc.kill("SIGTERM");
    }
    streamlitProc = null;
  }
}

function quitApp() {
  isQuitting = true;
  killStreamlit();
  if (tray) { tray.destroy(); tray = null; }
  app.quit();
}

// ──────────────────────────────────────────
// 앱 생명주기
// ──────────────────────────────────────────

app.whenReady().then(async () => {
  createSplash();
  startStreamlit();

  try {
    await waitForStreamlit(WAIT_TIMEOUT);
  } catch (err) {
    if (splashWindow) splashWindow.close();
    dialog.showErrorBox("시작 오류", `Streamlit 서버를 시작할 수 없습니다.\n\n${err.message}`);
    quitApp();
    return;
  }

  createMainWindow();
  createTray();

  if (splashWindow) { splashWindow.close(); splashWindow = null; }
  showMainWindow();
});

app.on("window-all-closed", (e) => {
  if (process.platform !== "darwin") e.preventDefault();
});

app.on("activate", () => {
  if (mainWindow) mainWindow.show();
});

app.on("before-quit", () => {
  isQuitting = true;
  killStreamlit();
});
