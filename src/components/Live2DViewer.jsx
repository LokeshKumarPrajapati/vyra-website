import { useEffect, useRef } from 'react'
import * as PIXI from 'pixi.js'
import { Live2DModel } from 'pixi-live2d-display/cubism4'

Live2DModel.registerTicker(PIXI.Ticker)

PIXI.settings.PRECISION_FRAGMENT  = 'highp'
PIXI.settings.PRECISION_VERTEX    = 'highp'
PIXI.settings.MIPMAP_TEXTURES     = PIXI.MIPMAP_MODES.ON
PIXI.settings.ANISOTROPIC_LEVEL   = 16
PIXI.settings.SCALE_MODE          = PIXI.SCALE_MODES.LINEAR
PIXI.settings.FILTER_RESOLUTION   = Math.min(window.devicePixelRatio * 2, 4)

const MODEL_URL  = '/vyra2d/v2_14emu_school_t02.model3.json'
const RESOLUTION = Math.min(Math.max((window.devicePixelRatio || 1) * 3, 4), 6)

// ── Random idle poses ─────────────────────────────────────────────────────────
const POSE_SETS = [
  { pose: 'w-cute11-pose',       face: 'face_ncsmile_18'    },
  { pose: 'w-cute11-poseB',      face: 'face_smile_12'      },
  { pose: 'w-cute01-pose',       face: 'face_sparkling_02'  },
  { pose: 'w-cute02-pose',       face: 'face_ncsmile_09'    },
  { pose: 'w-cute14-pose',       face: 'face_smile_09'      },
  { pose: 'w-cute11-piece',      face: 'face_wink_01'       },
  { pose: 'w-happy11-piece',     face: 'face_e_01'          },
  { pose: 'w-cute01-tilthead',   face: 'face_wonder_train_01' },
  { pose: 'w-cute11-tilthead',   face: 'face_ncsmile_18'    },
  { pose: 'w-adult01-tilthead',  face: 'face_ncsmile_07'    },
  { pose: 'w-cute14-tilthead',   face: 'face_smile_03'      },
  { pose: 'w-cute11-shy02',      face: 'face_shy_01'        },
  { pose: 'w-cute01-shy',        face: 'w-adult01-blushed'  },
  { pose: 'w-normal15-shy',      face: 'face_smile_15'      },
  { pose: 'w-cute12-pose',       face: 'face_shy_01'        },
  { pose: 'w-happy11-pose',      face: 'face_sparkling_02'  },
  { pose: 'w-happy14-pose',      face: 'face_smile_07'      },
  { pose: 'w-happy02-pose',      face: 'face_ncsmile_18'    },
  { pose: 'w-cute11-glad',       face: 'face_delicious_01'  },
  { pose: 'w-cute11-forward',    face: 'face_e_01'          },
  { pose: 'w-cute01-forward03',  face: 'face_wonder_train_01' },
  { pose: 'w-cute11-bright',     face: 'face_sparkling_02'  },
  { pose: 'w-cute11-delicious',  face: 'face_delicious_01'  },
  { pose: 'w-cute11-guts',       face: 'face_e_01'          },
  { pose: 'w-cool02-pose',       face: 'face_ncsmile_01'    },
  { pose: 'w-cool10-pose',       face: 'face_smile_02'      },
  { pose: 'w-cool13-pose',       face: 'face_ncsmile_03'    },
  { pose: 'w-adult01-pose',      face: 'face_ncsmile_07'    },
  { pose: 'w-adult02-pose',      face: 'face_smile_01'      },
  { pose: 'w-pure12-pose',       face: 'face_ncsmile_09'    },
  { pose: 'w-cute01-sleep05',    face: 'face_sleepy_01'     },
]

