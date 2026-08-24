#!/usr/bin/env python3
#
# Rattlegram Desktop
# Copyright 2025 
# Stuart MacIntosh ZL3TUX <stuart@macintosh.nz>
#

from datetime import date, datetime
import pickle
import os
import platform
import re
import zmq
import subprocess
import serial
import PyQt6
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import pyqtSignal, pyqtSlot, QThread
from PyQt6.QtGui import QStandardItemModel, QStandardItem
from PyQt6.QtWidgets import QApplication, QListView, QAbstractItemView, QMainWindow
from PySide6.QtCore import QObject, QEvent, Qt, QThread, Signal, Slot

from rattlegram_desktop_config import RattlegramDesktopConfig
from rattlegram_desktop_callsign_dialog import Ui_callsignDialog
from rattlegram_desktop_cfo_dialog import Ui_CFODialog
from rattlegram_desktop_about_dialog import Ui_AboutDialog
from rattlegram_desktop_vox_dialog import Ui_VOXDialog

from IPython import embed

CONTROL_CHARS = [
        Qt.Key.Key_Enter,
        Qt.Key.Key_Return,
        16777219, # BS backspace
        16777223, # DEL
        16777232, # HOME
        16777233 # END
        ]

class InputEventFilter(QtCore.QObject):
    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.KeyPress:
            key_event = event
            l = len(obj.text())
            key = key_event.key()

            if l >= 85 and key not in CONTROL_CHARS:
                print('discard\tlen:%s\tkey:%s' % (l, key_event.key()))
                return True

        retvar = super().eventFilter(obj, event)
        return retvar

class Worker(QObject):
    print('Worker thread')
    finished = Signal()
    progress = Signal(int)

    running = True
    # while running:
    #     recv = self.socket.recv()
    #     print('tx thread got: %s' % rx)

    #     #  Do 'work'

    #     # Send reply back to client
    #     self.socket.send(b"Sent")
    # self.socket.close()

    def run(self):
        print('Worker.run()')
        while running:
            time.sleep(5)  # Simulate a long-running task
            self.progress.emit(i + 1)
            print(i)
            embed()
        self.finished.emit()

