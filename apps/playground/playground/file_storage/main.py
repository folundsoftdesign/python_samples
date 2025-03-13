import hashlib
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from io import BytesIO
from typing import Annotated, List, Optional

import jwt
from beanie import Document, PydanticObjectId, init_beanie
from fastapi import Depends, FastAPI, File, Header, HTTPException, Path, Response, UploadFile
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorGridFSBucket
from pydantic import BaseModel, StringConstraints
from starlette import status

MONGO_URI = os.getenv("MONGO_URI", "mongodb://root:secret@172.17.0.1:30001")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 1024 * 1024 * 1024))  # default 1GB
JWT_SECRET = os.getenv("JWT_SECRET", "very_secret_key")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "admin_secret_key")

DATABASE_NAME = "sample"


class UploadResponse(BaseModel):
    filename: str
    gridfs_id: str
    file_hash: str


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# Utilities
def current_utc_timestamp():
    return datetime.now(timezone.utc)


class FileMetadata(Document):
    bucket_name: str
    filename: str
    last_modified: datetime
    gridfs_id: PydanticObjectId
    file_hash: Optional[str] = None
    content_type: str
    file_size: Optional[int] = None
    tenant_id: str

    class Config:
        collection = "file_metadata"
        arbitrary_types_allowed = True
        indexes = [[("tenant_id", 1), ("bucket_name", 1), ("filename", 1)]]


def calculate_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Lifecycle started")

    client: AsyncIOMotorClient = AsyncIOMotorClient(MONGO_URI)
    db: AsyncIOMotorDatabase = client[DATABASE_NAME]
    await init_beanie(database=db, document_models=[FileMetadata])
    gridfs = AsyncIOMotorGridFSBucket(db)

    app.state.gridfs = gridfs

    yield


app = FastAPI(lifespan=lifespan)


