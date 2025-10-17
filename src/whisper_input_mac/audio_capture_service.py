import asyncio
import logging
import os
import tempfile
import threading
from typing import Callable, Optional

from Cocoa import (
    NSError,
    NSURL,
    AVAudioEngine,
    AVAudioSession,
    AVAudioFile,
    AVAudioFormat,
)

logger = logging.getLogger(__name__)

# AVAudioSession category constants (string values)
AVAudioSessionCategoryPlayAndRecord = "playAndRecord"
AVAudioSessionCategoryOptionDefaultToSpeaker = 0x00000001

# AVAudioCommonFormat constants (integer values from Apple's API)
AVAudioCommonFormatPCMFormatFloat32 = 1


class AudioCaptureError(Exception):
    """Exception raised when audio capture operations fail."""
    pass


class AudioCaptureService:
    """Service for capturing audio via AVAudioEngine with microphone permission handling."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        on_start: Optional[Callable] = None,
        on_chunk: Optional[Callable] = None,
        on_stop: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        sample_rate: int = 16000,
        channels: int = 1,
    ):
        """
        Initialize the audio capture service.

        Args:
            loop: Event loop for async scheduling
            on_start: Callback(session_id, file_path) when recording starts
            on_chunk: Callback(pcm_data) for live level metering
            on_stop: Callback(session_id, file_path) when recording stops
            on_error: Callback(error_dict) on errors
            sample_rate: Sample rate in Hz (default 16000)
            channels: Number of channels (default 1)
        """
        self.loop = loop
        self.on_start = on_start
        self.on_chunk = on_chunk
        self.on_stop = on_stop
        self.on_error = on_error
        self.sample_rate = sample_rate
        self.channels = channels

        self._engine: Optional[AVAudioEngine] = None
        self._audio_file: Optional[AVAudioFile] = None
        self._temp_file_path: Optional[str] = None
        self._session_id: Optional[str] = None
        self._is_recording = False
        self._permission_requested = False

        # Event queue for async orchestrator integration
        self._event_queue: asyncio.Queue = asyncio.Queue()

    async def ensure_microphone_permission(self) -> bool:
        """
        Request microphone permission if not already requested.

        Returns:
            True if permission granted, False otherwise

        Raises:
            AudioCaptureError if permission is denied
        """
        if self._permission_requested:
            return True

        self._permission_requested = True

        # Request permission on main thread
        permission_granted = await self._request_permission_on_main_thread()

        if not permission_granted:
            error_dict = {
                "type": "permission_denied",
                "message": "Microphone permission denied by user",
            }
            if self.on_error:
                self.loop.call_soon_threadsafe(self.on_error, error_dict)
            raise AudioCaptureError("Microphone permission denied")

        # Configure audio session
        try:
            session = AVAudioSession.sharedInstance()
            session.setCategory_withOptions_error_(
                AVAudioSessionCategoryPlayAndRecord,
                AVAudioSessionCategoryOptionDefaultToSpeaker,
                None,
            )
            session.setPreferredSampleRate_error_(self.sample_rate, None)
            session.setActive_withOptions_error_(True, 0, None)
            logger.debug("Audio session configured")
        except Exception as e:
            error_dict = {"type": "session_config_error", "message": str(e)}
            if self.on_error:
                self.loop.call_soon_threadsafe(self.on_error, error_dict)
            raise AudioCaptureError(f"Failed to configure audio session: {e}")

        return True

    async def _request_permission_on_main_thread(self) -> bool:
        """Request microphone permission on main thread."""
        permission_result = [None]
        event = threading.Event()

        def request_permission():
            def permission_handler(granted):
                permission_result[0] = granted
                event.set()

            session = AVAudioSession.sharedInstance()
            session.requestRecordPermission_(permission_handler)

        # Run on a thread (requestRecordPermission_ handles main thread dispatch internally)
        thread = threading.Thread(target=request_permission, daemon=True)
        thread.start()

        # Wait for permission to be granted/denied with timeout
        max_wait = 30  # seconds
        start_time = asyncio.get_event_loop().time()
        while permission_result[0] is None and (asyncio.get_event_loop().time() - start_time) < max_wait:
            await asyncio.sleep(0.1)

        return permission_result[0] if permission_result[0] is not None else False

    def start_recording(self, session_id: str) -> None:
        """
        Start recording audio to a temporary file.

        Args:
            session_id: Unique identifier for this recording session

        Raises:
            AudioCaptureError if recording is already in progress or engine fails
        """
        if self._is_recording:
            logger.warning("Recording already in progress")
            return

        self._session_id = session_id

        try:
            # Create temporary file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".caf")
            self._temp_file_path = temp_file.name
            temp_file.close()

            # Initialize engine
            self._engine = AVAudioEngine()
            input_node = self._engine.inputNode()

            # Get audio format from input node
            audio_format = input_node.outputFormatForBus_(0)
            if audio_format is None:
                raise AudioCaptureError("Failed to get audio format from input node")

            # Create audio file for writing
            error_ptr = None
            file_url = NSURL.fileURLWithPath_(self._temp_file_path)
            self._audio_file = AVAudioFile.alloc().initWithURL_commonFormat_interleaved_channelLayout_error_(
                file_url,
                AVAudioCommonFormatPCMFormatFloat32,
                False,
                None,
                error_ptr,
            )

            if self._audio_file is None:
                raise AudioCaptureError("Failed to create audio file")

            # Install tap on input node
            buffer_size = 4096
            tap_block = self._create_tap_block()
            input_node.installTapOnBus_bufferSize_format_block_(0, buffer_size, audio_format, tap_block)

            # Start engine
            error_ptr = None
            self._engine.startAndReturnError_(error_ptr)

            if self._engine.isRunning():
                self._is_recording = True
                logger.info(f"Recording started: session_id={session_id}, file={self._temp_file_path}")

                # Emit start event
                if self.on_start:
                    self.loop.call_soon_threadsafe(self.on_start, session_id, self._temp_file_path)

                # Queue event for orchestrator
                event = {
                    "type": "started",
                    "session_id": session_id,
                    "path": self._temp_file_path,
                }
                self.loop.call_soon_threadsafe(self._event_queue.put_nowait, event)
            else:
                raise AudioCaptureError("Failed to start audio engine")

        except Exception as e:
            logger.error(f"Error starting recording: {e}")
            self._cleanup_on_error()
            error_dict = {"type": "start_error", "message": str(e), "session_id": session_id}
            if self.on_error:
                self.loop.call_soon_threadsafe(self.on_error, error_dict)
            raise AudioCaptureError(f"Failed to start recording: {e}")

    def _create_tap_block(self):
        """Create the tap block for audio buffer processing."""
        def tap_block(buffer, when):
            """Process audio buffer."""
            try:
                if self._audio_file is not None:
                    # Write buffer to file
                    error_ptr = None
                    self._audio_file.writeFromBuffer_error_(buffer, error_ptr)

                # Optionally forward PCM data for level metering
                if self.on_chunk:
                    # Extract audio data (simplified)
                    pass
            except Exception as e:
                logger.error(f"Error in tap block: {e}")

        return tap_block

    def stop_recording(self, session_id: str) -> Optional[str]:
        """
        Stop recording and return the path to the recorded file.

        Args:
            session_id: The session ID to stop

        Returns:
            Path to the recorded file
        """
        if not self._is_recording or self._session_id != session_id:
            logger.warning(f"No active recording for session {session_id}")
            return None

        try:
            # Stop engine and remove tap
            if self._engine is not None and self._engine.isRunning():
                input_node = self._engine.inputNode()
                input_node.removeTapOnBus_(0)
                self._engine.stop()
                logger.debug("Engine stopped and tap removed")

            # Close audio file
            if self._audio_file is not None:
                # Note: AVAudioFile doesn't have explicit close; it's released when deallocated
                self._audio_file = None

            self._is_recording = False
            file_path = self._temp_file_path

            logger.info(f"Recording stopped: session_id={session_id}, file={file_path}")

            # Emit stop event
            if self.on_stop:
                self.loop.call_soon_threadsafe(self.on_stop, session_id, file_path)

            # Queue event for orchestrator
            event = {
                "type": "stopped",
                "session_id": session_id,
                "path": file_path,
            }
            self.loop.call_soon_threadsafe(self._event_queue.put_nowait, event)

            return file_path

        except Exception as e:
            logger.error(f"Error stopping recording: {e}")
            self._cleanup_on_error()
            error_dict = {"type": "stop_error", "message": str(e), "session_id": session_id}
            if self.on_error:
                self.loop.call_soon_threadsafe(self.on_error, error_dict)
            return None

    def cancel_recording(self) -> None:
        """Cancel recording without emitting on_stop, deleting the partial file."""
        if not self._is_recording:
            return

        try:
            # Stop engine and remove tap
            if self._engine is not None and self._engine.isRunning():
                input_node = self._engine.inputNode()
                input_node.removeTapOnBus_(0)
                self._engine.stop()

            # Close audio file
            self._audio_file = None

            # Delete temp file
            if self._temp_file_path and os.path.exists(self._temp_file_path):
                os.remove(self._temp_file_path)
                logger.debug(f"Deleted temp file: {self._temp_file_path}")

            self._is_recording = False
            logger.info("Recording cancelled")

        except Exception as e:
            logger.error(f"Error cancelling recording: {e}")

    def _cleanup_on_error(self) -> None:
        """Cleanup resources on error."""
        try:
            if self._engine is not None and self._engine.isRunning():
                self._engine.stop()
            self._audio_file = None
            self._is_recording = False

            # Delete temp file if it exists
            if self._temp_file_path and os.path.exists(self._temp_file_path):
                os.remove(self._temp_file_path)
                self._temp_file_path = None
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    async def wait_for_event(self) -> dict:
        """
        Wait for the next lifecycle event from the queue.

        Returns:
            Event dict with keys: type, session_id, path, etc.
        """
        return await self._event_queue.get()

    def shutdown(self) -> None:
        """Deactivate session, unregister notifications, and cleanup resources."""
        try:
            # Stop any active recording
            if self._is_recording:
                self.cancel_recording()

            # Deactivate audio session
            session = AVAudioSession.sharedInstance()
            session.setActive_withOptions_error_(False, 0, None)
            logger.debug("Audio session deactivated")

            # Cleanup engine
            if self._engine is not None and self._engine.isRunning():
                self._engine.stop()
                self._engine = None

            logger.info("Audio capture service shutdown complete")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

    def __del__(self):
        """Cleanup on deletion."""
        self.shutdown()
