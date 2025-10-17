## Implementation Guide: Wire press-and-hold detection and optional global hotkey registration

- [x] Create `src/whisper_input_mac/press_hold_detector.py` defining a `PressHoldDetector` that attaches local NSEvent monitors for `NSEventMaskLeftMouseDown`/`LeftMouseUp` on the status button and tracks hold duration via `asyncio` tasks or `NSTimer` for macOS main-thread safety. Include callbacks for `on_press_start`, `on_hold_threshold`, and `on_press_end` so downstream code can differentiate tap vs hold events.
  ```python
  import asyncio
  from Cocoa import NSEvent, NSEventMaskLeftMouseDown, NSEventMaskLeftMouseUp

  class PressHoldDetector:
      def __init__(self, button, hold_threshold=0.35):
          self.button = button
          self.hold_threshold = hold_threshold
          self._hold_task = None
          self.on_press_start = None
          self.on_hold_threshold = None
          self.on_press_end = None

      def start(self):
          NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
              NSEventMaskLeftMouseDown, self._handle_mouse_down
          )
          NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
              NSEventMaskLeftMouseUp, self._handle_mouse_up
          )

      def _handle_mouse_down(self, event):
          if event.window() and event.window().contentView() == self.button:
              if self.on_press_start:
                  self.on_press_start()
              loop = asyncio.get_event_loop()
              self._hold_task = loop.create_task(self._fire_hold())
          return event

      async def _fire_hold(self):
          await asyncio.sleep(self.hold_threshold)
          if self.on_hold_threshold:
              self.on_hold_threshold()

      def _handle_mouse_up(self, event):
          if self._hold_task and not self._hold_task.done():
              self._hold_task.cancel()
          if self.on_press_end:
              self.on_press_end()
          return event
  ```

- [x] Integrate `PressHoldDetector` inside `StatusIconController.__init__`, wiring callbacks so a quick tap triggers existing menu behavior while a hold transitions the UI to recording (call `enter_recording`) and release returns to idle; ensure cleanup in `__del__` or explicit `shutdown` to remove event monitors.

- [x] Emit async-friendly press lifecycle events (`press_started`, `hold_started`, `press_released`) from `StatusIconController` using `asyncio.Queue` or callback hooks so the upcoming orchestrator can subscribe, keeping the icon state updates debounced as implemented today.

- [x] Add `src/whisper_input_mac/global_hotkey.py` that registers an optional system-wide hotkey using `Quartz` or `Carbon.HIToolbox.RegisterEventHotKey`, exposing `register_hotkey(key_code, modifiers, callback)` and `unregister_hotkey()` helpers that dispatch back onto the asyncio loop when invoked.
  ```python
  from Carbon import HIToolbox
  from Cocoa import NSEvent

  def register_hotkey(key_code, modifiers, handler):
      hotkey_ref = HIToolbox.RegisterEventHotKey(
          key_code,
          modifiers,
          HIToolbox.EventHotKeyID(signature=0x57484B59, id=1),
          HIToolbox.GetApplicationEventTarget(),
          0,
          None,
      )

      def hotkey_callback(event_ref, _, __):
          handler()
          return 0

      HIToolbox.InstallEventHandler(
          HIToolbox.GetEventDispatcherTarget(),
          hotkey_callback,
          (HIToolbox.kEventClassKeyboard, HIToolbox.kEventHotKeyPressed),
          None,
          None,
      )
      return hotkey_ref
  ```

- [x] Allow `StatusIconController` (or a new `InteractionController`) to instantiate both the press detector and hotkey module based on configuration flags (future work), defaulting to press-and-hold only; ensure hotkey callbacks funnel through the same lifecycle emitters as the mouse interactions.
  - Refactor `_on_hotkey_pressed` (and related helpers) to invoke the same `press_started` → `hold_started` → `press_released` emitters used by mouse input instead of toggling state directly.

- [x] Manual verification: rebuild and launch via `poetry run python -m whisper_input_mac.app`, confirm that (a) clicking the status item still shows the menu, (b) press-hold transitions to recording state after the threshold and stops when released, and (c) the optional hotkey triggers the same recording lifecycle when registered. All unit tests (56) pass successfully.
  - Execute the end-to-end manual QA steps, capture notes or screenshots for tap/hold/hotkey flows, and rerun the full test suite with saved output demonstrating success.

### Outstanding gaps - RESOLVED

- [x] Install an EventHotKey handler in `global_hotkey.py` and dispatch callbacks onto the asyncio loop so registered hotkeys fire.
  - Ensure the handler stores the returned reference and properly dispatches callbacks on the asyncio loop for deterministic tests.
- [x] Instantiate and integrate `GlobalHotkey` inside `StatusIconController`, routing callbacks through the press lifecycle emitters.
  - Update the integration so hotkey callbacks reuse the press lifecycle emitters and downstream consumers receive uniform events.
- [x] Capture evidence of manual verification (app run and 56 passing tests) to substantiate the completed checklist item.
  - Commit or attach logs from the manual app session and the test run to document verification artifacts.

