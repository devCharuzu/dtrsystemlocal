from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models import UploadedXlsFile
from services.xls_parser import XlsFormatError, parse_xls_file
from services.upload_storage import is_safe_stored_path, validate_upload_filename

router = APIRouter(prefix="/xlslogs", tags=["xlslogs"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# Directory where uploaded .xls exports are permanently stored
XLS_STORE = Path(__file__).resolve().parent.parent / "xls_uploads"
XLS_STORE.mkdir(exist_ok=True)


@router.get("/", response_class=HTMLResponse)
def upload_page(request: Request, db: Session = Depends(get_db)):
    uploaded_files = (
        db.query(UploadedXlsFile)
        .order_by(UploadedXlsFile.uploaded_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "xlslogs.html",
        {"uploaded_files": uploaded_files},
    )


@router.post("/upload")
async def upload_xls(file: UploadFile = File(...), db: Session = Depends(get_db)):
    # ── 1. Extension guard ────────────────────────────────────────────────────
    try:
        filename = validate_upload_filename(file.filename, ".xls")
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={
                "error": (
                    "Only .xls files are accepted. If your file is .xlsx, open it "
                    "and save as 'Excel 97-2003 Workbook (.xls)'."
                )
            },
        )

    # ── 2. Duplicate guard ────────────────────────────────────────────────────
    existing = db.query(UploadedXlsFile).filter_by(filename=filename).first()
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

    # ── 4. Parse first — a bad workbook must not be recorded as ingested ──────
    dest_path = XLS_STORE / filename
    file_created = False
    try:
        result = parse_xls_file(content, filename, db)
        if dest_path.exists():
            db.rollback()
            return JSONResponse(
                status_code=409,
                content={"error": "A local file with this name already exists."},
            )

        # ── 5. Save file and upload record in one guarded transaction ─────────
        dest_path.write_bytes(content)
        file_created = True
        record = UploadedXlsFile(
            filename=filename,
            file_size_bytes=len(content),
            stored_path=str(dest_path),
            period=result.get("period"),
        )
        db.add(record)
        db.commit()
    except XlsFormatError as exc:
        db.rollback()
        return JSONResponse(status_code=400, content={"error": str(exc)})
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
async def delete_xls_file(file_id: int, db: Session = Depends(get_db)):
    record = db.query(UploadedXlsFile).filter_by(id=file_id).first()
    if not record:
        return JSONResponse(
            status_code=404,
            content={"error": "File record not found."},
        )

    # Remove from disk if the file still exists
    if record.stored_path:
        disk_file = Path(record.stored_path)
        if not is_safe_stored_path(disk_file, XLS_STORE):
            return JSONResponse(
                status_code=400,
                content={"error": "Stored file path is outside the upload directory."},
            )
        if disk_file.exists():
            disk_file.unlink()

    db.delete(record)
    db.commit()
    return JSONResponse(content={"success": True, "deleted": record.filename})
