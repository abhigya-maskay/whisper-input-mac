import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional

from .audio_capture_service import AudioCaptureService
from .status_icon_controller import StatusIconController, IconState
from .transcription import LightningWhisperTranscriber, TranscriptionConfig, TranscriptionError
from .accessibility import FocusObserver, wait_for_trusted_access, AccessibilityPermissionError
from .text_injector import TextInjector

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

        # Queue for emitting injection events to downstream components
        self.injection_events: asyncio.Queue = asyncio.Queue()

        # Initialize focus observer for tracking focused UI element
        try:
            self.focus_observer = FocusObserver()
            logger.debug("FocusObserver initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize FocusObserver: {e}")
            self.focus_observer = None

        # Initialize text injector for sending transcribed text
        try:
            self.text_injector = TextInjector(restore_clipboard=True)
            logger.debug("TextInjector initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize TextInjector: {e}")
            self.text_injector = None

    async def startup_permissions_check(self):
        """
        Check and request necessary permissions during startup.

        This method checks both microphone and accessibility permissions,
        prompting the user to grant them if needed.
        """
        logger.info("Checking permissions at startup...")

        # Check microphone permission
        try:
            await self.audio_service.ensure_microphone_permission()
            logger.info("Microphone permission granted")
        except Exception as e:
            logger.warning(f"Microphone permission check failed: {e}")

        # Check accessibility permission
        if self.focus_observer:
            try:
                # First, trigger the system prompt if not already trusted
                loop = asyncio.get_running_loop()
                is_trusted = await loop.run_in_executor(
                    None, self.focus_observer.ensure_trusted, True
                )

                if is_trusted:
                    logger.info("Accessibility permission already granted")
                else:
                    # Wait for user to grant permission after seeing the prompt
                    logger.info("Waiting for accessibility permission...")
                    has_access = await wait_for_trusted_access(
                        self.focus_observer,
                        timeout=30.0,  # Give user time to navigate to Settings
                        poll_interval=0.5
                    )
                    if has_access:
                        logger.info("Accessibility permission granted")
                    else:
                        logger.warning(
                            "Accessibility permission not granted. "
                            "Focus tracking will be limited. "
                            "Please enable accessibility access in System Preferences."
                        )
            except AccessibilityPermissionError as e:
                logger.warning(f"Accessibility permission check failed: {e}")
            except Exception as e:
                logger.warning(f"Unexpected error checking accessibility permission: {e}")

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

            # Log focused element metadata for debugging
            if self.focus_observer:
                try:
                    focused_info = self.focus_observer.get_focused_element()
                    if focused_info:
                        logger.debug(
                            f"Focused app - Bundle: {focused_info.bundle_identifier}, "
                            f"Role: {focused_info.role}, Subrole: {focused_info.subrole}"
                        )
                except AccessibilityPermissionError:
                    logger.debug("Accessibility permission not available for focus tracking")
                except Exception as e:
                    logger.debug(f"Failed to get focused element info: {e}")

            if transcribed_text:
                # Inject transcribed text to active application
                if self.text_injector:
                    success, error_msg = self.text_injector.send_text(transcribed_text)
                    if success:
                        logger.info(f"Text injected successfully: {len(transcribed_text)} characters")
                        # Emit success event for downstream components
                        await self.injection_events.put({
                            "type": "injection_success",
                            "session_id": session_id,
                            "text": transcribed_text,
                            "char_count": len(transcribed_text),
                        })
                    else:
                        logger.error(f"Text injection failed: {error_msg}")
                        # Emit failure event for downstream components
                        await self.injection_events.put({
                            "type": "injection_failure",
                            "session_id": session_id,
                            "text": transcribed_text,
                            "char_count": len(transcribed_text),
                            "error_message": error_msg,
                        })
                else:
                    logger.warning("TextInjector not available, skipping text injection")
                    # Emit failure event when injector is not available
                    await self.injection_events.put({
                        "type": "injection_failure",
                        "session_id": session_id,
                        "text": transcribed_text,
                        "char_count": len(transcribed_text),
                        "error_message": "TextInjector not available",
                    })
            else:
                logger.warning("Empty transcription result")
                # Emit failure event for empty transcription
                await self.injection_events.put({
                    "type": "injection_failure",
                    "session_id": session_id,
                    "text": "",
                    "char_count": 0,
                    "error_message": "Empty transcription result",
                })

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


    def shutdown(self):
        """Clean up resources."""
        if self._current_session_id:
            self.audio_service.cancel_recording()
        self.transcriber.shutdown()
        logger.debug("Orchestrator shutdown complete")
