from __future__ import annotations

import copy
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QRunnable, QSettings, QSize, Qt, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractButton,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .ingest import SUPPORTED_FILES, InputGroup, analyze_inputs
from .models import ProjectRecord, ProvenanceCandidate
from .pdf import default_output_path, generate_pdf
from .sites import CachedWebClient, enrich_records
from .util import site_for_url, unique_strings


APP_STYLE = """
QWidget { background: #11151b; color: #e8edf4; font-family: "Segoe UI"; font-size: 10pt; }
QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget { background: #11151b; }
QToolBar { background: #171c24; border: 0; border-bottom: 1px solid #2a313d; padding: 7px; spacing: 6px; }
QToolButton { background: transparent; border: 0; border-radius: 6px; padding: 7px 10px; color: #dfe5ed; }
QToolButton:hover { background: #252c37; }
QFrame#Sidebar { background: #151a21; border-right: 1px solid #2b323d; }
QFrame#DropZone { background: #181e27; border: 2px dashed #3e4a59; border-radius: 12px; }
QFrame#DropZone[dragActive="true"] { border-color: #ff7043; background: #211d1c; }
QFrame#ImagePreview { background: #171d25; border: 1px solid #313a47; border-radius: 9px; }
QLabel#DropTitle { font-size: 15pt; font-weight: 650; }
QLabel#DropHint, QLabel#Subtle { color: #8f99a8; }
QLabel#Section { font-size: 10pt; font-weight: 700; color: #aeb8c5; text-transform: uppercase; }
QListWidget { background: #11161d; border: 1px solid #29313c; border-radius: 8px; padding: 4px; outline: none; }
QListWidget::item { padding: 11px 9px; border-radius: 6px; margin: 2px; }
QListWidget::item:selected { background: #313846; color: white; }
QListWidget::item:hover { background: #222a35; }
QTableWidget { background: #11161d; border: 1px solid #29313c; gridline-color: #29313c; }
QTableWidget::item { padding: 6px; }
QHeaderView::section { background: #202732; color: #dfe5ed; border: 0; border-right: 1px solid #343d49; padding: 8px; font-weight: 700; }
QLineEdit, QPlainTextEdit, QComboBox { background: #171d25; border: 1px solid #313a47; border-radius: 7px; padding: 8px; selection-background-color: #f06035; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border-color: #f06035; }
QComboBox::drop-down { border: 0; width: 28px; }
QPushButton { background: #252d38; border: 1px solid #37414f; border-radius: 7px; padding: 9px 14px; font-weight: 600; }
QPushButton:hover { background: #303946; }
QPushButton#Primary { background: #f06035; border-color: #f06035; color: white; }
QPushButton#Primary:hover { background: #ff7043; }
QPushButton:disabled { color: #6e7783; background: #1a2028; border-color: #282f39; }
QStatusBar { background: #171c24; color: #98a3b2; border-top: 1px solid #2a313d; }
QProgressBar { background: #171d25; border: 1px solid #313a47; border-radius: 5px; text-align: center; }
QProgressBar::chunk { background: #f06035; border-radius: 4px; }
QSplitter::handle { background: #2b323d; width: 1px; }
QToolTip { background: #252d38; color: white; border: 1px solid #3a4553; padding: 5px; }
"""


