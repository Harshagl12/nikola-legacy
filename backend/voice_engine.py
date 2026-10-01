"""
Always-on Voice Engine for NIKOLA.
Handles wake word detection, VAD, STT, and TTS.
Separate from voice_service.py which handles on-demand API calls.
"""

import asyncio
import re
import threading
import time
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
        self._microphone_state = "MICROPHONE_UNKNOWN"
        self._microphone_device: Optional[str] = None
        self._microphone_index: Optional[int] = None
        self._last_voice_error: Optional[str] = None
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

    @property
    def microphone_state(self) -> str:
        """Return the last observed physical microphone state."""
        return self._microphone_state

    @property
    def microphone_device(self) -> Optional[str]:
        """Return the selected physical input device name."""
        return self._microphone_device

    @property
    def last_voice_error(self) -> Optional[str]:
        """Return a safe diagnostic for the last microphone failure."""
        return self._last_voice_error

    def _set_microphone_state(
        self,
        state: str,
        *,
        error: Optional[str] = None,
    ) -> None:
        self._microphone_state = state
        self._last_voice_error = error
        logger.info(
            "Microphone state changed",
            state=state,
            device_index=self._microphone_index,
            device=self._microphone_device,
            error=error,
        )

    def _choose_sounddevice_input(self) -> Optional[int]:
        """Choose the default usable input, then the first usable input."""
        if not SOUNDDEVICE_AVAILABLE:
            return None
        try:
            devices = sd.query_devices()
        except Exception as error:
            self._set_microphone_state("MICROPHONE_UNAVAILABLE", error=str(error))
            return None

        candidates: list[int] = []
        try:
            default_input = sd.default.device[0]
            if isinstance(default_input, int) and default_input >= 0:
                candidates.append(default_input)
        except Exception:
            pass
        candidates.extend(index for index in range(len(devices)) if index not in candidates)

        for index in candidates:
            try:
                device = devices[index]
                if device.get("max_input_channels", 0) > 0:
                    self._microphone_index = index
                    self._microphone_device = str(device.get("name") or f"input-{index}")
                    return index
            except (IndexError, TypeError, AttributeError):
                continue
        self._set_microphone_state("MICROPHONE_UNAVAILABLE", error="No input microphone device found")
        return None

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


    def _transcribe(self, pcm_frames: list[bytes], purpose: str = "utterance") -> str:
        """Transcribe PCM frames using faster-Whisper.
        
        Args:
            pcm_frames: List of raw PCM frames
            
        Returns:
            Transcribed text
        """
        if not self.whisper_model:
            return ""
        
        temp_path = None

        started = time.perf_counter()
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
            logger.info(
                "Audio transcribed",
                purpose=purpose,
                text_length=len(text),
                elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
            )
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
                        self._microphone_index = None
                        self._microphone_device = "PyAudio default input"
                        self._set_microphone_state("MICROPHONE_READY")

                        def read_frame() -> bytes:
                            return stream.read(FRAME_SIZE, exception_on_overflow=False)

                    elif self._audio_backend == "sounddevice":
                        input_device = self._choose_sounddevice_input()
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
                        self._set_microphone_state("MICROPHONE_READY")
                        logger.info("Using microphone device", device_index=input_device)

                        def read_frame() -> bytes:
                            data, overflowed = stream.read(FRAME_SIZE)
                            if overflowed:
                                logger.warning("Microphone input overflow detected")
                            return bytes(data)
                    else:
                        logger.error("No audio backend selected")
                        return

                    utterance_frames: list[bytes] = []
                    silent_frames = 0
                    speech_started_at = None

                    while self._running:
                        try:
                            frame = read_frame()
                            is_speech = self._is_speech_frame(frame)
                            if is_speech:
                                if not utterance_frames:
                                    speech_started_at = time.perf_counter()
                                utterance_frames.append(frame)
                                silent_frames = 0
                            elif utterance_frames:
                                silent_frames += 1

                            # Transcribe one complete utterance rather than repeatedly
                            # sending short rolling buffers to Whisper while idle.
                            utterance_complete = (
                                utterance_frames
                                and (
                                    silent_frames >= self._silence_frames_commit
                                    or len(utterance_frames) >= 200
                                )
                            )
                            if utterance_complete:
                                purpose = (
                                    "wake_detection"
                                    if self._state == "IDLE"
                                    else "command"
                                )
                                command_started_at = speech_started_at or time.perf_counter()
                                text = self._transcribe(utterance_frames, purpose=purpose)
                                utterance_frames = []
                                silent_frames = 0
                                speech_started_at = None

                                if self._state == "IDLE":
                                    if self._contains_wake_word(text):
                                        logger.info(
                                            "Wake word detected",
                                            wake_latency_ms=round(
                                                (time.perf_counter() - command_started_at) * 1000,
                                                1,
                                            ),
                                        )
                                        query = self._remove_wake_word(text).strip(" ,.!?\n\t")
                                        if query:
                                            logger.info("Recognized command", text=query)
                                            if self._loop is not None:
                                                asyncio.run_coroutine_threadsafe(
                                                    self._handle_query(query, command_started_at),
                                                    self._loop,
                                                )
                                            self._state = "IDLE"
                                        else:
                                            self._state = "LISTENING"
                                            if self._loop is not None:
                                                asyncio.run_coroutine_threadsafe(
                                                    self._async_speak("Yes?"),
                                                    self._loop,
                                                )
                                elif self._state == "LISTENING":
                                    query = self._remove_wake_word(text).strip(" ,.!?\n\t")
                                    if query:
                                        logger.info("Recognized command", text=query)
                                        if self._loop is not None:
                                            asyncio.run_coroutine_threadsafe(
                                                self._handle_query(query, command_started_at),
                                                self._loop,
                                            )
                                    self._state = "IDLE"
                                continue

                        except (IOError, OSError) as e:
                            logger.warning("Audio stream error", error=str(e))
                            self._set_microphone_state("MICROPHONE_UNAVAILABLE", error=str(e))
                            break

                except Exception as e:
                    # Keep retrying if device is temporarily unavailable/busy.
                    logger.error("Listen loop error", error=str(e))
                    self._set_microphone_state("MICROPHONE_UNAVAILABLE", error=str(e))
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
            self._set_microphone_state("MICROPHONE_STOPPED")
            self._running = False

    async def _async_speak(self, text: str) -> None:
        """Async wrapper for speak."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.speak, text)

    def _contains_wake_word(self, text: str) -> bool:
        """Accept the configured phrase and the assistant's spoken name."""
        normalized = " ".join(text.lower().split())
        configured = " ".join(self.wake_word.split())
        return configured in normalized or re.search(r"\bnikola\b", normalized) is not None

    def _remove_wake_word(self, text: str) -> str:
        """Remove a configured wake phrase or a spoken Nikola prefix."""
        normalized = text
        if self.wake_word:
            normalized = re.sub(
                re.escape(self.wake_word),
                "",
                normalized,
                flags=re.IGNORECASE,
            )
        return re.sub(r"\b(?:hey\s+)?nikola\b", "", normalized, flags=re.IGNORECASE)

    async def _handle_query(
        self,
        query: str,
        command_started_at: float | None = None,
    ) -> None:
        """Handle recognized query by calling backend /ask.
        
        Args:
            query: Recognized query text
        """
        started = time.perf_counter()
        api_key = settings.NIKOLA_API_KEY
        if not api_key:
            logger.error("Voice command refused because the configured API key is missing")
            await self._async_speak("Nikola could not authenticate with the local backend.")
            return
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self.backend_url}/ask",
                    json={"query": query, "use_rag": True, "source": "voice"},
                    headers={"X-API-Key": api_key},
                )
                
                if response.status_code == 200:
                    data = response.json()
                    answer = data.get("answer", "")
                    await self._async_speak(answer)
                else:
                    logger.error(
                        "Backend voice request failed",
                        status=response.status_code,
                        elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
                        voice_to_response_ms=round(
                            (time.perf_counter() - command_started_at) * 1000,
                            1,
                        ) if command_started_at else None,
                    )
                    if response.status_code == 401:
                        await self._async_speak("Nikola's local backend rejected the voice request.")
                    elif response.status_code == 503:
                        await self._async_speak("Nikola's local services are still starting.")
                    else:
                        await self._async_speak("Nikola could not complete that voice request.")
                logger.info(
                    "Voice request completed",
                    status=response.status_code,
                    elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
                    voice_to_response_ms=round(
                        (time.perf_counter() - command_started_at) * 1000,
                        1,
                    ) if command_started_at else None,
                )
        except Exception as e:
            logger.error("Query handler error", error=str(e))
            await self._async_speak("Nikola could not connect to the local backend.")

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