def get_tenant_id(authorization: str = Header(...)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.split("Bearer ")[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload["tenant_id"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except KeyError:
        raise HTTPException(status_code=400, detail="tenant_id missing from token")


class TokenRequest(BaseModel):
    tenant_id: Annotated[str, StringConstraints(min_length=1, max_length=255, pattern="^[a-zA-Z0-9_-]+$")]


def verify_admin_key(admin_key: str = Header(...)):
    if admin_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin API key")


@app.get("/generate_token")
async def generate_token(request: TokenRequest = Depends(), admin_key: str = Depends(verify_admin_key)) -> str:
    tenant_id = request.tenant_id
    now = current_utc_timestamp().timestamp()

    logger.info("Generating token")

    payload = {"tenant_id": tenant_id, "exp": now + 3600, "iat": now}

    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


@app.get("/list")
async def list_objects(tenant_id: str = Depends(get_tenant_id)) -> List[FileMetadata]:
    logger.info("Listing all objects")
    return await FileMetadata.find(FileMetadata.tenant_id == tenant_id).to_list()


@app.put("/{bucket_name}/{filename}")
async def upload_object(
    bucket_name: str = Path(..., title="Bucket Name", min_length=1),
    filename: str = Path(..., title="Filename", min_length=1),
    file: UploadFile = File(...),
    tenant_id: str = Depends(get_tenant_id),
):
    logger.info(f"Attempting to upload file: {filename} in bucket: {bucket_name}, size: {file.size}")

    if file.size is None or file.size == 0:
        logger.warning(f"Upload rejected: Empty file - {filename} in {bucket_name}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")

    if file.size > MAX_FILE_SIZE:
        logger.warning(f"Upload rejected: File size exceeded - {filename} in {bucket_name}, size: {file.size}")
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds the limit of {MAX_FILE_SIZE} bytes",
        )

    existing_file = await FileMetadata.find_one(
        FileMetadata.tenant_id == tenant_id,
        FileMetadata.bucket_name == bucket_name,
        FileMetadata.filename == filename,
    )
    if existing_file:
        logger.warning(f"Upload rejected: File already exists - {filename} in {bucket_name}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"File '{filename}' already exists in bucket '{bucket_name}'",
        )

    try:
        gridfs: AsyncIOMotorGridFSBucket = app.state.gridfs
        file_hash = hashlib.sha256()
        file_content = b""

        while chunk := await file.read(1024 * 1024):  # Read in 1MB chunks
            file_content += chunk
            file_hash.update(chunk)

        gridfs_id = await gridfs.upload_from_stream(filename=filename, source=BytesIO(file_content))

        await FileMetadata(
            tenant_id=tenant_id,
            bucket_name=bucket_name,
            filename=filename,
            last_modified=current_utc_timestamp(),
            gridfs_id=gridfs_id,
            file_hash=file_hash.hexdigest(),
            content_type=file.content_type,
            file_size=file.size,
        ).insert()

        logger.info(
            f"File uploaded successfully: {filename} in bucket: {bucket_name}, size: {file.size}, hash: {file_hash.hexdigest()}"
        )
        return Response(status_code=status.HTTP_201_CREATED, headers={"ETag": file_hash.hexdigest()})

    except Exception as e:
        logger.error(f"File upload failed: {str(e)} - {filename} in {bucket_name}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")
    finally:
        await file.close()


@app.get("/{bucket_name}/{filename}")
async def download_object(
    bucket_name: str = Path(..., title="Bucket Name", min_length=1, max_length=255, regex="^[a-zA-Z0-9_-]+$"),
    filename: str = Path(..., title="Filename", min_length=1, max_length=255),
    if_none_match: Optional[str] = Header(None),
    tenant_id: str = Depends(get_tenant_id),
):
    logger.info(f"Attempting to download file: {filename} in bucket: {bucket_name}")

    file_metadata = await FileMetadata.find_one(
        FileMetadata.tenant_id == tenant_id, FileMetadata.bucket_name == bucket_name, FileMetadata.filename == filename
    )
    if not file_metadata:
        logger.warning(f"Download failed: File not found - {filename} in {bucket_name}")
        raise HTTPException(status_code=404, detail="File not found")

    if if_none_match and file_metadata.file_hash == if_none_match:
        logger.info(f"Download prevented: File not modified - {filename} in {bucket_name}")
        return Response(status_code=status.HTTP_304_NOT_MODIFIED)

    try:
        gridfs: AsyncIOMotorGridFSBucket = app.state.gridfs
        gridfs_file = await gridfs.open_download_stream(file_metadata.gridfs_id)
        if not gridfs_file:
            logger.error(f"Download failed: GridFS file not found - {filename} in {bucket_name}")
            raise HTTPException(status_code=500, detail="GridFS file not found")

        async def generate_chunks():
            chunk_size = 1024 * 1024  # 1MB chunks
            while chunk := await gridfs_file.read(chunk_size):
                yield chunk

        logger.info(f"File download started: {filename} in bucket: {bucket_name}, size: {file_metadata.file_size}")

        return StreamingResponse(
            generate_chunks(),
            media_type=file_metadata.content_type,
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "ETag": file_metadata.file_hash,
                "Content-Length": str(gridfs_file.length),
            },
        )
    except Exception as e:
        logger.error(f"Download failed: {str(e)} - {filename} in {bucket_name}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


@app.delete("/{bucket_name}/{filename}")
async def delete_object(bucket_name: str, filename: str, tenant_id: str = Depends(get_tenant_id)):
    logger.info("Attempting to delete file: %s in bucket: %s", filename, bucket_name)
    file_metadata = await FileMetadata.find_one(
        FileMetadata.tenant_id == tenant_id, FileMetadata.bucket_name == bucket_name, FileMetadata.filename == filename
    )

    if not file_metadata:
        logger.warning("Delete failed: File not found - %s in %s", filename, bucket_name)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    gridfs = app.state.gridfs
    await gridfs.delete(file_metadata.gridfs_id)
    await file_metadata.delete()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
