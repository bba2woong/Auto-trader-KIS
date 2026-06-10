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

const { app, BrowserWindow, Menu, Tray, dialog, shell, nativeImage } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const http = require("http");
const fs   = require("fs");

// ──────────────────────────────────────────
// 경로 설정
// ──────────────────────────────────────────

const IS_PACKAGED = app.isPackaged;

// 프로젝트 루트: 개발 시 electron/../, 배포 시 resources/app/
const PROJECT_ROOT = IS_PACKAGED
  ? path.join(process.resourcesPath)          // extraResources가 여기에 복사됨
  : path.join(__dirname, "..");               // kis_trader/

// venv 경로
const VENV_ROOT = IS_PACKAGED
  ? path.join(process.resourcesPath, "venv")
  : path.join(PROJECT_ROOT, "venv");

const STREAMLIT_EXE = path.join(VENV_ROOT, "Scripts", "streamlit.exe");
const APP_PY        = path.join(PROJECT_ROOT, "app.py");
const ICON_PATH     = path.join(__dirname, "..", "assets", "icon.ico");

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
  console.log(`[Electron] app.py: ${APP_PY}`);
  console.log(`[Electron] cwd: ${PROJECT_ROOT}`);

  streamlitProc = spawn(STREAMLIT_EXE, ["run", APP_PY, "--server.headless", "true"], {
    cwd: PROJECT_ROOT,
    env: {
      ...process.env,
      // Streamlit 브라우저 자동 열기 방지
      STREAMLIT_SERVER_HEADLESS: "true",
      STREAMLIT_BROWSER_GATHER_USAGE_STATS: "false",
    },
    windowsHide: true,   // 콘솔 창 숨기기
  });

  streamlitProc.stdout.on("data", (data) => {
    console.log(`[Streamlit] ${data.toString().trim()}`);
  });
  streamlitProc.stderr.on("data", (data) => {
    console.error(`[Streamlit ERR] ${data.toString().trim()}`);
  });
  streamlitProc.on("exit", (code) => {
    console.log(`[Streamlit] 프로세스 종료 (code=${code})`);
  });
}

// ──────────────────────────────────────────
// Streamlit 서버 준비 대기
// ──────────────────────────────────────────

function waitForStreamlit(timeout) {
  return new Promise((resolve, reject) => {
    const start   = Date.now();
    const interval = setInterval(() => {
      http.get(STREAMLIT_URL, (res) => {
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
    width:           400,
    height:          250,
    frame:           false,
    alwaysOnTop:     true,
    transparent:     true,
    resizable:       false,
    skipTaskbar:     true,
    webPreferences:  { contextIsolation: true },
  });

  splashWindow.loadURL(`data:text/html;charset=utf-8,
    <html>
    <head><style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      body {
        background: #1a1a2e;
        color: #e0e0e0;
        font-family: 'Segoe UI', sans-serif;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        height: 100vh;
        border-radius: 12px;
        border: 1px solid #333;
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
      <h1>📈 KIS Auto Trader</h1>
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

function createMainWindow() {
  const iconOpt = fs.existsSync(ICON_PATH) ? { icon: ICON_PATH } : {};

  mainWindow = new BrowserWindow({
    width:   1400,
    height:  900,
    title:   "KIS Auto Trader",
    show:    false,   // 스플래시 숨기고 나서 표시
    webPreferences: {
      contextIsolation: true,
      nodeIntegration:  false,
    },
    ...iconOpt,
  });

  mainWindow.loadURL(STREAMLIT_URL);

  // 창 닫기(X) → 트레이로 최소화 (완전 종료 아님)
  mainWindow.on("close", (e) => {
    if (!isQuitting) {
      e.preventDefault();
      mainWindow.hide();
      if (tray) {
        tray.displayBalloon({
          title:   "KIS Auto Trader",
          content: "트레이에서 실행 중입니다.",
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
        {
          label:       "종료",
          accelerator: "CmdOrCtrl+Q",
          click:       () => quitApp(),
        },
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
  let trayIcon;
  try {
    trayIcon = nativeImage.createFromPath(ICON_PATH);
    if (trayIcon.isEmpty()) throw new Error("empty");
  } catch {
    // 아이콘 없으면 빈 이미지 사용
    trayIcon = nativeImage.createEmpty();
  }

  tray = new Tray(trayIcon);
  tray.setToolTip("KIS Auto Trader");

  const contextMenu = Menu.buildFromTemplate([
    {
      label: "열기",
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      },
    },
    { type: "separator" },
    {
      label: "종료",
      click: () => quitApp(),
    },
  ]);

  tray.setContextMenu(contextMenu);

  // 트레이 더블클릭 → 창 표시
  tray.on("double-click", () => {
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

// ──────────────────────────────────────────
// 정리 및 종료
// ──────────────────────────────────────────

function killStreamlit() {
  if (streamlitProc) {
    console.log("[Electron] Streamlit 프로세스 종료 중...");
    try {
      // Windows에서 자식 프로세스 트리 전체 종료
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
  // 스플래시 표시
  createSplash();

  // Streamlit 시작
  startStreamlit();

  // 서버 응답 대기
  try {
    await waitForStreamlit(WAIT_TIMEOUT);
  } catch (err) {
    if (splashWindow) splashWindow.close();
    dialog.showErrorBox("시작 오류", `Streamlit 서버를 시작할 수 없습니다.\n\n${err.message}`);
    quitApp();
    return;
  }

  // 메인 창 + 트레이 생성
  createMainWindow();
  createTray();

  // 스플래시 닫고 메인 창 표시
  if (splashWindow) { splashWindow.close(); splashWindow = null; }
  mainWindow.show();
  mainWindow.focus();
});

app.on("window-all-closed", (e) => {
  // 모든 창이 닫혀도 트레이가 있으면 앱 유지 (Windows 동작)
  if (process.platform !== "darwin") {
    e.preventDefault();
  }
});

app.on("activate", () => {
  // macOS: dock 클릭 시 창 복원
  if (mainWindow) {
    mainWindow.show();
  }
});

app.on("before-quit", () => {
  isQuitting = true;
  killStreamlit();
});
