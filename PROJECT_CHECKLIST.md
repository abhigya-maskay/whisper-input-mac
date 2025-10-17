## Menu Bar UI
- [x] Scaffold Poetry-managed macOS app entry point with `NSStatusBar` status item.
- [x] Implement custom status icon rendering with idle, recording, and spinner states.
- [x] Wire press-and-hold detection and optional global hotkey registration.

## Audio Capture Service
- [x] Initialize `AVAudioEngine` session via `PyObjC`, configuring microphone input and permissions.
- [x] Implement press-triggered PCM recording to a temporary file with error monitoring.
- [x] Finalize recording on release and publish completion events.

## Transcription Pipeline
- [x] Integrate Lightning Whisper MLX, including dependency installation, weight caching, and configuration exposure.
- [x] Build an async worker to queue audio jobs and invoke transcription.
- [x] Emit structured success or error messages back to the orchestrator.

## Focus-Aware Text Injector
- [ ] Access the focused UI element using Accessibility (`AXUIElement`) APIs.
- [ ] Implement keystroke injection via `CGEvent` with fallback to clipboard paste.
- [ ] Provide completion or error callbacks for orchestrator handling.

## Event Orchestrator
- [x] Establish a central `asyncio` loop coordinating UI, audio, transcription, and injection events.
- [x] Maintain a state machine that updates status icon and tooltips per lifecycle stage.
- [x] Handle error propagation and recovery across components.

## Configuration & Tooling
- [x] Define Poetry `pyproject.toml` with dependencies, scripts, and lint/test tooling.
- [x] Implement a configuration loader (YAML or JSON) for language, sample rate, and hotkeys.
- [x] Set up CI-ready `pytest`, `ruff`, and `mypy` configurations with mocks or stubs.

## Data Flow Integration
- [x] Connect press events to start the audio service and track session metadata.
- [x] Chain release events to enqueue temporary audio files for transcription.
- [ ] Route transcription results to the text injector or surface failure feedback.

## Permissions & UX
- [ ] Implement first-launch prompts for microphone and accessibility access with status UI.
- [ ] Add status item menu entries for About, Preferences, and Quit.
- [ ] Provide preference UI or CLI for language selection, autopunctuation, and hotkeys.

## Packaging & Deployment
- [ ] Configure a reproducible Poetry environment and `poetry run` scripts.
- [ ] Package as a menu-bar-only app using `py2app` or `briefcase` with required entitlements.
- [ ] Prepare signing and notarization workflow and plan optional Sparkle auto-update integration.