// ── Emotion → motion (matches vyra's [EMOTION:xxx] tag system) ───────────────
const EMOTION_MAP = {
  happy:     { pose: 'w-happy02-pose',       face: 'face_ncsmile_18'      },
  sad:       { pose: 'w-normal15-shy',        face: 'face_cry_01'          },
  angry:     { pose: 'w-cool02-pose',         face: 'face_angry_01'        },
  surprised: { pose: 'w-cute01-tilthead',     face: 'face_ncsurprise_03'   },
  thinking:  { pose: 'w-cute01-tilthead',     face: 'face_wonder_train_01' },
  playful:   { pose: 'w-cute11-piece',        face: 'face_e_01'            },
  loving:    { pose: 'w-cute11-forward',      face: 'face_ncsmile_18'      },
  love:      { pose: 'w-cute11-forward',      face: 'face_ncsmile_18'      },
  shy:       { pose: 'w-cute11-shy02',        face: 'face_shy_01'          },
  disgusted: { pose: 'w-cool10-pose',         face: 'face_disgust_01'      },
  sleepy:    { pose: 'w-cute01-sleep05',      face: 'face_sleepy_01'       },
  neutral:   { pose: 'w-cool10-pose',         face: 'face_ncnormal_01'     },
  serious:   { pose: 'w-adult01-pose',        face: 'face_ncnormal_01'     },
  cry:       { pose: 'w-normal15-shy',        face: 'face_cry_01'          },
  scared:    { pose: 'w-cute01-shakehead04',  face: 'face_ncsurprise_03'   },
  protective:{ pose: 'w-cool02-pose',         face: 'face_angry_01'        },
  jealous:   { pose: 'w-cute11-shy02',        face: 'face_disgust_01'      },
  caring:    { pose: 'w-happy02-pose',        face: 'face_ncsmile_09'      },
}

// ── Touch reaction zones ──────────────────────────────────────────────────────
const TOUCH_REACTIONS = {
  head: [
    { pose: 'w-cute01-shakehead04', face: 'face_ncsurprise_03'   },
    { pose: 'w-cute11-tilthead',    face: 'face_wonder_train_01' },
    { pose: 'w-cute14-shakehead',   face: 'face_e_01'            },
    { pose: 'w-cute12-nod',         face: 'face_ncsmile_18'      },
    { pose: 'w-adult01-tilthead',   face: 'face_ncsurprise_04'   },
  ],
  face: [
    { pose: 'w-special11-cheek',    face: 'face_spicy_01'        },
    { pose: 'w-special11-cheekB',   face: 'face_e_01'            },
    { pose: 'w-cute11-shy02',       face: 'face_shy_01'          },
    { pose: 'w-cute01-shy',         face: 'face_ncsmile_18'      },
    { pose: 'w-cute11-nbshy02',     face: 'w-adult01-blushed'    },
  ],
  body: [
    { pose: 'w-cute11-bright',      face: 'face_sparkling_02'    },
    { pose: 'w-cute11-glad',        face: 'face_delicious_01'    },
    { pose: 'w-cute11-forward',     face: 'face_e_01'            },
    { pose: 'w-cute11-fidget02',    face: 'face_wonder_train_01' },
    { pose: 'w-cute11-guts',        face: 'face_ncsmile_18'      },
  ],
  lower: [
    { pose: 'w-cute11-piece',       face: 'face_wink_01'         },
    { pose: 'w-happy11-shakehand',  face: 'face_sparkling_02'    },
    { pose: 'w-cute02-guts',        face: 'face_e_01'            },
    { pose: 'w-special11-wandahoi', face: 'face_spicy_01'        },
    { pose: 'w-cute14-pose',        face: 'face_delicious_01'    },
  ],
}

function pickRandom(arr, excludePose) {
  const pool = arr.filter(x => (x.pose || x) !== excludePose)
  return pool[Math.floor(Math.random() * pool.length)]
}

