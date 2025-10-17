"""Tests for the transcription module."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

from whisper_input_mac.transcription import (
    LightningWhisperTranscriber,
    TranscriptionConfig,
    TranscriptionError,
)


class TestTranscriptionConfig:
    """Tests for TranscriptionConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = TranscriptionConfig()
        assert config.model_name == "base"
        assert config.temperature == 0.0
        assert config.language is None
        assert config.prompt is None
        assert config.cache_dir is not None

    def test_custom_config(self):
        """Test custom configuration values."""
        cache_path = Path("/custom/cache")
        config = TranscriptionConfig(
            model_name="small",
            temperature=0.5,
            language="en",
            prompt="Transcribe speech",
            cache_dir=cache_path,
        )
        assert config.model_name == "small"
        assert config.temperature == 0.5
        assert config.language == "en"
        assert config.prompt == "Transcribe speech"
        assert config.cache_dir == cache_path

    def test_cache_dir_from_environment(self):
        """Test cache directory resolution from environment variable."""
        with patch.dict("os.environ", {"WHISPER_INPUT_CACHE_DIR": "/tmp/custom"}):
            config = TranscriptionConfig()
            assert config.cache_dir == Path("/tmp/custom")

    def test_cache_dir_default_macos(self):
        """Test default cache directory for macOS."""
        with patch.dict("os.environ", {}, clear=True):
            config = TranscriptionConfig()
            expected = Path.home() / "Library" / "Application Support" / "WhisperInputMac" / "models"
            assert config.cache_dir == expected

    def test_cache_dir_string_conversion(self):
        """Test that string cache_dir is converted to Path."""
        config = TranscriptionConfig(cache_dir="/some/path")
        assert isinstance(config.cache_dir, Path)
        assert str(config.cache_dir) == "/some/path"


