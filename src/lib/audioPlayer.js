export class AudioPlayer {
  constructor({ onPlayStart, onPlayEnd } = {}) {
    this.onPlayStart   = onPlayStart
    this.onPlayEnd     = onPlayEnd
    this.ctx           = null
    this.analyser      = null
    this.nextStartTime = 0
    this._playing      = false
    this._endTimer     = null
  }

  _boot() {
    if (this.ctx) return
    this.ctx     = new AudioContext({ sampleRate: 24000 })
    this.analyser = this.ctx.createAnalyser()
    this.analyser.fftSize              = 512
    this.analyser.smoothingTimeConstant = 0.3
    this.analyser.connect(this.ctx.destination)
    this.nextStartTime = this.ctx.currentTime
  }

  addChunk(base64pcm) {
    this._boot()
    if (this.ctx.state === 'suspended') this.ctx.resume()

    // Decode base64 PCM → Float32
    const binary = atob(base64pcm)
    const bytes  = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
    const int16  = new Int16Array(bytes.buffer)
    const f32    = new Float32Array(int16.length)
    for (let i = 0; i < int16.length; i++) f32[i] = int16[i] / 32768

    const buf    = this.ctx.createBuffer(1, f32.length, 24000)
    buf.getChannelData(0).set(f32)

    const src    = this.ctx.createBufferSource()
    src.buffer   = buf
    src.connect(this.analyser)

    const start  = Math.max(this.ctx.currentTime, this.nextStartTime)
    src.start(start)
    this.nextStartTime = start + buf.duration

    if (!this._playing) {
      this._playing = true
      this.onPlayStart?.()
    }

    // Schedule onPlayEnd after the last queued chunk finishes (+50 ms buffer)
    if (this._endTimer) clearTimeout(this._endTimer)
    const msUntilEnd = (this.nextStartTime - this.ctx.currentTime) * 1000 + 50
    this._endTimer = setTimeout(() => {
      this._playing = false
      this.onPlayEnd?.()
    }, msUntilEnd)
  }

  // Returns 0–1 RMS amplitude of the current audio output (for lip sync)
  getAmplitude() {
    if (!this.analyser || !this._playing) return 0
    const data = new Uint8Array(this.analyser.frequencyBinCount)
    this.analyser.getByteTimeDomainData(data)
    let sum = 0
    for (let i = 0; i < data.length; i++) {
      const v = (data[i] - 128) / 128
      sum += v * v
    }
    // Scale up (raw RMS is small) and clamp to 1
    return Math.min(1, Math.sqrt(sum / data.length) * 5)
  }

  stop() {
    if (this._endTimer) clearTimeout(this._endTimer)
    this._playing = false
    try { this.ctx?.close() } catch (_) {}
    this.ctx = this.analyser = null
    this.nextStartTime = 0
  }

  get isPlaying() { return this._playing }
}