class DropZone(QFrame):
    inputs_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        for font_path in (
            Path("C:/Windows/Fonts/segoeui.ttf"),
            Path("C:/Windows/Fonts/seguisb.ttf"),
            Path("C:/Windows/Fonts/segoeuib.ttf"),
            Path("C:/Windows/Fonts/seguisym.ttf"),
            Path("C:/Windows/Fonts/seguiemj.ttf"),
        ):
            if font_path.exists():
                QFontDatabase.addApplicationFont(str(font_path))
        QApplication.instance().setFont(QFont("Segoe UI", 10))
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(154)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QLabel("⇩")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 29pt; color: #ff7043; background: transparent;")
        title = QLabel("Drop a project here")
        title.setObjectName("DropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("Files, folders, or model-page links")
        hint.setObjectName("DropHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(hint)

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        mime = event.mimeData()
        if mime.hasUrls() or (mime.hasText() and "http" in mime.text()):
            event.acceptProposedAction()
            self._set_drag_active(True)

    def dragLeaveEvent(self, event) -> None:  # type: ignore[override]
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        self._set_drag_active(False)
        mime = event.mimeData()
        values: list[str] = []
        for url in mime.urls():
            if url.isLocalFile():
                values.append(url.toLocalFile())
            elif url.scheme() in {"http", "https"}:
                values.append(url.toString())
        if not values and mime.hasText():
            values.extend(re.findall(r"https?://[^\s]+", mime.text()))
        if values:
            self.inputs_dropped.emit(unique_strings(values))
            event.acceptProposedAction()


class PdfThemeToggle(QAbstractButton):
    def __init__(self) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setFixedSize(48, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Switch between light and dark PDF output")
        self.setAccessibleName("Dark PDF theme")

    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = self.rect().adjusted(1, 2, -1, -2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#f06035" if self.isChecked() else "#46515f"))
        painter.drawRoundedRect(track, 11, 11)
        knob_size = 18
        knob_x = self.width() - knob_size - 4 if self.isChecked() else 4
        painter.setBrush(QColor("#f4f6f9"))
        painter.drawEllipse(knob_x, 4, knob_size, knob_size)
        painter.end()


class AutoGrowingPlainTextEdit(QPlainTextEdit):
    """A wrapped text editor whose height follows its document content."""

    def __init__(self, minimum_lines: int = 3, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._minimum_lines = max(1, minimum_lines)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().documentLayout().documentSizeChanged.connect(self._update_height)
        self.textChanged.connect(self._update_height)
        self._update_height()

    def _update_height(self, *_args) -> None:
        document = self.document()
        layout = document.documentLayout()
        document_height = 0.0
        block = document.firstBlock()
        while block.isValid():
            document_height += layout.blockBoundingRect(block).height()
            block = block.next()
        document_height += document.documentMargin() * 2
        margins = self.contentsMargins()
        chrome_height = margins.top() + margins.bottom() + (self.frameWidth() * 2) + 18
        minimum_height = (self.fontMetrics().lineSpacing() * self._minimum_lines) + chrome_height
        required_height = max(minimum_height, int(document_height + chrome_height + 0.999))
        if self.height() != required_height:
            self.setFixedHeight(required_height)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_height()


class FolderAssignmentDialog(QDialog):
    IGNORE_LABEL = "Do not include"

    def __init__(self, root: Path, files: list[Path], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.root = root
        self.files = files
        self.setWindowTitle("Assign folder contents to PDFs")
        self.resize(820, 560)

        layout = QVBoxLayout(self)
        instructions = QLabel(
            "Choose which PDF each file belongs to. Select an existing group, type a new PDF name, "
            "or choose Do not include. Files with the same group name become one project."
        )
        instructions.setWordWrap(True)
        instructions.setObjectName("Subtle")
        layout.addWidget(instructions)

        self.table = QTableWidget(len(files), 2)
        self.table.setHorizontalHeaderLabels(["Project part or file", "PDF group"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

        default_groups = unique_strings(self.suggested_group(root, file) for file in files)
        group_choices = [*default_groups, self.IGNORE_LABEL]
        self.group_editors: list[QComboBox] = []
        for row, file in enumerate(files):
            relative = file.relative_to(root)
            file_item = QTableWidgetItem(str(relative))
            file_item.setToolTip(str(file))
            file_item.setFlags(file_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, file_item)

            group_editor = QComboBox()
            group_editor.setEditable(True)
            group_editor.addItems(group_choices)
            group_editor.setCurrentText(self.suggested_group(root, file))
            group_editor.setMinimumWidth(240)
            self.table.setCellWidget(row, 1, group_editor)
            self.group_editors.append(group_editor)
        layout.addWidget(self.table, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import groups")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def suggested_group(root: Path, file: Path) -> str:
        relative_parent = file.relative_to(root).parent
        if relative_parent == Path("."):
            return root.name
        return " / ".join(relative_parent.parts)

    def input_groups(self) -> list[InputGroup]:
        grouped: dict[str, list[Path]] = {}
        for file, editor in zip(self.files, self.group_editors, strict=True):
            group_name = editor.currentText().strip()
            if not group_name or group_name == self.IGNORE_LABEL:
                continue
            grouped.setdefault(group_name, []).append(file)
        return [
            InputGroup(root=self.root, files=files, title=group_name)
            for group_name, files in grouped.items()
        ]


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class AnalysisWorker(QRunnable):
    def __init__(self, inputs: list[str | InputGroup], cache_dir: Path) -> None:
        super().__init__()
        self.inputs = inputs
        self.cache_dir = cache_dir
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            records = analyze_inputs(self.inputs)
            records = enrich_records(records, cache_dir=self.cache_dir, allow_search=True)
            self.signals.finished.emit(records)
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class SeedWorker(QRunnable):
    def __init__(self, index: int, record: ProjectRecord, seed_url: str, cache_dir: Path) -> None:
        super().__init__()
        self.index = index
        self.record = copy.deepcopy(record)
        self.seed_url = seed_url
        self.cache_dir = cache_dir
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            candidate = ProvenanceCandidate(
                url=self.seed_url,
                site=site_for_url(self.seed_url),
                confidence=1.0,
                evidence=["URL supplied manually as the project seed"],
                title=self.record.title,
            )
            self.record.candidates = [candidate, *[item for item in self.record.candidates if item.url != self.seed_url]]
            self.record.select_candidate(candidate)
            self.record.discovery_url = self.seed_url
            self.record.warnings = [
                warning
                for warning in self.record.warnings
                if "No embedded source URL" not in warning
                and "filename search is needed" not in warning
                and not warning.startswith("Could not read ")
            ]
            enriched = enrich_records([self.record], cache_dir=self.cache_dir, allow_search=False)[0]
            self.signals.finished.emit((self.index, enriched))
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Project2PDF")
        self.resize(1220, 790)
        self.setMinimumSize(940, 650)
        self.settings = QSettings("Project2PDF", "Project2PDF")
        saved_pdf_theme = str(self.settings.value("pdf_theme", "light")).casefold()
        self.pdf_theme = saved_pdf_theme if saved_pdf_theme in {"light", "dark"} else "light"
        self.records: list[ProjectRecord] = []
        self.current_index = -1
        self.thread_pool = QThreadPool.globalInstance()
        cache_value = self.settings.value("cache_dir", "")
        self.cache_dir = Path(str(cache_value)) if cache_value else Path.home() / ".cache" / "Project2PDF"
        self._build_ui()
        self._restore_state()

    def _build_ui(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        self.addToolBar(toolbar)

        add_files = QAction("Add files", self)
        add_files.triggered.connect(self.choose_files)
        toolbar.addAction(add_files)
        add_folder = QAction("Add folder", self)
        add_folder.triggered.connect(self.choose_folder)
        toolbar.addAction(add_folder)
        toolbar.addSeparator()
        self.reset_fields_action = QAction("Reset fields", self)
        self.reset_fields_action.setToolTip("Clear the selected project's fields without removing its files")
        self.reset_fields_action.setEnabled(False)
        self.reset_fields_action.triggered.connect(self.confirm_reset_current_fields)
        toolbar.addAction(self.reset_fields_action)
        clear = QAction("Clear list", self)
        clear.triggered.connect(self.clear_projects)
        toolbar.addAction(clear)
        toolbar.addSeparator()
        open_source = QAction("Open source", self)
        open_source.triggered.connect(self.open_current_source)
        toolbar.addAction(open_source)
        toolbar_spacer = QWidget()
        toolbar_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(toolbar_spacer)
        theme_widget = QWidget()
        theme_layout = QHBoxLayout(theme_widget)
        theme_layout.setContentsMargins(8, 0, 5, 0)
        theme_layout.setSpacing(7)
        theme_label = QLabel("PDF")
        theme_label.setObjectName("Subtle")
        self.light_theme_label = QLabel("☀")
        self.light_theme_label.setToolTip("Light PDF")
        self.light_theme_label.setStyleSheet("font-size: 14pt;")
        self.pdf_theme_toggle = PdfThemeToggle()
        self.pdf_theme_toggle.setChecked(self.pdf_theme == "dark")
        self.pdf_theme_toggle.toggled.connect(self.pdf_theme_changed)
        self.dark_theme_label = QLabel("☾")
        self.dark_theme_label.setToolTip("Dark PDF")
        self.dark_theme_label.setStyleSheet("font-size: 16pt;")
        theme_layout.addWidget(theme_label)
        theme_layout.addWidget(self.light_theme_label)
        theme_layout.addWidget(self.pdf_theme_toggle)
        theme_layout.addWidget(self.dark_theme_label)
        toolbar.addWidget(theme_widget)
        self._update_pdf_theme_labels()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setMinimumWidth(330)
        sidebar.setMaximumWidth(440)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 18, 18, 18)
        sidebar_layout.setSpacing(12)
        self.drop_zone = DropZone()
        self.drop_zone.inputs_dropped.connect(self.add_inputs)
        sidebar_layout.addWidget(self.drop_zone)
        section = QLabel("Projects")
        section.setObjectName("Section")
        sidebar_layout.addWidget(section)
        self.project_list = QListWidget()
        self.project_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.project_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.project_list.currentRowChanged.connect(self.select_project)
        self.project_list.customContextMenuRequested.connect(self.show_project_context_menu)
        sidebar_layout.addWidget(self.project_list, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        sidebar_layout.addWidget(self.progress)
        splitter.addWidget(sidebar)

        self.stack = QStackedWidget()
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(1, 1)

        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_title = QLabel("Build a durable record of every print")
        empty_title.setStyleSheet("font-size: 20pt; font-weight: 650;")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint = QLabel("Drop a project to discover its source, review its details, and create a linked PDF.")
        empty_hint.setObjectName("Subtle")
        empty_hint.setWordWrap(True)
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint.setMaximumWidth(520)
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_hint)
        self.stack.addWidget(empty)

        editor_container = QWidget()
        editor_outer = QVBoxLayout(editor_container)
        editor_outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(30, 26, 34, 30)
        editor_layout.setSpacing(14)

        header_row = QHBoxLayout()
        self.heading = QLabel("Project")
        self.heading.setStyleSheet("font-size: 22pt; font-weight: 700;")
        header_row.addWidget(self.heading, 1)
        self.confidence = QLabel("")
        self.confidence.setStyleSheet("padding: 6px 10px; border-radius: 10px; background: #252d38; color: #aeb8c5;")
        header_row.addWidget(self.confidence)
        editor_layout.addLayout(header_row)
        self.evidence = QLabel("")
        self.evidence.setObjectName("Subtle")
        self.evidence.setWordWrap(True)
        editor_layout.addWidget(self.evidence)

        self.image_preview_frame = QFrame()
        self.image_preview_frame.setObjectName("ImagePreview")
        image_preview_layout = QHBoxLayout(self.image_preview_frame)
        image_preview_layout.setContentsMargins(12, 12, 12, 12)
        self.image_preview = QLabel("No project image found")
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setMinimumSize(260, 150)
        self.image_preview.setMaximumHeight(210)
        self.image_preview.setStyleSheet("background: #0f1318; border-radius: 6px; color: #7f8996;")
        self.image_preview.setScaledContents(False)
        self.image_summary = QLabel("")
        self.image_summary.setObjectName("Subtle")
        self.image_summary.setWordWrap(True)
        self.image_summary.setMinimumWidth(180)
        image_preview_layout.addWidget(self.image_preview, 1)
        image_preview_layout.addWidget(self.image_summary)
        editor_layout.addWidget(self.image_preview_frame)

        source_section = QLabel("Source")
        source_section.setObjectName("Section")
        editor_layout.addWidget(source_section)
        source_form = QFormLayout()
        source_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.candidate_combo = QComboBox()
        self.candidate_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.candidate_combo.setMinimumContentsLength(24)
        self.candidate_combo.currentIndexChanged.connect(self.candidate_changed)
        self.source_url = QLineEdit()
        self.source_url.setPlaceholderText("Paste a model-page URL to seed this project")
        source_url_widget = QWidget()
        source_url_layout = QHBoxLayout(source_url_widget)
        source_url_layout.setContentsMargins(0, 0, 0, 0)
        source_url_layout.setSpacing(8)
        source_url_layout.addWidget(self.source_url, 1)
        self.fetch_url_button = QPushButton("Fetch from URL")
        self.fetch_url_button.setObjectName("Primary")
        self.fetch_url_button.setToolTip("Use this page as the source and merge its details into the project")
        self.fetch_url_button.clicked.connect(self.fetch_from_url)
        source_url_layout.addWidget(self.fetch_url_button)
        self.creator = QLineEdit()
        self.creator_url = QLineEdit()
        self.license_name = QLineEdit()
        self.license_url = QLineEdit()
        source_form.addRow("Detected source", self.candidate_combo)
        source_form.addRow("Original URL", source_url_widget)
        source_form.addRow("Creator", self.creator)
        source_form.addRow("Creator URL", self.creator_url)
        source_form.addRow("License", self.license_name)
        source_form.addRow("License URL", self.license_url)
        editor_layout.addLayout(source_form)

        details_section = QLabel("Project details")
        details_section.setObjectName("Section")
        editor_layout.addWidget(details_section)
        details_form = QFormLayout()
        details_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.title_edit = QLineEdit()
        self.description = AutoGrowingPlainTextEdit()
        self.instructions = AutoGrowingPlainTextEdit()
        self.tags = QLineEdit()
        details_form.addRow("Title", self.title_edit)
        details_form.addRow("Summary", self.description)
        details_form.addRow("Print instructions", self.instructions)
        details_form.addRow("Tags", self.tags)
        editor_layout.addLayout(details_form)

        files_section = QLabel("Files and warnings")
        files_section.setObjectName("Section")
        editor_layout.addWidget(files_section)
        self.file_summary = QLabel("")
        self.file_summary.setWordWrap(True)
        self.file_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        editor_layout.addWidget(self.file_summary)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.generate_all_button = QPushButton("Generate all PDFs")
        self.generate_all_button.clicked.connect(self.generate_all)
        self.generate_button = QPushButton("Generate this PDF")
        self.generate_button.setObjectName("Primary")
        self.generate_button.clicked.connect(self.generate_current)
        actions.addWidget(self.generate_all_button)
        actions.addWidget(self.generate_button)
        editor_layout.addLayout(actions)
        editor_layout.addStretch(1)
        scroll.setWidget(editor)
        editor_outer.addWidget(scroll)
        self.stack.addWidget(editor_container)

        status = QStatusBar()
        self.setStatusBar(status)
        status.showMessage("Ready")

    def _restore_state(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.settings.setValue("geometry", self.saveGeometry())
        super().closeEvent(event)

    @Slot(bool)
    def pdf_theme_changed(self, dark: bool) -> None:
        self.pdf_theme = "dark" if dark else "light"
        self.settings.setValue("pdf_theme", self.pdf_theme)
        self._update_pdf_theme_labels()
        self.statusBar().showMessage(f"PDF theme: {self.pdf_theme.title()}", 3000)

    def _update_pdf_theme_labels(self) -> None:
        active = "#ffb36b"
        inactive = "#737e8d"
        self.light_theme_label.setStyleSheet(
            f"font-size: 14pt; color: {inactive if self.pdf_theme == 'dark' else active};"
        )
        self.dark_theme_label.setStyleSheet(
            f"font-size: 16pt; color: {active if self.pdf_theme == 'dark' else inactive};"
        )

    @Slot()
    def choose_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Choose project files",
            str(Path.home()),
            "3D projects (*.3mf *.stl *.obj *.step *.stp *.pdf *.url *.jpg *.jpeg *.png *.webp);;All files (*)",
        )
        if files:
            self.add_inputs(files)

    @Slot()
    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose project folder", str(Path.home()))
        if folder:
            self.add_inputs([folder])

    @Slot(list)
    def add_inputs(self, inputs: list[str]) -> None:
        if not inputs:
            return
        prepared_inputs: list[str | InputGroup] = []
        for value in inputs:
            path = Path(value).expanduser()
            if path.is_dir():
                folder_inputs = self._prepare_folder_input(path.resolve())
                if folder_inputs is None:
                    continue
                prepared_inputs.extend(folder_inputs)
            else:
                prepared_inputs.append(value)
        if not prepared_inputs:
            return
        self.progress.setVisible(True)
        self.drop_zone.setEnabled(False)
        self.statusBar().showMessage(f"Analyzing {len(prepared_inputs)} project group(s)…")
        worker = AnalysisWorker(prepared_inputs, self.cache_dir)
        worker.signals.finished.connect(self.analysis_finished)
        worker.signals.failed.connect(self.analysis_failed)
        self.thread_pool.start(worker)

    def _prepare_folder_input(self, root: Path) -> list[str | InputGroup] | None:
        files = sorted(
            file
            for file in root.rglob("*")
            if file.is_file() and file.suffix.lower() in SUPPORTED_FILES
        )
        if not files:
            return [str(root)]
        candidate_areas = unique_strings(
            FolderAssignmentDialog.suggested_group(root, file) for file in files
        )
        if len(candidate_areas) < 2:
            return [str(root)]

        prompt = QMessageBox(self)
        prompt.setWindowTitle("Multiple project groups found")
        prompt.setIcon(QMessageBox.Icon.Question)
        prompt.setText(
            f"{root.name} contains {len(files)} supported files across "
            f"{len(candidate_areas)} folder areas."
        )
        prompt.setInformativeText(
            "Create one combined PDF project, or split the contents and choose which parts belong to each PDF?"
        )
        one_pdf = prompt.addButton("One PDF", QMessageBox.ButtonRole.AcceptRole)
        split_pdf = prompt.addButton("Split / assign…", QMessageBox.ButtonRole.ActionRole)
        prompt.addButton(QMessageBox.StandardButton.Cancel)
        prompt.setDefaultButton(one_pdf)
        prompt.exec()

        if prompt.clickedButton() == one_pdf:
            return [str(root)]
        if prompt.clickedButton() != split_pdf:
            return None

        assignment = FolderAssignmentDialog(root, files, self)
        if assignment.exec() != QDialog.DialogCode.Accepted:
            return None
        groups = assignment.input_groups()
        if not groups:
            QMessageBox.warning(self, "Nothing assigned", "Assign at least one file to a PDF group.")
            return None
        return groups

    @Slot(object)
    def analysis_finished(self, records: object) -> None:
        self.progress.setVisible(False)
        self.drop_zone.setEnabled(True)
        added = list(records) if isinstance(records, list) else []
        start_index = len(self.records)
        self.records.extend(added)
        for record in added:
            item = QListWidgetItem()
            item.setText(self._list_text(record))
            item.setToolTip("\n".join(record.evidence + record.warnings))
            self.project_list.addItem(item)
        if added:
            self.project_list.setCurrentRow(start_index)
        self.statusBar().showMessage(f"Added {len(added)} project(s)", 5000)

    @Slot(str)
    def analysis_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self.drop_zone.setEnabled(True)
        QMessageBox.critical(self, "Analysis failed", message)
        self.statusBar().showMessage("Analysis failed", 5000)

    def _list_text(self, record: ProjectRecord) -> str:
        site = record.site or "Source not found"
        marker = "●" if record.confidence >= 0.9 else "◐" if record.confidence >= 0.65 else "○"
        return f"{marker}  {record.display_name}\n     {site}"

    @Slot(int)
    def select_project(self, index: int) -> None:
        if self.current_index >= 0:
            self.commit_editor()
        self.current_index = index
        self.reset_fields_action.setEnabled(0 <= index < len(self.records))
        if index < 0 or index >= len(self.records):
            self.stack.setCurrentIndex(0)
            return
        self.stack.setCurrentIndex(1)
        self.load_editor(self.records[index])

    def load_editor(self, record: ProjectRecord) -> None:
        self.heading.setText(record.display_name)
        label = "High confidence" if record.confidence >= 0.9 else "Medium confidence" if record.confidence >= 0.65 else "Needs review"
        color = "#5fc78b" if record.confidence >= 0.9 else "#f3b95f" if record.confidence >= 0.65 else "#ff7979"
        self.confidence.setText(label)
        self.confidence.setStyleSheet(f"padding: 6px 10px; border-radius: 10px; background: #252d38; color: {color};")
        self.evidence.setText(" • ".join(record.evidence) or "No source evidence yet")
        self.candidate_combo.blockSignals(True)
        self.candidate_combo.clear()
        if record.candidates:
            for candidate in record.candidates:
                self.candidate_combo.addItem(
                    f"{candidate.site} — {candidate.confidence_label} — {candidate.url}", candidate
                )
            selected = next((i for i, item in enumerate(record.candidates) if item.url == record.source_url), 0)
            self.candidate_combo.setCurrentIndex(selected)
        else:
            self.candidate_combo.addItem("No candidate found")
        self.candidate_combo.blockSignals(False)
        self.source_url.setText(record.source_url)
        self.creator.setText(record.creator)
        self.creator_url.setText(record.creator_url)
        self.license_name.setText(record.license_name)
        self.license_url.setText(record.license_url)
        self.title_edit.setText(record.title)
        self.description.setPlainText(record.description)
        self.instructions.setPlainText(record.print_instructions)
        self.tags.setText(", ".join(record.tags))
        file_lines = [f"• {path.name}" for path in record.source_files]
        if record.dimensions_mm:
            file_lines.append("\nGeometry: " + " × ".join(f"{value:g}" for value in record.dimensions_mm) + " mm")
        if record.warnings:
            file_lines.append("\nWarnings:\n" + "\n".join(f"• {warning}" for warning in record.warnings))
        self.file_summary.setText("\n".join(file_lines) or "No local files (URL project)")
        self._load_image_preview(record)

    def _load_image_preview(self, record: ProjectRecord) -> None:
        local_sources = [
            Path(source)
            for source in record.images
            if not source.startswith(("http://", "https://", "3mf://")) and Path(source).is_file()
        ]
        web_count = sum(source.startswith(("http://", "https://")) for source in record.images)
        pixmap = QPixmap()
        preview_source = ""
        if local_sources:
            pixmap = QPixmap(str(local_sources[0]))
            preview_source = f"Local image: {local_sources[0].name}"
        elif record.embedded_images:
            pixmap.loadFromData(record.embedded_images[0])
            preview_source = "Embedded 3MF preview"
        if pixmap.isNull():
            self.image_preview.clear()
            self.image_preview.setText("Web images will appear after enrichment" if web_count else "No project image found")
        else:
            self.image_preview.setText("")
            self.image_preview.setPixmap(
                pixmap.scaled(
                    620,
                    200,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        counts = [
            f"{len(local_sources)} local",
            f"{len(record.embedded_images)} embedded",
            f"{web_count} web",
        ]
        self.image_summary.setText(
            f"{preview_source or 'Project images'}\n\n"
            + " • ".join(counts)
            + "\n\nLocal images are prioritized in the generated PDF."
        )

    def commit_editor(self) -> None:
        if self.current_index < 0 or self.current_index >= len(self.records):
            return
        record = self.records[self.current_index]
        record.source_url = self.source_url.text().strip()
        record.site = record.site or (urlparse(record.source_url).hostname or "")
        record.creator = self.creator.text().strip()
        record.creator_url = self.creator_url.text().strip()
        record.license_name = self.license_name.text().strip()
        record.license_url = self.license_url.text().strip()
        record.title = self.title_edit.text().strip()
        record.description = self.description.toPlainText().strip()
        record.print_instructions = self.instructions.toPlainText().strip()
        record.tags = unique_strings(self.tags.text().split(","))
        self.heading.setText(record.display_name)
        item = self.project_list.item(self.current_index)
        if item:
            item.setText(self._list_text(record))

    @Slot(int)
    def candidate_changed(self, index: int) -> None:
        if self.current_index < 0 or index < 0:
            return
        candidate = self.candidate_combo.itemData(index)
        if candidate is None:
            return
        record = self.records[self.current_index]
        record.select_candidate(candidate)
        self.source_url.setText(candidate.url)
        self.evidence.setText(" • ".join(candidate.evidence))

    @Slot()
    def fetch_from_url(self) -> None:
        if self.current_index < 0:
            return
        seed_url = self.source_url.text().strip()
        parsed = urlparse(seed_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            QMessageBox.warning(self, "Invalid URL", "Enter a complete http:// or https:// model-page URL.")
            return
        self.commit_editor()
        self.fetch_url_button.setEnabled(False)
        self.progress.setVisible(True)
        self.statusBar().showMessage(f"Fetching project details from {parsed.netloc}…")
        worker = SeedWorker(self.current_index, self.records[self.current_index], seed_url, self.cache_dir)
        worker.signals.finished.connect(self.seed_finished)
        worker.signals.failed.connect(self.seed_failed)
        self.thread_pool.start(worker)

    @Slot(object)
    def seed_finished(self, result: object) -> None:
        self.fetch_url_button.setEnabled(True)
        self.progress.setVisible(False)
        index, record = result
        if 0 <= index < len(self.records):
            self.records[index] = record
            item = self.project_list.item(index)
            if item:
                item.setText(self._list_text(record))
                item.setToolTip("\n".join(record.evidence + record.warnings))
            if index == self.current_index:
                self.load_editor(record)
        self.statusBar().showMessage("Project details fetched from the supplied URL", 6000)

    @Slot(str)
    def seed_failed(self, message: str) -> None:
        self.fetch_url_button.setEnabled(True)
        self.progress.setVisible(False)
        QMessageBox.critical(self, "Could not fetch URL", message)
        self.statusBar().showMessage("URL enrichment failed", 5000)

    @Slot()
    def clear_projects(self) -> None:
        self.records.clear()
        self.current_index = -1
        self.project_list.clear()
        self.reset_fields_action.setEnabled(False)
        self.stack.setCurrentIndex(0)
        self.statusBar().showMessage("Cleared")

    @Slot()
    def confirm_reset_current_fields(self) -> None:
        if self.current_index < 0 or self.current_index >= len(self.records):
            return
        project_name = self.records[self.current_index].display_name
        answer = QMessageBox.question(
            self,
            "Reset project fields?",
            f'Clear the editable information for "{project_name}"?\n\n'
            "Imported files, model details, images, and warnings will be kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.reset_current_fields()

    def reset_current_fields(self) -> None:
        if self.current_index < 0 or self.current_index >= len(self.records):
            return
        record = self.records[self.current_index]
        record.source_url = ""
        record.discovery_url = ""
        record.site = ""
        record.confidence = 0.0
        record.evidence.clear()
        record.creator = ""
        record.creator_url = ""
        record.license_name = ""
        record.license_url = ""
        record.title = ""
        record.description = ""
        record.print_instructions = ""
        record.published = ""
        record.updated = ""
        record.category = ""
        record.tags.clear()
        record.candidates.clear()

        item = self.project_list.item(self.current_index)
        if item:
            item.setText(self._list_text(record))
        self.load_editor(record)
        self.statusBar().showMessage("Reset fields; imported files were kept", 5000)

    @Slot(object)
    def show_project_context_menu(self, position: object) -> None:
        item = self.project_list.itemAt(position)
        if item is None:
            return
        row = self.project_list.row(item)
        menu = QMenu(self.project_list)
        delete_action = menu.addAction("Delete")
        selected = menu.exec(self.project_list.viewport().mapToGlobal(position))
        if selected == delete_action:
            self.remove_project(row)

    def remove_project(self, row: int) -> None:
        if row < 0 or row >= len(self.records):
            return
        if self.current_index >= 0 and self.current_index != row:
            self.commit_editor()

        removed_name = self.records[row].display_name
        self.project_list.blockSignals(True)
        self.project_list.takeItem(row)
        self.records.pop(row)
        self.project_list.blockSignals(False)

        if not self.records:
            self.current_index = -1
            self.reset_fields_action.setEnabled(False)
            self.stack.setCurrentIndex(0)
        else:
            next_row = min(row, len(self.records) - 1)
            self.current_index = -1
            self.project_list.setCurrentRow(next_row)
        self.statusBar().showMessage(f"Deleted {removed_name}", 4000)

    @Slot()
    def open_current_source(self) -> None:
        if self.current_index < 0:
            return
        self.commit_editor()
        url = self.records[self.current_index].source_url
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _choose_output_directory(self) -> Path | None:
        start = str(self.settings.value("output_dir", str(Path.home() / "Documents")))
        selected = QFileDialog.getExistingDirectory(self, "Choose PDF output folder", start)
        if not selected:
            return None
        self.settings.setValue("output_dir", selected)
        return Path(selected)

    @Slot()
    def generate_current(self) -> None:
        if self.current_index < 0:
            return
        self.commit_editor()
        directory = self._choose_output_directory()
        if directory:
            self._generate([self.records[self.current_index]], directory)

    @Slot()
    def generate_all(self) -> None:
        if not self.records:
            return
        self.commit_editor()
        directory = self._choose_output_directory()
        if directory:
            self._generate(self.records, directory)

    def _generate(self, records: list[ProjectRecord], directory: Path) -> None:
        self.generate_button.setEnabled(False)
        self.generate_all_button.setEnabled(False)
        web = CachedWebClient(cache_dir=self.cache_dir)
        outputs: list[Path] = []
        try:
            for record in records:
                self.statusBar().showMessage(f"Generating {record.display_name}…")
                QApplication.processEvents()
                output = default_output_path(record, directory)
                if output.exists():
                    counter = 2
                    while output.with_stem(f"{output.stem} ({counter})").exists():
                        counter += 1
                    output = output.with_stem(f"{output.stem} ({counter})")
                outputs.append(generate_pdf(record, output, web=web, theme=self.pdf_theme))
        except Exception as exc:
            QMessageBox.critical(self, "PDF generation failed", str(exc))
        finally:
            web.close()
            self.generate_button.setEnabled(True)
            self.generate_all_button.setEnabled(True)
        if outputs:
            self.statusBar().showMessage(f"Generated {len(outputs)} PDF(s)", 7000)
            message = "Created:\n\n" + "\n".join(str(path) for path in outputs)
            QMessageBox.information(self, "PDFs created", message)


def _application_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#f06035"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 13, 13)
    painter.setPen(QColor("white"))
    font = painter.font()
    font.setBold(True)
    font.setPointSize(18)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "P²")
    painter.end()
    return QIcon(pixmap)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Project2PDF")
    app.setOrganizationName("Project2PDF")
    app.setWindowIcon(_application_icon())
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
