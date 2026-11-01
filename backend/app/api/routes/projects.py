from sqlalchemy.exc import IntegrityError
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.db.models import Project
from backend.app.db.session import get_db
from backend.app.schemas.projects import ProjectCreate, ProjectUpdate, ProjectResponse

router = APIRouter(prefix="/api/v1/projects", tags=["Projects"])


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
):
    project = Project(
        name=payload.name,
        description=payload.description,
    )

    db.add(project)

    try:
        db.commit()
        db.refresh(project)
    except Exception:
        db.rollback()
        raise

    return project


@router.get("", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.created_at.desc()).all()


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: UUID,
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    changes = payload.model_dump(exclude_unset=True)

    if "name" in changes and changes["name"] is None:
        raise HTTPException(
            status_code=422,
            detail="Project name cannot be null",
        )

    for field, value in changes.items():
        setattr(project, field, value)

    try:
        db.commit()
        db.refresh(project)
    except Exception:
        db.rollback()
        raise

    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: UUID,
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    db.delete(project)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Cannot delete project with related records",
        )

