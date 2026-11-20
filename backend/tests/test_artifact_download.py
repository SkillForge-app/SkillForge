import hashlib
import io
import zipfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.services.artifact_download import (
    ArtifactFilesError,
    build_zip,
    collect_files,
)


def write_artifact(root: Path, compilation_id, name: str, content: str, **overrides):
    path = root / str(compilation_id) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    values = {
        "file_path": name,
        "storage_url": f"{compilation_id}/{name}",
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_collects_the_recorded_files(tmp_path):
    cid = uuid4()
    artifacts = [
        write_artifact(tmp_path, cid, "CLAUDE.md", "# Title\n"),
        write_artifact(tmp_path, cid, ".claude/agents/x.md", "agent\n"),
    ]

    files = collect_files(artifacts, tmp_path, cid)

    assert files == {"CLAUDE.md": b"# Title\n", ".claude/agents/x.md": b"agent\n"}


def test_files_sent_by_an_external_runner_are_skipped(tmp_path):
    cid = uuid4()
    ours = write_artifact(tmp_path, cid, "AGENTS.md", "ok")
    external = SimpleNamespace(
        file_path="report.txt", storage_url="https://example.com/report", content_hash=None
    )
    no_url = SimpleNamespace(file_path="x", storage_url=None, content_hash=None)

    assert list(collect_files([ours, external, no_url], tmp_path, cid)) == ["AGENTS.md"]


def test_a_missing_file_is_an_error(tmp_path):
    cid = uuid4()
    artifact = write_artifact(tmp_path, cid, "AGENTS.md", "ok")
    (tmp_path / str(cid) / "AGENTS.md").unlink()

    with pytest.raises(ArtifactFilesError, match="missing"):
        collect_files([artifact], tmp_path, cid)


def test_a_file_changed_on_disk_is_an_error(tmp_path):
    cid = uuid4()
    artifact = write_artifact(tmp_path, cid, "AGENTS.md", "ok")
    (tmp_path / str(cid) / "AGENTS.md").write_text("tampered", encoding="utf-8")

    with pytest.raises(ArtifactFilesError, match="changed"):
        collect_files([artifact], tmp_path, cid)


def test_a_path_outside_the_compilation_folder_is_refused(tmp_path):
    cid = uuid4()
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    other = uuid4()
    write_artifact(tmp_path, other, "AGENTS.md", "other run")

    for stored in ("../secret.txt", f"{other}/AGENTS.md", "/etc/passwd"):
        artifact = SimpleNamespace(
            file_path="AGENTS.md",
            storage_url=stored,
            content_hash=hashlib.sha256(b"x").hexdigest(),
        )
        with pytest.raises(ArtifactFilesError, match="outside"):
            collect_files([artifact], tmp_path, cid)


def test_zip_holds_every_file_and_is_deterministic():
    files = {"b.md": b"2", "a/c.json": b"{}", "z.txt": "مرحبا".encode("utf-8")}

    data = build_zip(files)

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert sorted(archive.namelist()) == sorted(files)
        assert archive.testzip() is None
        for name, content in files.items():
            assert archive.read(name) == content
    assert data == build_zip(dict(reversed(list(files.items()))))
