# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Experimental PyQt6 desktop GUI for [Rattlegram](https://github.com/aicodix) — an amateur-radio digital-mode chat client. Messages are typed in the GUI, encoded to audio by an external `encode` binary, and played out a soundcard into a radio transceiver. Author: Stuart MacIntosh ZL3TUX.

## Commands

```bash
./rattlegram_desktop.py          # run the app
python3 rattlegram_desktop_config.py   # dump/inspect config, drops into IPython
python3 tonegen.py -s 48000 -d 0.5 -o out.f32 1300   # standalone tone generator
```

Every UI module also has a `__main__` block that launches just its own dialog — the fastest way to iterate on a single dialog:

```bash
python3 rattlegram_desktop_callsign_dialog.py
```

There are no tests, no linter config, and no dependency manifest. Runtime deps must be installed by hand: `PyQt6`, `PySide6` (both are required — see below), `pyzmq`, `pyserial`, `pyaudio`, `numpy`, `scipy`, `ipython`. The shell scripts in `bin/` additionally need `sox`, `ffmpeg`, `mpv`, and `alsa-utils` (`arecord`).

To actually launch and drive the GUI — verified environment setup, a programmatic driver, and screenshots — use the `run-rattlegram-desktop` skill (`.claude/skills/run-rattlegram-desktop/`). Note that only one instance can run at a time: `Ui_MainWindow.__init__` binds ZMQ on `tcp://*:5556`, so a second process dies with `Address already in use` before showing a window.

## Architecture

**Entry point is thin.** `rattlegram_desktop.py` only parses args and bootstraps Qt (`QApplication` → `QMainWindow` → `Ui_MainWindow().setupUi()`). Roughly 200 of its 272 lines are commented-out prototype code for planned `receiver()` / `transmitter()` threads (pyaudio capture piped to `decode`, ZeroMQ REQ/REP on port 5555). Nothing there is live; don't treat it as the design.

**The real app is `rattlegram_desktop_main.py`.** `Ui_MainWindow` builds the message list, user list, input field, and Settings/Help menus, and owns the TX path.

**UI files are generated code that is now the source of truth.** Every `Ui_*` class was produced by `pyuic6` from a `.ui` file, but the `.ui` files were deleted (commit `3c1585f`, "the generated output is used only"). `build.sh` contains nothing but the commented-out `pyuic6` invocations, kept for reference. So: **hand-edit the `.py` files directly**; do not try to regenerate them, and match the existing pyuic6 idiom — plain `object` subclasses, `setupUi(widget)` + `retranslateUi(widget)`, absolute pixel geometry via `setGeometry(QRect(...))`, signals connected inside `setupUi`. A `rattlegram_desktop_ptt_dialog.ui` existed in the first commit but no `.py` was ever generated from it, which is why PTT settings have no UI.

**Dialog button callbacks look wrong but aren't.** `buttonbox_accepted(button)` in the dialog modules takes the Ui instance as its first argument despite the parameter being named `button` (e.g. `button.config.set_value(...)`). Keep that shape when adding dialogs.

**Config** — `RattlegramDesktopConfig` (`rattlegram_desktop_config.py`) reads/writes a flat JSON file at `~/.rattlegram.json` with keys `callsign`, `CFO`, `encode`, `decode`, creating it with defaults on first run. Note `get_value()` re-reads the file from disk on *every* call and prints each access; there is no caching or in-memory state, and each dialog constructs its own `RattlegramDesktopConfig`. Default callsign is derived from the OS username, ASCII-stripped, uppercased, truncated to 13 chars.

**Input constraints come from the modem wire format**, enforced by `QObject` event filters rather than validators:
- Callsign: base-37 alphabet only (`0-9`, `A-Z`, `_`), max 13 chars, lowercase auto-uppercased — `InputEventFilter` in `rattlegram_desktop_callsign_dialog.py`.
- Message: max 85 chars — a separate `InputEventFilter` in `rattlegram_desktop_main.py`.

Both filters hard-code Qt key codes as integers (`16777219` = Backspace, etc.) alongside `Qt.Key` enums.

**TX path** — `rattlegram_send()` → `transmit()`: exports `CALLSIGN` and `CFO` into the environment, optionally asserts PTT (serial DTR), then `subprocess.run`s a platform-specific script resolved by `tx_script()` relative to `REPO_DIR`. On Linux that's `bin/rattlegram_tx.sh` (`encode` → `tonegen.py` → `sox`/`ffmpeg` → `mpv`); on Darwin it's `bin/macos_tx.sh`. PTT is driven by the optional `ptt` config key — absent means VOX, and an unopenable port logs a warning instead of raising. Messages starting with `/` are handled as IRC-style commands (`/help`, `/ping`; `/ping` shells out to `bin/modem_ping.sh`).

**There are two mutually incompatible modem protocols in play — this is the single most important thing to know.** The Rattlegram *phone app* speaks the wire format of a private fork (`rattlegram-cli`), which is what the prebuilt `bin/linux-*/encode`/`decode` binaries are. Current `aicodix/modem` HEAD is a **different** protocol: `symbol_len = guard*40` and selectable BPSK…QAM4096, versus the app's `symbol_length = 1280*RATE/8000`, `guard = symbol/8`, and fixed QPSK. Audio from modem HEAD is audible to the phone but undecodable by it. Consequences:

- The fork's CLI takes `MESSAGE CALLSIGN [NOISE_SYMBOLS] [CARRIER_FREQUENCY] [RATE] [BITS] [CHANNEL] [MAPPING] [FILE]`, and its `decode` takes `OUTPUT INPUT [SKIP]` — output first, the reverse of upstream.
- `NOISE_SYMBOLS` and `MAPPING` are app concepts that don't exist upstream; seeing them in a usage string identifies the fork.
- The default `CFO` of 1300 is correct for the fork. Upstream would reject it (it requires multiples of 300 and only supports 44100/48000), but upstream is the wrong codec here — don't "fix" 1300.
- The fork's source is not public (`barf/rattlegram-cli`, `barf/modem-short`, `barf/modem-next` are all 404), so there is no macOS/Windows build. `bin/macos_tx.sh` runs the bundled `linux-aarch64` binary in a `linux/arm64` container. The authoritative protocol source is the native C++ in `aicodix/rattlegram` (`app/src/main/cpp/encoder.hh`), which could be wrapped in a CLI to get a native build.

**Native encoder.** `native/encode.cc` wraps the app's own `Encoder<RATE>` in a CLI and `make -C native` builds it to `bin/<os>-<arch>/encode`, fetching the app sources on first build. `bin/macos_tx.sh` prefers that binary and falls back to the container. Two things to know:

- The app's headers call `assert()` but rely on the NDK to include `<cassert>`; a non-Android build must include it itself.
- **Signal quality is strongly rate-dependent**, because the encoder's PAPR-reduction stage is templated on `(32000 + RATE/2)/RATE`, which integer-divides to 4 at 8 kHz but 1 at 44.1/48 kHz. Measured Es/N0 on a clean file: **8000 → 23 dB, 16000 → 15 dB, 32000 → does not decode at all, 44100/48000 → 9 dB.** So the native encoder defaults to **8 kHz**. The prebuilt fork binaries don't apply that stage and are fine at 48 kHz, which is why `rattlegram_tx.sh` uses 48000. Encoder output also peaks near half scale after PAPR reduction and must be normalised, or it is ~6 dB too quiet to survive acoustic coupling — that alone was the difference between decoding and not decoding.

**Known-good interop parameters.** Confirmed working in both directions against the real Rattlegram app on iOS, acoustically coupled: `CFO=1300`, `NOISE_SYMBOLS=4`, `MAPPING=4`, `RATE=48000`, `BITS=16`, `CHANNEL=0`, using the bundled fork binaries. These are the defaults in `bin/macos_tx.sh` and match what `bin/rattlegram_tx.sh` passes. Typical Es/N0 over laptop speaker to phone mic is 15–22 dB, so there is plenty of margin. If interop ever breaks, suspect the binary/protocol before these numbers.

**RX path is not implemented.** `bin/rattlegram_rx.sh` (`arecord | decode` in a loop) exists but nothing in the GUI invokes it, so the message list only ever shows locally-sent messages and the user list is never populated.

## Hazards to know before editing

- **Hard-coded absolute paths — partly fixed.** `transmit()` and `ping()` now resolve scripts against `REPO_DIR`, and PTT is optional, so TX works on macOS. But the three Linux `bin/*.sh` scripts still hard-code `/home/barf/radio/...` for their `ENCODE`/`DECODE`/`TONEGEN`/`WAVOUT` paths, ignoring the `encode`/`decode` values in the config file, and `rattlegram_tx.sh` still sets `XDG_RUNTIME_DIR=/run/user/1000`. `bin/rattlegram_tx.sh` also does `rm -vf $WAVOUT/*` against a fixed directory — make that a `mktemp -d` if you touch it. `modem_ping.sh` additionally wants `1700_start.wav`/`1700_end.wav`, which aren't in the repo, so `/ping` cannot work from a clean checkout.
- **Nothing live consumes the config's `encode`/`decode` keys.** The only reference is inside the commented-out `receiver()` in `rattlegram_desktop.py`, so the bundled `bin/<platform>/` binaries are reached only via the shell scripts' own hard-coded paths.
- **`sox`'s level-triggered `silence` filter cannot be used for capture.** It discards roughly the first 100 ms, which is where the sync preamble lives, so nothing decodes. `bin/macos_rx.sh` uses fixed windows deliberately and says so in a comment.
- **Linux-only binaries.** `bin/linux-amd64/` and `bin/linux-aarch64/` hold prebuilt `encode`/`decode`. `rattlegram_desktop_config.py` computes Windows and Darwin paths too, but both are marked "unsupported yet" and no such binaries are shipped.
- **PyQt6 and PySide6 are mixed in the same modules.** `rattlegram_desktop_main.py` pulls widgets from PyQt6 but `Qt`, `QObject`, `Signal`, `Slot`, `QThread` from PySide6; the callsign dialog mixes `QFont` (PyQt6) with `QFontDatabase` (PySide6). Both packages must be installed. This is fragile — if you touch these imports, verify the app still launches.
- **`Worker` is dead and broken.** Its `run()` references undefined names (`running`, `time`, `i`) and calls `embed()`. A `QThread` + `Worker` pair is constructed in `setupUi` but `start_long_task()` is never connected to anything, so it never runs. Fix it properly or leave it alone; don't wire it up as-is.
- **`from IPython import embed` is the debugger of choice** throughout, and `print()` is the logging mechanism. There is no logging module in use.
- `rattlegram_send()` uses the deprecated `datetime.utcnow()`.
