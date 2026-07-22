from __future__ import annotations

from project2pdf.ingest import InputGroup, analyze_inputs


def test_explicit_input_groups_create_separate_project_records(tmp_path) -> None:
    body_folder = tmp_path / "Body"
    accessory_folder = tmp_path / "Accessories"
    body_folder.mkdir()
    accessory_folder.mkdir()
    body = body_folder / "body.stl"
    stand = accessory_folder / "stand.stl"
    empty_binary_stl = b"\0" * 80 + (0).to_bytes(4, "little")
    body.write_bytes(empty_binary_stl)
    stand.write_bytes(empty_binary_stl)

    records = analyze_inputs(
        [
            InputGroup(root=tmp_path, files=[body], title="Main telescope"),
            InputGroup(root=tmp_path, files=[stand], title="Display stand"),
        ]
    )

    assert [record.title for record in records] == ["Main telescope", "Display stand"]
    assert records[0].model_files == ["body.stl"]
    assert records[1].model_files == ["stand.stl"]
