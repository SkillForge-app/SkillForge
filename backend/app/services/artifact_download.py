"""Read the files a compiler run wrote to disk and pack them into a zip.

compilation_service.compile_job writes each file to ARTIFACTS_DIR/<compilation_id>/<path> and
records the path (storage_url, relative to ARTIFACTS_DIR) and the SHA-256 in `artifacts`.
Artifacts sent by an external runner through POST /runs/{id}/result keep whatever string the
runner sent in storage_url; they are not files of ours and are left out of the zip.
"""

import hashlib
import io
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any

# Fixed so that the same files always give the same zip bytes.
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class ArtifactFilesError(RuntimeError):
    """The recorded files are missing or no longer match what was recorded."""


def collect_files(
    artifacts: Iterable[Any], artifacts_root: Path, compilation_id: Any
) -> dict[str, bytes]:
    """Return {file_path: bytes} for the artifacts that are our own files.

    Raises ArtifactFilesError if a file is missing, lies outside the compilation's folder, or has
    a different hash than the one recorded.
    """
    folder = (artifacts_root / str(compilation_id)).resolve()
    files: dict[str, bytes] = {}

    for artifact in artifacts:
        stored = artifact.storage_url
        if not stored or artifact.content_hash is None:
            continue  # sent by an external runner, not written by compile_job

        path = (artifacts_root / PurePosixPath(stored)).resolve()
        if not path.is_relative_to(folder):
            raise ArtifactFilesError(f"Artifact {artifact.file_path} points outside its folder")
        if not path.is_file():
            raise ArtifactFilesError(f"Artifact file is missing: {artifact.file_path}")

        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != artifact.content_hash:
            raise ArtifactFilesError(f"Artifact file changed on disk: {artifact.file_path}")
        files[artifact.file_path] = data

    return files


def build_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
    return buffer.getvalue()
