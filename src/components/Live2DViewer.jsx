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

// ── Random idle poses — broad variety across all character types ──────────────
const POSE_SETS = [
  // cute11 series
  { pose: 'w-cute11-pose',        face: 'face_ncsmile_18'    },
  { pose: 'w-cute11-poseB',       face: 'face_smile_12'      },
  { pose: 'w-cute11-tilthead',    face: 'face_ncsmile_18'    },
  { pose: 'w-cute11-tilthead02',  face: 'face_smile_03'      },
  { pose: 'w-cute11-piece',       face: 'face_wink_01'       },
  { pose: 'w-cute11-bright',      face: 'face_sparkling_02'  },
  { pose: 'w-cute11-forward',     face: 'face_e_01'          },
  { pose: 'w-cute11-glad',        face: 'face_delicious_01'  },
  // cute01 series
  { pose: 'w-cute01-pose',        face: 'face_sparkling_02'  },
  { pose: 'w-cute01-tilthead',    face: 'face_wonder_train_01'},
  { pose: 'w-cute01-tilthead02',  face: 'face_ncsmile_02'    },
  { pose: 'w-cute01-forward03',   face: 'face_ncsmile_18'    },
  // cute02 / cute12 / cute13 / cute14
  { pose: 'w-cute02-pose',        face: 'face_ncsmile_09'    },
  { pose: 'w-cute02-tilthead',    face: 'face_smile_05'      },
  { pose: 'w-cute12-pose',        face: 'face_ncsmile_01'    },
  { pose: 'w-cute13-tilthead',    face: 'face_smile_04'      },
  { pose: 'w-cute14-pose',        face: 'face_smile_09'      },
  { pose: 'w-cute14-tilthead',    face: 'face_smile_03'      },
  // happy series
  { pose: 'w-happy02-pose',       face: 'face_ncsmile_18'    },
  { pose: 'w-happy11-pose',       face: 'face_sparkling_02'  },
  { pose: 'w-happy14-pose',       face: 'face_smile_07'      },
  { pose: 'w-happy11-piece',      face: 'face_e_01'          },
  { pose: 'w-happy09-tilthead',   face: 'face_smile_08'      },
  { pose: 'w-happy16-tilthead',   face: 'face_smile_06'      },
  // adult series
  { pose: 'w-adult01-pose',       face: 'face_ncsmile_07'    },
  { pose: 'w-adult02-pose',       face: 'face_smile_01'      },
  { pose: 'w-adult05-pose',       face: 'face_ncsmile_03'    },
  { pose: 'w-adult12-pose',       face: 'face_ncsmile_09'    },
  { pose: 'w-adult01-tilthead',   face: 'face_ncsmile_07'    },
  { pose: 'w-adult02-tilthead',   face: 'face_smile_02'      },
  // cool series
  { pose: 'w-cool02-pose',        face: 'face_ncsmile_01'    },
  { pose: 'w-cool06-pose',        face: 'face_smile_04'      },
  { pose: 'w-cool09-pose',        face: 'face_ncsmile_03'    },
  { pose: 'w-cool10-pose',        face: 'face_smile_02'      },
  { pose: 'w-cool13-pose',        face: 'face_ncsmile_03'    },
  { pose: 'w-cool16-pose',        face: 'face_ncsmile_01'    },
  // normal series
  { pose: 'w-normal01-pose',      face: 'face_ncsmile_01'    },
  { pose: 'w-normal03-pose',      face: 'face_smile_05'      },
  { pose: 'w-normal04-pose',      face: 'face_ncsmile_09'    },
  { pose: 'w-normal07-pose',      face: 'face_ncnormal_01'   },
  { pose: 'w-normal08-pose',      face: 'face_ncsmile_01'    },
  { pose: 'w-normal15-pose',      face: 'face_ncsmile_09'    },
  { pose: 'w-normal16-pose',      face: 'face_ncsmile_03'    },
  { pose: 'w-normal17-pose',      face: 'face_smile_06'      },
  // animal / pure12
  { pose: 'w-animal12-pose',      face: 'face_smile_07'      },
  { pose: 'w-pure12-pose',        face: 'face_ncsmile_09'    },
  // shy/soft idle
  { pose: 'w-cute11-shy02',       face: 'face_shy_01'        },
  { pose: 'w-cute01-shy',         face: 'face_smile_15'      },
  { pose: 'w-normal15-shy',       face: 'face_ncsmile_09'    },
]

