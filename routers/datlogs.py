from fastapi import APIRouter, Depends, UploadFile, File, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from models import RawLog, UploadedDatFile
from services.dat_parser import parse_dat_file
from services.upload_storage import is_safe_stored_path, validate_upload_filename
from pathlib import Path
import shutil

router = APIRouter(prefix="/datlogs", tags=["datlogs"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# Directory where uploaded .dat files are permanently stored
DAT_STORE = Path(__file__).resolve().parent.parent / "dat_uploads"
DAT_STORE.mkdir(exist_ok=True)


@router.get("/", response_class=HTMLResponse)
def upload_page(request: Request, db: Session = Depends(get_db)):
    uploaded_files = (
        db.query(UploadedDatFile)
        .order_by(UploadedDatFile.uploaded_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "datlogs.html",
        {"uploaded_files": uploaded_files},
    )


@router.post("/upload")
async def upload_dat(file: UploadFile = File(...), db: Session = Depends(get_db)):
    # ── 1. Extension guard ────────────────────────────────────────────────────
    try:
        filename = validate_upload_filename(file.filename, ".dat")
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": str(exc)},
        )

    # ── 2. Duplicate guard ────────────────────────────────────────────────────
    existing = db.query(UploadedDatFile).filter_by(filename=filename).first()
    if existing:
        return JSONResponse(
            status_code=409,
            content={
                "error": "duplicate",
                "message": (
                    f"'{filename}' has already been uploaded "
                    f"on {existing.uploaded_at.strftime('%B %d, %Y at %I:%M %p')}. "
                    "Upload a different file or rename it if the data has changed."
                ),
                "uploaded_at": existing.uploaded_at.isoformat(),
            },
        )

    # ── 3. Read bytes ─────────────────────────────────────────────────────────
    content = await file.read()

    # ── 4. Parse before persisting anything ───────────────────────────────────
    result = parse_dat_file(content, filename, db)
    if result["parsed"] == 0:
        db.rollback()
        return JSONResponse(
            status_code=400,
            content={"error": "No valid attendance records were found in this file."},
        )

    # ── 5. Save the file without overwriting an untracked local upload ────────
    dest_path = DAT_STORE / filename
    if dest_path.exists():
        db.rollback()
        return JSONResponse(
            status_code=409,
            content={"error": "A local file with this name already exists."},
        )
    file_created = False
    try:
        dest_path.write_bytes(content)
        file_created = True

        # ── 6. Record the upload so future duplicates are blocked ─────────────
        record = UploadedDatFile(
            filename=filename,
            file_size_bytes=len(content),
            stored_path=str(dest_path),
        )
        db.add(record)
        db.commit()
    except Exception:
        db.rollback()
        if file_created:
            dest_path.unlink(missing_ok=True)
        raise

    return JSONResponse(
        content={
            "success": True,
            "filename": filename,
            "file_size_bytes": len(content),
            **result,
        }
    )


@router.delete("/delete/{file_id}")
async def delete_dat_file(file_id: int, db: Session = Depends(get_db)):
    record = db.query(UploadedDatFile).filter_by(id=file_id).first()
    if not record:
        return JSONResponse(
            status_code=404,
            content={"error": "File record not found."},
        )

    # Remove from disk if the file still exists
    if record.stored_path:
        disk_file = Path(record.stored_path)
        if not is_safe_stored_path(disk_file, DAT_STORE):
            return JSONResponse(
                status_code=400,
                content={"error": "Stored file path is outside the upload directory."},
            )
        if disk_file.exists():
            disk_file.unlink()

    db.delete(record)
    db.commit()
    return JSONResponse(content={"success": True, "deleted": record.filename})


@router.patch("/rename/{file_id}")
async def rename_dat_file(file_id: int, payload: dict, db: Session = Depends(get_db)):
    try:
        new_name = validate_upload_filename(payload.get("new_filename"), ".dat")
    except (AttributeError, ValueError) as exc:
        return JSONResponse(
            status_code=400,
            content={"error": str(exc)},
        )

    record = db.query(UploadedDatFile).filter_by(id=file_id).first()
    if not record:
        return JSONResponse(
            status_code=404,
            content={"error": "File record not found."},
        )

    # Check for name collision with another record
    conflict = db.query(UploadedDatFile).filter(
        UploadedDatFile.filename == new_name,
        UploadedDatFile.id != file_id,
    ).first()
    if conflict:
        return JSONResponse(
            status_code=409,
            content={"error": f"A file named '{new_name}' already exists."},
        )

    # Rename on disk
    if record.stored_path:
        old_path = Path(record.stored_path)
        if not is_safe_stored_path(old_path, DAT_STORE):
            return JSONResponse(
                status_code=400,
                content={"error": "Stored file path is outside the upload directory."},
            )
        if old_path.exists():
            new_path = old_path.parent / new_name
            if new_path.exists():
                return JSONResponse(
                    status_code=409,
                    content={"error": f"A local file named '{new_name}' already exists."},
                )
            old_path.rename(new_path)
            record.stored_path = str(new_path)

    old_name = record.filename
    record.filename = new_name
    db.query(RawLog).filter_by(source_file=old_name).update(
        {RawLog.source_file: new_name}, synchronize_session=False
    )
    db.commit()
    return JSONResponse(content={"success": True, "new_filename": new_name})
