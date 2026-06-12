import { useEffect, useRef } from 'react'

/**
 * LaserFlow — WebGL fragment-shader background effect.
 * Props match the React Bits @react-bits/LaserFlow-JS-CSS API.
 */
export default function LaserFlow({
  color            = '#bbb0ff',
  wispDensity      = 1,
  flowSpeed        = 0.35,
  verticalSizing   = 2,
  horizontalSizing = 0.5,
  fogIntensity     = 0.45,
  fogScale         = 0.3,
  wispSpeed        = 15,
  wispIntensity    = 5,
  flowStrength     = 0.25,
  decay            = 1.1,
  horizontalBeamOffset = 0,
  verticalBeamOffset   = -0.5,
  style            = {},
}) {
  const canvasRef = useRef(null)

  // Convert hex colour → [r, g, b] in 0–1
  const hexToRgb = (hex) => {
    const h = hex.replace('#', '')
    return [
      parseInt(h.slice(0, 2), 16) / 255,
      parseInt(h.slice(2, 4), 16) / 255,
      parseInt(h.slice(4, 6), 16) / 255,
    ]
  }

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl')
    if (!gl) return

    // ── Vertex shader ──────────────────────────────────────────────────────────
    const vert = `
      attribute vec2 a_pos;
      void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }
    `

    // ── Fragment shader ────────────────────────────────────────────────────────
    const frag = `
      precision highp float;

      uniform vec2  u_res;
      uniform float u_time;
      uniform vec3  u_color;
      uniform float u_wispDensity;
      uniform float u_flowSpeed;
      uniform float u_vSize;
      uniform float u_hSize;
      uniform float u_fogIntensity;
      uniform float u_fogScale;
      uniform float u_wispSpeed;
      uniform float u_wispIntensity;
      uniform float u_flowStrength;
      uniform float u_decay;
      uniform float u_hOffset;
      uniform float u_vOffset;

      // ── Noise helpers ──────────────────────────────────────────────────────
      vec3 hash3(vec2 p) {
        vec3 q = vec3(dot(p, vec2(127.1, 311.7)),
                      dot(p, vec2(269.5, 183.3)),
                      dot(p, vec2(419.2, 371.9)));
        return fract(sin(q) * 43758.5453);
      }

      float noise(vec2 p) {
        vec2 i = floor(p);
        vec2 f = fract(p);
        vec2 u = f * f * (3.0 - 2.0 * f);
        float a = dot(hash3(i + vec2(0,0)), vec3(1,0,0));
        float b = dot(hash3(i + vec2(1,0)), vec3(1,0,0));
        float c = dot(hash3(i + vec2(0,1)), vec3(1,0,0));
        float d = dot(hash3(i + vec2(1,1)), vec3(1,0,0));
        return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
      }

      float fbm(vec2 p) {
        float v  = 0.0;
        float a  = 0.5;
        vec2  sh = vec2(1.0);
        for (int i = 0; i < 5; i++) {
          v += a * noise(p);
          p  = p * 2.0 + sh;
          a *= 0.5;
        }
        return v;
      }

      // ── Laser beam ────────────────────────────────────────────────────────
      float beam(vec2 uv, float offset, float t) {
        float y   = uv.y + u_vOffset + offset;
        float warp = fbm(vec2(uv.x * u_hSize + t * u_flowSpeed, t * 0.2)) * u_flowStrength;
        float dist = abs(y + warp);
        float w    = 0.015 * u_vSize;
        return smoothstep(w, 0.0, dist);
      }

      // ── Wisp particle ─────────────────────────────────────────────────────
      float wisp(vec2 uv, vec2 center, float size) {
        float d = length(uv - center);
        return smoothstep(size, 0.0, d);
      }

      void main() {
        vec2 uv = (gl_FragCoord.xy / u_res) * 2.0 - 1.0;
        uv.x   *= u_res.x / u_res.y;   // aspect-correct
        uv.x   += u_hOffset;

        float t = u_time;

        // Flowing beams
        float glow = 0.0;
        float beamCount = 4.0 + u_wispDensity * 3.0;
        for (float i = 0.0; i < 7.0; i++) {
          if (i >= beamCount) break;
          float off   = (i / beamCount) * 0.6 - 0.3;
          float speed = 1.0 + i * 0.15;
          glow += beam(uv, off, t * speed) * (1.0 - i / beamCount * 0.4);
        }

        // Wisp particles
        float wispGlow = 0.0;
        float wCount = 6.0 * u_wispDensity;
        for (float i = 0.0; i < 18.0; i++) {
          if (i >= wCount) break;
          vec2  h    = hash3(vec2(i * 13.7, i * 7.3)).xy;
          float phase = h.x * 6.28;
          float speed = 0.3 + h.y * 0.4;
          vec2  center = vec2(
            sin(t * speed * u_wispSpeed * 0.05 + phase) * 0.8,
            u_vOffset + (h.y - 0.5) * u_vSize * 0.8
          );
          float sz = 0.05 + h.x * 0.08;
          wispGlow += wisp(uv, center, sz) * u_wispIntensity * 0.12;
        }

        // Fog layer
        float fog = fbm(uv * u_fogScale + vec2(t * 0.04, 0.0)) * u_fogIntensity;

        // Combined
        float total = clamp(glow + wispGlow * 0.5 + fog * 0.3, 0.0, 1.0);

        // Decay / vignette from top+bottom
        float vig = 1.0 - pow(abs(uv.y - u_vOffset) * u_decay, 2.0);
        vig = clamp(vig, 0.0, 1.0);

        vec3 col = u_color * total * vig;

        // Bloom: additive bright core
        float core = pow(clamp(glow, 0.0, 1.0), 2.5);
        col += u_color * core * 0.6;

        gl_FragColor = vec4(col, total * vig * 0.95);
      }
    `

    const compile = (type, src) => {
      const s = gl.createShader(type)
      gl.shaderSource(s, src)
      gl.compileShader(s)
      return s
    }

    const prog = gl.createProgram()
    gl.attachShader(prog, compile(gl.VERTEX_SHADER, vert))
    gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, frag))
    gl.linkProgram(prog)
    gl.useProgram(prog)

    // Full-screen quad
    const buf = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, buf)
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, 1,1]), gl.STATIC_DRAW)
    const aPos = gl.getAttribLocation(prog, 'a_pos')
    gl.enableVertexAttribArray(aPos)
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0)

    // Uniforms
    const U = (n) => gl.getUniformLocation(prog, n)
    const uRes  = U('u_res');  const uTime = U('u_time')
    const uCol  = U('u_color');const uWD   = U('u_wispDensity')
    const uFS   = U('u_flowSpeed'); const uVS = U('u_vSize')
    const uHS   = U('u_hSize');const uFI   = U('u_fogIntensity')
    const uFSc  = U('u_fogScale'); const uWSp = U('u_wispSpeed')
    const uWI   = U('u_wispIntensity'); const uFStr = U('u_flowStrength')
    const uDec  = U('u_decay'); const uHO = U('u_hOffset'); const uVO = U('u_vOffset')

    const rgb = hexToRgb(color)
    gl.uniform3f(uCol, rgb[0], rgb[1], rgb[2])
    gl.uniform1f(uWD,   wispDensity)
    gl.uniform1f(uFS,   flowSpeed)
    gl.uniform1f(uVS,   verticalSizing)
    gl.uniform1f(uHS,   horizontalSizing)
    gl.uniform1f(uFI,   fogIntensity)
    gl.uniform1f(uFSc,  fogScale)
    gl.uniform1f(uWSp,  wispSpeed)
    gl.uniform1f(uWI,   wispIntensity)
    gl.uniform1f(uFStr, flowStrength)
    gl.uniform1f(uDec,  decay)
    gl.uniform1f(uHO,   horizontalBeamOffset)
    gl.uniform1f(uVO,   verticalBeamOffset)

    gl.enable(gl.BLEND)
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE)   // additive blending for glow

    let raf
    const resize = () => {
      canvas.width  = canvas.offsetWidth
      canvas.height = canvas.offsetHeight
      gl.viewport(0, 0, canvas.width, canvas.height)
      gl.uniform2f(uRes, canvas.width, canvas.height)
    }

    const ro = new ResizeObserver(resize)
    ro.observe(canvas)
    resize()

    const startTime = performance.now()
    const draw = () => {
      gl.uniform1f(uTime, (performance.now() - startTime) / 1000)
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
      raf = requestAnimationFrame(draw)
    }
    draw()

    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      gl.deleteProgram(prog)
      gl.deleteBuffer(buf)
    }
  }, [color, wispDensity, flowSpeed, verticalSizing, horizontalSizing,
      fogIntensity, fogScale, wispSpeed, wispIntensity, flowStrength,
      decay, horizontalBeamOffset, verticalBeamOffset])

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        ...style,
      }}
    />
  )
}
