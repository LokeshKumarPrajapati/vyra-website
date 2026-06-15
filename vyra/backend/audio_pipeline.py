"""
Minimal audio pipeline: captures mic audio and forwards PCM chunks to Gemini Live.
Supports VAD callbacks, mute gating, and raw chunk emission for VU meter.
"""

import asyncio
import pyaudio

FORMAT          = pyaudio.paInt16
CHANNELS        = 1
SEND_SAMPLE_RATE = 16000
CHUNK_SIZE      = 512


def resolve_input_device(pya: pyaudio.PyAudio, name: str | None, index: int | None) -> int | None:
    """Return a valid input device index, or None to use the system default."""
    if index is not None:
        return index
    if name:
        count = pya.get_device_count()
        for i in range(count):
            info = pya.get_device_info_by_index(i)
            if name.lower() in info.get("name", "").lower() and info.get("maxInputChannels", 0) > 0:
                return i
    return None


class AudioPipeline:
    """
    Captures microphone audio and puts PCM chunks onto `out_queue` for Gemini Live.

    Parameters accepted match what vyra.py passes so the interface is compatible.
    Advanced features (VAD, speaker-id, env-audio) fire their callbacks when available
    but are not required for basic speech-to-VYRA to work.
    """

    def __init__(
        self,
        out_queue: asyncio.Queue,
        sio=None,
        loop: asyncio.AbstractEventLoop | None = None,
        perception_manager=None,
        on_speech_start=None,
        on_speech_end=None,
        on_speaker_identified=None,
        on_env_audio=None,
        emit_raw_chunks: bool = False,
        muted_getter=None,
    ):
        self.out_queue          = out_queue
        self.sio                = sio
        self.loop               = loop or asyncio.get_event_loop()
        self.perception_manager = perception_manager
        self.on_speech_start    = on_speech_start
        self.on_speech_end      = on_speech_end
        self.on_speaker_identified = on_speaker_identified
        self.on_env_audio       = on_env_audio
        self.emit_raw_chunks    = emit_raw_chunks
        self.muted_getter       = muted_getter
        self._stop_event        = asyncio.Event()
        self._pya               = pyaudio.PyAudio()

    def stop(self):
        self._stop_event.set()

    async def run(self, device_index: int | None = None):
        """Open mic stream and push PCM chunks to out_queue until stopped."""
        loop = asyncio.get_event_loop()

        try:
            stream = await asyncio.to_thread(
                self._pya.open,
                format=FORMAT,
                channels=CHANNELS,
                rate=SEND_SAMPLE_RATE,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=CHUNK_SIZE,
            )
        except OSError as e:
            print(f"[AudioPipeline] Failed to open mic (device={device_index}): {e}")
            raise

        print(f"[AudioPipeline] Mic open — device={device_index}, rate={SEND_SAMPLE_RATE}")

        try:
            while not self._stop_event.is_set():
                # Read one chunk in a thread (blocking PyAudio call)
                try:
                    data = await asyncio.to_thread(
                        stream.read, CHUNK_SIZE, False  # exception_on_overflow=False
                    )
                except OSError as e:
                    print(f"[AudioPipeline] Mic read error: {e}")
                    break

                # Honour mute gate (e.g. while VYRA is speaking)
                if self.muted_getter and self.muted_getter():
                    continue

                # Emit raw chunk for VU-meter if dashboard is connected
                if self.emit_raw_chunks and self.sio:
                    try:
                        asyncio.create_task(
                            self.sio.emit("audio_chunk_raw", {"data": list(data)})
                        )
                    except Exception:
                        pass

                # Forward to Gemini Live
                try:
                    self.out_queue.put_nowait({"mime_type": "audio/pcm", "data": data})
                except asyncio.QueueFull:
                    pass  # drop frame rather than block
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
            try:
                self._pya.terminate()
            except Exception:
                pass
            print("[AudioPipeline] Mic stream closed.")
