"""
On-demand Voice Service for NIKOLA backend.
Handles transcription and synthesis called via FastAPI endpoints.
"""

import asyncio
import os
import io
import time
import tempfile
from pathlib import Path
from typing import Optional, Tuple

try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False
    WhisperModel = None

import pyttsx3

from backend.config import settings
from backend.logger import get_logger

logger = get_logger(__name__)

# Model cache
_whisper_model = None


def check_stt_health() -> bool:
    """Verify Whisper model and TTS engine are loaded and responsive."""
    try:
        if not FASTER_WHISPER_AVAILABLE:
            return False
        model = _get_whisper_model()
        if model is None:
            return False
        # Test TTS init responsiveness
        engine = pyttsx3.init()
        return True
    except Exception as e:
        logger.error("STT/TTS health check failed", error=str(e))
        return False


def cleanup_temp_files():
    """Delete audio temp files (.wav, .mp3, .webm) older than 24 hours."""
    try:
        temp_dir = Path(tempfile.gettempdir())
        now = time.time()
        count = 0
        for ext in [".wav", ".mp3", ".webm"]:
            for f in temp_dir.glob(f"*{ext}"):
                try:
                    if f.is_file() and (now - f.stat().st_mtime) > 86400:
                        f.unlink()
                        count += 1
                except Exception:
                    pass
        if count > 0:
            logger.info("Cleaned up old audio temp files", count=count)
    except Exception as e:
        logger.error("Temp file cleanup failed", error=str(e))


def _get_whisper_model():
    """Get or create whisper model (cached)."""
    global _whisper_model
    
    if not FASTER_WHISPER_AVAILABLE:
        raise RuntimeError("faster-whisper not available")
    
    if _whisper_model is None:
        try:
            _whisper_model = WhisperModel(
                settings.WHISPER_MODEL,
                device="cpu",
                compute_type="int8"
            )
        except Exception as e:
            logger.error("Failed to load whisper model", error=str(e))
            raise
    
    return _whisper_model


async def transcribe_audio(audio_bytes: bytes, language: str = "en") -> dict:
    """Transcribe audio file using Whisper.
    
    Args:
        audio_bytes: Raw audio bytes
        language: Language code (default 'en')
        
    Returns:
        Dict with text, confidence, and error
    """
    try:
        cleanup_temp_files()
        
        if not check_stt_health():
            return {
                "text": "",
                "confidence": 0.0,
                "error": "STT engine not healthy or unavailable"
            }
        # Validate audio
        is_valid, error_msg = validate_audio(audio_bytes)
        if not is_valid:
            return {
                "text": "",
                "confidence": 0.0,
                "error": error_msg
            }
        
        # Write to temp file and transcribe
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                _transcribe_sync,
                audio_bytes,
                language
            ),
            timeout=60
        )
        
        return result
    except TimeoutError:
        logger.error("Transcription timed out")
        return {
            "text": "",
            "confidence": 0.0,
            "error": "Transcription timed out"
        }
    except Exception as e:
        logger.error("Transcription failed", error=str(e))
        return {
            "text": "",
            "confidence": 0.0,
            "error": str(e)
        }


def _transcribe_sync(audio_bytes: bytes, language: str) -> dict:
    """Synchronous transcription (runs in executor)."""
    import tempfile
    import os
    
    if not FASTER_WHISPER_AVAILABLE:
        return {
            "text": "",
            "confidence": 0.0,
            "error": "faster-whisper not available"
        }
    
    try:
        # Write to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            temp_path = f.name
        
        try:
            # Get cached model
            model = _get_whisper_model()
            
            # Transcribe
            segments, info = model.transcribe(
                temp_path,
                language=language
            )
            
            # Combine segments
            text = " ".join(segment.text for segment in segments).strip()
            
            # Confidence from info
            confidence = 0.9 if text else 0.0
            
            logger.info("Audio transcribed", text_length=len(text))
            
            return {
                "text": text,
                "confidence": confidence,
                "error": None
            }
        finally:
            # Clean up temp file
            try:
                os.unlink(temp_path)
            except:
                pass
    except Exception as e:
        logger.error("Transcription sync error", error=str(e), exc_info=True)
        return {
            "text": "",
            "confidence": 0.0,
            "error": str(e)
        }


async def synthesize_speech(text: str, voice_id: str = "default") -> Tuple[bytes, str]:
    """Synthesize speech from text.
    
    Args:
        text: Text to synthesize
        voice_id: Voice identifier (unused for pyttsx3)
        
    Returns:
        Tuple of (audio_bytes, content_type)
    """
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            _synthesize_sync,
            text
        )
        
        return result
    except Exception as e:
        logger.error("Synthesis failed", error=str(e))
        raise


def _synthesize_sync(text: str) -> Tuple[bytes, str]:
    """Synchronous synthesis (runs in executor)."""
    cleanup_temp_files()
    
    try:
        from backend.piper_tts import PiperTTSEngine
        engine = PiperTTSEngine()
        audio_bytes, content_type = engine.synthesize(text)
        logger.info("Speech synthesized", text_length=len(text))
        return audio_bytes, content_type
    except Exception as e:
        logger.error("Synthesis sync error", error=str(e))
        raise



def validate_audio(audio_bytes: bytes) -> Tuple[bool, str]:
    """Validate audio file.
    
    Args:
        audio_bytes: Raw audio bytes
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check size < 25MB
    if len(audio_bytes) > 25 * 1024 * 1024:
        return False, "Audio file too large (max 25MB)"
    
    # Check format by header
    if len(audio_bytes) < 12:
        return False, "Audio file too small"
    
    # Check for known audio formats
    # WAV: RIFF header
    if audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE":
        return True, ""
    
    # MP3: ID3 or FF FB/FA/F9/F8
    if audio_bytes[:3] == b"ID3" or audio_bytes[:2] in [b"\xff\xfb", b"\xff\xfa", b"\xff\xf9", b"\xff\xf8"]:
        return True, ""
    
    # OGG: OggS
    if audio_bytes[:4] == b"OggS":
        return True, ""
    
    # FLAC: fLaC
    if audio_bytes[:4] == b"fLaC":
        return True, ""
    
    # M4A: ftyp
    if audio_bytes[4:8] == b"ftyp":
        return True, ""
    
    # Accept anyway (let Whisper handle it)
    logger.warning("Unknown audio format, accepting anyway")
    return True, ""
