/**
 * cursor-overlay.js  — v4 (instant-show + smooth)
 * Vyra Cursor Intelligence Layer
 *
 * KEY CHANGES from v3:
 *   1. Tracking indicator REMOVED — was causing the black rectangle in top-right
 *   2. Chip shows INSTANTLY (loading/skeleton state) before backend responds
 *      — no 300ms blank wait; content arrives async and updates in-place
 *   3. Cursor position streamed at 60fps to renderer when overlay is visible
 *      — lets renderer use RAF lerp for in-window animations
 *   4. HOVER_DEBOUNCE_MS reduced to 200ms (from 300ms)
 *   5. Backend response fires overlay:show AGAIN (no setBounds) — seamless update
 *
 * WHY NO TRANSPARENT WINDOW:
 *   D3D11 ANGLE (forced by RTX GPU) breaks per-pixel alpha → opaque only.
 *   Dynamic popup approach: small opaque window, resized per component.
 */

const {
    BrowserWindow, ipcMain, desktopCapturer,
    globalShortcut, screen,
} = require('electron');
const path = require('path');
const http  = require('http');

// ── Constants ──────────────────────────────────────────────────────────────────
const POLL_INTERVAL_MS  = 8;    // 120fps cursor polling
const MOVE_THRESHOLD_PX = 2;    // skip IPC if delta < 2px
const HOVER_DEBOUNCE_MS = 200;  // ms after cursor stops → trigger hover analysis
const POS_STREAM_MS     = 16;   // ~60fps position stream to renderer (when visible)
const OVERLAY_PRELOAD   = path.join(__dirname, 'overlay-preload.js');

// Per-component window size + cursor offset
const COMPONENT_CONFIGS = {
    hover:     { width: 210, height: 190, ox:  18, oy: -10 },
    menu:      { width: 215, height: 295, ox:   2, oy:   2 },
    selection: { width: 350, height:  50, ox:   0, oy: -60 },
    region:    { width: 295, height: 430, ox:  20, oy:   0 },
    clipboard: { width: 330, height: 430, fixed: { right: 24, top: 80 } },
    palette:   { width: 580, height: 460, centered: true },
};

// ── State ──────────────────────────────────────────────────────────────────────
let overlayWindow    = null;
let overlayReady     = false;   // true once did-finish-load fires
let pendingShowMsg   = null;    // last overlay:show queued before page loaded
let pollTimer        = null;
let hoverTimer       = null;
let lastX            = -999;
let lastY            = -999;
let lastPosSend      = 0;       // throttle for cursor:pos stream
let captureInFlight  = false;
let mouseHook        = null;
let uiohookAvailable = false;
let altIsDown        = false;
let currentComponent = null;    // type of currently-shown component

// ── uiohook-napi (optional global hook) ───────────────────────────────────────
try {
    mouseHook        = require('uiohook-napi');
    uiohookAvailable = true;
    console.log('[CursorOverlay] uiohook-napi loaded');
} catch (e) {
    console.warn('[CursorOverlay] uiohook-napi not found → polling:', e.message);
}

// ── Create overlay window ──────────────────────────────────────────────────────
function createOverlayWindow(isDev) {
    overlayWindow = new BrowserWindow({
        width:       1,
        height:      1,
        x:           0,
        y:           0,
        show:        false,
        transparent: false,
        frame:       false,
        alwaysOnTop: true,
        skipTaskbar: true,
        resizable:   false,
        movable:     false,
        focusable:   true,
        hasShadow:   true,
        webPreferences: {
            nodeIntegration:      true,
            contextIsolation:     false,
            preload:              OVERLAY_PRELOAD,
            backgroundThrottling: false,
        },
    });

    overlayWindow.setAlwaysOnTop(true, 'pop-up-menu');

    const url = isDev
        ? 'http://localhost:5173/overlay.html'
        : `file://${path.join(__dirname, '../dist/overlay.html')}`;

    overlayWindow.loadURL(url).catch(err => {
        console.error('[CursorOverlay] loadURL error:', err.message);
    });

    // Mark page ready and flush any queued show payload
    overlayWindow.webContents.on('did-finish-load', () => {
        overlayReady = true;
        if (pendingShowMsg) {
            if (currentComponent && overlayWindow && !overlayWindow.isDestroyed()) {
                overlayWindow.webContents.send('overlay:show', pendingShowMsg);
            }
            pendingShowMsg = null;
        }
        console.log('[CursorOverlay] Overlay page ready');
    });

    overlayWindow.on('blur',   () => _hideOverlay('blur'));
    overlayWindow.on('closed', () => { overlayWindow = null; overlayReady = false; });

    console.log('[CursorOverlay] Overlay window created (v4 instant-show)');
    return overlayWindow;
}

