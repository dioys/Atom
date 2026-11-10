"""callpanel.py - Step 13: the two windows of the call helper.

    CallPanel      shown during a call: what Atom hears, what to say, and what you were asked to do
    ProfileDialog  your skills and the files that describe you (from any folder)

Only drawing and clicking live here. The thinking is in callmode.py, the listening in loopback.py,
the screen reading in screenreader.py and the memory of your skills in userprofile.py.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import config
from tools import ABOUT_ME_FOLDER

_SOURCE_NAMES = {
    "quick": "quick line",
    "profile": "from your profile",
    "ai": "written by the AI from your profile",
    "stall": "a polite line to buy you a moment",
    "screen": "read from the problem you picked on the screen",
}


def source_label(source: str, grounded: bool = True) -> str:
    """A short note under the suggested answer: where it came from, and a warning when it is a guess."""
    text = _SOURCE_NAMES.get(source, source or "")
    if not grounded and source != "stall":
        text += "  -  NOT in your profile, check it before you say it"
    return text


class CallPanel(QDialog):
    """A small window you keep beside the call. It never speaks and nobody else sees it."""

    # the controller calls its callbacks from other threads; signals bring them safely to the window
    line_heard = Signal(str, str)
    task_found = Signal(str)
    answer_ready = Signal(str, str, str, bool, bool)    # question, text, source, grounded, final
    status_changed = Signal(str)
    problem = Signal(str)
    summary_ready = Signal(str)

    start_requested = Signal()
    stop_requested = Signal()
    screen_requested = Signal()
    question_typed = Signal(str)
    auto_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Atom - Call helper")
        self.resize(460, 640)
        self._running = False
        self._problem = ""
        self._ticking = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(6)

        top = QHBoxLayout()
        self.start_btn = QPushButton("Start listening")
        self.start_btn.clicked.connect(self._start_or_stop)
        self.screen_btn = QPushButton("Pick a problem on screen")
        self.screen_btn.setToolTip("Drag a box around ONE problem on your screen. Atom reads only that and answers it.")
        self.screen_btn.clicked.connect(self.screen_requested)
        top.addWidget(self.start_btn)
        top.addWidget(self.screen_btn)
        top.addStretch(1)
        layout.addLayout(top)

        self.status = QLabel("Not listening.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        title = QLabel("Say this")
        title.setObjectName("title")
        layout.addWidget(title)
        self.asked = QLabel("")
        self.asked.setObjectName("muted")
        self.asked.setWordWrap(True)
        layout.addWidget(self.asked)
        self.answer = QPlainTextEdit()
        self.answer.setReadOnly(True)
        self.answer.setPlaceholderText("When the other person asks you something, my suggested answer appears here.")
        self.answer.setMinimumHeight(110)
        self.answer.setStyleSheet("font-size: 15px;")
        layout.addWidget(self.answer, 2)
        self.source = QLabel("")
        self.source.setObjectName("muted")
        self.source.setWordWrap(True)
        layout.addWidget(self.source)

        ask_row = QHBoxLayout()
        self.typed = QLineEdit()
        self.typed.setPlaceholderText("Or type what they asked and press Enter...")
        self.typed.returnPressed.connect(self._ask_typed)
        copy = QPushButton("Copy answer")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.answer.toPlainText()))
        ask_row.addWidget(self.typed, 1)
        ask_row.addWidget(copy)
        layout.addLayout(ask_row)
        self.auto = QCheckBox("Answer questions by myself")
        self.auto.setChecked(bool(config.CALL_AUTO_ANSWER))
        self.auto.toggled.connect(self.auto_changed)
        layout.addWidget(self.auto)

        title2 = QLabel("What you were asked to do")
        title2.setObjectName("title")
        layout.addWidget(title2)
        self.tasks = QListWidget()
        self.tasks.setMaximumHeight(110)
        self.tasks.itemChanged.connect(self._task_ticked)
        layout.addWidget(self.tasks, 1)

        title3 = QLabel("What I heard")
        title3.setObjectName("title")
        layout.addWidget(title3)
        self.heard = QPlainTextEdit()
        self.heard.setReadOnly(True)
        self.heard.setMaximumBlockCount(400)
        layout.addWidget(self.heard, 2)

        self.note = QLabel("")
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

        self.line_heard.connect(self._on_line)
        self.task_found.connect(self._on_task)
        self.answer_ready.connect(self._on_answer)
        self.status_changed.connect(self._set_status)
        self.problem.connect(self._on_problem)
        self.summary_ready.connect(self._on_summary)

    # ------------------------------------------------------------ connect to a controller
    def attach(self, controller) -> None:
        """Route a CallController's reports to this window (works from any thread)."""
        controller.on_line = lambda speaker, text: self.line_heard.emit(speaker, text)
        controller.on_task = lambda task: self.task_found.emit(task)
        controller.on_answer = lambda question, answer, final: self.answer_ready.emit(
            question, answer.text, answer.source, bool(answer.grounded), bool(final))
        controller.on_status = lambda text: self.status_changed.emit(text)
        controller.on_error = lambda text: self.problem.emit(text)
        controller.on_summary = lambda text: self.summary_ready.emit(text)

    # ------------------------------------------------------------ state
    def set_running(self, running: bool) -> None:
        self._running = running
        self.start_btn.setText("Stop and summarise" if running else "Start listening")
        if not running:
            self.status.setText("Not listening.")

    def begin_call(self) -> None:
        """A new call: clear the screen."""
        self.heard.clear()
        self.tasks.clear()
        self._problem = ""
        self.answer.clear()
        self.asked.setText("")
        self.source.setText("")
        self.note.setText("")

    def _start_or_stop(self) -> None:
        (self.stop_requested if self._running else self.start_requested).emit()

    def _ask_typed(self) -> None:
        text = self.typed.text().strip()
        if text:
            self.typed.clear()
            self.question_typed.emit(text)

    # ------------------------------------------------------------ reports (always on the window's thread)
    def _on_line(self, speaker: str, text: str) -> None:
        self.heard.appendPlainText(("THEM: " if speaker == "them" else "ME:   ") + text)

    def _on_task(self, task: str) -> None:
        item = QListWidgetItem(task)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Unchecked)
        self.tasks.addItem(item)

    def _on_answer(self, question: str, text: str, source: str, grounded: bool, final: bool) -> None:
        self.asked.setText("You pointed at the problem on your screen:" if source == "screen" else "They asked: " + question)
        self.answer.setPlainText(text)
        label = source_label(source, grounded)
        self.source.setText(label if final else label + "  (a better answer is being written...)")

    def _set_status(self, text: str) -> None:
        self.status.setText(text)

    def _on_problem(self, text: str) -> None:
        self._problem = text
        self.note.setText(text)

    def _on_summary(self, text: str) -> None:
        self.status.setText("The call is finished and saved.")
        self.note.setText((self._problem + "\n\n" if self._problem else "") + "Summary:\n" + text)

    def _task_ticked(self, item: QListWidgetItem) -> None:
        # ticking only changes how the line looks here; the call log keeps the task either way
        if self._ticking:
            return
        self._ticking = True                    # setFont fires itemChanged again
        try:
            font = item.font()
            font.setStrikeOut(item.checkState() == Qt.CheckState.Checked)
            item.setFont(font)
        finally:
            self._ticking = False


