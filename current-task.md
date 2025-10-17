## Implementation Guide: Wire press-and-hold detection and optional global hotkey registration

- [x] Review current menu bar event flow in `src/whisper_input_mac/status_icon_controller.py` to map out where press lifecycle callbacks should be dispatched to downstream consumers.
  Study how the status item button is created, how state transitions are handled, and identify hook points for press-start, hold, and release events that will integrate with future orchestrator logic.
- [x] Implement a reusable `PressHoldDetector` helper in `src/whisper_input_mac/press_hold_detector.py` that monitors the status button for mouse down/up events and differentiates between tap vs hold.
  Use `NSEvent.addLocalMonitorForEventsMatchingMask_handler_` for both down and up masks, schedule an `asyncio.create_task(asyncio.sleep(hold_threshold))` to fire the hold callback, and ensure cancellation on quick releases.
- [x] Expose three callbacks on `PressHoldDetector`—`on_press_start`, `on_hold_threshold`, and `on_press_end`—and ensure they dispatch via the running asyncio loop (falling back to synchronous invocation when no loop is active).
  Include robust cleanup in `stop()` and `__del__` to remove monitors safely, logging any failures for diagnostics.
- [x] Instantiate `PressHoldDetector` inside `StatusIconController._setup_press_hold_detector` with a default hold threshold of ~350ms and wire callbacks to enqueue lifecycle messages on an internal `asyncio.Queue` (`press_events`).
  Ensure `press_events` lazily initializes the queue, that each lifecycle event is a dict like `{"type": "press_started"}`, and that queue operations are awaited using `asyncio.create_task` to avoid blocking the main thread.
- [x] Update `StatusIconController.enter_recording()` and `exit_recording()` to react to hold and release events respectively, transitioning icons via existing debounce helpers and logging at INFO level.
  Confirm the busy state still functions and that the spinner lifecycle remains unaffected by press handling.
- [x] Create a `GlobalHotkey` manager in `src/whisper_input_mac/global_hotkey.py` that wraps `Carbon.HIToolbox` APIs when available, providing `register`, `unregister`, and `cleanup` methods plus an internal event handler that forwards presses to asyncio callbacks.
  Guard against missing Carbon imports, log fallbacks, and ensure the handler dispatches callbacks using `loop.call_soon_threadsafe` when possible.
- [x] Extend `StatusIconController` with `_setup_global_hotkey` to opt-in registration of a Space-bar hotkey (no modifiers) that replays the same lifecycle sequence as a hold interaction by enqueuing `press_started`, `hold_started`, and `press_released` events.
  Provide a constructor flag `enable_hotkey` (default False) and ensure resources are released in `shutdown()`.
- [x] Update `src/whisper_input_mac/app.py` to accept CLI flags or environment toggles for `enable_press_hold` and `enable_hotkey`, defaulting to press-hold enabled and hotkey disabled, and pass them through to `StatusIconController`.
  Verify logging configuration surfaces hotkey availability warnings when Carbon is absent.
- [x] Add unit tests: mock `NSEvent` for press detection (e.g., using `pytest` monkeypatch) and mock `HIToolbox` for hotkey registration to assert callbacks fire, monitors are installed/removed, and queue events contain expected payloads.
  Place tests in `tests/test_press_hold_detector.py` and `tests/test_global_hotkey.py`, using `pytest.mark.asyncio` where needed.
- [x] Run automated checks with `poetry run pytest tests/test_press_hold_detector.py tests/test_global_hotkey.py` (plus the existing suite) to validate coverage.
  Capture logs or attach debugger screenshots demonstrating the press lifecycle emitted from both mouse and hotkey flows.
- [x] Perform manual verification: `poetry run python -m whisper_input_mac.app --enable-press-hold --enable-hotkey`
  Press and hold the status icon to confirm recording state transitions, tap quickly to ensure no hold trigger, and press the Space-bar hotkey to confirm the same lifecycle events and state changes.