// ── Show / hide helpers ────────────────────────────────────────────────────────
function _showComponent(type, x, y, payload) {
    if (!overlayWindow || overlayWindow.isDestroyed()) return;

    const cfg = COMPONENT_CONFIGS[type];
    if (!cfg) return;

    const display = screen.getPrimaryDisplay().bounds;
    const sw = display.width, sh = display.height;
    const dx = display.x,    dy = display.y;

    let wx, wy;
    if (cfg.centered) {
        wx = dx + Math.round((sw - cfg.width)  / 2);
        wy = dy + Math.round(sh * 0.15);
    } else if (cfg.fixed) {
        wx = dx + sw - cfg.width - (cfg.fixed.right || 24);
        wy = dy + (cfg.fixed.top || 80);
    } else {
        wx = Math.min(x + cfg.ox, dx + sw - cfg.width  - 8);
        wy = Math.max(y + cfg.oy, dy + 8);
        if (wy + cfg.height > dy + sh - 8) wy = dy + sh - cfg.height - 8;
        if (wx < dx + 8) wx = dx + 8;
    }

    currentComponent = type;

    // Send IPC payload FIRST (React renders before window is visible)
    sendToOverlay('overlay:show', { type, x, y, ...payload });

    // Check if window is already shown for this component type — skip setBounds
    if (!overlayWindow.isVisible()) {
        overlayWindow.setBounds({
            x: Math.round(wx), y: Math.round(wy),
            width: cfg.width,  height: cfg.height,
        }, false);

        // 16ms delay → React renders skeleton before window appears (no white flash)
        // Capture type now — if _hideOverlay fires before timer, currentComponent will
        // be null and we skip the show (prevents the stale black-box race condition).
        const snapType = type;
        setTimeout(() => {
            if (overlayWindow && !overlayWindow.isDestroyed() && currentComponent === snapType) {
                overlayWindow.showInactive();
            }
        }, 16);
    }
    // If already visible: just sent IPC above — React updates in-place, no reposition
}

function _hideOverlay(reason) {
    if (!overlayWindow || overlayWindow.isDestroyed()) return;
    currentComponent = null;
    overlayWindow.hide();
    sendToOverlay('overlay:hide', { reason });
}

// ── Backend hover ping  (with INSTANT pre-show) ────────────────────────────────
function _pingHover(x, y) {
    // ① Show skeleton IMMEDIATELY — zero perceived lag
    _showComponent('hover', x, y, { loading: true });

    // ② Ping backend for real context
    const req = http.request(
        {
            hostname: '127.0.0.1', port: 8000,
            path:     `/cursor/hover?x=${x}&y=${y}`,
            method:   'GET', timeout: 500,
        },
        (res) => {
            let raw = '';
            res.on('data', d => raw += d);
            res.on('end', () => {
                if (res.statusCode !== 200) { _hideOverlay('bad-status'); return; }
                try {
                    const ctx = JSON.parse(raw);
                    if (ctx && ctx.type && ctx.type !== 'unknown') {
                        // Update chip IN PLACE — no setBounds, no flicker
                        sendToOverlay('overlay:show', {
                            type:    'hover',
                            loading: false,
                            x, y,
                            ...ctx,
                        });
                    } else {
                        _hideOverlay('unknown');
                    }
                } catch (_) { _hideOverlay('parse-err'); }
            });
        }
    );
    req.on('error',   () => { _hideOverlay('net-err'); });
    req.on('timeout', () => { req.destroy(); _hideOverlay('timeout'); });
    req.end();
}

// ── Core move handler ──────────────────────────────────────────────────────────
function _onCursorMove(x, y) {
    const dx = x - lastX;
    const dy = y - lastY;
    if (Math.abs(dx) < MOVE_THRESHOLD_PX && Math.abs(dy) < MOVE_THRESHOLD_PX) return;

    lastX = x;
    lastY = y;

    // Hide hover chip as soon as cursor moves (feels instant)
    if (currentComponent === 'hover') {
        _hideOverlay('moved');
    } else if (!currentComponent && overlayWindow?.isVisible()) {
        // Stale visible window with no active component — force close
        overlayWindow.hide();
    }

    // Reset hover debounce
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => _pingHover(x, y), HOVER_DEBOUNCE_MS);

    // Stream position to renderer at ~60fps when overlay is visible
    const now = Date.now();
    if (
        overlayWindow && !overlayWindow.isDestroyed() && overlayWindow.isVisible() &&
        now - lastPosSend >= POS_STREAM_MS
    ) {
        lastPosSend = now;
        sendToOverlay('cursor:pos', { x, y });
    }
}

// ── Mouse tracking ─────────────────────────────────────────────────────────────
function startMouseTracking() {
    if (uiohookAvailable && mouseHook) {
        _startUiohook();
    } else {
        _startPolling();
    }
}

