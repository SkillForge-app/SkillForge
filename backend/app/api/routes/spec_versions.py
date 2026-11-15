from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db.models import Project, SpecVersion
from backend.app.db.session import get_db
from backend.app.schemas.spec_versions import (
    SpecValidationRequest,
    SpecValidationResponse,
    ValidationIssueResponse,
    SpecVersionCreate,
    SpecVersionResponse,
    SpecVersionDiffResponse,
)
from backend.app.spec.validator import validate_spec


router = APIRouter(prefix="/api/v1", tags=["SkillSpec Versions"])


def _validate(data: dict[str, Any]):
    result = validate_spec(data)

    errors = [
        ValidationIssueResponse(
            path=issue.path,
            code=issue.code,
            message=issue.message,
            severity=issue.severity,
        )
        for issue in result.errors
    ]

    warnings = [
        ValidationIssueResponse(
            path=issue.path,
            code=issue.code,
            message=issue.message,
            severity=issue.severity,
        )
        for issue in result.warnings
    ]

    return result, errors, warnings


@router.post(
    "/specs/validate",
    response_model=SpecValidationResponse,
)
def validate_skillspec(payload: SpecValidationRequest):
    result, errors, warnings = _validate(payload.spec)

    return SpecValidationResponse(
        valid=result.ok,
        errors=errors,
        warnings=warnings,
    )


@router.post(
    "/projects/{project_id}/versions",
    response_model=SpecVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_spec_version(
    project_id: UUID,
    payload: SpecVersionCreate,
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    result, errors, _ = _validate(payload.spec)

    if not result.ok or result.spec is None:
        raise HTTPException(
            status_code=422,
            detail=[error.model_dump() for error in errors],
        )

    spec_data = result.spec.model_dump(mode="json")

    latest_version = (
        db.query(func.max(SpecVersion.version_number))
        .filter(SpecVersion.project_id == project_id)
        .scalar()
    )

    version = SpecVersion(
        project_id=project_id,
        version_number=(latest_version or 0) + 1,
        spec_data=spec_data,
    )

    db.add(version)

    try:
        db.commit()
        db.refresh(version)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Spec version conflict. Please retry.",
        )

    return version


@router.get(
    "/projects/{project_id}/versions",
    response_model=list[SpecVersionResponse],
)
def list_spec_versions(
    project_id: UUID,
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    return (
        db.query(SpecVersion)
        .filter(SpecVersion.project_id == project_id)
        .order_by(SpecVersion.version_number.desc())
        .all()
    )


def _diff_values(old: Any, new: Any, path: str, changes: dict):
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(old.keys() - new.keys()):
            changes["removed"].append({
                "path": f"{path}.{key}" if path else key,
                "value": old[key],
            })

        for key in sorted(new.keys() - old.keys()):
            changes["added"].append({
                "path": f"{path}.{key}" if path else key,
                "value": new[key],
            })

        for key in sorted(old.keys() & new.keys()):
            child_path = f"{path}.{key}" if path else key
            _diff_values(old[key], new[key], child_path, changes)

    elif old != new:
        changes["changed"].append({
            "path": path,
            "old_value": old,
            "new_value": new,
        })


@router.get(
    "/projects/{project_id}/versions/diff",
    response_model=SpecVersionDiffResponse,
)
def diff_spec_versions(
    project_id: UUID,
    from_version: int = Query(ge=1),
    to_version: int = Query(ge=1),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if from_version == to_version:
        raise HTTPException(
            status_code=422,
            detail="from_version and to_version must be different",
        )

    versions = (
        db.query(SpecVersion)
        .filter(
            SpecVersion.project_id == project_id,
            SpecVersion.version_number.in_([from_version, to_version]),
        )
        .all()
    )

    version_map = {item.version_number: item for item in versions}

    if from_version not in version_map or to_version not in version_map:
        raise HTTPException(
            status_code=404,
            detail="One or both spec versions were not found",
        )

    changes = {
        "added": [],
        "removed": [],
        "changed": [],
    }

    _diff_values(
        version_map[from_version].spec_data,
        version_map[to_version].spec_data,
        "",
        changes,
    )

    return SpecVersionDiffResponse(
        project_id=project_id,
        from_version=from_version,
        to_version=to_version,
        **changes,
    )
