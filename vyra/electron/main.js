const { app, BrowserWindow, ipcMain, Tray, Menu, nativeImage } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

// ── Vyra Cursor Intelligence Overlay ────────────────────────────────────────
const cursorOverlay = require('./cursor-overlay');
// ── GPU / Hardware Acceleration ─────────────────────────────────────────────
// Target: NVIDIA RTX 3050 Laptop (D3D11 path) + Intel Iris Xe (display).
// These flags push Electron's renderer onto the dGPU and enable zero-copy paths.

// ANGLE D3D11 — most stable NVIDIA+Intel combo on Windows
app.commandLine.appendSwitch('use-angle', 'd3d11');

// Prefer high-performance (discrete) GPU over integrated
app.commandLine.appendSwitch('force_high_performance_gpu');

// Allow GPUs that Chromium normally blocklists
app.commandLine.appendSwitch('ignore-gpu-blocklist');
app.commandLine.appendSwitch('disable-gpu-driver-bug-workarounds');

// GPU rasterization — moves tile rendering from CPU threads to GPU shaders
app.commandLine.appendSwitch('enable-gpu-rasterization');

// Zero-copy texture uploads — eliminates CPU→GPU copy for canvas/WebGL
app.commandLine.appendSwitch('enable-zero-copy');

// Hardware video decode (DXVA2/D3D11VA) — offloads video from CPU
app.commandLine.appendSwitch('enable-accelerated-video-decode');
app.commandLine.appendSwitch('enable-accelerated-video-encode');

// Native GPU memory buffers — shared surfaces without extra copies
app.commandLine.appendSwitch('enable-native-gpu-memory-buffers');

// Don't hard-limit GPU process restarts
app.commandLine.appendSwitch('disable-gpu-process-crash-limit');

// Skia uses GPU for all 2D drawing (canvas, CSS, SVG animations)
app.commandLine.appendSwitch('use-skia-renderer');

// Feature flags: GPU compositing, OOP rasterization, accelerated canvas
app.commandLine.appendSwitch('enable-features',
  'Vulkan,UseSkiaRenderer,CanvasOopRasterization,' +
  'GpuRasterization,AcceleratedVideoDecodeLinuxGL'
);

// Cap Chromium compositor VRAM at 512 MB so Python ML keeps the rest
app.commandLine.appendSwitch('max-gpu-memory-mb', '512');
// ────────────────────────────────────────────────────────────────────────────

let mainWindow;
let pythonProcess;
let tray = null;

// When launched with --background (e.g. from Windows login auto-start), stay tray-only
const IS_BACKGROUND_START = process.argv.includes('--background');

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1920,
        height: 1080,
        webPreferences: {
            nodeIntegration: true,
            contextIsolation: false, // For simple IPC/Socket.IO usage
        },
        backgroundColor: '#000000',
        frame: false, // Frameless for custom UI
        titleBarStyle: 'hidden',
        show: false, // Don't show until ready
    });

    // In dev, load Vite server. In prod, load index.html
    const isDev = process.env.NODE_ENV !== 'production';

    const loadFrontend = (retries = 3) => {
        const url = isDev ? 'http://localhost:5173' : null;
        const loadPromise = isDev
            ? mainWindow.loadURL(url)
            : mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));

        loadPromise
            .then(() => {
                console.log('Frontend loaded successfully!');
                windowWasShown = true;
                mainWindow.show();
                if (isDev) {
                    mainWindow.webContents.openDevTools();
                }
            })
            .catch((err) => {
                console.error(`Failed to load frontend: ${err.message}`);
                if (retries > 0) {
                    console.log(`Retrying in 1 second... (${retries} retries left)`);
                    setTimeout(() => loadFrontend(retries - 1), 1000);
                } else {
                    console.error('Failed to load frontend after all retries. Keeping window open.');
                    windowWasShown = true;
                    mainWindow.show(); // Show anyway so user sees something
                }
            });
    };

    loadFrontend();

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