function _startUiohook() {
    const { uIOhook, UiohookKey } = mouseHook;

    uIOhook.on('mousemove', e => _onCursorMove(e.x, e.y));

    uIOhook.on('mousedown', e => {
        if (e.button === 2) {
            _showComponent('menu', e.x, e.y, { x: e.x, y: e.y });
        }
    });

    uIOhook.on('keydown', e => {
        if (e.keycode === UiohookKey.Alt && !altIsDown) {
            altIsDown = true;
            sendToOverlay('cursor:alt-down', {});
        }
    });
    uIOhook.on('keyup', e => {
        if (e.keycode === UiohookKey.Alt) {
            altIsDown = false;
            sendToOverlay('cursor:alt-up', {});
        }
    });

    uIOhook.start();
    console.log('[CursorOverlay] uiohook started (global)');
}

function _startPolling() {
    console.log('[CursorOverlay] 120fps polling started');
    pollTimer = setInterval(() => {
        const p = screen.getCursorScreenPoint();
        _onCursorMove(p.x, p.y);
    }, POLL_INTERVAL_MS);
}

// ── Explicit region capture (on-demand only) ───────────────────────────────────
async function _captureRegion(x, y, w, h) {
    if (captureInFlight) return null;
    captureInFlight = true;
    try {
        const b  = screen.getPrimaryDisplay().bounds;
        const tw = Math.min(b.width, 1920), th = Math.min(b.height, 1080);
        const sources = await desktopCapturer.getSources({
            types: ['screen'], thumbnailSize: { width: tw, height: th },
        });
        if (!sources.length) return null;
        const sx = tw / b.width, sy = th / b.height;
        const cropped = sources[0].thumbnail.crop({
            x:      Math.round(x * sx),
            y:      Math.round(y * sy),
            width:  Math.min(tw - Math.round(x * sx), Math.round(w * sx)),
            height: Math.min(th - Math.round(y * sy), Math.round(h * sy)),
        });
        return cropped.toDataURL();
    } catch (e) {
        console.error('[CursorOverlay] captureRegion:', e.message);
        return null;
    } finally {
        captureInFlight = false;
    }
}

// ── IPC setup ──────────────────────────────────────────────────────────────────
function setupIPC() {
    ipcMain.on('overlay:show-component', (_e, { type, x, y, ...rest }) => {
        _showComponent(type, x, y, rest);
    });

    ipcMain.on('overlay:hide', () => _hideOverlay('renderer'));

    ipcMain.handle('overlay:capture-region', async (_e, { x, y, w, h }) => {
        return await _captureRegion(x, y, w, h);
    });

    ipcMain.on('overlay:action', (_e, payload) => {
        const wins    = BrowserWindow.getAllWindows();
        const mainWin = wins.find(w => w !== overlayWindow && !w.isDestroyed());
        if (mainWin) mainWin.webContents.send('cursor:action', payload);
        _hideOverlay('action');
    });

    ipcMain.on('cursor:push', (_e, payload) => {
        if (payload?.type === 'selection') {
            _showComponent('selection', payload.x || 400, payload.y || 300, payload);
        } else if (payload?.type === 'clipboard') {
            _showComponent('clipboard', 0, 0, payload);
        }
    });
}

// ── Shortcuts ──────────────────────────────────────────────────────────────────
function registerShortcuts() {
    const reg = (key, fn) => {
        try { globalShortcut.register(key, fn); }
        catch (e) { console.warn('[CursorOverlay] shortcut conflict:', key); }
    };

    reg('CommandOrControl+Shift+Space', () => {
        if (!overlayWindow || overlayWindow.isDestroyed()) return;
        if (overlayWindow.isVisible()) {
            _hideOverlay('toggle');
        } else {
            _showComponent('palette', 0, 0, {});
        }
    });

    reg('CommandOrControl+Shift+K', () => _showComponent('palette', 0, 0, {}));

    console.log('[CursorOverlay] Shortcuts registered');
}

// ── Util ───────────────────────────────────────────────────────────────────────
function sendToOverlay(channel, data) {
    if (!overlayWindow || overlayWindow.isDestroyed()) return;

    if (!overlayReady) {
        // Page not loaded yet — buffer the latest show payload; drop hide/pos
        if (channel === 'overlay:show') pendingShowMsg = data;
        return;
    }

    overlayWindow.webContents.send(channel, data);
}

// ── Cleanup ────────────────────────────────────────────────────────────────────
function destroyOverlay() {
    if (pollTimer)  { clearInterval(pollTimer);  pollTimer  = null; }
    if (hoverTimer) { clearTimeout(hoverTimer);  hoverTimer = null; }
    if (uiohookAvailable && mouseHook) {
        try { mouseHook.uIOhook.stop(); } catch (_) {}
    }
    try { globalShortcut.unregisterAll(); } catch (_) {}
    if (overlayWindow && !overlayWindow.isDestroyed()) overlayWindow.destroy();
    overlayWindow = null;
    overlayReady  = false;
    pendingShowMsg = null;
}

module.exports = {
    createOverlayWindow,
    startMouseTracking,
    registerShortcuts,
    setupIPC,
    destroyOverlay,
    sendToOverlay,
    isOverlayRunning: () => overlayWindow !== null && !overlayWindow.isDestroyed(),
};
