import hashlib
import mimetypes
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.compiler.compilers.claude_compiler import ClaudeCompiler
from backend.app.compiler.compilers.codex_compiler import CodexCompiler
from backend.app.core.config import settings
from backend.app.db.models import Artifact, Compilation, Job, SpecVersion


COMPILERS = {
    "claude_code": ClaudeCompiler,
    "codex": CodexCompiler,
}


def _safe_output_path(base_dir: Path, filename: str) -> Path:
    relative_path = Path(filename)

    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError(f"Unsafe compiler output path: {filename}")

    output_path = (base_dir / relative_path).resolve()

    if not output_path.is_relative_to(base_dir.resolve()):
        raise ValueError(f"Unsafe compiler output path: {filename}")

    return output_path


def compile_job(db: Session, job_id: UUID) -> None:
    """Compile a claimed job and persist its generated artifacts."""

    job = db.get(Job, job_id)

    if job is None or job.status != "running":
        raise ValueError("Job must exist and be in running state.")

    compilation = db.get(Compilation, job.compilation_id)

    if compilation is None:
        raise ValueError("Associated compilation was not found.")

    compilation_id = compilation.id
    artifacts_root = Path(settings.ARTIFACTS_DIR).resolve()
    compilation_dir = artifacts_root / str(compilation_id)

    try:
        spec_version = db.get(SpecVersion, compilation.spec_version_id)

        if spec_version is None:
            raise ValueError("Associated spec version was not found.")

        compiler_class = COMPILERS.get(compilation.target_platform)

        if compiler_class is None:
            raise ValueError(
                f"Unsupported target platform: {compilation.target_platform}"
            )

        generated_files = compiler_class().compile(spec_version.spec_data)

        if not generated_files:
            raise ValueError("Compiler returned no output files.")

        artifacts_root.mkdir(parents=True, exist_ok=True)

        # Generate all output files before changing database artifact records.
        for filename, content in generated_files.items():
            if not isinstance(filename, str) or not isinstance(content, str):
                raise ValueError("Compiler returned an invalid output file.")

            output_path = _safe_output_path(compilation_dir, filename)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content, encoding="utf-8")

        existing_artifacts = db.execute(
            select(Artifact).where(
                Artifact.compilation_id == compilation_id
            )
        ).scalars().all()

        artifacts_by_path = {
            artifact.file_path: artifact
            for artifact in existing_artifacts
        }

        for filename, content in generated_files.items():
            output_path = _safe_output_path(compilation_dir, filename)
            relative_path = output_path.relative_to(
                artifacts_root
            ).as_posix()

            artifact = artifacts_by_path.get(filename)

            if artifact is None:
                artifact = Artifact(
                    compilation_id=compilation_id,
                    file_path=filename,
                )
                db.add(artifact)

            artifact.file_type = (
                mimetypes.guess_type(filename)[0]
                or "application/octet-stream"
            )
            artifact.content_hash = hashlib.sha256(
                content.encode("utf-8")
            ).hexdigest()
            artifact.storage_url = relative_path

        now = datetime.now(timezone.utc)

        job.status = "completed"
        job.error_message = None
        job.completed_at = now

        compilation.status = "completed"
        compilation.error_message = None
        compilation.completed_at = now

        db.commit()

    except Exception as exc:
        db.rollback()

        if compilation_dir.exists():
            shutil.rmtree(compilation_dir)

        job = db.get(Job, job_id)
        compilation = db.get(Compilation, compilation_id)

        now = datetime.now(timezone.utc)

        if job is not None:
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = now

        if compilation is not None:
            compilation.status = "failed"
            compilation.error_message = str(exc)
            compilation.completed_at = now

        db.commit()
