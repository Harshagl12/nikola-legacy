"""
Piper TTS Engine for Nikola AI.
Provides fast, offline text-to-speech synthesis with pyttsx3 fallback.
"""
import os
import shutil
import subprocess
import tempfile
import pyttsx3
from pathlib import Path
from backend.config import settings
from backend.logger import get_logger

logger = get_logger(__name__)


class PiperTTSEngine:
    """Offline Text-to-Speech synthesizer using Piper with pyttsx3 fallback."""

    def __init__(self):
        self.piper_path = shutil.which("piper") or self._find_piper_exe()
        self.model_path = getattr(settings, "PIPER_MODEL_PATH", "")
        self.pyttsx3_engine = None

        try:
            self.pyttsx3_engine = pyttsx3.init()
            self.pyttsx3_engine.setProperty("rate", 170)
            self.pyttsx3_engine.setProperty("volume", 0.9)
        except Exception as e:
            logger.warning("pyttsx3 initialization failed", error=str(e))

    def _find_piper_exe(self) -> str | None:
        possible_paths = [
            Path("C:/nikola/backend/tools/piper/piper.exe"),
            Path("C:/nikola/backend/models/piper/piper.exe"),
            Path(os.path.expanduser("~/.local/bin/piper.exe")),
        ]
        for p in possible_paths:
            if p.exists():
                return str(p.resolve())
        return None

    def synthesize(self, text: str) -> tuple[bytes, str]:
        """Synthesize text to audio bytes (WAV)."""
        # Try Piper executable if present and model exists
        if self.piper_path and self.model_path and os.path.exists(self.model_path):
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    out_wav = tmp.name

                cmd = [
                    self.piper_path,
                    "--model", self.model_path,
                    "--output_file", out_wav
                ]
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                proc.communicate(input=text.encode("utf-8"), timeout=10)

                if os.path.exists(out_wav) and os.path.getsize(out_wav) > 0:
                    with open(out_wav, "rb") as f:
                        audio_data = f.read()
                    os.unlink(out_wav)
                    return audio_data, "audio/wav"
            except Exception as e:
                logger.warning("Piper synthesis failed, falling back to pyttsx3", error=str(e))

        # Fallback to pyttsx3
        if self.pyttsx3_engine:
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    out_wav = tmp.name

                self.pyttsx3_engine.save_to_file(text, out_wav)
                self.pyttsx3_engine.runAndWait()

                if os.path.exists(out_wav) and os.path.getsize(out_wav) > 0:
                    with open(out_wav, "rb") as f:
                        audio_data = f.read()
                    os.unlink(out_wav)
                    return audio_data, "audio/wav"
            except Exception as e:
                logger.error("pyttsx3 fallback failed", error=str(e))

        # Return silent 0.5s WAV header if all engines fail
        return self._generate_silent_wav(), "audio/wav"

    def speak(self, text: str):
        """Speak text directly through speakers."""
        audio_bytes, _ = self.synthesize(text)
        if self.pyttsx3_engine:
            try:
                self.pyttsx3_engine.say(text)
                self.pyttsx3_engine.runAndWait()
            except Exception:
                pass

    def _generate_silent_wav(self) -> bytes:
        import wave
        import io
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b'\x00' * 16000)
        return buf.getvalue()