class Ui_MainWindow(object):
    def __init__(self):
        super().__init__()
        self.config = RattlegramDesktopConfig()
        self.zmqcontext = zmq.Context()
        self.zmqsocket = self.zmqcontext.socket(zmq.REP)
        self.zmqsocket.bind("tcp://*:5556")
        #     while tx_enabled:
        #         recv = socket.recv()
        #         rx = pickle.loads(recv)


        print('Ui_MainWindow.__init__() complete')

    @Slot()
    def start_long_task(self):
        print('start_long_task() called...')
        self.statusbar.showMessage("Task running...")
        # self.button.setEnabled(False)
        self.thread.start()

    @Slot(int)
    def update_progress(self, value):
        print('update_progress(%s)' % value)
        self.statusbar.showMessage(f"Progress: {value}")

    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.resize(639, 480)
        self.centralwidget = QtWidgets.QWidget(parent=MainWindow)
        self.centralwidget.setObjectName("centralwidget")
        self.messageView = QtWidgets.QListView(parent=self.centralwidget)
        self.messageView.setGeometry(QtCore.QRect(10, 10, 501, 381))
        self.messageView.setObjectName("messageView")
        self.messageView.setWordWrap(True)
        self.messageView.setFixedWidth(500)
        
        self.userlistView = QtWidgets.QListView(parent=self.centralwidget)
        self.userlistView.setGeometry(QtCore.QRect(520, 10, 111, 381))
        self.userlistView.setObjectName("userlistView")
        self.userlistView.setWordWrap(False)

        self.messageTextEdit = QtWidgets.QLineEdit(parent=self.centralwidget)
        self.messageTextEdit.setGeometry(QtCore.QRect(10, 400, 461, 31))
        self.messageTextEdit.setObjectName("messageTextEdit")
        self.messageTextEdit.returnPressed.connect(self.rattlegram_send)
        self.message_input_filter = InputEventFilter()
        self.messageTextEdit.installEventFilter(self.message_input_filter)
        self.sendButton = QtWidgets.QPushButton(parent=self.centralwidget)
        self.sendButton.setGeometry(QtCore.QRect(480, 400, 151, 31))
        self.sendButton.setObjectName("sendButton")
        self.sendButton.clicked.connect(self.rattlegram_send)
        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QtWidgets.QMenuBar(parent=MainWindow)
        self.menubar.setGeometry(QtCore.QRect(0, 0, 639, 23))
        self.menubar.setObjectName("menubar")
        self.menuSettings = QtWidgets.QMenu(parent=self.menubar)
        self.menuSettings.setObjectName("menuSettings")
        self.menuHelp = QtWidgets.QMenu(parent=self.menubar)
        self.menuHelp.setObjectName("menuHelp")
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QtWidgets.QStatusBar(parent=MainWindow)
        self.statusbar.setObjectName("statusbar")
        MainWindow.setStatusBar(self.statusbar)
        self.actionAbout = QtGui.QAction(parent=MainWindow)
        self.actionAbout.setObjectName("actionAbout")
        self.actionAbout.triggered.connect(self.open_about_dialog)
        self.actionCallsign = QtGui.QAction(parent=MainWindow)
        self.actionCallsign.setObjectName("actionCallsign")
        self.actionCallsign.triggered.connect(self.open_callsign_dialog)
        self.actionCFO = QtGui.QAction(parent=MainWindow)
        self.actionCFO.setObjectName("actionCFO")
        self.actionCFO.triggered.connect(self.open_cfo_dialog)
        self.actionVOX = QtGui.QAction(parent=MainWindow)
        self.actionVOX.setObjectName("actionVOX")
        self.actionVOX.triggered.connect(self.open_vox_dialog)
        self.actionReceive = QtGui.QAction(parent=MainWindow)
        self.actionReceive.setObjectName("actionReceive")
        self.actionReceive.setCheckable(True)
        self.actionReceive.setEnabled(rx_script() is not None)
        self.actionReceive.toggled.connect(self.toggle_receive)
        self.menuSettings.addAction(self.actionCallsign)
        self.menuSettings.addAction(self.actionCFO)
        self.menuSettings.addAction(self.actionVOX)
        self.menuSettings.addAction(self.actionReceive)
        self.menuHelp.addAction(self.actionAbout)
        self.menubar.addAction(self.menuSettings.menuAction())
        self.menubar.addAction(self.menuHelp.menuAction())

        self.model = QStandardItemModel()
        self.model.setObjectName("messageViewItems")
        self.messageView.setModel(self.model)
        self.messageView.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        self.userlist_model = QStandardItemModel()
        self.userlist_model.setObjectName("userlistViewItems")
        self.userlistView.setModel(self.userlist_model)
        self.userlistView.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.seen_callsigns = set()

        # Receiving is opt-in: it holds the microphone open, so don't take it
        # without being asked. Toggled from Settings -> Receive.
        self.rx_process = None
        self.rx_buffer = b''

        self.retranslateUi(MainWindow)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

        self.thread = QThread()
        self.worker = Worker()
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.progress.connect(self.update_progress)

        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop_receiver)
        print('setupUi() complete')

    def retranslateUi(self, MainWindow):
        _translate = QtCore.QCoreApplication.translate
        MainWindow.setWindowTitle(_translate("MainWindow", "Rattlegram Desktop"))
        self.sendButton.setText(_translate("MainWindow", "Send"))
        self.menuSettings.setTitle(_translate("MainWindow", "Settings"))
        self.menuHelp.setTitle(_translate("MainWindow", "Help"))
        self.actionAbout.setText(_translate("MainWindow", "About"))
        self.actionCallsign.setText(_translate("MainWindow", "Callsign"))
        self.actionCFO.setText(_translate("MainWindow", "CFO"))
        self.actionVOX.setText(_translate("MainWindow", "VOX"))
        self.actionReceive.setText(_translate("MainWindow", "Receive"))

    def open_about_dialog(self):
        dialog = QtWidgets.QDialog()
        about_dialog = Ui_AboutDialog()
        about_dialog.setupUi(dialog)
        dialog.exec()

    def open_callsign_dialog(self):
        dialog = QtWidgets.QDialog()
        callsign_dialog = Ui_callsignDialog()
        callsign_dialog.setupUi(dialog)
        dialog.exec()

    def open_cfo_dialog(self):
        dialog = QtWidgets.QDialog()
        cfo_dialog = Ui_CFODialog()
        cfo_dialog.setupUi(dialog)
        dialog.exec()

    def open_vox_dialog(self):
        dialog = QtWidgets.QDialog()
        vox_dialog = Ui_VOXDialog()
        vox_dialog.setupUi(dialog)
        dialog.exec()

    def toggle_receive(self, enabled):
        if enabled:
            self.start_receiver()
        else:
            self.stop_receiver()

    def start_receiver(self):
        script = rx_script()
        if script is None or not os.access(script, os.X_OK):
            print('receive: no usable script (%s)' % script)
            self.statusbar.showMessage('Receive unavailable on this platform')
            self.actionReceive.setChecked(False)
            return
        self.rx_buffer = b''
        self.rx_process = QtCore.QProcess()
        self.rx_process.readyReadStandardOutput.connect(self.rx_ready_read)
        self.rx_process.start(script, [])
        print('receive: started %s' % script)
        self.statusbar.showMessage('Receiving...')

    def stop_receiver(self):
        if self.rx_process is None:
            return
        print('receive: stopping')
        self.rx_process.readyReadStandardOutput.disconnect()
        self.rx_process.terminate()
        if not self.rx_process.waitForFinished(2000):
            self.rx_process.kill()
        self.rx_process = None
        self.statusbar.showMessage('Receive stopped')

    def rx_ready_read(self):
        self.rx_buffer += bytes(self.rx_process.readAllStandardOutput())
        while b'\n' in self.rx_buffer:
            line, self.rx_buffer = self.rx_buffer.split(b'\n', 1)
            self.handle_rx_line(line.decode('utf-8', 'replace').strip())

    def handle_rx_line(self, line):
        if not line:
            return
        print('rx: %s' % line)
        m = RX_LINE.match(line)
        if not m:
            # progress chatter from the script, e.g. "listening in 8s windows"
            return
        callsign, message = m.group(1), m.group(2)
        t = datetime.utcnow()
        self.model.appendRow(QStandardItem(
            "%s <%s> %s" % (t.isoformat().split('.')[0], callsign, message)))
        self.messageView.scrollToBottom()
        if callsign and callsign not in self.seen_callsigns:
            self.seen_callsigns.add(callsign)
            self.userlist_model.appendRow(QStandardItem(callsign))

    def rattlegram_send(self):
        message = self.messageTextEdit.text()
        if len(message) > 0:
            if message[0] == '/':
                # interpret "IRC" command
                if message[1:5].lower() == 'help':
                    # help
                    messageViewItem = QStandardItem("Rattlegram Desktop\r\nCommands:\r\n\t/help\r\n\t/ping")
                    self.model.appendRow(messageViewItem)
                if message[1:5].lower() == 'ping':
                    # TODO
                    print('ping')
                    ping()
                self.messageTextEdit.setText('')
            else:
                t=datetime.utcnow()
                messageViewItem = QStandardItem("%s <%s> %s" % (t.isoformat().split('.')[0], self.config.get_value('callsign'), message))
                
                transmit(message)
                self.messageTextEdit.setText('')
                self.model.appendRow(messageViewItem)

