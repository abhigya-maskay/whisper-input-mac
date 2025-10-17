"""CLI tool to prefetch Lightning Whisper MLX models to avoid download latency during first use."""

import argparse
import logging
import sys
from pathlib import Path

from ..transcription import LightningWhisperTranscriber, TranscriptionConfig, TranscriptionError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """Prefetch models for offline use."""
    parser = argparse.ArgumentParser(
        description="Prefetch Lightning Whisper MLX models to cache directory"
    )
    parser.add_argument(
        "--model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Model size to prefetch (default: base)",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        help="Custom cache directory (default: ~/Library/Application Support/WhisperInputMac/models)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info(f"Prefetching model: {args.model}")
    if args.cache:
        logger.info(f"Using cache directory: {args.cache}")

    try:
        # Create config
        config = TranscriptionConfig(
            model_name=args.model,
            cache_dir=args.cache,
        )

        # Create transcriber (this will download and cache the model)
        logger.info("Initializing transcriber (downloading model if needed)...")
        transcriber = LightningWhisperTranscriber(config)

        logger.info("Model prefetch completed successfully!")
        logger.info(f"Model cached at: {config.cache_dir / args.model}")
        logger.info("You can now use the app without waiting for initial model download.")

        return 0

    except TranscriptionError as e:
        logger.error(f"Transcription error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
