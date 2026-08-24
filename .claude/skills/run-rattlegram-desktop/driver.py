#!/usr/bin/env python3
"""
Programmatic driver for the Rattlegram Desktop PyQt6 GUI.

Two modes:

    driver.py smoke          launch, exercise a flow, screenshot, exit non-zero on failure
    driver.py repl           read commands from stdin, one per line (pipe or tmux send-keys)

REPL commands:

    type <text>              set the message input field
    send                     activate the send path (as pressing Return / Send does)
    rows                     print every row currently in the message list
    ss [name]                render the main window to <shots>/<name>.png
    dialog <which> [name]    build+render a dialog: callsign | cfo | about | vox
    config <key>             print a value from ~/.rattlegram.json
    quit                     exit 0

Flags:

    --stub-tx                replace transmit() with a no-op that records its args.
                             Required off Linux: the real transmit() opens
                             /dev/ttyUSB0 for PTT and shells out to hard-coded
                             /home/barf/... paths, so it raises SerialException
                             before the message is ever appended to the list.

Screenshots use QWidget.grab(), which renders through Qt itself. It needs no
screen-recording permission and works when `screencapture` is blocked.
"""

import os
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
os.chdir(REPO)

SHOTS = Path(os.environ.get("RG_SHOTS", "/tmp/rattlegram-shots"))
SHOTS.mkdir(parents=True, exist_ok=True)

STUB_TX = "--stub-tx" in sys.argv
MODE = "smoke" if "smoke" in sys.argv else "repl"

from PyQt6 import QtWidgets                                    # noqa: E402
from PyQt6.QtCore import QSocketNotifier, QTimer               # noqa: E402

import rattlegram_desktop_main as rgmain                       # noqa: E402
from rattlegram_desktop_main import Ui_MainWindow              # noqa: E402
from rattlegram_desktop_about_dialog import Ui_AboutDialog     # noqa: E402
from rattlegram_desktop_callsign_dialog import Ui_callsignDialog  # noqa: E402
from rattlegram_desktop_cfo_dialog import Ui_CFODialog         # noqa: E402
from rattlegram_desktop_vox_dialog import Ui_VOXDialog         # noqa: E402

DIALOGS = {
    "callsign": Ui_callsignDialog,
    "cfo": Ui_CFODialog,
    "about": Ui_AboutDialog,
    "vox": Ui_VOXDialog,
}

sent = []
if STUB_TX:
    def _stub_transmit(message):
        sent.append(message)
        print("[stub-tx] transmit(%r)" % message)
        return True
    rgmain.transmit = _stub_transmit


def out(*a):
    print(*a)
    sys.stdout.flush()


class Driver:
    def __init__(self):
        self.app = QtWidgets.QApplication(sys.argv[:1])
        self.win = QtWidgets.QMainWindow()
        self.ui = Ui_MainWindow()          # binds ZMQ REP on tcp://*:5556
        self.ui.setupUi(self.win)
        self.win.show()
        self.app.processEvents()
        self.failures = 0

    # --- individual actions ------------------------------------------------
    def do_type(self, text):
        self.ui.messageTextEdit.setText(text)
        out("input = %r" % self.ui.messageTextEdit.text())

    def do_send(self):
        try:
            self.ui.rattlegram_send()
            out("send ok; rows=%d input=%r"
                % (self.ui.model.rowCount(), self.ui.messageTextEdit.text()))
        except Exception as e:
            self.failures += 1
            out("send RAISED %s: %s" % (type(e).__name__, e))

    def do_rows(self):
        n = self.ui.model.rowCount()
        out("rows=%d" % n)
        for r in range(n):
            out("  [%d] %r" % (r, self.ui.model.item(r).text()))

    def do_ss(self, name="main"):
        self.app.processEvents()
        path = SHOTS / ("%s.png" % name)
        ok = self.win.grab().save(str(path))
        out("screenshot %s -> %s" % ("ok" if ok else "FAILED", path))
        if not ok:
            self.failures += 1

    def do_dialog(self, which, name=None):
        cls = DIALOGS.get(which)
        if cls is None:
            self.failures += 1
            out("unknown dialog %r; try: %s" % (which, ", ".join(DIALOGS)))
            return
        dlg = QtWidgets.QDialog()
        # NB: build+show, never exec() -- exec() spins a nested modal loop and
        # the driver would stop reading stdin until the dialog is dismissed.
        cls().setupUi(dlg)
        dlg.show()
        self.app.processEvents()
        path = SHOTS / ("%s.png" % (name or ("dialog_%s" % which)))
        ok = dlg.grab().save(str(path))
        out("dialog %s title=%r -> %s (%s)"
            % (which, dlg.windowTitle(), path, "ok" if ok else "FAILED"))
        if not ok:
            self.failures += 1
        dlg.close()

    def do_config(self, key):
        out("config %s = %r" % (key, self.ui.config.get_value(key)))

    # --- dispatch ----------------------------------------------------------
    def dispatch(self, line):
        parts = line.strip().split()
        if not parts:
            return
        cmd, args = parts[0], parts[1:]
        if cmd == "quit":
            self.app.quit()
        elif cmd == "type":
            self.do_type(" ".join(args))
        elif cmd == "send":
            self.do_send()
        elif cmd == "rows":
            self.do_rows()
        elif cmd == "ss":
            self.do_ss(*args[:1])
        elif cmd == "dialog":
            self.do_dialog(*args[:2])
        elif cmd == "config":
            self.do_config(*args[:1])
        elif cmd == "help":
            out(__doc__)
        else:
            out("unknown command %r (try 'help')" % cmd)

    # --- modes -------------------------------------------------------------
    def run_repl(self):
        out("driver ready (stub-tx=%s shots=%s); type 'help'" % (STUB_TX, SHOTS))
        notifier = QSocketNotifier(sys.stdin.fileno(),
                                   QSocketNotifier.Type.Read)

        def on_stdin():
            line = sys.stdin.readline()
            if not line:                       # EOF -- piped input finished
                self.app.quit()
                return
            try:
                self.dispatch(line)
            except Exception:
                self.failures += 1
                traceback.print_exc()
                sys.stdout.flush()

        notifier.activated.connect(on_stdin)
        self.app.exec()
        return self.failures

    def run_smoke(self):
        out("== smoke (stub-tx=%s) ==" % STUB_TX)
        out("window title = %r" % self.win.windowTitle())
        out("send button  = %r" % self.ui.sendButton.text())

        self.do_config("callsign")
        self.do_type("/help")               # command path, no subprocess
        self.do_send()
        self.do_type("CQ CQ DE ZL3TUX")     # message path
        self.do_send()
        self.do_rows()
        self.do_ss("main")
        for which in DIALOGS:
            self.do_dialog(which)

        if self.ui.model.rowCount() < 1:
            self.failures += 1
            out("FAIL: message list is empty")
        out("== smoke %s (%d failure(s)) =="
            % ("PASS" if not self.failures else "FAIL", self.failures))
        return self.failures


if __name__ == "__main__":
    d = Driver()
    if MODE == "smoke":
        QTimer.singleShot(0, lambda: sys.exit(d.run_smoke()))
        d.app.exec()
    else:
        sys.exit(d.run_repl())
