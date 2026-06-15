export class AudioCapture {
  constructor({ onChunk }) {
    this.onChunk   = onChunk
    this.stream    = null
    this.ctx       = null
    this.processor = null
    this.source    = null
    this.active    = false
  }

  async start() {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, sampleRate: 16000 }
    })

    // Request 16 kHz context to match Gemini's expected input
    this.ctx    = new AudioContext({ sampleRate: 16000 })
    this.source = this.ctx.createMediaStreamSource(this.stream)

    // 512 samples @ 16 kHz ≈ 32 ms chunks — matches vyra's CHUNK_SIZE=1024 at 32 kHz
    this.processor = this.ctx.createScriptProcessor(512, 1, 1)
    this.processor.onaudioprocess = (e) => {
      if (!this.active) return
      this.onChunk(_float32ToBase64PCM(e.inputBuffer.getChannelData(0)))
    }

    this.source.connect(this.processor)
    this.processor.connect(this.ctx.destination)
    this.active = true
  }

  stop() {
    this.active = false
    try { this.processor?.disconnect() }  catch (_) {}
    try { this.source?.disconnect() }     catch (_) {}
    this.stream?.getTracks().forEach(t => t.stop())
    this.ctx?.close()
    this.processor = this.source = this.stream = this.ctx = null
  }
}

function _float32ToBase64PCM(float32) {
  const int16  = new Int16Array(float32.length)
  for (let i = 0; i < float32.length; i++) {
    const s   = Math.max(-1, Math.min(1, float32[i]))
    int16[i]  = s < 0 ? s * 0x8000 : s * 0x7FFF
  }
  const uint8  = new Uint8Array(int16.buffer)
  let binary   = ''
  for (let i = 0; i < uint8.length; i++) binary += String.fromCharCode(uint8[i])
  return btoa(binary)
}
