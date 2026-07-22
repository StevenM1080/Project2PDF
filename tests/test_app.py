from __future__ import annotations

import os

from project2pdf.app import MainWindow
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
