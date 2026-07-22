from __future__ import annotations

import os

from project2pdf.app import FolderAssignmentDialog, MainWindow
from project2pdf.models import ProjectRecord


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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