class ProfileDialog(QDialog):
    """Your skills and the files about you. Atom answers questions about you from this and nothing else."""

    finished_job = Signal(str)
    changed = Signal()          # the list of profile files changed (the Files window should refresh)

    def __init__(self, parent: QWidget | None, profile):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle("Atom - My skills and files")
        self.resize(480, 600)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(6)

        title = QLabel("My skills and experience")
        title.setObjectName("title")
        layout.addWidget(title)
        self.facts = QListWidget()
        layout.addWidget(self.facts, 3)
        add_row = QHBoxLayout()
        self.kind = QComboBox()
        for kind in ("skill", "experience", "project", "education", "strength", "about"):
            self.kind.addItem(kind, kind)
        self.new_fact = QLineEdit()
        self.new_fact.setPlaceholderText("For example: Power BI, DAX, 3 years in data analysis...")
        self.new_fact.returnPressed.connect(self._add_fact)
        add = QPushButton("Add")
        add.clicked.connect(self._add_fact)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove_fact)
        add_row.addWidget(self.kind)
        add_row.addWidget(self.new_fact, 1)
        add_row.addWidget(add)
        add_row.addWidget(remove)
        layout.addLayout(add_row)

        layout.addSpacing(6)
        title2 = QLabel("Files about me (the \"About me\" folder of your Files window)")
        title2.setObjectName("title")
        layout.addWidget(title2)
        hint = QLabel("A CV, a certificate list, a project report... Atom keeps them where they are, reads them, "
                      "and uses them to answer questions about you.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.files = QListWidget()
        layout.addWidget(self.files, 2)
        file_row = QHBoxLayout()
        add_file = QPushButton("Add a file...")
        add_file.clicked.connect(self._add_file)
        add_folder = QPushButton("Add a folder...")
        add_folder.clicked.connect(self._add_folder)
        unpin = QPushButton("Remove file")
        unpin.clicked.connect(self._remove_file)
        learn = QPushButton("Learn from my files")
        learn.setToolTip("Atom reads these files and turns what they say into the short list above")
        learn.clicked.connect(self._learn)
        for button in (add_file, add_folder, unpin, learn):
            file_row.addWidget(button)
        file_row.addStretch(1)
        layout.addLayout(file_row)

        self.message = QLabel("")
        self.message.setObjectName("muted")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        close_row.addWidget(close)
        layout.addLayout(close_row)

        self.finished_job.connect(self._job_done)
        self.refresh()

    # ------------------------------------------------------------ list
    def refresh(self) -> None:
        self.facts.clear()
        for item in self.profile.items():
            row = QListWidgetItem(f"{item.kind}:  {item.text}")
            row.setData(Qt.ItemDataRole.UserRole, item.id)
            self.facts.addItem(row)
        self.files.clear()
        for record in self.profile.pinned():
            row = QListWidgetItem(record.name)
            row.setToolTip(record.path)
            row.setData(Qt.ItemDataRole.UserRole, record.name)
            self.files.addItem(row)

    def _say(self, text: str) -> None:
        self.message.setText(text)

    # ------------------------------------------------------------ facts
    def _add_fact(self) -> None:
        text = self.new_fact.text().strip()
        if not text:
            return
        try:
            # one box can hold several: "Python, SQL, Power BI"
            added = self.profile.add_many(text, self.kind.currentData())
        except ValueError as problem:
            self._say(str(problem))
            return
        self.new_fact.clear()
        self._say(f"Added {len(added)}." if added else "I already had that.")
        self.refresh()

    def _remove_fact(self) -> None:
        row = self.facts.currentItem()
        if row is None:
            self._say("Click one in the list first.")
            return
        self.profile.remove(f"#{int(row.data(Qt.ItemDataRole.UserRole))}")
        self._say("Removed.")
        self.refresh()

    # ------------------------------------------------------------ files
    def _background(self, work, working: str) -> None:
        """Do slow work (reading a file, asking the AI) off the window's thread."""
        self._say(working)

        def run() -> None:
            try:
                message = work()
            except Exception as error:
                message = f"That did not work: {error}"
            self.finished_job.emit(str(message))

        threading.Thread(target=run, daemon=True).start()

    def _job_done(self, message: str) -> None:
        self._say(message)
        self.refresh()
        self.changed.emit()

    def _add_file(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose the files about you", "",
                                                "Documents (*.pdf *.docx *.doc *.txt *.md *.xlsx *.csv *.pptx);;All files (*)")
        if not paths:
            return

        def work() -> str:
            done, problems = 0, []
            for path in paths:
                ok, message = self.profile.pin(path)
                if ok:
                    done += 1
                else:
                    problems.append(message)
            return (f"Added {done} file(s) to your profile." if done else "Nothing was added.") + \
                   ((" " + " ".join(problems[:2])) if problems else "")

        self._background(work, "Reading the file(s)...")

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder about you")
        if not folder:
            return

        def work() -> str:
            added, problems = self.profile.store.add([folder], folder=ABOUT_ME_FOLDER)
            return f"Added {len(added)} file(s) from that folder." + ((" " + problems[0]) if problems and not added else "")

        self._background(work, "Reading the folder...")

    def _remove_file(self) -> None:
        row = self.files.currentItem()
        if row is None:
            self._say("Click a file in the list first.")
            return
        ok, message = self.profile.unpin(str(row.data(Qt.ItemDataRole.UserRole)))
        self._say(message)
        self.refresh()

    def _learn(self) -> None:
        if not self.profile.pinned():
            self._say("Add a file first.")
            return

        def work() -> str:
            count = self.profile.learn_from_files()
            return f"I found {count} new thing(s) in your files and added them to the list." if count else \
                   "I read your files but found nothing new to add."

        self._background(work, "Reading your files with the AI... (this sends their text to Groq)")
