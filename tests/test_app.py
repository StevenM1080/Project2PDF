from __future__ import annotations

import os

from PySide6.QtCore import Qt

from project2pdf.app import AutoGrowingPlainTextEdit, FolderAssignmentDialog, MainWindow
from project2pdf.models import ProjectRecord


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_source_actions_are_grouped_with_url_controls(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.fetch_url_button.text() == "Fetch"
    assert window.open_source_button.text() == "Source"
    assert window.fetch_url_button.objectName() == "Primary"
    assert window.open_source_button.objectName() == "Primary"
    assert window.fetch_url_button.parentWidget() is window.open_source_button.parentWidget()


def test_multiline_editor_grows_without_internal_scrollbars(qtbot) -> None:
    editor = AutoGrowingPlainTextEdit(minimum_lines=2)
    editor.resize(360, editor.height())
    qtbot.addWidget(editor)
    editor.show()
    initial_height = editor.height()

    editor.setPlainText("\n".join(f"A complete line of project details {number}" for number in range(12)))

    qtbot.waitUntil(lambda: editor.height() > initial_height)
    assert editor.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert editor.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert editor.verticalScrollBar().maximum() == 0


def test_reset_fields_keeps_imported_project_assets(qtbot, tmp_path) -> None:
    model_file = tmp_path / "part.stl"
    record = ProjectRecord(
        input_root=tmp_path,
        source_files=[model_file],
        title="Edited title",
        creator="Creator",
        creator_url="https://example.com/creator",
        source_url="https://example.com/model",
        discovery_url="https://example.com/search",
        site="Example",
        confidence=0.9,
        evidence=["Found in metadata"],
        description="Description",
        print_instructions="Print slowly",
        license_name="CC BY",
        license_url="https://example.com/license",
        published="2025",
        updated="2026",
        category="Tools",
        tags=["useful"],
        model_files=["part.stl"],
        dimensions_mm=(10.0, 20.0, 30.0),
        print_settings={"layer_height": "0.2"},
        images=[str(tmp_path / "photo.png")],
        embedded_images=[b"preview"],
        candidates=[],
        warnings=["Keep this warning"],
        raw_metadata={"keep": True},
    )
    window = MainWindow()
    qtbot.addWidget(window)
    window.analysis_finished([record])

    window.reset_current_fields()

    assert record.title == ""
    assert record.source_url == ""
    assert record.creator == ""
    assert record.description == ""
    assert record.tags == []
    assert record.source_files == [model_file]
    assert record.model_files == ["part.stl"]
    assert record.dimensions_mm == (10.0, 20.0, 30.0)
    assert record.print_settings == {"layer_height": "0.2"}
    assert record.images == [str(tmp_path / "photo.png")]
    assert record.embedded_images == [b"preview"]
    assert record.warnings == ["Keep this warning"]
    assert record.raw_metadata == {"keep": True}
    assert "part.stl" in window.file_summary.text()


def test_remove_project_deletes_only_requested_item_and_selects_next(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.analysis_finished(
        [
            ProjectRecord(title="First"),
            ProjectRecord(title="Second"),
            ProjectRecord(title="Third"),
        ]
    )

    window.project_list.setCurrentRow(1)
    window.remove_project(1)

    assert [record.title for record in window.records] == ["First", "Third"]
    assert window.project_list.count() == 2
    assert window.project_list.currentRow() == 1
    assert window.records[window.current_index].title == "Third"

    window.remove_project(1)
    window.remove_project(0)
    assert window.records == []
    assert window.project_list.count() == 0
    assert window.current_index == -1
    assert window.stack.currentIndex() == 0


def test_folder_assignment_can_merge_reassign_and_ignore_files(qtbot, tmp_path) -> None:
    first_folder = tmp_path / "Body"
    second_folder = tmp_path / "Accessories"
    first_folder.mkdir()
    second_folder.mkdir()
    first = first_folder / "body.stl"
    second = second_folder / "stand.stl"
    first.write_bytes(b"model")
    second.write_bytes(b"model")

    dialog = FolderAssignmentDialog(tmp_path, [first, second])
    qtbot.addWidget(dialog)
    assert [editor.currentText() for editor in dialog.group_editors] == ["Body", "Accessories"]
    dialog.group_editors[0].setCurrentText("Complete kit")
    dialog.group_editors[1].setCurrentText("Complete kit")
    groups = dialog.input_groups()
    assert len(groups) == 1
    assert groups[0].title == "Complete kit"
    assert groups[0].files == [first, second]

    dialog.group_editors[1].setCurrentText(FolderAssignmentDialog.IGNORE_LABEL)
    groups = dialog.input_groups()
    assert groups[0].files == [first]
