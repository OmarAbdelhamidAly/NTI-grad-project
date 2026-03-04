"""Router for managing system policies (Idea 3: Policy Enforcement Guardrails)."""

import uuid
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.postgres import get_db
from app.infrastructure.api_dependencies import get_current_user, require_admin
from app.models.policy import SystemPolicy
from app.models.user import User
from app.schemas.policy import SystemPolicyCreate, SystemPolicyListResponse, SystemPolicyResponse

router = APIRouter(prefix="/api/v1/policies", tags=["policies"])


@router.get("/", response_model=SystemPolicyListResponse)
async def list_policies(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List all system policies for the current tenant."""
    result = await db.execute(
        select(SystemPolicy).where(SystemPolicy.tenant_id == current_user.tenant_id)
    )
    return {"policies": result.scalars().all()}


@router.post("/", response_model=SystemPolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_policy(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    policy_in: SystemPolicyCreate,
):
    """Create a new system policy (Admin only)."""
    new_policy = SystemPolicy(
        tenant_id=current_user.tenant_id,
        name=policy_in.name,
        rule_type=policy_in.rule_type,
        description=policy_in.description,
    )
    db.add(new_policy)
    await db.commit()
    await db.refresh(new_policy)
    return new_policy


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(
    policy_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a system policy (Admin only)."""
    result = await db.execute(
        select(SystemPolicy).where(
            SystemPolicy.id == policy_id, 
            SystemPolicy.tenant_id == current_user.tenant_id
        )
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    await db.execute(delete(SystemPolicy).where(SystemPolicy.id == policy_id))
    await db.commit()
    return None
