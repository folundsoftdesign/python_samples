import hashlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from io import BytesIO
from typing import List, Optional

from beanie import Document, PydanticObjectId, init_beanie
from fastapi import FastAPI, File, Header, HTTPException, Query, Response, UploadFile
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorGridFSBucket
from pydantic import BaseModel
from starlette import status

MONGO_URI = "mongodb://root:secret@172.17.0.1:30001"
DATABASE_NAME = "sample"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Utilities
def current_utc_timestamp():
    return datetime.now(timezone.utc)


class FileMetadata(Document):
    filename: str
    last_modified: datetime
    gridfs_id: PydanticObjectId
    file_hash: Optional[str] = None

    class Config:
        collection = "file_metadata"
        arbitrary_types_allowed = True


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
    logger.info("Lifecycle started")

    client: AsyncIOMotorClient = AsyncIOMotorClient(MONGO_URI)
    db: AsyncIOMotorDatabase = client[DATABASE_NAME]
    await init_beanie(database=db, document_models=[FileMetadata])
    gridfs = AsyncIOMotorGridFSBucket(db)

    app.state.gridfs = gridfs

    # await seed_database(gridfs)
    yield


app = FastAPI(lifespan=lifespan)


# Old Upload and Download Endpoints
@app.get("/download/{filename}")
async def download_file(filename: str, filehash: Optional[str] = Query(None)):
    file_metadata = await FileMetadata.find_one(FileMetadata.filename == filename)
    if not file_metadata:
        raise HTTPException(status_code=404, detail="File not found")

    gridfs = app.state.gridfs
    gridfs_file = await gridfs.open_download_stream(file_metadata.gridfs_id)
    if not gridfs_file:
        raise HTTPException(status_code=500, detail="GridFS file not found")

    content = await gridfs_file.read()

    if filehash:
        if file_metadata.file_hash == filehash:
            return Response(status_code=status.HTTP_304_NOT_MODIFIED)

    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


class UploadResponse(BaseModel):
    filename: str
    gridfs_id: str
    file_hash: str


@app.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)) -> UploadResponse:
    gridfs: AsyncIOMotorGridFSBucket = app.state.gridfs
    filename = file.filename if file.filename else "unnamed.bin"
    file_hash = hashlib.sha256()
    file_content = b""

    try:
        while chunk := await file.read(1024 * 1024):  # Read in 1MB chunks
            file_content += chunk
            file_hash.update(chunk)

        gridfs_id = await gridfs.upload_from_stream(filename=filename, source=BytesIO(file_content))

        await FileMetadata(
            filename=filename,
            last_modified=current_utc_timestamp(),
            gridfs_id=gridfs_id,
            file_hash=file_hash.hexdigest(),
        ).insert()

        return UploadResponse(filename=filename, gridfs_id=str(gridfs_id), file_hash=file_hash.hexdigest())

    except Exception as e:
        # Handle potential errors during file reading or GridFS upload
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")
    finally:
        await file.close()  # close the file stream.


# S3 Compliant Endpoints
@app.put("/{filename}")
async def upload_object(filename: str, file: UploadFile = File(...)):
    gridfs: AsyncIOMotorGridFSBucket = app.state.gridfs
    file_hash = hashlib.sha256()
    file_content = b""

    try:
        while chunk := await file.read(1024 * 1024):  # Read in 1MB chunks
            file_content += chunk
            file_hash.update(chunk)

        gridfs_id = await gridfs.upload_from_stream(filename=filename, source=BytesIO(file_content))

        await FileMetadata(
            filename=filename,
            last_modified=current_utc_timestamp(),
            gridfs_id=gridfs_id,
            file_hash=file_hash.hexdigest(),
        ).insert()

        return Response(status_code=status.HTTP_201_CREATED, headers={"ETag": file_hash.hexdigest()})

    except Exception as e:
        # Handle potential errors during file reading or GridFS upload
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")
    finally:
        await file.close()  # close the file stream.


@app.get("/list", response_model=List[FileMetadata])
async def list_objects():
    return await FileMetadata.find_all().to_list()


@app.get("/{filename}")
async def download_object(filename: str, range_header: Optional[str] = Header(None), if_none_match: Optional[str] = Header(None)):
    """
    Downloads a file from GridFS, supporting partial content requests and conditional GETs.

    This endpoint retrieves a file from GridFS based on the provided filename. It supports:

    -   **Partial Content Requests (Range Header):**
        -   Allows clients to request specific byte ranges of the file, enabling resumable downloads and efficient streaming of large files.
        -   If a valid `Range` header is provided, the endpoint returns a `206 Partial Content` response with the requested byte range.
        -   If the `Range` header is invalid, a `416 Requested Range Not Satisfiable` response is returned.

    -   **Conditional GETs (If-None-Match Header):**
        -   Supports conditional GET requests using the `If-None-Match` header.
        -   If the provided `If-None-Match` value matches the file's ETag (file hash), a `304 Not Modified` response is returned, indicating that the client's cached version is up-to-date.

    -   **Standard File Download:**
        -   If no `Range` or `If-None-Match` headers are provided, the endpoint returns the entire file with a `200 OK` response.

    Args:
        filename (str): The name of the file to download.
        app (FastAPI): The FastAPI application instance.
        range_header (Optional[str]): The HTTP `Range` header, specifying the requested byte range.
        if_none_match (Optional[str]): The HTTP `If-None-Match` header, used for conditional GETs.

    Returns:
        Response: The file content or a response indicating partial content or not modified.

    Raises:
        HTTPException:
            -   404: If the file is not found.
            -   416: If the `Range` header is invalid.
            -   500: If there is an error accessing GridFS.
    """
    file_metadata = await FileMetadata.find_one(FileMetadata.filename == filename)
    if not file_metadata:
        raise HTTPException(status_code=404, detail="File not found")

    if if_none_match and file_metadata.file_hash == if_none_match:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED)

    gridfs = app.state.gridfs
    gridfs_file = await gridfs.open_download_stream(file_metadata.gridfs_id)
    if not gridfs_file:
        raise HTTPException(status_code=500, detail="GridFS file not found")

    if range_header:
        try:
            start, end = parse_range_header(range_header, gridfs_file.length)
            gridfs_file = await gridfs.open_download_stream(file_metadata.gridfs_id, skip=start, limit=end - start + 1)
            content = await gridfs_file.read()
            return Response(
                content=content,
                media_type="application/octet-stream",
                status_code=status.HTTP_206_PARTIAL_CONTENT,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{gridfs_file.length}",
                    "Content-Length": str(len(content)),
                    "ETag": file_metadata.file_hash,
                },
            )
        except ValueError:
            raise HTTPException(status_code=416, detail="Invalid Range")

    else:
        content = await gridfs_file.read()
        return Response(
            content=content,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "ETag": file_metadata.file_hash,
                "Content-Length": str(gridfs_file.length),
            },
        )


def parse_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    """Parses the Range header."""
    if not range_header.startswith("bytes="):
        raise ValueError("Invalid range header")
    ranges = range_header[6:].split("-")
    start = int(ranges[0]) if ranges[0] else 0
    end = int(ranges[1]) if ranges[1] else file_size - 1
    if start < 0:
        start = file_size + start
    if end >= file_size:
        end = file_size - 1
    if start > end:
        raise ValueError("Invalid range")
    return start, end


@app.delete("/{filename}")
async def delete_object(filename: str):
    file_metadata = await FileMetadata.find_one(FileMetadata.filename == filename)
    if not file_metadata:
        raise HTTPException(status_code=404, detail="File not found")
