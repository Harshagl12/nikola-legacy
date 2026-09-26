"""
Always-on Voice Engine for NIKOLA.
Handles wake word detection, VAD, STT, and TTS.
Separate from voice_service.py which handles on-demand API calls.
"""

import asyncio
import re
import threading
import time
from collections import deque
from typing import Optional
import tempfile
import wave

import httpx
import numpy as np
import pyttsx3

from backend.config import settings
from backend.logger import get_logger

logger = get_logger(__name__)

# Optional dependencies
try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False

try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False

try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

try:
    import webrtcvad
    WEBRTCVAD_AVAILABLE = True
except ImportError:
    WEBRTCVAD_AVAILABLE = False

# Audio parameters
SAMPLE_RATE = 16000
FRAME_DURATION_MS = 30
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)  # 480 samples


class VoiceEngine:
    """Always-on background voice engine with wake word, VAD, STT, TTS."""

    def __init__(self, backend_url: str):
        """Initialize voice engine.
        
        Args:
            backend_url: Backend API URL for ASK requests
        """
        # Always initialize state so status checks never crash.
        self.backend_url = backend_url
        self.wake_word = settings.WAKE_WORD.lower()
        self._enabled = False
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._state = "IDLE"  # IDLE, LISTENING
        self.whisper_model = None
        self.tts_engine = None
        self.vad = None
        self._audio_backend = None
        self._energy_threshold = 280.0
        self._wake_detect_frames = 18
        self._silence_frames_commit = 25

        if not WHISPER_AVAILABLE:
            logger.warning("Voice engine disabled - faster-whisper missing")
            return

        if not PYAUDIO_AVAILABLE and not SOUNDDEVICE_AVAILABLE:
            logger.warning("Voice engine disabled - no audio input backend (need pyaudio or sounddevice)")
            return

        if not WEBRTCVAD_AVAILABLE:
            logger.warning("webrtcvad not available - using RMS speech detection fallback")
        
        self._enabled = True
        self._audio_backend = "pyaudio" if PYAUDIO_AVAILABLE else "sounddevice"
        
        # Load models
        try:
            self.whisper_model = WhisperModel(
                settings.WHISPER_MODEL,
                device="cpu",
                compute_type="int8"
            )
        except Exception as e:
            logger.error("Failed to load Whisper model", error=str(e))
            self.whisper_model = None
            self._enabled = False
            return
        
        # Initialize VAD (optional)
        if WEBRTCVAD_AVAILABLE:
            self.vad = webrtcvad.Vad(2)  # Aggressiveness 2
        
        # Initialize TTS
        from backend.piper_tts import PiperTTSEngine
        self.piper_engine = PiperTTSEngine()
        
        logger.info("Voice engine initialized", wake_word=self.wake_word, backend=self._audio_backend)

    def _is_speech_frame(self, frame: bytes) -> bool:
        """Detect if frame contains speech using WebRTC VAD or RMS fallback."""
        if self.vad is not None:
            try:
                return self.vad.is_speech(frame, SAMPLE_RATE)
            except Exception:
                pass

        # Fallback when webrtcvad is unavailable: simple RMS threshold.
        audio = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        if audio.size == 0:
            return False
        rms = float(np.sqrt(np.mean(audio * audio)))
        return rms > self._energy_threshold

    def speak(self, text: str) -> None:
        """Speak text using TTS. Called via executor.
        
        Args:
            text: Text to speak
        """
        if not self._enabled:
            logger.debug("Voice engine not available for speech")
            return
        
        try:
            # Clean markdown
            cleaned = re.sub(r'[*_`]', '', text)
            cleaned = re.sub(r'https?://\S+', '', cleaned)
            
            # Truncate
            if len(cleaned) > 500:
                cleaned = cleaned[:500] + "..."
            
            logger.debug("Speaking text", length=len(cleaned))
            self.piper_engine.speak(cleaned)
        except Exception as e:
            logger.error("TTS failed", error=str(e))


    def _transcribe(self, pcm_frames: list[bytes]) -> str:
        """Transcribe PCM frames using faster-Whisper.
        
        Args:
            pcm_frames: List of raw PCM frames
            
        Returns:
            Transcribed text
        """
        if not self.whisper_model:
            return ""
        
        temp_path = None

        try:
            # Join frames and convert to audio
            audio_bytes = b"".join(pcm_frames)
            audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            
            # Write to temp file for faster-whisper
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                with wave.open(f.name, 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(SAMPLE_RATE)
                    wav.writeframes((audio * 32768).astype(np.int16).tobytes())
                temp_path = f.name
            
            # Transcribe
            segments, info = self.whisper_model.transcribe(
                temp_path,
                language="en"
            )
            
            text = " ".join(segment.text for segment in segments).strip().lower()
            logger.debug("Transcribed audio", text_length=len(text))
            return text
        except Exception as e:
            logger.error("Transcription failed", error=str(e))
            return ""
        finally:
            if temp_path:
                try:
                    import os
                    os.unlink(temp_path)
                except Exception:
                    pass

    def _listen_loop(self) -> None:
        """Main listening loop: wake word -> listening -> query."""
        audio = None
        stream = None

        try:
            def choose_sounddevice_input() -> Optional[int]:
                try:
                    devices = sd.query_devices()
                except Exception:
                    return None

                try:
                    default_input = sd.default.device[0]
                    if isinstance(default_input, int) and default_input >= 0:
                        if devices[default_input]["max_input_channels"] > 0:
                            return default_input
                except Exception:
                    pass

                for idx, dev in enumerate(devices):
                    try:
                        if dev.get("max_input_channels", 0) > 0:
                            return idx
                    except Exception:
                        continue

                return None

            logger.info("Voice listening loop started", backend=self._audio_backend)

            while self._running:
                try:
                    if self._audio_backend == "pyaudio":
                        audio = pyaudio.PyAudio()
                        stream = audio.open(
                            format=pyaudio.paInt16,
                            channels=1,
                            rate=SAMPLE_RATE,
                            input=True,
                            frames_per_buffer=FRAME_SIZE,
                            exception_on_overflow=False
                        )

                        def read_frame() -> bytes:
                            return stream.read(FRAME_SIZE, exception_on_overflow=False)

                    elif self._audio_backend == "sounddevice":
                        input_device = choose_sounddevice_input()
                        if input_device is None:
                            raise RuntimeError("No input microphone device found")

                        stream = sd.RawInputStream(
                            samplerate=SAMPLE_RATE,
                            blocksize=FRAME_SIZE,
                            channels=1,
                            dtype="int16",
                            device=input_device
                        )
                        stream.start()
                        logger.info("Using microphone device", device_index=input_device)

                        def read_frame() -> bytes:
                            data, overflowed = stream.read(FRAME_SIZE)
                            return bytes(data)
                    else:
                        logger.error("No audio backend selected")
                        return

                    ring_buffer = deque(maxlen=80)
                    speech_frames = 0
                    silent_frames = 0

                    while self._running:
                        try:
                            frame = read_frame()
                            ring_buffer.append(frame)

                            is_speech = self._is_speech_frame(frame)

                            if self._state == "IDLE":
                                if is_speech:
                                    speech_frames += 1
                                else:
                                    speech_frames = 0

                                if speech_frames >= self._wake_detect_frames:
                                    text = self._transcribe(list(ring_buffer))
                                    if self.wake_word in text:
                                        logger.info("Wake word detected")
                                        self._state = "LISTENING"
                                        if self._loop is not None:
                                            asyncio.run_coroutine_threadsafe(
                                                self._async_speak("Yes?"),
                                                self._loop
                                            )
                                        speech_frames = 0
                                        silent_frames = 0
                                        ring_buffer.clear()
                                    else:
                                        speech_frames = 0

                            elif self._state == "LISTENING":
                                if is_speech:
                                    silent_frames = 0
                                else:
                                    silent_frames += 1

                                if silent_frames >= self._silence_frames_commit:
                                    text = self._transcribe(list(ring_buffer))
                                    if text:
                                        query = text.replace(self.wake_word, "").strip(" ,.!?\n\t")
                                        if not query:
                                            query = text
                                        logger.info("Recognized command", text=query)
                                        if self._loop is not None:
                                            asyncio.run_coroutine_threadsafe(
                                                self._handle_query(query),
                                                self._loop
                                            )
                                    self._state = "IDLE"
                                    silent_frames = 0
                                    ring_buffer.clear()

                        except (IOError, OSError) as e:
                            logger.warning("Audio stream error", error=str(e))
                            continue

                except Exception as e:
                    # Keep retrying if device is temporarily unavailable/busy.
                    logger.error("Listen loop error", error=str(e))
                    if self._running:
                        time.sleep(3)
                finally:
                    if stream is not None:
                        try:
                            if self._audio_backend == "pyaudio":
                                stream.stop_stream()
                                stream.close()
                            else:
                                stream.stop()
                                stream.close()
                        except Exception:
                            pass
                        stream = None

                    if audio is not None:
                        try:
                            audio.terminate()
                        except Exception:
                            pass
                        audio = None
        except Exception as e:
            logger.error("Listen loop error", error=str(e))
        finally:
            self._running = False

    async def _async_speak(self, text: str) -> None:
        """Async wrapper for speak."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.speak, text)

    async def _handle_query(self, query: str) -> None:
        """Handle recognized query by calling backend /ask.
        
        Args:
            query: Recognized query text
        """
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self.backend_url}/ask",
                    json={"query": query, "use_rag": True}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    answer = data.get("answer", "")
                    await self._async_speak(answer)
                else:
                    logger.error("Backend /ask failed", status=response.status_code)
        except Exception as e:
            logger.error("Query handler error", error=str(e))

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Start voice engine.
        
        Args:
            loop: Event loop for async operations
        """
        if not self._enabled:
            logger.warning("Voice engine not available - skipping start")
            return

        if self._running:
            logger.info("Voice engine already running")
            return
        
        self._loop = loop
        self._running = True
        
        # Start listen loop in daemon thread
        thread = threading.Thread(target=self._listen_loop, daemon=True)
        thread.start()
        
        logger.info("Voice engine started")

    def stop(self) -> None:
        """Stop voice engine."""
        self._running = False
        logger.info("Voice engine stopped")
