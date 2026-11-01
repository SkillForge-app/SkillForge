from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import Project, Repository
from backend.app.db.session import get_db
from backend.app.schemas.repositories import (
    RepositoryCreate,
    RepositoryResponse,
    RepositoryUpdate,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["Repositories"],
)


@router.post(
    "/projects/{project_id}/repositories",
    response_model=RepositoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_repository(
    project_id: UUID,
    payload: RepositoryCreate,
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    repository = Repository(
        project_id=project_id,
        provider=payload.provider,
        repository_url=str(payload.repository_url),
        default_branch=payload.default_branch,
    )

    db.add(repository)

    try:
        db.commit()
        db.refresh(repository)
    except Exception:
        db.rollback()
        raise

    return repository


@router.get(
    "/projects/{project_id}/repositories",
    response_model=list[RepositoryResponse],
)
def list_repositories(
    project_id: UUID,
    db: Session = Depends(get_db),
):
    if db.get(Project, project_id) is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    statement = select(Repository).where(
        Repository.project_id == project_id
    )

    return db.scalars(statement).all()


@router.get(
    "/repositories/{repository_id}",
    response_model=RepositoryResponse,
)
def get_repository(
    repository_id: UUID,
    db: Session = Depends(get_db),
):
    repository = db.get(Repository, repository_id)

    if repository is None:
        raise HTTPException(
            status_code=404,
            detail="Repository not found",
        )

    return repository


@router.patch(
    "/repositories/{repository_id}",
    response_model=RepositoryResponse,
)
def update_repository(
    repository_id: UUID,
    payload: RepositoryUpdate,
    db: Session = Depends(get_db),
):
    repository = db.get(Repository, repository_id)

    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    changes = payload.model_dump(exclude_unset=True)

    for field in ("provider", "repository_url"):
        if field in changes and changes[field] is None:
            raise HTTPException(
                status_code=422,
                detail=f"{field} cannot be null",
            )

    if "repository_url" in changes:
        changes["repository_url"] = str(changes["repository_url"])

    for field, value in changes.items():
        setattr(repository, field, value)

    db.commit()
    db.refresh(repository)

    return repository


@router.delete(
    "/repositories/{repository_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_repository(
    repository_id: UUID,
    db: Session = Depends(get_db),
):
    repository = db.get(Repository, repository_id)

    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    db.delete(repository)
    db.commit()