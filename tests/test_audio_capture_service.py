"""Tests for audio_capture_service module."""

import asyncio
import os
import tempfile
import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock, call
from Cocoa import NSApplication, NSApplicationActivationPolicyAccessory

from whisper_input_mac.audio_capture_service import (
    AudioCaptureService,
    AudioCaptureError,
)


@pytest.fixture(scope="session", autouse=True)
def setup_app():
    """Setup NSApplication for macOS API calls."""
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    yield


@pytest.fixture
def event_loop():
    """Create an event loop for tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_audio_session():
    """Create a mock AVAudioSession."""
    session = MagicMock()
    session.requestRecordPermission_.side_effect = lambda handler: handler(True)
    session.setCategory_withOptions_error_.return_value = True
    session.setPreferredSampleRate_error_.return_value = True
    session.setActive_withOptions_error_.return_value = True
    return session


@pytest.fixture
def mock_audio_engine():
    """Create a mock AVAudioEngine."""
    engine = MagicMock()
    engine.isRunning.return_value = True
    input_node = MagicMock()
    engine.inputNode.return_value = input_node
    return engine


@pytest.fixture
def mock_audio_file():
    """Create a mock AVAudioFile."""
    audio_file = MagicMock()
    return audio_file


@pytest.fixture
def service(event_loop):
    """Create an AudioCaptureService instance with mock callbacks."""
    on_start = Mock()
    on_chunk = Mock()
    on_stop = Mock()
    on_error = Mock()

    service = AudioCaptureService(
        loop=event_loop,
        on_start=on_start,
        on_chunk=on_chunk,
        on_stop=on_stop,
        on_error=on_error,
        sample_rate=16000,
        channels=1,
    )
    service.on_start = on_start
    service.on_chunk = on_chunk
    service.on_stop = on_stop
    service.on_error = on_error
    
    # Mock loop.call_soon_threadsafe to execute callbacks immediately for testing
    def call_soon_threadsafe_mock(callback, *args):
        callback(*args)
    
    service.loop.call_soon_threadsafe = Mock(side_effect=call_soon_threadsafe_mock)
    
    return service


class TestAudioCaptureServiceInitialization:
    """Test AudioCaptureService initialization."""

    def test_service_initializes(self, event_loop):
        """Test service initializes with correct state."""
        service = AudioCaptureService(loop=event_loop)

        assert service.loop is event_loop
        assert service.sample_rate == 16000
        assert service.channels == 1
        assert service._is_recording is False
        assert service._permission_requested is False

    def test_service_custom_params(self, event_loop):
        """Test service accepts custom parameters."""
        on_start = Mock()
        on_error = Mock()

        service = AudioCaptureService(
            loop=event_loop,
            on_start=on_start,
            on_error=on_error,
            sample_rate=44100,
            channels=2,
        )

        assert service.on_start is on_start
        assert service.on_error is on_error
        assert service.sample_rate == 44100
        assert service.channels == 2


class TestAudioCaptureError:
    """Test AudioCaptureError exception."""

    def test_error_is_exception(self):
        """Test AudioCaptureError is an Exception subclass."""
        assert issubclass(AudioCaptureError, Exception)

    def test_error_can_be_raised(self):
        """Test AudioCaptureError can be raised and caught."""
        with pytest.raises(AudioCaptureError):
            raise AudioCaptureError("Test error")


class TestMicrophonePermission:
    """Test microphone permission handling."""

    @pytest.mark.asyncio
    async def test_permission_granted(self, service, event_loop):
        """Test successful permission grant."""
        with patch("whisper_input_mac.audio_capture_service.AVAudioSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.sharedInstance.return_value = mock_session

            # Simulate permission grant
            with patch.object(service, "_request_permission_on_main_thread") as mock_request:
                mock_request.return_value = True

                result = await service.ensure_microphone_permission()

                assert result is True
                assert service._permission_requested is True
                mock_session.setCategory_withOptions_error_.assert_called_once()
                mock_session.setActive_withOptions_error_.assert_called_once()

    @pytest.mark.asyncio
    async def test_permission_denied(self, service):
        """Test permission denial."""
        with patch.object(service, "_request_permission_on_main_thread") as mock_request:
            mock_request.return_value = False

            with pytest.raises(AudioCaptureError):
                await service.ensure_microphone_permission()

            assert service._permission_requested is True
            service.on_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_permission_only_requested_once(self, service):
        """Test permission is only requested once."""
        with patch.object(service, "_request_permission_on_main_thread") as mock_request:
            mock_request.return_value = True

            with patch("whisper_input_mac.audio_capture_service.AVAudioSession") as mock_session_class:
                mock_session = MagicMock()
                mock_session_class.sharedInstance.return_value = mock_session

                # First call
                await service.ensure_microphone_permission()
                assert mock_request.call_count == 1

                # Second call should not request again
                result = await service.ensure_microphone_permission()
                assert mock_request.call_count == 1
                assert result is True


class TestRecordingLifecycle:
    """Test recording start/stop lifecycle."""

    def test_start_recording_creates_temp_file(self, service):
        """Test start_recording creates a temporary file."""
        with patch("whisper_input_mac.audio_capture_service.AVAudioEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine_class.return_value = mock_engine
            mock_engine.isRunning.return_value = True

            input_node = MagicMock()
            mock_engine.inputNode.return_value = input_node
            input_node.outputFormatForBus_.return_value = MagicMock()

            with patch("whisper_input_mac.audio_capture_service.AVAudioFile") as mock_file_class:
                mock_file = MagicMock()
                mock_file_class.alloc().initWithURL_commonFormat_interleaved_channelLayout_error_.return_value = mock_file

                service.start_recording("test-session-1")

                assert service._is_recording is True
                assert service._temp_file_path is not None
                assert service._session_id == "test-session-1"

                # Cleanup
                if service._temp_file_path and os.path.exists(service._temp_file_path):
                    os.remove(service._temp_file_path)

    def test_start_recording_emits_on_start(self, service):
        """Test start_recording emits on_start callback."""
        with patch("whisper_input_mac.audio_capture_service.AVAudioEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine_class.return_value = mock_engine
            mock_engine.isRunning.return_value = True

            input_node = MagicMock()
            mock_engine.inputNode.return_value = input_node
            input_node.outputFormatForBus_.return_value = MagicMock()

            with patch("whisper_input_mac.audio_capture_service.AVAudioFile"):
                service.start_recording("test-session-1")

                # on_start should be called via loop.call_soon_threadsafe
                service.on_start.assert_called()
                call_args = service.on_start.call_args
                assert call_args[0][0] == "test-session-1"  # session_id
                assert call_args[0][1] is not None  # file_path

                # Cleanup
                if service._temp_file_path and os.path.exists(service._temp_file_path):
                    os.remove(service._temp_file_path)

    def test_start_recording_guards_double_start(self, service):
        """Test start_recording prevents double-start."""
        service._is_recording = True

        service.start_recording("test-session-1")

        # Should return early without starting
        assert service._session_id is None

    def test_stop_recording_emits_on_stop(self, service):
        """Test stop_recording emits on_stop callback."""
        with patch("whisper_input_mac.audio_capture_service.AVAudioEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine_class.return_value = mock_engine
            mock_engine.isRunning.return_value = True

            input_node = MagicMock()
            mock_engine.inputNode.return_value = input_node
            input_node.outputFormatForBus_.return_value = MagicMock()

            with patch("whisper_input_mac.audio_capture_service.AVAudioFile"):
                # Start recording
                service.start_recording("test-session-1")
                service.on_start.reset_mock()

                # Stop recording
                file_path = service.stop_recording("test-session-1")

                assert file_path is not None
                assert service._is_recording is False
                service.on_stop.assert_called_once()

                # Cleanup
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)

    def test_stop_recording_wrong_session_id(self, service):
        """Test stop_recording with wrong session ID."""
        service._is_recording = True
        service._session_id = "test-session-1"

        result = service.stop_recording("wrong-session-id")

        assert result is None
        assert service._is_recording is True  # Still recording

    def test_cancel_recording_deletes_file(self, service):
        """Test cancel_recording deletes temp file."""
        with patch("whisper_input_mac.audio_capture_service.AVAudioEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine_class.return_value = mock_engine
            mock_engine.isRunning.return_value = True

            input_node = MagicMock()
            mock_engine.inputNode.return_value = input_node
            input_node.outputFormatForBus_.return_value = MagicMock()

            with patch("whisper_input_mac.audio_capture_service.AVAudioFile"):
                # Start recording
                service.start_recording("test-session-1")
                temp_file_path = service._temp_file_path
                assert os.path.exists(temp_file_path)

                # Cancel recording
                service.cancel_recording()

                assert service._is_recording is False
                assert not os.path.exists(temp_file_path)
                # on_stop should NOT be called
                service.on_stop.assert_not_called()


class TestErrorHandling:
    """Test error handling and cleanup."""

    def test_engine_start_failure(self, service):
        """Test handling of engine start failure."""
        with patch("whisper_input_mac.audio_capture_service.AVAudioEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine_class.return_value = mock_engine
            mock_engine.isRunning.return_value = False  # Engine failed to start

            input_node = MagicMock()
            mock_engine.inputNode.return_value = input_node
            input_node.outputFormatForBus_.return_value = MagicMock()

            with patch("whisper_input_mac.audio_capture_service.AVAudioFile"):
                with pytest.raises(AudioCaptureError):
                    service.start_recording("test-session-1")

                service.on_error.assert_called_once()
                assert service._is_recording is False

                # Temp file should be cleaned up
                if service._temp_file_path:
                    assert not os.path.exists(service._temp_file_path)

    def test_no_audio_format_failure(self, service):
        """Test handling when audio format is None."""
        with patch("whisper_input_mac.audio_capture_service.AVAudioEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine_class.return_value = mock_engine

            input_node = MagicMock()
            mock_engine.inputNode.return_value = input_node
            input_node.outputFormatForBus_.return_value = None  # No format

            with pytest.raises(AudioCaptureError):
                service.start_recording("test-session-1")

            service.on_error.assert_called_once()

    def test_cleanup_on_error(self, service):
        """Test cleanup happens on error."""
        service._is_recording = True
        mock_engine = MagicMock()
        service._engine = mock_engine

        # Create a temp file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".caf")
        temp_file_path = temp_file.name
        service._temp_file_path = temp_file_path
        temp_file.close()

        assert os.path.exists(temp_file_path)

        # Cleanup on error
        service._cleanup_on_error()

        assert service._is_recording is False
        assert service._engine is not None
        assert not os.path.exists(temp_file_path)


class TestAsyncEventQueue:
    """Test async event queue for orchestrator integration."""

    @pytest.mark.asyncio
    async def test_wait_for_event(self, service):
        """Test wait_for_event returns queued events."""
        event = {"type": "started", "session_id": "test-1", "path": "/tmp/test.caf"}
        await service._event_queue.put(event)

        received_event = await service.wait_for_event()

        assert received_event == event

    @pytest.mark.asyncio
    async def test_events_queue_on_start(self, service):
        """Test events are queued on start_recording."""
        with patch("whisper_input_mac.audio_capture_service.AVAudioEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine_class.return_value = mock_engine
            mock_engine.isRunning.return_value = True

            input_node = MagicMock()
            mock_engine.inputNode.return_value = input_node
            input_node.outputFormatForBus_.return_value = MagicMock()

            with patch("whisper_input_mac.audio_capture_service.AVAudioFile"):
                service.start_recording("test-session-1")

                # Event should be queued
                event = await asyncio.wait_for(service.wait_for_event(), timeout=1)
                assert event["type"] == "started"
                assert event["session_id"] == "test-session-1"

                # Cleanup
                if service._temp_file_path and os.path.exists(service._temp_file_path):
                    os.remove(service._temp_file_path)

    @pytest.mark.asyncio
    async def test_events_queue_on_stop(self, service):
        """Test events are queued on stop_recording."""
        with patch("whisper_input_mac.audio_capture_service.AVAudioEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine_class.return_value = mock_engine
            mock_engine.isRunning.return_value = True

            input_node = MagicMock()
            mock_engine.inputNode.return_value = input_node
            input_node.outputFormatForBus_.return_value = MagicMock()

            with patch("whisper_input_mac.audio_capture_service.AVAudioFile"):
                service.start_recording("test-session-1")

                # Clear start event
                await service.wait_for_event()

                # Stop recording
                service.stop_recording("test-session-1")

                # Stop event should be queued
                event = await asyncio.wait_for(service.wait_for_event(), timeout=1)
                assert event["type"] == "stopped"
                assert event["session_id"] == "test-session-1"


class TestShutdown:
    """Test shutdown and cleanup."""

    def test_shutdown_deactivates_session(self, service):
        """Test shutdown deactivates audio session."""
        with patch("whisper_input_mac.audio_capture_service.AVAudioSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.sharedInstance.return_value = mock_session

            service.shutdown()

            mock_session.setActive_withOptions_error_.assert_called_once()

    def test_shutdown_stops_engine(self, service):
        """Test shutdown stops engine if running."""
        mock_engine = MagicMock()
        mock_engine.isRunning.return_value = True
        service._engine = mock_engine

        with patch("whisper_input_mac.audio_capture_service.AVAudioSession"):
            service.shutdown()

            mock_engine.stop.assert_called_once()

    def test_shutdown_cancels_active_recording(self, service):
        """Test shutdown cancels active recording."""
        with patch("whisper_input_mac.audio_capture_service.AVAudioEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine_class.return_value = mock_engine
            mock_engine.isRunning.return_value = True

            input_node = MagicMock()
            mock_engine.inputNode.return_value = input_node
            input_node.outputFormatForBus_.return_value = MagicMock()

            with patch("whisper_input_mac.audio_capture_service.AVAudioFile"):
                with patch("whisper_input_mac.audio_capture_service.AVAudioSession"):
                    # Start recording
                    service.start_recording("test-session-1")
                    temp_file_path = service._temp_file_path

                    # Shutdown should cancel recording and clean up
                    service.shutdown()

                    assert service._is_recording is False
                    if temp_file_path:
                        assert not os.path.exists(temp_file_path)
