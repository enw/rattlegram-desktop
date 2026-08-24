---
name: run-rattlegram-desktop
description: Build, launch, run, drive, smoke-test, and screenshot the Rattlegram Desktop PyQt6 GUI. Use when asked to run or start the app, take a screenshot of a dialog or the main window, verify a UI change works, or set up the Python environment for this repo.
---

# Run Rattlegram Desktop

PyQt6 amateur-radio chat GUI. It is driven programmatically by
`.claude/skills/run-rattlegram-desktop/driver.py`, which builds the real
`Ui_MainWindow`, sends input, reads the message model, and renders widgets to
PNG via `QWidget.grab()`.

All paths below are relative to the repo root. **Verified on macOS 15
(arm64).** The GUI runs fine here; the transmit path is Linux-only (see
Gotchas) and was not verifiable on this host.

## Prerequisites

Needs Homebrew `python@3.12` (already present here; `brew install python@3.12`
if not). 3.12 was chosen for Qt wheel availability — the default `python3` on
this host is 3.14 and was not tested.

```bash
brew install portaudio
```

`portaudio` is required because `rattlegram_desktop.py` does a top-level
`import pyaudio`, so the app will not start without it — even though nothing
in the live code path uses it.

## Setup

```bash
/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv ~/.venvs/rattlegram
~/.venvs/rattlegram/bin/pip install --upgrade pip
~/.venvs/rattlegram/bin/pip install PyQt6 PySide6 pyzmq pyserial numpy scipy ipython
```

`pyaudio` has no arm64 wheel and must compile against Homebrew portaudio:

```bash
export CFLAGS="-I/opt/homebrew/include" LDFLAGS="-L/opt/homebrew/lib"
~/.venvs/rattlegram/bin/pip install pyaudio
```

Both PyQt6 **and** PySide6 are required — the app mixes the two bindings in
the same modules. There is no build step; there is no test suite.

## Run: agent path

One-shot smoke test. Exercises `/help`, a real message send, the message
model, and renders the main window plus all four dialogs. Exits 0 on pass,
1 on failure:

```bash
~/.venvs/rattlegram/bin/python .claude/skills/run-rattlegram-desktop/driver.py smoke --stub-tx
```

Screenshots land in `/tmp/rattlegram-shots/` (override with `RG_SHOTS`):
`main.png`, `dialog_callsign.png`, `dialog_cfo.png`, `dialog_about.png`,
`dialog_vox.png`. **Open them.** A blank PNG means the launch failed.

Scripted REPL — pipe commands on stdin, one per line:

```bash
printf 'config CFO\ntype HELLO WORLD\nsend\nrows\nss repl_check\ndialog cfo cfo_repl\nquit\n' \
  | ~/.venvs/rattlegram/bin/python -u .claude/skills/run-rattlegram-desktop/driver.py repl --stub-tx
```

Commands: `type <text>`, `send`, `rows`, `ss [name]`,
`dialog <callsign|cfo|about|vox> [name]`, `config <key>`, `help`, `quit`.

Interactive REPL under tmux, for iterating without relaunching:

```bash
tmux new-session -d -s rg "~/.venvs/rattlegram/bin/python -u .claude/skills/run-rattlegram-desktop/driver.py repl --stub-tx"
sleep 6
tmux send-keys -t rg 'type DE ZL3TUX K' Enter; sleep 1
tmux send-keys -t rg 'send' Enter; sleep 1
tmux send-keys -t rg 'ss tmux_check' Enter; sleep 2
tmux capture-pane -t rg -p | grep -v '^objc\[' | grep -v '^$' | tail -10
tmux send-keys -t rg 'quit' Enter
tmux kill-session -t rg
```

## Run: human path

```bash
~/.venvs/rattlegram/bin/python rattlegram_desktop.py
```

A window opens. Useless for verification without a display, and typing a
message into it fails on this platform — prefer the driver.

## Gotchas

- **Only one instance can exist at a time.** `Ui_MainWindow.__init__` binds a
  ZMQ REP socket on `tcp://*:5556` before any window appears, so a second
  process dies with `zmq.error.ZMQError: Address already in use
  (addr='tcp://*:5556')`. Clear a stale one with
  `pkill -f rattlegram_desktop.py`. This bites when the driver is run while
  the app is already open.
- **`--stub-tx` is mandatory off Linux.** The real `transmit()` opens
  `/dev/ttyUSB0` to assert PTT and shells out to hard-coded
  `/home/barf/src/rattlegram-desktop/bin/...` paths, so it raises
  `SerialException` on macOS. Worse, it raises *before* clearing the input
  field or appending the row, so in the GUI the message silently stays in the
  box with no error shown. `--stub-tx` replaces `rattlegram_desktop_main.transmit`
  with a recorder so the full send flow can be driven.
- **`screencapture` does not work here** — it fails with `could not create
  image from display` (no Screen Recording permission for the calling
  process). `QWidget.grab()` renders through Qt and needs no permission; that
  is why the driver uses it. Don't waste time on TCC.
- **`grab()` on macOS omits the menu bar.** Qt puts Settings/Help in the
  native global menu bar, so they are absent from `main.png`. Not a failure.
- **Never `exec()` a dialog from the driver.** `exec()` spins a nested modal
  event loop and the driver stops reading stdin until dismissed. The driver
  uses `setupUi()` + `show()` + `processEvents()` instead — note this differs
  from the app's own `open_*_dialog` methods, which do use `exec()`.
- **Do not pipe the driver's stdout through `grep` inside tmux.** grep
  block-buffers when stdout isn't a tty, so `capture-pane` shows a completely
  empty pane and the driver looks hung. Filter the output of `capture-pane`
  instead, as above.
- **`objc[...]: Class QDarwin*PermissionHandler is implemented in both ...`
  on every launch is expected noise**, not an error — both PyQt6 and PySide6
  Qt libraries load into one process. Filter with `grep -v '^objc\['`.
- **`Worker thread` printing at import time is normal** — it's a bare `print`
  in a class body. The `Worker` thread is never started and its `run()` is
  broken (references undefined `running`, `time`, `i`).
- The driver reads the real user config at `~/.rattlegram.json`. It only
  *renders* dialogs and never clicks OK, so it does not mutate that file.
- `qt.qpa.fonts: ... missing font family "Monospace"` comes from the callsign
  dialog on macOS. Cosmetic.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'PyQt6'` | Using the wrong interpreter. Use the absolute `~/.venvs/rattlegram/bin/python`, not `python3`. |
| `zmq.error.ZMQError: Address already in use` | Another instance holds port 5556: `pkill -f rattlegram_desktop.py`. |
| `send RAISED SerialException: could not open port /dev/ttyUSB0` | Expected off Linux. Add `--stub-tx`. |
| `fatal error: 'portaudio.h' file not found` when installing pyaudio | `brew install portaudio`, then re-install with the `CFLAGS`/`LDFLAGS` exports above. |
| `screencapture: could not create image from display` | Use the driver's `ss` command instead. |
| tmux pane is empty after `send-keys` | Output is being piped through `grep` inside the pane. Launch the driver unpiped. |
