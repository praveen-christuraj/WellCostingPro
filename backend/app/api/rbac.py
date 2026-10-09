from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from app.api.deps import Current, Db, require, owner, granted
from app.core.security import hash_password
from app.models import User, Role, Permission
from app.schemas.rbac import (UserCreate, UserUpdate, UserOut, RoleCreate, RoleUpdate, RoleOut,
                              PermissionCreate, PermissionUpdate, PermissionOut, IDList, Overview)
from app.services import audit

router = APIRouter(tags=["Access management"])


def scoped(db, model, item_id, org_id):
    item = db.get(model, item_id)
    if not item or item.organization_id != org_id:
        raise HTTPException(404, "Not found")
    return item


def commit(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A record with this value already exists")


def flush(db):
    """Persist new ids for audit records without leaving the surrounding transaction."""
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A record with this value already exists")


def assert_assignable(actor, roles):
    if not owner(actor) and any(not {p.key for p in role.permissions}.issubset(granted(actor)) for role in roles):
        raise HTTPException(403, "Cannot assign a role with capabilities you do not hold")


def resolve_ids(db, model, ids, org_id):
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "Duplicate IDs are not allowed")
    items = list(db.scalars(select(model).where(model.id.in_(ids), model.organization_id == org_id)).all()) if ids else []
    if len(items) != len(ids):
        raise HTTPException(422, "One or more IDs do not belong to this organization")
    return items


@router.get("/overview", response_model=Overview)
def overview(db: Db, user: Current):
    org = user.organization_id
    can_read_users = owner(user) or "users:read" in granted(user)
    can_read_roles = owner(user) or "roles:read" in granted(user)
    return {"users": db.scalar(select(func.count(User.id)).where(User.organization_id == org)),
            "active_users": db.scalar(select(func.count(User.id)).where(User.organization_id == org, User.is_active.is_(True))),
            "roles": db.scalar(select(func.count(Role.id)).where(Role.organization_id == org)),
            "permissions": db.scalar(select(func.count(Permission.id)).where(Permission.organization_id == org)),
            "recent_users": list(db.scalars(select(User).where(User.organization_id == org).order_by(User.created_at.desc()).limit(5)).all()) if can_read_users else [],
            "role_distribution": [{"name": role.name, "count": len(role.users)} for role in db.scalars(select(Role).where(Role.organization_id == org).order_by(Role.name)).all()] if can_read_roles else []}


@router.get("/users", response_model=list[UserOut], dependencies=[Depends(require("users:read"))])
def list_users(db: Db, user: Current):
    return db.scalars(select(User).where(User.organization_id == user.organization_id).order_by(User.created_at.desc())).all()


@router.post("/users", response_model=UserOut, status_code=201, dependencies=[Depends(require("users:create"))])
def create_user(data: UserCreate, request: Request, db: Db, user: Current):
    if data.role_ids and not owner(user) and "assignments:write" not in granted(user):
        raise HTTPException(403, "Permission denied")
    roles = resolve_ids(db, Role, data.role_ids, user.organization_id)
    assert_assignable(user, roles)
    if any(r.is_owner for r in roles):
        raise HTTPException(403, "Owner role cannot be assigned through this endpoint")
    item = User(organization_id=user.organization_id, email=data.email.lower(), full_name=data.full_name.strip(), password_hash=hash_password(data.password), roles=roles)
    db.add(item)
    flush(db)
    audit.record(db, organization_id=user.organization_id, actor=user, action="create", entity_type="user",
                 entity_id=item.id, entity_label=item.email,
                 summary=f"Created user {item.full_name} <{item.email}>" + (f" with roles: {', '.join(r.name for r in roles)}" if roles else ""),
                 request=request)
    commit(db)
    db.refresh(item)
    return item


@router.patch("/users/{item_id}", response_model=UserOut, dependencies=[Depends(require("users:update"))])
def update_user(item_id: str, data: UserUpdate, request: Request, db: Db, user: Current):
    item = scoped(db, User, item_id, user.organization_id)
    assert_assignable(user, item.roles)
    if any(r.is_owner for r in item.roles) and not owner(user):
        raise HTTPException(403, "Only an owner can edit an owner")
    if data.is_active is False and (item.id == user.id or any(r.is_owner for r in item.roles)):
        raise HTTPException(403, "Cannot deactivate yourself or an organization owner")
    changed = [key for key, value in data.model_dump(exclude_unset=True).items() if getattr(item, key) != value]
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    if changed:
        audit.record(db, organization_id=user.organization_id, actor=user, action="update", entity_type="user",
                     entity_id=item.id, entity_label=item.email,
                     summary=f"Updated user {item.email}: {', '.join(changed)}", request=request)
    commit(db)
    return item


@router.put("/users/{item_id}/roles", response_model=UserOut, dependencies=[Depends(require("assignments:write"))])
def assign_roles(item_id: str, data: IDList, request: Request, db: Db, user: Current):
    item = scoped(db, User, item_id, user.organization_id)
    roles = resolve_ids(db, Role, data.ids, user.organization_id)
    assert_assignable(user, item.roles)
    assert_assignable(user, roles)
    if any(r.is_owner for r in roles) or any(r.is_owner for r in item.roles):
        raise HTTPException(403, "Owner role assignments are managed by provisioning")
    item.roles = roles
    audit.record(db, organization_id=user.organization_id, actor=user, action="assign", entity_type="user",
                 entity_id=item.id, entity_label=item.email,
                 summary=f"Set roles for {item.email}: {', '.join(r.name for r in roles) or 'none'}", request=request)
    commit(db)
    return item