// ── System Tray ──────────────────────────────────────────────────────────────
// 16×16 violet circle encoded as a minimal inline PNG.
// If the base64 fails to decode, nativeImage.createEmpty() is used as fallback
// so a tray entry still appears (blank icon) without crashing.
const TRAY_ICON_B64 =
    'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAA' +
    'bElEQVQ4T2NkYGD4z0BEYGCgqmFABf8JtAEAAP//AwBQSwEC' +
    'FQAUAAAAAAAAIQAAAAAAAAAAAAAAAAAAAAAQAAAA';

function showDashboard() {
    if (mainWindow) {
        if (mainWindow.isMinimized()) mainWindow.restore();
        mainWindow.show();
        mainWindow.focus();
    } else {
        createWindow();
    }
}

function createTray() {
    let icon;
    try {
        icon = nativeImage.createFromDataURL('data:image/png;base64,' + TRAY_ICON_B64);
    } catch (_) {
        icon = nativeImage.createEmpty();
    }

    tray = new Tray(icon);
    tray.setToolTip('JARVIS — running in background');

    const buildMenu = () => Menu.buildFromTemplate([
        {
            label: 'Show Dashboard',
            click: () => showDashboard(),
        },
        { type: 'separator' },
        {
            label: 'Start on Login',
            type: 'checkbox',
            checked: app.getLoginItemSettings().openAtLogin,
            click: (item) => {
                app.setLoginItemSettings({
                    openAtLogin: item.checked,
                    args: ['--background'],
                });
            },
        },
        { type: 'separator' },
        {
            label: 'Quit JARVIS',
            click: () => {
                tray = null;
                app.quit();
            },
        },
    ]);

    tray.setContextMenu(buildMenu());

    // Rebuild menu on click so the "Start on Login" checkbox reflects current state
    tray.on('right-click', () => tray.setContextMenu(buildMenu()));

    // Left-click / double-click opens the dashboard
    tray.on('click', () => showDashboard());
    tray.on('double-click', () => showDashboard());
}

function startPythonBackend() {
    const scriptPath = path.join(__dirname, '../backend/server.py');
    console.log(`Starting Python backend: ${scriptPath}`);

    // Assuming 'python' is in PATH. In prod, this would be the executable.
    pythonProcess = spawn('python', [scriptPath], {
        cwd: path.join(__dirname, '../backend'),
    });

    pythonProcess.stdout.on('data', (data) => {
        console.log(`[Python]: ${data}`);
    });

    pythonProcess.stderr.on('data', (data) => {
        console.error(`[Python Error]: ${data}`);
    });
}

