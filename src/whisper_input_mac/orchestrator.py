import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional

from .audio_capture_service import AudioCaptureService
from .status_icon_controller import StatusIconController, IconState
from .transcription import LightningWhisperTranscriber, TranscriptionConfig, TranscriptionError

logger = logging.getLogger(__name__)


class TranscriptionOrchestrator:
    """Orchestrates recording, transcription, and UI state management."""

    def __init__(
        self,
        audio_service: AudioCaptureService,
        icon_controller: StatusIconController,
        transcriber: Optional[LightningWhisperTranscriber] = None,
    ):
        """
        Initialize the orchestrator.

        Args:
            audio_service: AudioCaptureService instance for recording
            icon_controller: StatusIconController for UI updates
            transcriber: LightningWhisperTranscriber instance (created if not provided)
        """
        self.audio_service = audio_service
        self.icon_controller = icon_controller
        self.transcriber = transcriber or LightningWhisperTranscriber()
        self._current_session_id: Optional[str] = None
        self._is_processing = False

    async def handle_press_lifecycle(self):
        """
        Listen to press events from the icon controller and manage recording/transcription.

        This method should be run as a background task to continuously process press events.
        """
        try:
            while True:
                event = await self.icon_controller.press_events.get()
                await self._handle_press_event(event)
        except asyncio.CancelledError:
            logger.debug("Press lifecycle handler cancelled")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in press lifecycle handler: {e}", exc_info=True)

    async def _handle_press_event(self, event: dict):
        """
        Handle a single press lifecycle event.

        Args:
            event: Event dict with keys 'type', etc.
        """
        event_type = event.get("type")

        if event_type == "press_started":
            await self._on_press_started()
        elif event_type == "hold_started":
            await self._on_hold_started()
        elif event_type == "press_released":
            await self._on_press_released()
        else:
            logger.warning(f"Unknown press event type: {event_type}")

    async def _on_press_started(self):
        """Handle initial press (no action yet, waiting for hold threshold)."""
        logger.debug("Press started")

    async def _on_hold_started(self):
        """Start recording when hold threshold is reached."""
        if self._is_processing:
            logger.warning("Already processing, ignoring hold_started")
            return

        self._current_session_id = str(uuid.uuid4())
        logger.info(f"Starting recording session: {self._current_session_id}")

        try:
            await self.audio_service.ensure_microphone_permission()
            self.audio_service.start_recording(self._current_session_id)
        except Exception as e:
            logger.error(f"Failed to start recording: {e}")
            self.icon_controller.set_idle()

    async def _on_press_released(self):
        """Stop recording and transcribe audio."""
        if not self._current_session_id:
            logger.debug("No active recording session to stop")
            return

        session_id = self._current_session_id
        self._current_session_id = None
        self._is_processing = True

        try:
            # Stop recording
            audio_path = self.audio_service.stop_recording(session_id)
            if not audio_path:
                logger.error("Failed to stop recording")
                self.icon_controller.set_idle()
                return

            logger.info(f"Recording stopped, file: {audio_path}")

            # Update UI to busy state for transcription
            self.icon_controller.set_busy()

            # Transcribe asynchronously
            logger.info("Starting transcription...")
            result = await self.transcriber.transcribe_audio(Path(audio_path))

            # Extract text
            transcribed_text = result.get("text", "")
            logger.info(f"Transcription complete: {len(transcribed_text)} characters")

            if transcribed_text:
                # Paste transcribed text to active application
                self._paste_to_clipboard(transcribed_text)
                logger.info("Text sent to clipboard")
            else:
                logger.warning("Empty transcription result")

            # Reset UI
            self.icon_controller.set_idle()

        except TranscriptionError as e:
            logger.warning(f"Transcription failed: {e}")
            self.icon_controller.set_idle()
        except Exception as e:
            logger.error(f"Unexpected error during transcription: {e}", exc_info=True)
            self.icon_controller.set_idle()
        finally:
            self._is_processing = False

    @staticmethod
    def _paste_to_clipboard(text: str):
        """
        Paste text to clipboard and simulate paste command.

        Args:
            text: Text to paste
        """
        try:
            from Cocoa import NSPasteboard, NSStringPboardType, NSString

            pasteboard = NSPasteboard.generalPasteboard()
            pasteboard.clearContents()
            ns_string = NSString.stringWithString_(text)
            pasteboard.setString_forType_(ns_string, NSStringPboardType)
            logger.debug(f"Text copied to clipboard: {len(text)} characters")

            # TODO: Simulate paste command (Cmd+V) to automatically paste
            # This would require additional event handling

        except Exception as e:
            logger.warning(f"Failed to copy to clipboard: {e}")

    def shutdown(self):
        """Clean up resources."""
        if self._current_session_id:
            self.audio_service.cancel_recording()
        self.transcriber.shutdown()
        logger.debug("Orchestrator shutdown complete")