@router.get("/roles", response_model=list[RoleOut], dependencies=[Depends(require("roles:read"))])
def list_roles(db: Db, user: Current):
    return db.scalars(select(Role).where(Role.organization_id == user.organization_id).order_by(Role.name)).all()


@router.post("/roles", response_model=RoleOut, status_code=201, dependencies=[Depends(require("roles:create"))])
def create_role(data: RoleCreate, request: Request, db: Db, user: Current):
    item = Role(organization_id=user.organization_id, name=data.name.strip(), description=data.description)
    db.add(item)
    flush(db)
    audit.record(db, organization_id=user.organization_id, actor=user, action="create", entity_type="role",
                 entity_id=item.id, entity_label=item.name, summary=f"Created role {item.name}", request=request)
    commit(db)
    db.refresh(item)
    return item


@router.patch("/roles/{item_id}", response_model=RoleOut, dependencies=[Depends(require("roles:update"))])
def update_role(item_id: str, data: RoleUpdate, request: Request, db: Db, user: Current):
    item = scoped(db, Role, item_id, user.organization_id)
    if item.is_owner:
        raise HTTPException(403, "Owner role cannot be edited")
    assert_assignable(user, [item])
    changed = [key for key, value in data.model_dump(exclude_unset=True).items() if getattr(item, key) != (value.strip() if key == "name" and value else value)]
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value.strip() if key == "name" else value)
    if changed:
        audit.record(db, organization_id=user.organization_id, actor=user, action="update", entity_type="role",
                     entity_id=item.id, entity_label=item.name,
                     summary=f"Updated role {item.name}: {', '.join(changed)}", request=request)
    commit(db)
    return item


@router.delete("/roles/{item_id}", status_code=204, dependencies=[Depends(require("roles:delete"))])
def delete_role(item_id: str, request: Request, db: Db, user: Current):
    item = scoped(db, Role, item_id, user.organization_id)
    if item.is_owner:
        raise HTTPException(403, "Owner role cannot be deleted")
    assert_assignable(user, [item])
    audit.record(db, organization_id=user.organization_id, actor=user, action="delete", entity_type="role",
                 entity_id=item.id, entity_label=item.name, summary=f"Deleted role {item.name}", request=request)
    db.delete(item)
    commit(db)


@router.put("/roles/{item_id}/permissions", response_model=RoleOut, dependencies=[Depends(require("assignments:write"))])
def assign_permissions(item_id: str, data: IDList, request: Request, db: Db, user: Current):
    item = scoped(db, Role, item_id, user.organization_id)
    if item.is_owner:
        raise HTTPException(403, "Owner role permissions are managed by provisioning")
    permissions = resolve_ids(db, Permission, data.ids, user.organization_id)
    if not owner(user) and any(p.key not in granted(user) for p in permissions):
        raise HTTPException(403, "Cannot grant capabilities you do not hold")
    assert_assignable(user, [item])
    item.permissions = permissions
    audit.record(db, organization_id=user.organization_id, actor=user, action="assign", entity_type="role",
                 entity_id=item.id, entity_label=item.name,
                 summary=f"Set permissions for role {item.name}: {', '.join(p.key for p in permissions) or 'none'}", request=request)
    commit(db)
    return item


@router.get("/permissions", response_model=list[PermissionOut], dependencies=[Depends(require("permissions:read"))])
def list_permissions(db: Db, user: Current):
    return db.scalars(select(Permission).where(Permission.organization_id == user.organization_id).order_by(Permission.key)).all()


@router.post("/permissions", response_model=PermissionOut, status_code=201, dependencies=[Depends(require("permissions:create"))])
def create_permission(data: PermissionCreate, request: Request, db: Db, user: Current):
    item = Permission(organization_id=user.organization_id, **data.model_dump())
    db.add(item)
    flush(db)
    audit.record(db, organization_id=user.organization_id, actor=user, action="create", entity_type="permission",
                 entity_id=item.id, entity_label=item.key, summary=f"Created permission {item.key}", request=request)
    commit(db)
    db.refresh(item)
    return item


@router.patch("/permissions/{item_id}", response_model=PermissionOut, dependencies=[Depends(require("permissions:update"))])
def update_permission(item_id: str, data: PermissionUpdate, request: Request, db: Db, user: Current):
    item = scoped(db, Permission, item_id, user.organization_id)
    if not owner(user) and item.key not in granted(user):
        raise HTTPException(403, "Cannot edit a capability you do not hold")
    item.description = data.description
    audit.record(db, organization_id=user.organization_id, actor=user, action="update", entity_type="permission",
                 entity_id=item.id, entity_label=item.key, summary=f"Updated permission {item.key}", request=request)
    commit(db)
    return item


@router.delete("/permissions/{item_id}", status_code=204, dependencies=[Depends(require("permissions:delete"))])
def delete_permission(item_id: str, request: Request, db: Db, user: Current):
    item = scoped(db, Permission, item_id, user.organization_id)
    if not owner(user) and item.key not in granted(user):
        raise HTTPException(403, "Cannot delete a capability you do not hold")
    audit.record(db, organization_id=user.organization_id, actor=user, action="delete", entity_type="permission",
                 entity_id=item.id, entity_label=item.key, summary=f"Deleted permission {item.key}", request=request)
    db.delete(item)
    commit(db)