// ── Emotion → motion arrays — all 250+ model motions covered ─────────────────
// pose = body/hand motion  |  face = facial expression
// Random pick per trigger = natural variety, same emotion never looks identical.
const EMOTION_MAP = {

  // ── POSITIVE ──────────────────────────────────────────────────────────────

  happy: [
    { pose: 'w-cute11-glad',         face: 'face_delicious_01'  },
    { pose: 'w-cute11-glad02',       face: 'face_sparkling_02'  },
    { pose: 'w-cute11-nbglad02',     face: 'face_sparkling_01'  },
    { pose: 'w-cute01-glad',         face: 'face_ncsmile_18'    },
    { pose: 'w-cute01-glad03',       face: 'face_sparkling_03'  },
    { pose: 'w-cute02-glad',         face: 'face_smile_07'      },
    { pose: 'w-adult02-glad',        face: 'face_ncsmile_19'    },
    { pose: 'w-adult11-glad02',      face: 'face_ncsmile_17'    },
    { pose: 'w-adult12-glad',        face: 'face_smile_09'      },
    { pose: 'w-happy14-glad',        face: 'face_sparkling_03'  },
    { pose: 'w-normal01-glad',       face: 'face_smile_12'      },
    { pose: 'w-cute11-bright',       face: 'face_sparkling_02'  },
    { pose: 'w-happy02-pose',        face: 'face_ncsmile_18'    },
    { pose: 'w-happy11-pose',        face: 'face_sparkling_02'  },
    { pose: 'w-happy14-pose',        face: 'face_smile_07'      },
    { pose: 'w-happy16-nod',         face: 'face_ncsmile_18'    },
  ],
  delighted: [
    { pose: 'w-cute11-delicious',    face: 'face_delicious_01'  },
    { pose: 'w-cute11-deliciousB',   face: 'face_delicious_01'  },
    { pose: 'w-cute01-delicious02',  face: 'face_delicious_01'  },
    { pose: 'w-adult02-delicious',   face: 'face_delicious_01'  },
    { pose: 'w-adult11-delicious02', face: 'face_delicious_01'  },
    { pose: 'w-adult11-delicious03', face: 'face_sparkling_02'  },
  ],
  excited: [
    { pose: 'w-cute11-guts',         face: 'face_sparkling_02'  },
    { pose: 'w-happy11-guts',        face: 'face_sparkling_03'  },
    { pose: 'w-cute02-guts',         face: 'face_e_01'          },
    { pose: 'w-cool02-guts',         face: 'face_sparkling_01'  },
    { pose: 'w-normal01-guts',       face: 'face_sparkling_02'  },
    { pose: 'w-happy02-purpose',     face: 'face_sparkling_02'  },
    { pose: 'w-normal01-purpose',    face: 'face_e_01'          },
    { pose: 'w-special11-wandahoi',  face: 'face_sparkling_02'  },
    { pose: 'w-cute11-bright',       face: 'face_sparkling_03'  },
  ],
  loving: [
    { pose: 'w-cute11-forward',      face: 'face_ncsmile_18'    },
    { pose: 'w-cute11-nbforward',    face: 'face_ncsmile_17'    },
    { pose: 'w-cute01-forward03',    face: 'face_ncsmile_19'    },
    { pose: 'w-cute02-forward',      face: 'face_ncsmile_18'    },
    { pose: 'w-cute13-forward',      face: 'face_smile_16'      },
    { pose: 'w-happy09-forward',     face: 'face_ncsmile_09'    },
    { pose: 'w-happy14-forward',     face: 'face_sparkling_01'  },
    { pose: 'w-normal03-forward',    face: 'face_ncsmile_08'    },
    { pose: 'w-normal04-forward',    face: 'face_ncsmile_10'    },
    { pose: 'w-normal15-greeting',   face: 'face_ncsmile_18'    },
    { pose: 'w-cool10-forward',      face: 'face_ncsmile_17'    },
    { pose: 'w-cool13-forward',      face: 'face_ncsmile_09'    },
    { pose: 'w-noromal16-forward',   face: 'face_ncsmile_18'    },
    { pose: 'w-normal16-forward',    face: 'face_ncsmile_17'    },
    { pose: 'w-normal17-forward',    face: 'face_ncsmile_09'    },
  ],
  love: [
    { pose: 'w-cute11-forward',      face: 'face_sparkling_02'  },
    { pose: 'w-cute11-glad',         face: 'face_sparkling_03'  },
    { pose: 'w-cute01-forward03',    face: 'face_sparkling_02'  },
    { pose: 'w-cute11-bright',       face: 'face_sparkling_01'  },
    { pose: 'w-happy01-shakehand',   face: 'face_sparkling_02'  },
    { pose: 'w-cute11-nbforward',    face: 'face_sparkling_02'  },
    { pose: 'w-happy14-forward',     face: 'face_sparkling_03'  },
    { pose: 'w-cute11-wink',         face: 'face_sparkling_02'  },
  ],
  caring: [
    { pose: 'w-happy02-pose',        face: 'face_ncsmile_09'    },
    { pose: 'w-cute11-glad',         face: 'face_ncsmile_08'    },
    { pose: 'w-cute11-forward',      face: 'face_ncsmile_10'    },
    { pose: 'w-adult12-glad',        face: 'face_smile_12'      },
    { pose: 'w-adult11-glad02',      face: 'face_ncsmile_07'    },
    { pose: 'w-happy14-forward',     face: 'face_ncsmile_09'    },
    { pose: 'w-normal03-forward',    face: 'face_ncsmile_08'    },
    { pose: 'w-adult02-glad',        face: 'face_ncsmile_10'    },
  ],
  playful: [
    { pose: 'w-cute11-piece',        face: 'face_wink_01'       },
    { pose: 'w-happy11-piece',       face: 'face_e_01'          },
    { pose: 'w-adult11-piece',       face: 'face_wink_01'       },
    { pose: 'w-normal01-piece',      face: 'face_smile_11'      },
    { pose: 'w-normal02-piece',      face: 'face_wink_01'       },
    { pose: 'w-cute01-wink04',       face: 'face_wink_01'       },
    { pose: 'w-cute02-wink',         face: 'face_wink_01'       },
    { pose: 'w-cute11-wink',         face: 'face_wink_01'       },
    { pose: 'w-cute11-delicious',    face: 'face_delicious_01'  },
    { pose: 'w-special12-ninnin',    face: 'face_wink_01'       },
    { pose: 'w-special12-ninninB',   face: 'face_e_01'          },
    { pose: 'w-special11-cheek',     face: 'face_spicy_01'      },
    { pose: 'w-special11-cheekB',    face: 'face_e_01'          },
    { pose: 'w-special11-cheekC',    face: 'face_wink_01'       },
  ],
  greeting: [
    { pose: 'w-normal15-greeting',   face: 'face_sparkling_02'  },
    { pose: 'w-happy01-shakehand',   face: 'face_ncsmile_18'    },
    { pose: 'w-happy02-shakehand',   face: 'face_sparkling_01'  },
    { pose: 'w-happy11-shakehand',   face: 'face_sparkling_02'  },
    { pose: 'w-adult15-handshake',   face: 'face_ncsmile_07'    },
    { pose: 'w-adult01-shakehand',   face: 'face_ncsmile_18'    },
    { pose: 'w-cool01-shakehand',    face: 'face_sparkling_01'  },
    { pose: 'w-cute11-bright',       face: 'face_sparkling_02'  },
  ],
  smug: [
    { pose: 'w-cute14-smug',         face: 'face_smug_01'       },
    { pose: 'w-cool10-forward',      face: 'face_smug_01'       },
    { pose: 'w-cool02-thumb',        face: 'face_smug_01'       },
    { pose: 'w-cool13-forward',      face: 'face_smug_01'       },
    { pose: 'w-cool01-thumb',        face: 'face_smug_01'       },
  ],
  protective: [
    { pose: 'w-cool02-thumb',        face: 'face_angry_01'      },
    { pose: 'w-cool01-thumb',        face: 'face_serious_01'    },
    { pose: 'w-cool02-guts',         face: 'face_angry_02'      },
    { pose: 'w-normal01-guts',       face: 'face_serious_01'    },
    { pose: 'w-cool13-forward',      face: 'face_angry_03'      },
    { pose: 'w-happy14-angry',       face: 'face_serious_01'    },
  ],
  relief: [
    { pose: 'w-adult12-relief',      face: 'face_smile_08'      },
    { pose: 'w-normal03-relief',     face: 'face_ncsmile_09'    },
    { pose: 'w-normal04-relief',     face: 'face_smile_10'      },
    { pose: 'w-happy09-sigh',        face: 'face_smile_09'      },
    { pose: 'w-adult12-nod',         face: 'face_ncsmile_07'    },
  ],

  // ── NEUTRAL / COGNITIVE ─────────────────────────────────────────────────────

  neutral: [
    { pose: 'w-cool10-pose',         face: 'face_ncnormal_01'   },
    { pose: 'w-adult01-pose',        face: 'face_ncnormal_01'   },
    { pose: 'w-cute11-pose',         face: 'face_ncsmile_18'    },
    { pose: 'w-normal15-pose',       face: 'face_ncsmile_01'    },
    { pose: 'w-adult02-pose',        face: 'face_normal_01'     },
    { pose: 'w-cool06-pose',         face: 'face_ncnormal_01'   },
    { pose: 'w-normal07-pose',       face: 'face_ncnormal_01'   },
    { pose: 'w-normal17-pose',       face: 'face_ncsmile_03'    },
    { pose: 'w-normal03-pose',       face: 'face_ncsmile_01'    },
    { pose: 'w-noromal16-pose',      face: 'face_ncsmile_03'    },
  ],
  thinking: [
    { pose: 'w-adult01-think',       face: 'face_wonder_train_01' },
    { pose: 'w-adult05-think',       face: 'face_think_01'      },
    { pose: 'w-adult01-tilthead',    face: 'face_wonder_train_01' },
    { pose: 'w-adult02-tilthead',    face: 'face_think_01'      },
    { pose: 'w-adult05-tilthead',    face: 'face_wonder_train_01' },
    { pose: 'w-adult11-tilthead',    face: 'face_think_01'      },
    { pose: 'w-adult12-tilthead',    face: 'face_wonder_train_01' },
    { pose: 'w-cute01-tilthead',     face: 'face_wonder_train_01' },
    { pose: 'w-cute01-tilthead02',   face: 'face_think_01'      },
    { pose: 'w-cute01-tilthead04',   face: 'face_wonder_train_01' },
    { pose: 'w-cute11-tilthead',     face: 'face_think_01'      },
    { pose: 'w-cute11-tilthead02',   face: 'face_wonder_train_01' },
    { pose: 'w-cute11-nbtilthead',   face: 'face_think_01'      },
    { pose: 'w-cute02-tilthead',     face: 'face_wonder_train_01' },
    { pose: 'w-cute12-tilthead',     face: 'face_think_01'      },
    { pose: 'w-cute13-tilthead',     face: 'face_wonder_train_01' },
    { pose: 'w-cute14-tilthead',     face: 'face_think_01'      },
    { pose: 'w-cool02-tilthead',     face: 'face_wonder_train_01' },
    { pose: 'w-cool06-tilthead',     face: 'face_think_01'      },
    { pose: 'w-cool09-tilthead',     face: 'face_wonder_train_01' },
    { pose: 'w-cool10-tilthead',     face: 'face_think_01'      },
    { pose: 'w-cool13-tilthead',     face: 'face_wonder_train_01' },
    { pose: 'w-happy09-tilthead',    face: 'face_wonder_train_01' },
    { pose: 'w-happy14-tilthead',    face: 'face_think_01'      },
    { pose: 'w-normal01-tilthead',   face: 'face_wonder_train_01' },
    { pose: 'w-normal03-tilthead',   face: 'face_think_01'      },
    { pose: 'w-normal04-tilthead',   face: 'face_wonder_train_01' },
    { pose: 'w-normal07-tilthead',   face: 'face_think_01'      },
    { pose: 'w-normal15-tilthead',   face: 'face_wonder_train_01' },
    { pose: 'w-normal17-tilthead',   face: 'face_think_01'      },
    { pose: 'w-pure12-tilthead',     face: 'face_wonder_train_01' },
    { pose: 'w-animal02-tilthead',   face: 'face_think_01'      },
  ],
  curious: [
    { pose: 'w-normal15-lookaround', face: 'face_wonder_train_01' },
    { pose: 'w-normal03-lookleft',   face: 'face_ncsmile_02'    },
    { pose: 'w-normal03-lookright',  face: 'face_ncsmile_02'    },
    { pose: 'w-normal15-lookleft',   face: 'face_wonder_train_01' },
    { pose: 'w-normal15-lookright',  face: 'face_wonder_train_01' },
    { pose: 'w-animal12-lookright02', face: 'face_e_01'         },
    { pose: 'w-special01-lookdown',  face: 'face_wonder_train_01' },
    { pose: 'w-special15-senseforward', face: 'face_think_01'  },
    { pose: 'w-animal0212-tiltheadnod', face: 'face_wonder_train_01' },
    { pose: 'w-animal1202-nodtilthead', face: 'face_think_01'  },
  ],
  serious: [
    { pose: 'w-adult01-pose',        face: 'face_serious_01'    },
    { pose: 'w-adult02-pose',        face: 'face_ncnormal_01'   },
    { pose: 'w-adult05-pose',        face: 'face_serious_01'    },
    { pose: 'w-cool09-pose',         face: 'face_ncnormal_01'   },
    { pose: 'w-cool13-pose',         face: 'face_serious_01'    },
    { pose: 'w-cool16-pose',         face: 'face_serious_01'    },
    { pose: 'w-adult01-think',       face: 'face_serious_01'    },
    { pose: 'w-adult05-think',       face: 'face_serious_01'    },
    { pose: 'w-cool06-nod',          face: 'face_serious_01'    },
    { pose: 'w-cool10-nod',          face: 'face_serious_01'    },
    { pose: 'w-cool13-nod',          face: 'face_serious_01'    },
  ],
  agreeing: [
    { pose: 'w-adult01-nod',         face: 'face_ncsmile_01'    },
    { pose: 'w-adult02-nod',         face: 'face_ncsmile_03'    },
    { pose: 'w-adult05-nod',         face: 'face_ncsmile_07'    },
    { pose: 'w-adult11-nod',         face: 'face_ncsmile_09'    },
    { pose: 'w-adult12-nod',         face: 'face_ncsmile_07'    },
    { pose: 'w-animal01-nod',        face: 'face_ncsmile_03'    },
    { pose: 'w-animal12-nod',        face: 'face_ncsmile_01'    },
    { pose: 'w-cool06-nod',          face: 'face_ncsmile_01'    },
    { pose: 'w-cool10-nod',          face: 'face_ncsmile_03'    },
    { pose: 'w-cool13-nod',          face: 'face_ncsmile_01'    },
    { pose: 'w-cute02-nod',          face: 'face_ncsmile_09'    },
    { pose: 'w-cute02-nodB',         face: 'face_ncsmile_07'    },
    { pose: 'w-cute12-nod',          face: 'face_ncsmile_18'    },
    { pose: 'w-cute12-nbnod',        face: 'face_ncsmile_18'    },
    { pose: 'w-cute13-nod',          face: 'face_ncsmile_09'    },
    { pose: 'w-cute14-nod',          face: 'face_ncsmile_07'    },
    { pose: 'w-happy02-nod',         face: 'face_ncsmile_18'    },
    { pose: 'w-happy09-nod',         face: 'face_ncsmile_07'    },
    { pose: 'w-happy14-nod',         face: 'face_ncsmile_18'    },
    { pose: 'w-happy16-nod',         face: 'face_ncsmile_09'    },
    { pose: 'w-normal01-nod',        face: 'face_ncsmile_01'    },
    { pose: 'w-normal03-nod',        face: 'face_ncsmile_03'    },
    { pose: 'w-normal04-nod',        face: 'face_ncsmile_09'    },
    { pose: 'w-normal07-nod',        face: 'face_ncsmile_01'    },
    { pose: 'w-normal08-nod',        face: 'face_ncsmile_03'    },
    { pose: 'w-normal15-nod',        face: 'face_ncsmile_09'    },
    { pose: 'w-normal16-nod',        face: 'face_ncsmile_01'    },
    { pose: 'w-noromal16-nod',       face: 'face_ncsmile_03'    },
    { pose: 'w-normal17-nod',        face: 'face_ncsmile_07'    },
    { pose: 'w-pure12-nod',          face: 'face_ncsmile_09'    },
  ],

  // ── NEGATIVE ─────────────────────────────────────────────────────────────────

  sad: [
    { pose: 'w-cool16-sad',          face: 'face_sad_02'        },
    { pose: 'w-happy16-sad',         face: 'face_sad_01'        },
    { pose: 'w-normal07-sad',        face: 'face_ncsad_01'      },
    { pose: 'w-normal08-sad',        face: 'face_sad_03'        },
    { pose: 'w-cool13-sigh',         face: 'face_sad_04'        },
    { pose: 'w-happy09-sigh',        face: 'face_sad_05'        },
    { pose: 'w-normal07-sigh',       face: 'face_ncsad_01'      },
    { pose: 'w-normal15-shy',        face: 'face_sad_01'        },
    { pose: 'w-pure12-shy',          face: 'face_sad_02'        },
    { pose: 'w-adult02-trouble',     face: 'face_sad_03'        },
    { pose: 'w-cute12happy16-shakeheadsad', face: 'face_sad_02' },
    { pose: 'w-cute11-shy02',        face: 'face_sad_04'        },
  ],
  cry: [
    { pose: 'w-normal15-shy',        face: 'face_cry_03'        },
    { pose: 'w-cute11-shy02',        face: 'face_cry_01'        },
    { pose: 'w-pure12-shy',          face: 'face_cry_05'        },
    { pose: 'w-cute12-pose',         face: 'face_cry_07'        },
    { pose: 'w-cool13-sigh',         face: 'face_cry_04'        },
    { pose: 'w-happy16-sad',         face: 'face_cry_09'        },
    { pose: 'w-normal07-sigh',       face: 'face_cry_06'        },
    { pose: 'w-adult05-trouble',     face: 'face_cry_08'        },
    { pose: 'w-cute12happy16-shakeheadsad', face: 'face_cry_02' },
    { pose: 'w-cute01-shy',          face: 'face_cry_03'        },
  ],
  angry: [
    { pose: 'w-cool10-angry',        face: 'face_angry_02'      },
    { pose: 'w-cute13-angry',        face: 'face_angry_04'      },
    { pose: 'w-happy09-angry',       face: 'face_ncangry_01'    },
    { pose: 'w-happy14-angry',       face: 'face_angry_05'      },
    { pose: 'w-normal16-angry',      face: 'face_angry_06'      },
    { pose: 'w-noromal16-angry',     face: 'face_angry_03'      },
    { pose: 'w-cool02-pose',         face: 'face_ncangry_06'    },
    { pose: 'w-cool13-pose',         face: 'face_angry_01'      },
    { pose: 'w-cute13-nod',          face: 'face_ncangry_04'    },
  ],
  surprised: [
    { pose: 'w-cute01-shakehead04',  face: 'face_ncsurprise_03' },
    { pose: 'w-cute14-shakehead',    face: 'face_surprise_01'   },
    { pose: 'w-adult12-shakehead',   face: 'face_ncsurprise_04' },
    { pose: 'w-cute12-shakehead',    face: 'face_surprise_03'   },
    { pose: 'w-normal01-shakehead',  face: 'face_surprise_02'   },
    { pose: 'w-happy14-shakehead',   face: 'face_shock_01'      },
    { pose: 'w-happy14-shakeheadC',  face: 'face_ncsurprise_03' },
    { pose: 'w-cool13-shakehead',    face: 'face_ncshock_01'    },
    { pose: 'w-happy16-shakehead',   face: 'face_surprise_04'   },
    { pose: 'w-pure12-shakehead',    face: 'face_ncsurprise_03' },
    { pose: 'w-normal03-shakehead',  face: 'face_surprise_01'   },
    { pose: 'w-normal03-shakeheadB', face: 'face_ncshock_01'    },
    { pose: 'w-normal04-shakehead',  face: 'face_surprise_03'   },
    { pose: 'w-normal15-shakehead',  face: 'face_surprise_02'   },
    { pose: 'w-normal17-shakehead',  face: 'face_shock_01'      },
    { pose: 'w-noromal16-shakehead', face: 'face_ncsurprise_04' },
    { pose: 'w-normal16-shakehead',  face: 'face_surprise_04'   },
    { pose: 'w-normal02-shakehead',  face: 'face_ncshock_01'    },
    { pose: 'w-cool10-shakehead',    face: 'face_surprise_02'   },
    { pose: 'w-special15-senseshakehead', face: 'face_ncsurprise_04' },
  ],
  scared: [
    { pose: 'w-special11-scare',     face: 'face_scared_02'     },
    { pose: 'w-cute01-shakehead04',  face: 'face_scared_04'     },
    { pose: 'w-cute12-shakehead',    face: 'face_scared_06'     },
    { pose: 'w-normal15-shakehead',  face: 'face_scared_08'     },
    { pose: 'w-cute11-shy02',        face: 'face_scared_01'     },
    { pose: 'w-cool10-shakehead',    face: 'face_scared_03'     },
    { pose: 'w-pure12-shakehead',    face: 'face_scared_05'     },
    { pose: 'w-adult12-shakehead',   face: 'face_scared_07'     },
    { pose: 'w-normal03-shakehead',  face: 'face_scared_03'     },
    { pose: 'w-cute01-shy',          face: 'face_scared_01'     },
  ],
  shy: [
    { pose: 'w-cute11-shy02',        face: 'face_shy_01'        },
    { pose: 'w-cute11-shy02B',       face: 'face_shy_01'        },
    { pose: 'w-cute11-nbshy02',      face: 'face_shy_01'        },
    { pose: 'w-cute01-shy',          face: 'face_shy_01'        },
    { pose: 'w-normal15-shy',        face: 'face_shy_01'        },
    { pose: 'w-pure12-shy',          face: 'face_shy_01'        },
    { pose: 'w-animal12-shy02',      face: 'face_shy_01'        },
    { pose: 'w-adult01-blushed',     face: 'face_shy_01'        },
    { pose: 'w-adult02-blushed',     face: 'face_smile_15'      },
    { pose: 'w-adult05-blushed',     face: 'face_shy_01'        },
    { pose: 'w-adult11-blushed03',   face: 'face_shy_01'        },
    { pose: 'w-cool06-blushed',      face: 'face_shy_01'        },
    { pose: 'w-normal03-blushed',    face: 'face_shy_01'        },
    { pose: 'w-normal04-blushed',    face: 'face_shy_01'        },
  ],
  disgusted: [
    { pose: 'w-cool10-pose',         face: 'face_disgust_01'    },
    { pose: 'w-cool02-pose',         face: 'face_disgust_01'    },
    { pose: 'w-cool13-sigh',         face: 'face_disgust_01'    },
    { pose: 'w-happy14-lookaway',    face: 'face_disgust_01'    },
    { pose: 'w-cool10-forward',      face: 'face_disgust_01'    },
    { pose: 'w-cool16-pose',         face: 'face_disgust_01'    },
  ],
  jealous: [
    { pose: 'w-cute14-smug',         face: 'face_smug_01'       },
    { pose: 'w-happy14-lookaway',    face: 'face_disgust_01'    },
    { pose: 'w-cool10-trouble',      face: 'face_nctrouble_02'  },
    { pose: 'w-cute11-shy02',        face: 'face_disgust_01'    },
    { pose: 'w-cool10-forward',      face: 'face_smug_01'       },
    { pose: 'w-cool13-forward',      face: 'face_ncangry_04'    },
    { pose: 'w-normal16-shakehead',  face: 'face_disgust_01'    },
  ],
  worried: [
    { pose: 'w-adult02-trouble',     face: 'face_worry_01'      },
    { pose: 'w-cool10-trouble',      face: 'face_trouble_02'    },
    { pose: 'w-normal03-trouble',    face: 'face_ncworry_01'    },
    { pose: 'w-normal04-trouble',    face: 'face_trouble_04'    },
    { pose: 'w-adult05-trouble',     face: 'face_trouble_05'    },
    { pose: 'w-cool10-tilthead',     face: 'face_trouble_01'    },
    { pose: 'w-adult02-tilthead',    face: 'face_worry_01'      },
    { pose: 'w-normal07-tilthead',   face: 'face_trouble_03'    },
  ],
  nervous: [
    { pose: 'w-cute11-fidget02',     face: 'face_trouble_01'    },
    { pose: 'w-animal12-fidget02',   face: 'face_ncworry_01'    },
    { pose: 'w-animal12-fidget02B',  face: 'face_worry_01'      },
    { pose: 'w-pure12-fidget',       face: 'face_trouble_02'    },
    { pose: 'w-normal17-fidget',     face: 'face_nctrouble_02'  },
    { pose: 'w-cute11-nbshy02',      face: 'face_trouble_01'    },
    { pose: 'w-cute01-nbtilthead04', face: 'face_worry_01'      },
  ],
  sleepy: [
    { pose: 'w-cute01-sleep05',      face: 'face_sleepy_01'     },
    { pose: 'w-cute01-sleep05B',     face: 'face_sleepy_01'     },
    { pose: 'w-adult15-sleep',       face: 'face_sleepy_01'     },
    { pose: 'w-adult15-sleepB',      face: 'face_sleepy_01'     },
    { pose: 'w-normal07-sigh',       face: 'face_yawn_01'       },
    { pose: 'w-happy09-sigh',        face: 'face_sleepy_01'     },
    { pose: 'w-cool13-sigh',         face: 'face_sleepy_01'     },
    { pose: 'w-adult15-sleep',       face: 'face_yawn_01'       },
  ],

  // ── SPECIAL ──────────────────────────────────────────────────────────────────

  musical: [
    { pose: 'w-special11-musicalL',  face: 'face_sparkling_02'  },
    { pose: 'w-special15-yurayura',  face: 'face_smile_07'      },
    { pose: 'w-cute11-piece',        face: 'face_sparkling_01'  },
    { pose: 'w-cute11-delicious',    face: 'face_sparkling_02'  },
  ],
  dizzy: [
    { pose: 'w-special02-guruguru',  face: 'face_guruguru_01'   },
    { pose: 'w-special02-guruguru',  face: 'face_guruguru_02'   },
  ],
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
    let lastEmotionTime = 0
    let lastEmotionPose = null
    let lipAmpSource  = null   // () => number  — set by VoiceChat, sampled each ticker tick
    let smoothedAmp   = 0

    // priority 3 = FORCE in pixi-live2d-display — interrupts any running motion
    const PRIO_IDLE  = 1
    const PRIO_FORCE = 3

    // ── Play a matched pose + expression set ─────────────────────────────────
    function playSet(model, set, priority = PRIO_IDLE) {
      lastPose = set.pose
      try { model.motion(set.pose, 0, priority) } catch (_) {}
      setTimeout(() => {
        if (!alive) return
        try { model.motion(set.face, 0, priority) } catch (_) {}
      }, 300)
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

          // Lip sync ticker — runs AFTER Live2D motion update so our value wins
          app.ticker.add(() => {
            if (!lipAmpSource || !alive) return
            const raw = lipAmpSource()
            smoothedAmp += (raw - smoothedAmp) * 0.6  // fast follow
            try {
              model.internalModel.coreModel.setParameterValueById('ParamMouthOpenY', smoothedAmp, 1)
            } catch (_) {}
          })

          // ── Expose voice-chat control API via plain prop ref ──────────────
          if (controlRef) {
            controlRef.current = {
              triggerEmotion(name) {
                if (!alive) return
                const options = EMOTION_MAP[name] ?? EMOTION_MAP.neutral
                // Never repeat exact same pose twice in a row
                const pool = Array.isArray(options)
                  ? options.filter(o => o.pose !== lastEmotionPose)
                  : [options]
                const set = pool.length ? pool[Math.floor(Math.random() * pool.length)] : options[0]
                lastEmotionPose = set.pose
                // FORCE priority — overrides any running motion immediately
                playSet(model, set, PRIO_FORCE)
              },
              // Register an amplitude getter — called every PIXI ticker frame (after motion update)
              setLipSync(getFn) { lipAmpSource = getFn; smoothedAmp = 0 },
              clearLipSync()   { lipAmpSource = null;  smoothedAmp = 0 },
              pauseAutoReact() {
                externalPaused = true
                if (cycleTimer) { clearTimeout(cycleTimer); cycleTimer = null }
              },
              resumeAutoReact() {
                externalPaused = false
                lastEmotionTime = 0
                lastEmotionPose = null
                setTimeout(() => autoCycle(model), 1500)
              },
            }
          }

          autoCycle(model)

          pointerMoveHandler = (e) => {
            // During voice session: look straight ahead, ignore cursor
            if (externalPaused) return
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
