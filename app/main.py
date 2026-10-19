import hashlib, logging, os, re, secrets, tempfile, uuid
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile, BadZipFile
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.security import hash_password, verify_password, create_access_token, decode_subject
from app.database import get_db, engine
from app.models import Base, User, Workspace, StoredFile, ApiKey
from app.schemas import RegisterIn, LoginIn, TokenOut, UserOut, WorkspaceIn, WorkspaceOut, FileOut, FilePageOut, FilePublicAccessIn, ApiKeyCreateIn, ApiKeyOut, ApiKeyCreatedOut
from app.storage.telegram_provider import TelegramStorageProvider

app = FastAPI(title=settings.app_name, version="1.0.0", description="Telegram-backed cloud storage REST API")
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_url], allow_credentials=True, allow_methods=["GET","POST","PATCH","DELETE"], allow_headers=["Authorization","Content-Type","x-api-key","x-workspace-id"])
storage = TelegramStorageProvider()
logger = logging.getLogger("telecloud.storage")

def detect_content(path: str) -> str:
    """Prefer file signatures to untrusted browser Content-Type values."""
    with open(path, "rb") as stream: head = stream.read(32)
    known = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"),
             (b"GIF87a", "image/gif"), (b"GIF89a", "image/gif"), (b"%PDF-", "application/pdf"),
             (b"PK\x03\x04", "application/zip"), (b"OggS", "audio/ogg"), (b"ID3", "audio/mpeg"),
             (b"\x1aE\xdf\xa3", "video/webm"))
    for signature, mime in known:
        if head.startswith(signature): return mime
    if len(head) >= 12 and head[4:8] == b"ftyp": return "video/mp4"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP": return "image/webp"
    return "application/octet-stream"

@app.on_event("startup")
async def startup():
    # Convenient for local first run. Deploy schema changes with Alembic.
    if settings.app_env == "development":
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)

async def current_user(authorization: str | None = Header(default=None), db: AsyncSession = Depends(get_db)) -> User:
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401, "Authentication required")
    try: uid = uuid.UUID(decode_subject(authorization[7:]))
    except Exception: raise HTTPException(401, "Invalid access token")
    user = await db.get(User, uid)
    if not user: raise HTTPException(401, "User not found")
    return user

async def owned_workspace(workspace_id: uuid.UUID, user: User, db: AsyncSession) -> Workspace:
    ws = await db.scalar(select(Workspace).where(Workspace.id == workspace_id, Workspace.owner_id == user.id))
    if not ws: raise HTTPException(404, "Workspace not found")
    return ws

async def resolve_api_key(raw_key: str | None, db: AsyncSession) -> ApiKey:
    if not raw_key or not raw_key.startswith("tc_live_"):
        raise HTTPException(401, "A valid x-api-key header is required")
    digest = hashlib.sha256(raw_key.encode()).hexdigest()
    key = await db.scalar(select(ApiKey).where(ApiKey.key_hash == digest, ApiKey.revoked_at.is_(None)))
    if not key: raise HTTPException(401, "Invalid or revoked API key")
    return key

@app.get("/api/v1/health")
async def health(): return {"status":"ok", "storage":"available" if await storage.check_health() else "not_configured_or_unavailable"}

@app.post("/api/v1/auth/register", response_model=UserOut, status_code=201)
async def register(data: RegisterIn, db: AsyncSession = Depends(get_db)):
    email = data.email.lower()
    if await db.scalar(select(User.id).where(User.email == email)): raise HTTPException(409, "Email already registered")
    count = await db.scalar(select(func.count()).select_from(User))
    user = User(email=email, name=data.name, password_hash=hash_password(data.password), role="ADMIN" if count == 0 else "USER")
    db.add(user); await db.commit(); await db.refresh(user)
    db.add(Workspace(name="My Workspace", owner_id=user.id)); await db.commit()
    return user

@app.post("/api/v1/auth/login", response_model=TokenOut)
async def login(data: LoginIn, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == data.email.lower()))
    if not user or not verify_password(data.password, user.password_hash): raise HTTPException(401, "Invalid email or password")
    return TokenOut(access_token=create_access_token(str(user.id)))