app.whenReady().then(() => {
    ipcMain.on('window-minimize', () => {
        if (mainWindow) mainWindow.minimize();
    });

    ipcMain.on('window-maximize', () => {
        if (mainWindow) {
            if (mainWindow.isMaximized()) {
                mainWindow.unmaximize();
            } else {
                mainWindow.maximize();
            }
        }
    });

    ipcMain.on('window-close', () => {
        // Hide to tray instead of closing — app stays alive in background
        if (mainWindow) mainWindow.hide();
    });

    // Triggered by the frontend when a double-clap is detected
    ipcMain.on('show-dashboard', () => showDashboard());

    // Open JARVIS dashboard in a dedicated BrowserWindow (iframe blocks cross-origin in Electron)
    let jarvisWindow = null;
    ipcMain.on('open-jarvis-window', (_event, url) => {
        if (jarvisWindow && !jarvisWindow.isDestroyed()) {
            jarvisWindow.loadURL(url);
            jarvisWindow.focus();
            jarvisWindow.moveTop();
            return;
        }
        jarvisWindow = new BrowserWindow({
            width: 1400,
            height: 900,
            title: 'JARVIS Dashboard',
            backgroundColor: '#0a0a0a',
            alwaysOnTop: true,          // stay above the fullscreen VYRA window
            webPreferences: {
                nodeIntegration: false,
                contextIsolation: true,
            },
        });
        jarvisWindow.loadURL(url);
        jarvisWindow.once('ready-to-show', () => {
            jarvisWindow.show();
            jarvisWindow.focus();
            jarvisWindow.moveTop();
        });
        jarvisWindow.on('closed', () => { jarvisWindow = null; });
    });

    // Always create the tray so the app can live in the background
    createTray();

    checkBackendPort(8000).then((isTaken) => {
        // In background-start mode: boot the backend but don't show the window.
        // ClapDetectorService + PassiveMonitor start inside the backend automatically.
        const afterBackendReady = IS_BACKGROUND_START
            ? () => {
                console.log('[JARVIS] Background start — staying in tray. Backend running.');
              }
            : () => {
                createWindow();
                // ── Cursor Intelligence Overlay ──────────────────────────────
                // Start IPC handlers immediately (they guard for overlayWindow == null)
                cursorOverlay.setupIPC();
                cursorOverlay.registerShortcuts();

                // Boot the overlay window once the main window signals it's ready.
                // This avoids the black screen caused by the overlay loading before
                // the compositor has finished setting up the main window.
                ipcMain.once('main-window-ready', () => {
                    const isDev = process.env.NODE_ENV !== 'production';
                    cursorOverlay.createOverlayWindow(isDev);
                    cursorOverlay.startMouseTracking();
                    console.log('[CursorOverlay] ✅ Cursor Intelligence Layer started');
                });

                // Safety fallback: if the renderer never fires the signal, boot after 5s
                setTimeout(() => {
                    if (!cursorOverlay.isOverlayRunning?.()) {
                        const isDev = process.env.NODE_ENV !== 'production';
                        cursorOverlay.createOverlayWindow(isDev);
                        cursorOverlay.startMouseTracking();
                        console.log('[CursorOverlay] ✅ Overlay started via fallback timer');
                    }
                }, 5000);
              };

        if (isTaken) {
            console.log('Port 8000 is taken. Assuming backend is already running manually.');
            waitForBackend().then(afterBackendReady);
        } else {
            startPythonBackend();
            // Give Python a moment to start, then wait for health check
            setTimeout(() => {
                waitForBackend().then(afterBackendReady);
            }, 1000);
        }
    });

    app.on('activate', () => {
        // macOS: re-open window when dock icon is clicked with no windows open
        if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
});

function checkBackendPort(port) {
    return new Promise((resolve) => {
        const net = require('net');
        const server = net.createServer();
        server.once('error', (err) => {
            if (err.code === 'EADDRINUSE') {
                resolve(true);
            } else {
                resolve(false);
            }
        });
        server.once('listening', () => {
            server.close();
            resolve(false);
        });
        server.listen(port);
    });
}

function waitForBackend() {
    return new Promise((resolve) => {
        const check = () => {
            const http = require('http');
            http.get('http://127.0.0.1:8000/status', (res) => {
                if (res.statusCode === 200) {
                    console.log('Backend is ready!');
                    resolve();
                } else {
                    console.log('Backend not ready, retrying...');
                    setTimeout(check, 1000);
                }
            }).on('error', (err) => {
                console.log('Waiting for backend...');
                setTimeout(check, 1000);
            });
        };
        check();
    });
}

let windowWasShown = false;

app.on('window-all-closed', () => {
    // If the tray is active, the app lives in the system tray — do NOT quit.
    // The only way to quit is via the tray context menu "Quit JARVIS" item,
    // which sets tray = null before calling app.quit().
    if (tray) {
        console.log('[JARVIS] Window closed — staying in tray. Use tray icon to exit.');
        return;
    }
    // No tray: fall back to original quit logic
    if (process.platform !== 'darwin' && windowWasShown) {
        app.quit();
    } else if (!windowWasShown) {
        console.log('Window was never shown - keeping app alive to allow retries');
    }
});

app.on('will-quit', () => {
    cursorOverlay.destroyOverlay();
    console.log('App closing... Killing Python backend.');
    if (pythonProcess) {
        if (process.platform === 'win32') {
            // Windows: Force kill the process tree synchronously
            try {
                const { execSync } = require('child_process');
                execSync(`taskkill /pid ${pythonProcess.pid} /f /t`);
            } catch (e) {
                console.error('Failed to kill python process:', e.message);
            }
        } else {
            // Unix: SIGKILL
            pythonProcess.kill('SIGKILL');
        }
        pythonProcess = null;
    }
});
