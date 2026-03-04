"""Router for managing business-specific metrics (the 'Dictionary' RAG component)."""

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.postgres import get_db
from app.infrastructure.api_dependencies import get_current_user, require_admin
from app.models.metric import BusinessMetric
from app.models.user import User
from app.schemas.metric import (
    BusinessMetricCreate,
    BusinessMetricListResponse,
    BusinessMetricResponse,
    BusinessMetricUpdate,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


@router.get("/", response_model=BusinessMetricListResponse)
async def list_metrics(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List all business metrics for the current tenant."""
    result = await db.execute(
        select(BusinessMetric).where(BusinessMetric.tenant_id == current_user.tenant_id)
    )
    metrics = result.scalars().all()
    return {"metrics": metrics}


@router.post("/", response_model=BusinessMetricResponse, status_code=status.HTTP_201_CREATED)
async def create_metric(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    metric_in: BusinessMetricCreate,
):
    """Create a new business metric definition (Admin only)."""
    new_metric = BusinessMetric(
        tenant_id=current_user.tenant_id,
        name=metric_in.name,
        definition=metric_in.definition,
        formula=metric_in.formula,
    )
    db.add(new_metric)
    await db.commit()
    await db.refresh(new_metric)
    
    logger.info("metric_created", metric_name=new_metric.name, tenant_id=str(current_user.tenant_id))
    return new_metric


@router.delete("/{metric_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_metric(
    metric_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a business metric definition (Admin only)."""
    result = await db.execute(
        select(BusinessMetric).where(
            BusinessMetric.id == metric_id, 
            BusinessMetric.tenant_id == current_user.tenant_id
        )
    )
    metric = result.scalar_one_or_none()
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")
    
    await db.execute(delete(BusinessMetric).where(BusinessMetric.id == metric_id))
    await db.commit()
    
    logger.info("metric_deleted", metric_id=str(metric_id), tenant_id=str(current_user.tenant_id))
    return None