REPO_DIR = os.path.dirname(os.path.abspath(__file__))

def tx_script():
    # Darwin has no arecord/aplay and no native build of the encode fork, so it
    # gets its own script. Everything else keeps the original Linux path.
    if platform.system() == 'Darwin':
        return os.path.join(REPO_DIR, 'bin', 'macos_tx.sh')
    return os.path.join(REPO_DIR, 'bin', 'rattlegram_tx.sh')

def rx_script():
    # Only Darwin has a receive script whose output this parser understands.
    # bin/rattlegram_rx.sh prints the raw decoder output in a different shape.
    if platform.system() == 'Darwin':
        return os.path.join(REPO_DIR, 'bin', 'macos_rx.sh')
    return None

# Lines emitted by bin/macos_rx.sh, e.g.
#   RX <ZL3TUX> [flips 0] HELLO WORLD
#   RX <ZL3TUX> [Es/N0 17.1 17.9] HELLO WORLD
RX_LINE = re.compile(r'^RX <([^>]*)> \[[^\]]*\] (.*)$')

def ptt_on():
    # PTT is optional: with no 'ptt' key configured we assume VOX, which the tx
    # script already covers by prepending a warm-up tone. Returns the open port
    # so ptt_off() can drop DTR, or None.
    config = RattlegramDesktopConfig()
    device = config.get_value('ptt')
    if not device:
        return None
    try:
        ser = serial.Serial(device, 19200)
        ser.dtr = True
        return ser
    except Exception as e:
        # A missing or busy port must not swallow the message.
        print('PTT unavailable on %s: %s' % (device, e))
        return None

def ptt_off(ser):
    if ser is None:
        return
    ser.dtr = False
    ser.close()

def transmit(message):
    if len(message) == 0: return True
    config = RattlegramDesktopConfig()
    callsign = config.get_value('callsign')
    cfo = config.get_value('CFO')
    print('%s\t%s\t%s' % (callsign, cfo, message))

    _env = os.environ
    _env['CALLSIGN'] = callsign
    _env['CFO'] = str(cfo)

    script = tx_script()
    if not os.access(script, os.X_OK):
        print('transmit: %s is missing or not executable' % script)
        return False

    ser = ptt_on()
    try:
        p0 = subprocess.run([script, message], env=_env, capture_output=True)
    finally:
        ptt_off(ser)

    if p0.returncode != 0:
        print(p0)
        return False

    return True

def ping():
    # TODO
    config = RattlegramDesktopConfig()
    callsign = config.get_value('callsign')
    cfo = config.get_value('CFO')
    _env = os.environ
    _env['CALLSIGN'] = callsign
    _env['CFO'] = str(cfo)
    script = os.path.join(REPO_DIR, 'bin', 'modem_ping.sh')
    if not os.access(script, os.X_OK):
        print('ping: %s is missing or not executable' % script)
        return False
    p0 = subprocess.run([script], env=_env, capture_output=True)
    if p0.returncode != 0:
        print(p0)
        return False

    return True

if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    MainWindow = QtWidgets.QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(MainWindow)
    MainWindow.show()
    sys.exit(app.exec())