// controlRef: plain ref passed as prop — avoids forwardRef / React Fast Refresh conflict
export default function Live2DViewer({ controlRef }) {
  const mountRef = useRef(null)

  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return

    let app = null, alive = true, rafId = null
    let pointerMoveHandler = null, pointerDownHandler = null
    let cycleTimer = null, lastPose = null
    let isReacting = false
    let externalPaused = false

    // ── Play a matched pose + expression set ─────────────────────────────────
    function playSet(model, set) {
      lastPose = set.pose
      try { model.motion(set.pose) } catch (_) {}
      setTimeout(() => {
        if (!alive) return
        try { model.motion(set.face) } catch (_) {}
      }, 280)
    }

    // ── Auto-cycle random pose every 6.5–9.5 s ───────────────────────────────
    function autoCycle(model) {
      if (!alive || isReacting || externalPaused) return
      const set = pickRandom(POSE_SETS, lastPose)
      playSet(model, set)
      cycleTimer = setTimeout(() => autoCycle(model), 6500 + Math.random() * 3000)
    }

    // ── Zone-based touch reaction ─────────────────────────────────────────────
    function handleTouch(model, canvas, e) {
      if (!alive || externalPaused) return
      isReacting = true
      if (cycleTimer) clearTimeout(cycleTimer)

      const rect   = canvas.getBoundingClientRect()
      const relY   = (e.clientY - rect.top) / rect.height
      const modelY = Math.max(0, Math.min(1, (relY - 0.04) / 0.92))

      let zone
      if      (modelY < 0.20) zone = 'head'
      else if (modelY < 0.38) zone = 'face'
      else if (modelY < 0.65) zone = 'body'
      else                    zone = 'lower'

      const reaction = TOUCH_REACTIONS[zone][Math.floor(Math.random() * TOUCH_REACTIONS[zone].length)]
      playSet(model, reaction)

      cycleTimer = setTimeout(() => { isReacting = false; autoCycle(model) }, 4000)
    }

    const init = () => {
      if (!alive) return
      const W = mount.clientWidth, H = mount.clientHeight
      if (W <= 0 || H <= 0) { rafId = requestAnimationFrame(init); return }

      const canvas = document.createElement('canvas')
      canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block;cursor:pointer;'
      mount.appendChild(canvas)

      try {
        app = new PIXI.Application({
          view: canvas, width: W, height: H,
          backgroundAlpha: 0, antialias: true, autoDensity: true,
          resolution: RESOLUTION, powerPreference: 'high-performance',
          clearBeforeRender: true,
        })
      } catch { canvas.remove(); return }

      Live2DModel.from(MODEL_URL, { autoInteract: false })
        .then((model) => {
          if (!alive) { model.destroy(); return }
          // Disable PIXI event traversal — pixi-live2d-display uses old interactive API
          // which causes isInteractive() crash in PIXI v7.4+. We handle events on canvas directly.
          model.eventMode = 'none'
          app.stage.addChild(model)
          fitModel(model, W, H)

          // ── Expose voice-chat control API via plain prop ref ──────────────
          if (controlRef) {
            controlRef.current = {
              triggerEmotion(name) {
                if (!alive) return
                const set = EMOTION_MAP[name] ?? EMOTION_MAP.neutral
                playSet(model, set)
              },
              setMouthOpen(value) {
                if (!alive) return
                try {
                  model.internalModel.coreModel.setParameterValueById(
                    'ParamMouthOpenY', Math.max(0, Math.min(1, value)), 1
                  )
                } catch (_) {}
              },
              pauseAutoReact() {
                externalPaused = true
                if (cycleTimer) { clearTimeout(cycleTimer); cycleTimer = null }
              },
              resumeAutoReact() {
                externalPaused = false
                setTimeout(() => autoCycle(model), 1500)
              },
            }
          }

          autoCycle(model)

          pointerMoveHandler = (e) => {
            const rect = canvas.getBoundingClientRect()
            model.focus(e.clientX - rect.left, e.clientY - rect.top)
          }
          window.addEventListener('pointermove', pointerMoveHandler)

          pointerDownHandler = (e) => handleTouch(model, canvas, e)
          canvas.addEventListener('pointerdown', pointerDownHandler)

          const ro = new ResizeObserver(() => {
            if (!app || !alive) return
            const w = mount.clientWidth, h = mount.clientHeight
            if (w <= 0 || h <= 0) return
            app.renderer.resize(w, h)
            fitModel(model, w, h)
          })
          ro.observe(mount)
          mount._ro = ro
        })
        .catch(e => console.warn('[Live2D] load error:', e))
    }

    rafId = requestAnimationFrame(init)

    return () => {
      alive = false
      if (controlRef) controlRef.current = null
      if (rafId)              cancelAnimationFrame(rafId)
      if (cycleTimer)         clearTimeout(cycleTimer)
      if (pointerMoveHandler) window.removeEventListener('pointermove', pointerMoveHandler)
      if (mount._ro)          { mount._ro.disconnect(); delete mount._ro }
      if (app) {
        try { app.destroy(true, { children: true, texture: true }) } catch (_) {}
        app = null
      }
      mount.querySelectorAll('canvas').forEach(c => c.remove())
    }
  }, [])

  return <div ref={mountRef} style={{ position: 'relative', width: '100%', height: '100%' }} />
}

function fitModel(model, W, H) {
  const nativeH = model.height / model.scale.y
  const scale   = (H * 0.92) / nativeH
  model.scale.set(scale)
  model.x = (W - model.width)  / 2
  model.y = (H - model.height) / 2
}
