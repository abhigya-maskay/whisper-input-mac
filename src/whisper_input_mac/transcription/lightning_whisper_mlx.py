import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any

try:
    from lightning_whisper_mlx import LightningWhisperMLX
except ImportError:
    LightningWhisperMLX = None

logger = logging.getLogger(__name__)


class TranscriptionError(Exception):
    """Exception raised when transcription operations fail."""
    pass


@dataclass
class TranscriptionConfig:
    """Configuration for transcription settings."""
    model_name: str = "medium"
    temperature: float = 0.0
    language: Optional[str] = None
    prompt: Optional[str] = None
    cache_dir: Optional[Path] = None

    def __post_init__(self):
        """Ensure cache_dir is a Path object or resolved to default."""
        if self.cache_dir is None:
            self.cache_dir = self._get_default_cache_dir()
        elif isinstance(self.cache_dir, str):
            self.cache_dir = Path(self.cache_dir)

    @staticmethod
    def _get_default_cache_dir() -> Path:
        """Get the default cache directory for models."""
        cache_env = os.environ.get("WHISPER_INPUT_CACHE_DIR")
        if cache_env:
            return Path(cache_env).expanduser()
        return Path.home() / "Library" / "Application Support" / "WhisperInputMac" / "models"


class LightningWhisperTranscriber:
    """Transcriber using Lightning Whisper MLX for fast speech-to-text on Apple Silicon."""

    def __init__(self, config: Optional[TranscriptionConfig] = None) -> None:
        """
        Initialize the transcriber with configuration.

        Args:
            config: TranscriptionConfig instance with model and cache settings.
                    Defaults to base model with standard cache directory.

        Raises:
            TranscriptionError: If Lightning Whisper MLX is not installed.
        """
        if LightningWhisperMLX is None:
            raise TranscriptionError(
                "lightning-whisper-mlx is not installed. "
                "Install it with: poetry add lightning-whisper-mlx ml_dtypes"
            )

        self._config = config or TranscriptionConfig()
        self._pipeline: Optional[LightningWhisperMLX] = None
        self._ensure_cache_dir()

    def _ensure_cache_dir(self) -> None:
        """Ensure the cache directory exists."""
        try:
            self._config.cache_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Cache directory ready: {self._config.cache_dir}")
        except Exception as e:
            logger.warning(f"Failed to create cache directory: {e}")
            raise TranscriptionError(f"Could not create cache directory: {e}") from e

    def _ensure_pipeline(self) -> None:
        """Lazily initialize the MLX pipeline on first use."""
        if self._pipeline is not None:
            return

        try:
            logger.debug(
                f"Loading model '{self._config.model_name}' "
                f"with cache dir: {self._config.cache_dir}"
            )
            # Initialize LightningWhisperMLX
            # Note: The library handles model caching internally, we just specify the model name
            self._pipeline = LightningWhisperMLX(
                model=self._config.model_name,
                batch_size=6,  # Default batch size for good performance
                quant=None,    # No quantization by default
            )
            logger.info(f"Model '{self._config.model_name}' loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise TranscriptionError(f"Failed to load transcription model: {e}") from e

    def transcribe_file(self, audio_path: Path) -> dict:
        """
        Synchronously transcribe an audio file.

        Args:
            audio_path: Path to the audio file to transcribe.

        Returns:
            Normalized transcription response with keys:
            - text: The full transcribed text
            - segments: List of segment dictionaries
            - language: Detected language code

        Raises:
            TranscriptionError: If transcription fails.
        """
        try:
            self._ensure_pipeline()
            audio_path = Path(audio_path)

            if not audio_path.exists():
                raise TranscriptionError(f"Audio file not found: {audio_path}")

            logger.debug(f"Transcribing audio file: {audio_path}")
            result = self._pipeline.transcribe(str(audio_path))
            normalized = self._normalize_response(result)
            logger.info(f"Transcription completed: {len(normalized['text'])} characters")
            return normalized

        except TranscriptionError:
            raise
        except Exception as e:
            logger.warning(f"Transcription error: {e}", exc_info=True)
            raise TranscriptionError(f"Transcription failed: {e}") from e

    async def transcribe_audio(self, audio_path: Path) -> dict:
        """
        Asynchronously transcribe an audio file using a thread executor.

        This keeps the event loop responsive by offloading the blocking
        transcription operation to a thread pool.

        Args:
            audio_path: Path to the audio file to transcribe.

        Returns:
            Normalized transcription response.

        Raises:
            TranscriptionError: If transcription fails.
        """
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self.transcribe_file, audio_path)
            return result
        except Exception as e:
            logger.warning(f"Async transcription error: {e}")
            raise TranscriptionError(f"Async transcription failed: {e}") from e

    @staticmethod
    def _normalize_response(result: dict) -> dict:
        """
        Normalize the MLX pipeline response to a standard format.

        Args:
            result: Raw response from LightningWhisperMLX.transcribe()

        Returns:
            Normalized dictionary with text, segments, and language keys.
        """
        return {
            "text": result.get("text", ""),
            "segments": result.get("segments", []),
            "language": result.get("language", "unknown"),
        }

    def shutdown(self) -> None:
        """Clean up resources."""
        self._pipeline = None
        logger.debug("Transcriber shutdown complete")

    def __del__(self):
        """Cleanup on deletion."""
        self.shutdown()
