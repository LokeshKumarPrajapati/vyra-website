/**
 * overlay-preload.js
 * Preload for the Vyra cursor overlay BrowserWindow (dynamic popup mode).
 */
const { ipcRenderer } = require('electron');

const ALLOWED_CHANNELS = [
    'overlay:show',
    'overlay:hide',
    'cursor:alt-down',
    'cursor:alt-up',
    'cursor:pos',       // 60fps cursor position stream (x, y in screen coords)
];

window.overlayBridge = {
    on:  (ch, cb) => { if (ALLOWED_CHANNELS.includes(ch)) ipcRenderer.on(ch, (_e, d) => cb(d)); },
    off: (ch, cb) => ipcRenderer.removeListener(ch, cb),

    // Request main process to show a different component
    showComponent: (type, x, y, data) =>
        ipcRenderer.send('overlay:show-component', { type, x, y, ...data }),

    // Hide the overlay window
    hideOverlay: () => ipcRenderer.send('overlay:hide'),

    // Capture a screen region (for RegionAnalyzer)
    captureRegion: (rect) => ipcRenderer.invoke('overlay:capture-region', rect),

    // Send a cursor intelligence action back to the main Vyra pipeline
    sendAction: (payload) => ipcRenderer.send('overlay:action', payload),

    // No-ops kept for compatibility (not needed in dynamic popup mode)
    enableMouse:  () => {},
    disableMouse: () => {},
};
