from pathlib import Path

from admin.staging import StagingArea


def test_staging_accumulates_approved_workspaces(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "index.html").write_text("background: white", encoding="utf-8")

    staging = StagingArea(source, tmp_path / "staging")
    initial = staging.initialize()
    assert (initial.directory / "index.html").read_text(encoding="utf-8") == "background: white"

    first_workspace = tmp_path / "first-workspace"
    first_workspace.mkdir()
    (first_workspace / "index.html").write_text("background: blue", encoding="utf-8")
    first = staging.apply_workspace(first_workspace)

    second_workspace = tmp_path / "second-workspace"
    second_workspace.mkdir()
    for path in first.directory.iterdir():
        if path.is_file():
            (second_workspace / path.name).write_bytes(path.read_bytes())
    (second_workspace / "index.html").write_text("background: blue; color: white", encoding="utf-8")
    second = staging.apply_workspace(second_workspace)

    assert initial.revision_id != first.revision_id != second.revision_id
    assert (staging.current_revision().directory / "index.html").read_text(encoding="utf-8") == (
        "background: blue; color: white"
    )
    assert (source / "index.html").read_text(encoding="utf-8") == "background: white"
