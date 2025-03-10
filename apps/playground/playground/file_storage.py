import hashlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from io import BytesIO
from typing import List, Optional

from beanie import Document, init_beanie
from bson import ObjectId
from fastapi import FastAPI, File, Header, HTTPException, Query, Response, UploadFile
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorGridFSBucket
from starlette import status

MONGO_URI = "mongodb://localhost:27017"
DATABASE_NAME = "your_database"


# Utilities
def current_utc_timestamp():
    return datetime.now(timezone.utc)


class FileMetadata(Document):
    filename: str
    last_modified: datetime
    gridfs_id: ObjectId
    file_hash: Optional[str] = None


def calculate_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def seed_database(gridfs: AsyncIOMotorGridFSBucket):
    example_file_content = b"This is an example large binary file."
    example_file_content2 = b"This is another example large binary file that changed."

    gridfs_id1 = await gridfs.upload_from_stream(filename="example.bin", source=BytesIO(example_file_content))
    gridfs_id2 = await gridfs.upload_from_stream(filename="example2.bin", source=BytesIO(example_file_content2))

    await FileMetadata(
        filename="example.bin",
        last_modified=current_utc_timestamp(),
        gridfs_id=gridfs_id1,
        file_hash=calculate_hash(example_file_content),
    ).insert()
    await FileMetadata(
        filename="example2.bin",
        last_modified=current_utc_timestamp(),
        gridfs_id=gridfs_id2,
        file_hash=calculate_hash(example_file_content2),
    ).insert()


@asynccontextmanager
async def lifespan(app: FastAPI):
    client: AsyncIOMotorClient = AsyncIOMotorClient(MONGO_URI)
    db: AsyncIOMotorDatabase = client[DATABASE_NAME]
    await init_beanie(database=db, document_models=[FileMetadata])
    gridfs = AsyncIOMotorGridFSBucket(db)

    if await FileMetadata.count() == 0:
        await seed_database(gridfs)

    app.state.gridfs = gridfs
    yield


app = FastAPI(lifespan=lifespan)


# Old Upload and Download Endpoints
@app.get("/download/{filename}")
async def download_file(filename: str, app: FastAPI, filehash: Optional[str] = Query(None)):
    file_metadata = await FileMetadata.find_one(FileMetadata.filename == filename)
    if not file_metadata:
        raise HTTPException(status_code=404, detail="File not found")

    gridfs = app.state.gridfs
    gridfs_file = await gridfs.open_download_stream(file_metadata.gridfs_id)
    if not gridfs_file:
        raise HTTPException(status_code=500, detail="GridFS file not found")

    async def generate_chunks():
        try:
            while True:
                chunk = await gridfs_file.readchunk()
                if not chunk:
                    break
                yield chunk
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading GridFS file: {e}")

    if filehash:
        if file_metadata.file_hash == filehash:
            return Response(status_code=status.HTTP_304_NOT_MODIFIED)

    return Response(
        content=generate_chunks(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/upload/")
async def upload_file(file: UploadFile = File(...), app: FastAPI = FastAPI()):
    gridfs: AsyncIOMotorGridFSBucket = app.state.gridfs
    filename = file.filename if file.filename else "unnamed.bin"
    file_hash = hashlib.sha256()

    async def stream_file():
        while chunk := await file.read(1024 * 1024):  # 1MB chunks
            file_hash.update(chunk)
            yield chunk

    gridfs_id = await gridfs.upload_from_stream(filename=filename, source=stream_file())
    await FileMetadata(
        filename=filename, last_modified=current_utc_timestamp(), gridfs_id=gridfs_id, file_hash=file_hash.hexdigest()
    ).insert()
    return {"filename": filename, "gridfs_id": str(gridfs_id), "file_hash": file_hash.hexdigest()}


# S3 Compliant Endpoints
@app.put("/{filename}")
async def upload_object(filename: str, file: UploadFile = File(...), app: FastAPI = FastAPI()):
    gridfs: AsyncIOMotorGridFSBucket = app.state.gridfs
    file_hash = hashlib.sha256()

    async def stream_file():
        while chunk := await file.read(1024 * 1024):  # 1MB chunks
            file_hash.update(chunk)
            yield chunk

    gridfs_id = await gridfs.upload_from_stream(filename=filename, source=stream_file())
    await FileMetadata(
        filename=filename, last_modified=current_utc_timestamp(), gridfs_id=gridfs_id, file_hash=file_hash.hexdigest()
    ).insert()
    return Response(status_code=status.HTTP_201_CREATED)


@app.get("/{filename}")
async def download_object(
    filename: str, app: FastAPI, range_header: Optional[str] = Header(None), if_none_match: Optional[str] = Header(None)
):
    file_metadata = await FileMetadata.find_one(FileMetadata.filename == filename)
    if not file_metadata:
        raise HTTPException(status_code=404, detail="File not found")

    if if_none_match and file_metadata.file_hash == if_none_match:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED)

    gridfs = app.state.gridfs
    gridfs_file = await gridfs.open_download_stream(file_metadata.gridfs_id)
    if not gridfs_file:
        raise HTTPException(status_code=500, detail="GridFS file not found")

    async def generate_chunks():
        try:
            while True:
                chunk = await gridfs_file.readchunk()
                if not chunk:
                    break
                yield chunk
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading GridFS file: {e}")

    return Response(
        content=generate_chunks(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}", "ETag": file_metadata.file_hash},
    )


# Other S3-like Endpoints
@app.get("/list/", response_model=List[FileMetadata])
async def list_objects():
    return await FileMetadata.find_all().to_list()


@app.delete("/{filename}")
async def delete_object(filename: str, app: FastAPI):
    file_metadata = await FileMetadata.find_one(FileMetadata.filename == filename)
    if not file_metadata:
        raise HTTPException(status_code=404, detail="File not found")

    gridfs = app.state.gridfs
    await gridfs.delete(file_metadata.gridfs_id)
    await file_metadata.delete()
    return {"message": f"File '{filename}' deleted successfully"}


@app.head("/{filename}")
async def get_object_metadata(filename: str):
    file_metadata = await FileMetadata.find_one(FileMetadata.filename == filename)
    if not file_metadata:
        raise HTTPException(status_code=404, detail="File not found")
    return Response(headers={"Last-Modified": str(file_metadata.last_modified), "File-Hash": file_metadata.file_hash})