class TestLightningWhisperTranscriber:
    """Tests for LightningWhisperTranscriber class."""

    @patch("whisper_input_mac.transcription.lightning_whisper_mlx.LightningWhisperMLX")
    def test_initialization(self, mock_mlx_class):
        """Test transcriber initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TranscriptionConfig(model_name="base", cache_dir=Path(tmpdir))
            transcriber = LightningWhisperTranscriber(config)
            assert transcriber._config == config
            assert transcriber._pipeline is None

    @patch("whisper_input_mac.transcription.lightning_whisper_mlx.LightningWhisperMLX", None)
    def test_initialization_without_mlx_installed(self):
        """Test initialization fails gracefully if MLX not installed."""
        with pytest.raises(TranscriptionError, match="lightning-whisper-mlx is not installed"):
            LightningWhisperTranscriber()

    @patch("whisper_input_mac.transcription.lightning_whisper_mlx.LightningWhisperMLX")
    def test_cache_dir_creation(self, mock_mlx_class):
        """Test that cache directory is created on initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache" / "nested"
            config = TranscriptionConfig(cache_dir=cache_path)
            transcriber = LightningWhisperTranscriber(config)
            assert cache_path.exists()

    @patch("whisper_input_mac.transcription.lightning_whisper_mlx.LightningWhisperMLX")
    def test_lazy_loading_of_pipeline(self, mock_mlx_class):
        """Test that pipeline is lazily loaded on first use."""
        mock_pipeline_instance = MagicMock()
        mock_mlx_class.return_value = mock_pipeline_instance

        with tempfile.TemporaryDirectory() as tmpdir:
            config = TranscriptionConfig(cache_dir=Path(tmpdir))
            transcriber = LightningWhisperTranscriber(config)

            # Pipeline should not be loaded yet
            assert transcriber._pipeline is None

            # Create a dummy audio file
            audio_file = Path(tmpdir) / "test.wav"
            audio_file.write_bytes(b"dummy audio data")

            # Mock the transcribe method
            mock_pipeline_instance.transcribe.return_value = {
                "text": "Hello world",
                "segments": [],
                "language": "en",
            }

            # Transcribe should trigger lazy loading
            result = transcriber.transcribe_file(audio_file)

            # Verify pipeline was initialized
            assert transcriber._pipeline is not None
            mock_mlx_class.assert_called_once()

            # Verify transcribe was called
            mock_pipeline_instance.transcribe.assert_called_once_with(str(audio_file))

    @patch("whisper_input_mac.transcription.lightning_whisper_mlx.LightningWhisperMLX")
    def test_transcribe_file_success(self, mock_mlx_class):
        """Test successful file transcription."""
        mock_pipeline_instance = MagicMock()
        mock_mlx_class.return_value = mock_pipeline_instance

        mock_response = {
            "text": "Hello world",
            "segments": [{"start": 0.0, "end": 1.0, "text": "Hello"}],
            "language": "en",
        }
        mock_pipeline_instance.transcribe.return_value = mock_response

        with tempfile.TemporaryDirectory() as tmpdir:
            config = TranscriptionConfig(cache_dir=Path(tmpdir))
            transcriber = LightningWhisperTranscriber(config)

            audio_file = Path(tmpdir) / "test.wav"
            audio_file.write_bytes(b"dummy audio")

            result = transcriber.transcribe_file(audio_file)

            assert result["text"] == "Hello world"
            assert result["segments"] == mock_response["segments"]
            assert result["language"] == "en"

    @patch("whisper_input_mac.transcription.lightning_whisper_mlx.LightningWhisperMLX")
    def test_transcribe_file_not_found(self, mock_mlx_class):
        """Test transcription with non-existent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TranscriptionConfig(cache_dir=Path(tmpdir))
            transcriber = LightningWhisperTranscriber(config)

            with pytest.raises(TranscriptionError, match="Audio file not found"):
                transcriber.transcribe_file(Path(tmpdir) / "nonexistent.wav")

    @patch("whisper_input_mac.transcription.lightning_whisper_mlx.LightningWhisperMLX")
    def test_transcribe_file_mlx_error(self, mock_mlx_class):
        """Test error handling when MLX transcription fails."""
        mock_pipeline_instance = MagicMock()
        mock_mlx_class.return_value = mock_pipeline_instance
        mock_pipeline_instance.transcribe.side_effect = RuntimeError("MLX error")

        with tempfile.TemporaryDirectory() as tmpdir:
            config = TranscriptionConfig(cache_dir=Path(tmpdir))
            transcriber = LightningWhisperTranscriber(config)

            audio_file = Path(tmpdir) / "test.wav"
            audio_file.write_bytes(b"dummy audio")

            with pytest.raises(TranscriptionError, match="Transcription failed"):
                transcriber.transcribe_file(audio_file)

    @patch("whisper_input_mac.transcription.lightning_whisper_mlx.LightningWhisperMLX")
    @pytest.mark.asyncio
    async def test_transcribe_audio_async(self, mock_mlx_class):
        """Test async transcription using executor."""
        mock_pipeline_instance = MagicMock()
        mock_mlx_class.return_value = mock_pipeline_instance

        mock_response = {
            "text": "Hello world",
            "segments": [],
            "language": "en",
        }
        mock_pipeline_instance.transcribe.return_value = mock_response

        with tempfile.TemporaryDirectory() as tmpdir:
            config = TranscriptionConfig(cache_dir=Path(tmpdir))
            transcriber = LightningWhisperTranscriber(config)

            audio_file = Path(tmpdir) / "test.wav"
            audio_file.write_bytes(b"dummy audio")

            result = await transcriber.transcribe_audio(audio_file)

            assert result["text"] == "Hello world"
            assert result["language"] == "en"

    def test_normalize_response(self):
        """Test response normalization."""
        raw_response = {
            "text": "Hello world",
            "segments": [{"id": 0, "seek": 0, "start": 0.0, "end": 1.0, "text": "Hello"}],
            "language": "en",
        }

        normalized = LightningWhisperTranscriber._normalize_response(raw_response)

        assert normalized["text"] == "Hello world"
        assert normalized["segments"] == raw_response["segments"]
        assert normalized["language"] == "en"

    def test_normalize_response_missing_fields(self):
        """Test response normalization with missing fields."""
        raw_response = {"text": "Hello"}

        normalized = LightningWhisperTranscriber._normalize_response(raw_response)

        assert normalized["text"] == "Hello"
        assert normalized["segments"] == []
        assert normalized["language"] == "unknown"

    @patch("whisper_input_mac.transcription.lightning_whisper_mlx.LightningWhisperMLX")
    def test_shutdown(self, mock_mlx_class):
        """Test transcriber shutdown."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TranscriptionConfig(cache_dir=Path(tmpdir))
            transcriber = LightningWhisperTranscriber(config)
            transcriber._pipeline = MagicMock()

            transcriber.shutdown()

            assert transcriber._pipeline is None

    @patch("whisper_input_mac.transcription.lightning_whisper_mlx.LightningWhisperMLX")
    def test_ensure_pipeline_called_once(self, mock_mlx_class):
        """Test that pipeline is only initialized once."""
        mock_pipeline_instance = MagicMock()
        mock_mlx_class.return_value = mock_pipeline_instance

        mock_response = {
            "text": "Hello world",
            "segments": [],
            "language": "en",
        }
        mock_pipeline_instance.transcribe.return_value = mock_response

        with tempfile.TemporaryDirectory() as tmpdir:
            config = TranscriptionConfig(cache_dir=Path(tmpdir))
            transcriber = LightningWhisperTranscriber(config)

            audio_file = Path(tmpdir) / "test.wav"
            audio_file.write_bytes(b"dummy audio")

            # Call transcribe twice
            transcriber.transcribe_file(audio_file)
            transcriber.transcribe_file(audio_file)

            # MLX class should only be instantiated once
            mock_mlx_class.assert_called_once()


class TestTranscriptionError:
    """Tests for TranscriptionError exception."""

    def test_transcription_error_creation(self):
        """Test TranscriptionError can be created and raised."""
        error = TranscriptionError("Test error")
        assert str(error) == "Test error"

    def test_transcription_error_inheritance(self):
        """Test TranscriptionError inherits from Exception."""
        assert issubclass(TranscriptionError, Exception)