@app.get("/api/v1/users/me", response_model=UserOut)
async def me(user: User = Depends(current_user)): return user

@app.get("/api/v1/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return list((await db.scalars(select(Workspace).where(Workspace.owner_id == user.id).order_by(Workspace.created_at))).all())

@app.post("/api/v1/workspaces", response_model=WorkspaceOut, status_code=201)
async def create_workspace(data: WorkspaceIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    ws = Workspace(**data.model_dump(), owner_id=user.id); db.add(ws); await db.commit(); await db.refresh(ws); return ws

@app.get("/api/v1/workspaces/{workspace_id}/api-keys", response_model=list[ApiKeyOut])
async def list_api_keys(workspace_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await owned_workspace(workspace_id,user,db)
    rows = await db.scalars(select(ApiKey).where(ApiKey.workspace_id == workspace_id).order_by(ApiKey.created_at.desc()))
    return list(rows.all())

@app.post("/api/v1/workspaces/{workspace_id}/api-keys", response_model=ApiKeyCreatedOut, status_code=201)
async def create_api_key(workspace_id: uuid.UUID, data: ApiKeyCreateIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await owned_workspace(workspace_id,user,db)
    raw_key = "tc_live_" + secrets.token_urlsafe(32)
    key = ApiKey(workspace_id=workspace_id,created_by=user.id,name=data.name,key_prefix=raw_key[:16],key_hash=hashlib.sha256(raw_key.encode()).hexdigest())
    db.add(key); await db.commit(); await db.refresh(key)
    return {"id":key.id,"workspace_id":key.workspace_id,"name":key.name,"key_prefix":key.key_prefix,"created_at":key.created_at,"revoked_at":None,"key":raw_key}

@app.delete("/api/v1/api-keys/{key_id}", status_code=204)
async def revoke_api_key(key_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    key = await db.get(ApiKey,key_id)
    if not key or not await db.scalar(select(Workspace.id).where(Workspace.id==key.workspace_id,Workspace.owner_id==user.id)):
        raise HTTPException(404,"API key not found")
    if key.revoked_at is None: key.revoked_at = datetime.now(timezone.utc)
    await db.commit()

@app.post("/api/v1/api-keys/verify")
async def verify_api_key(x_api_key: str | None = Header(default=None), x_workspace_id: str | None = Header(default=None), db: AsyncSession = Depends(get_db)):
    key = await resolve_api_key(x_api_key, db)
    if x_workspace_id:
        try: requested_workspace = uuid.UUID(x_workspace_id)
        except ValueError as exc: raise HTTPException(422, "x-workspace-id must be a UUID") from exc
        if requested_workspace != key.workspace_id: raise HTTPException(403, "API key is not authorized for this workspace")
    return {"valid": True, "integrity": "verified", "key_prefix": key.key_prefix, "key_name": key.name, "workspace_id": str(key.workspace_id)}

@app.delete("/api/v1/workspaces/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    ws = await owned_workspace(workspace_id,user,db)
    files = list((await db.scalars(select(StoredFile).where(StoredFile.workspace_id == ws.id))).all())
    for f in files:
        try: await storage.delete_file(f.provider_ref)
        except Exception: raise HTTPException(503, "Storage cleanup failed; workspace remains intact")
    await db.delete(ws); await db.commit()

@app.get("/api/v1/workspaces/{workspace_id}/summary")
async def workspace_summary(workspace_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await owned_workspace(workspace_id,user,db)
    count, size = (await db.execute(select(func.count(StoredFile.id), func.coalesce(func.sum(StoredFile.size), 0)).where(StoredFile.workspace_id == workspace_id))).one()
    return {"file_count": count, "storage_bytes": size}

@app.get("/api/v1/workspaces/{workspace_id}/files", response_model=FilePageOut)
async def list_files(workspace_id: uuid.UUID, page: int = 1, limit: int = 20, q: str | None = None, category: str = "all", sort: str = "created", order: str = "desc", user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await owned_workspace(workspace_id,user,db)
    page, limit = max(1, page), min(100, max(1, limit))
    filters = [StoredFile.workspace_id == workspace_id]
    if q and q.strip(): filters.append(StoredFile.filename.ilike(f"%{q.strip()[:120]}%"))
    category_filters = {
        "images": StoredFile.mime_type.like("image/%"),
        "videos": StoredFile.mime_type.like("video/%"),
        "audio": StoredFile.mime_type.like("audio/%"),
        "archives": StoredFile.mime_type.in_(["application/zip", "application/x-zip-compressed"]),
        "documents": StoredFile.mime_type.in_(["application/pdf", "text/plain", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]),
    }
    if category in category_filters: filters.append(category_filters[category])
    total = await db.scalar(select(func.count(StoredFile.id)).where(*filters)) or 0
    sort_column = {"name": StoredFile.filename, "size": StoredFile.size, "created": StoredFile.created_at}.get(sort, StoredFile.created_at)
    sort_column = sort_column.asc() if order == "asc" else sort_column.desc()
    stmt = select(StoredFile).where(*filters).order_by(sort_column, StoredFile.id).offset((page-1)*limit).limit(limit)
    items = list((await db.scalars(stmt)).all())
    return {"items": items, "page": page, "limit": limit, "total": total}

@app.post("/api/v1/workspaces/{workspace_id}/files", response_model=FileOut, status_code=201)
async def upload_file(workspace_id: uuid.UUID, file: UploadFile = File(...), user: User = Depends(current_user), db: AsyncSession = Depends(get_db), caption: str | None = Form(default=None, max_length=1024), is_public: bool = Form(default=False)):
    await owned_workspace(workspace_id,user,db)
    clean_name = Path(file.filename or "upload").name.replace("\x00", "")[:255]
    if not clean_name: raise HTTPException(400,"Invalid filename")
    limit = settings.max_upload_size_mb * 1024 * 1024; size = 0; digest = hashlib.sha256()
    temp = tempfile.NamedTemporaryFile(delete=False)
    try:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit: raise HTTPException(413,"File exceeds configured upload limit")
            digest.update(chunk); temp.write(chunk)
        temp.close(); checksum = digest.hexdigest()
        actual_mime = detect_content(temp.name)
        if actual_mime.startswith("image/"):
            try:
                from PIL import Image as PillowImage
                with PillowImage.open(temp.name) as image: image.verify()
            except Exception as exc: raise HTTPException(400,"Image content is invalid") from exc
        if actual_mime == "application/zip":
            try:
                with ZipFile(temp.name) as archive:
                    names = archive.namelist()
                    if len(names) > 10000 or any(Path(n).is_absolute() or ".." in Path(n).parts for n in names):
                        raise HTTPException(400,"Archive contains unsafe paths or too many entries")
            except BadZipFile as exc: raise HTTPException(400,"Archive content is invalid") from exc
        prior = await db.scalar(select(StoredFile).where(StoredFile.workspace_id==workspace_id,StoredFile.sha256==checksum))
        if prior: raise HTTPException(409,"Duplicate file already exists in this workspace")
        try:
            with open(temp.name,"rb") as stream: reference = await storage.upload_file(stream,clean_name,actual_mime,caption)
        except Exception as exc:
            logger.exception("Telegram upload failed for workspace %s", workspace_id)
            reason = str(exc)
            if reason == "Telegram storage is not configured":
                detail = "Telegram storage is not configured. Set TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_STORAGE_CHANNEL_ID in backend/.env, then restart the backend."
            elif reason == "Telegram user session is not authorized":
                detail = "Telegram is not logged in. From the backend directory, run `python get_channel_id.py`, finish the Telegram sign-in, then restart the backend."
            elif "rate limit" in reason.lower():
                detail = "Telegram rate limited this upload. Wait and retry."
            else:
                detail = "Telegram upload failed. Check the backend terminal for the Telegram error; verify the session is authorized and the channel allows this account to post."
            raise HTTPException(503,detail) from exc
        record = StoredFile(workspace_id=workspace_id,uploaded_by=user.id,filename=clean_name,mime_type=actual_mime,size=size,sha256=checksum,provider_ref=reference,is_public=is_public)
        db.add(record); await db.commit(); await db.refresh(record); return record
    finally:
        temp.close(); os.unlink(temp.name)

@app.post("/api/v1/upload", status_code=200)
async def upload_with_api_key(file: UploadFile = File(...), workspace_form: str | None = Form(default=None, alias="workspace_id"), caption: str | None = Form(default=None, max_length=1024), is_public: bool = Form(default=False), x_api_key: str | None = Header(default=None), x_workspace_id: str | None = Header(default=None), db: AsyncSession = Depends(get_db)):
    key = await resolve_api_key(x_api_key,db)
    if x_workspace_id and workspace_form and x_workspace_id != workspace_form:
        raise HTTPException(400,"x-workspace-id and workspace_id must match")
    supplied_workspace = x_workspace_id or workspace_form
    try: workspace_id = uuid.UUID(supplied_workspace) if supplied_workspace else key.workspace_id
    except ValueError as exc: raise HTTPException(422,"Workspace ID must be a UUID") from exc
    if workspace_id != key.workspace_id: raise HTTPException(403,"API key is not authorized for this workspace")
    user = await db.get(User,key.created_by)
    if not user: raise HTTPException(401,"API key owner no longer exists")
    await owned_workspace(workspace_id,user,db)
    record = await upload_file(workspace_id,file,user,db,caption,is_public)
    url = f"{settings.backend_url.rstrip('/')}/api/v1/files/{record.id}"
    return {"success":True,"file_id":str(record.id),"file_url":url,"file_name":record.filename,"file_size":record.size,"mime_type":record.mime_type,"workspace_id":str(record.workspace_id),"checksum_sha256":record.sha256,"is_public":record.is_public}

@app.get("/api/v1/files/{file_id}")
async def download_file(file_id: uuid.UUID, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None), db: AsyncSession = Depends(get_db)):
    if x_api_key:
        key = await resolve_api_key(x_api_key,db)
        row = await db.scalar(select(StoredFile).where(StoredFile.id==file_id,StoredFile.workspace_id==key.workspace_id))
    elif authorization:
        if not authorization.startswith("Bearer "): raise HTTPException(401,"Invalid access token")
        try: user_id = uuid.UUID(decode_subject(authorization[7:]))
        except Exception: raise HTTPException(401,"Invalid access token")
        row = await db.scalar(select(StoredFile).join(Workspace).where(StoredFile.id==file_id,Workspace.owner_id==user_id))
    else:
        row = await db.get(StoredFile, file_id)
        if not row or not row.is_public: raise HTTPException(401,"Authentication required; this file is private")
    if not row: raise HTTPException(404,"File not found")
    try: data = await storage.download_file(row.provider_ref)
    except Exception as exc: raise HTTPException(503,"Stored file is temporarily unavailable") from exc
    safe_name = row.filename.replace('"', "")
    disposition = "inline" if row.is_public and row.mime_type.startswith("image/") else "attachment"
    cache_control = "public, max-age=300" if row.is_public else "private, no-store"
    return StreamingResponse(data, media_type=row.mime_type, headers={"Content-Disposition":f'{disposition}; filename="{safe_name}"',"Cache-Control":cache_control})

@app.patch("/api/v1/files/{file_id}/public", response_model=FileOut)
async def set_file_public_access(file_id: uuid.UUID, data: FilePublicAccessIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(StoredFile).join(Workspace).where(StoredFile.id==file_id,Workspace.owner_id==user.id))
    if not row: raise HTTPException(404,"File not found")
    row.is_public = data.is_public
    await db.commit()
    await db.refresh(row)
    return row

@app.delete("/api/v1/files/{file_id}", status_code=204)
async def delete_file(file_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(StoredFile).join(Workspace).where(StoredFile.id==file_id,Workspace.owner_id==user.id))
    if not row: raise HTTPException(404,"File not found")
    try: await storage.delete_file(row.provider_ref)
    except Exception as exc: raise HTTPException(503,"Storage cleanup failed; file record retained") from exc
    await db.delete(row); await db.commit()
