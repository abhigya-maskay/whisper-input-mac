## Implementation Guide: Integrate Lightning Whisper MLX, including dependency installation, weight caching, and configuration exposure

- [x] Inspect existing transcription interfaces in `src/whisper_input_mac` (search for modules like `transcription` or placeholders) to decide where the MLX-backed transcriber class should live; note any abstract base classes or event contracts to satisfy.
- [x] Add Lightning Whisper MLX dependencies to `pyproject.toml` with `poetry add lightning-whisper-mlx ml_dtypes` (the latter is required by MLX) and run `poetry lock`; confirm `poetry install` completes on Apple Silicon machines and capture any extra system requirements in project notes.
- [x] Create `src/whisper_input_mac/transcription/__init__.py` if missing and scaffold `src/whisper_input_mac/transcription/lightning_whisper_mlx.py` with a `LightningWhisperMLX` class that lazily loads the model on first transcription.
  ```python
  from pathlib import Path
  from lightning_whisper_mlx import LightningWhisperMLX


  class LightningWhisperTranscriber:
      def __init__(self, model_name: str, cache_dir: Path) -> None:
          self._model_name = model_name
          self._cache_dir = cache_dir
          self._pipeline = None

      def _ensure_pipeline(self) -> None:
          if self._pipeline is None:
              self._pipeline = LightningWhisperMLX(model=self._model_name, download_root=self._cache_dir)

      def transcribe_file(self, audio_path: Path) -> dict:
          self._ensure_pipeline()
          return self._pipeline.transcribe(str(audio_path))
  ```
- [x] Implement automatic cache directory resolution (default to `~/Library/Application Support/WhisperInputMac/models`) and allow overrides via environment variables or upcoming configuration loader; ensure directories are created with `Path.mkdir(parents=True, exist_ok=True)`.
- [x] Expose configuration knobs (model name, temperature, language, prompt) via a dataclass or simple settings object and thread these through the transcriber constructor; default to the `base` model and document supported variants inline.
- [x] Provide async-friendly wrappers by adding `async def transcribe_audio(self, audio_path: Path) -> dict` that offloads `transcribe_file` onto a thread executor using `asyncio.get_running_loop().run_in_executor(None, self.transcribe_file, audio_path)` to keep the event loop responsive.
- [x] Ensure transcription responses are normalized into a structured payload (e.g., `{"text": text, "segments": segments, "language": detected_language}`) and include error handling that wraps exceptions in domain-specific `TranscriptionError` types logged at WARNING level.
- [x] Wire the new transcriber into the orchestrator or worker entry point (e.g., `src/whisper_input_mac/orchestrator.py` or similar) by instantiating it with config values and invoking `await transcriber.transcribe_audio(temp_audio_path)` when jobs arrive.
- [x] Implement weight prefetch tooling: add a CLI helper `poetry run python -m whisper_input_mac.tools.prefetch_models --model base --cache ~/...` that instantiates the transcriber once to force downloads, and document usage in developer notes.
- [x] Add unit tests under `tests/transcription/test_lightning_whisper_mlx.py` that monkeypatch `LightningWhisperMLX` to avoid real downloads and assert lazy loading, cache path creation, and structured outputs; include an async test verifying executor usage.
- [x] Run `poetry run pytest tests/transcription/test_lightning_whisper_mlx.py` and the broader suite to verify integration; fix any new lint or typing issues surfaced by project tooling.
