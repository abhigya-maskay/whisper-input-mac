## Overview

Design a macOS Apple Silicon Python menu-bar application managed with Poetry that records audio while the status bar icon is held, transcribes the capture via Lightning Whisper MLX, and injects the resulting text into the currently focused control.

## Core Components

1. **Menu Bar UI**
   - Implemented with `NSStatusBar` using `PyObjC` or `rumps`.
   - Displays custom icon with state-driven tint/spinner feedback.
   - Handles press-and-hold gestures without opening any window; optional global shortcut registration.

2. **Audio Capture Service**
   - Wraps `AVAudioEngine` microphone session via `PyObjC`.
   - On press, configures input, writes PCM stream to a temporary file, and monitors for errors.
   - On release, finalizes file and notifies orchestrator.

3. **Transcription Pipeline**
   - Asynchronous worker module invoking `lightning-whisper-mlx` (direct API or subprocess).
   - Maintains cached model weights, configurable language/model size.
   - Emits transcription result or error signals.

4. **Focus-Aware Text Injector**
   - Uses Accessibility APIs (`AXUIElement`) to locate the focused element and `CGEvent` keystrokes to emit text.
   - Provides clipboard-paste fallback when direct key injection is unavailable.

5. **Event Orchestrator**
   - Central controller driven by an `asyncio` loop coordinating UI events, audio lifecycle, transcription jobs, and injection responses.
   - Updates status item tooltip/icon with current state.

6. **Configuration & Tooling**
   - Poetry `pyproject.toml` defines dependencies (`PyObjC`, Lightning Whisper MLX, testing stack).
   - Optional YAML/JSON config for hotkeys, sample rate, output behavior.
   - Testing via `pytest` with mocks for audio and accessibility layers; linting with `ruff`, typing with `mypy`.

## Data Flow

1. User presses and holds menu bar icon → Event Orchestrator starts Audio Capture Service.
2. User releases icon → Audio Capture Service stops and supplies temp audio file.
3. Orchestrator enqueues file for Transcription Pipeline.
4. Pipeline returns text or error → Orchestrator routes to Focus-Aware Text Injector or displays failure state.
5. Injector emits keystrokes into current focus (or clipboard paste), confirming completion to Orchestrator.

## Permissions & UX Considerations

- On first launch, prompt users to grant microphone and accessibility access; surface status via menu bar popoverless alerts.
- Provide brief onboarding tooltip through status item menu items (About, Preferences, Quit).
- Offer user preferences for transcription language, auto punctuation, and hotkey bindings.

## Packaging & Deployment

- Maintain reproducible environment with Poetry (`poetry install`, `poetry run` scripts).
- Bundle as a menu-bar-only app using `py2app` or `briefcase`; ensure entitlements cover microphone and accessibility usage.
- Sign and notarize for macOS distribution; optionally ship auto-update via Sparkle-compatible mechanism.
