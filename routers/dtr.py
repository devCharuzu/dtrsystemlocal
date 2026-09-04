from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from models import Employee, DTRCell, AuditLog, Verifier, format_display_time, undertime_hm
from services.pdf_generator import generate_form48_pdf
from datetime import date, datetime
from pathlib import Path
import calendar
import io
import re
from pypdf import PdfWriter

router = APIRouter(prefix="/dtr", tags=["dtr"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

SLOTS = ["AM_IN", "AM_OUT", "PM_IN", "PM_OUT"]


@router.get("/", response_class=HTMLResponse)
def dtr_home(request: Request, db: Session = Depends(get_db)):
    employees = db.query(Employee).order_by(Employee.full_name).all()
    return templates.TemplateResponse(
        request,
        "dtr_home.html",
        {"employees": employees, "now": datetime.now()},
    )


@router.get("/grid", response_class=HTMLResponse)
def dtr_grid(
    request: Request,
    employee_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    start_day: int = Query(1),
    end_day: int = Query(None),
    db: Session = Depends(get_db),
):
    if end_day is None:
        end_day = calendar.monthrange(year, month)[1]
    _validate_period(year, month, start_day, end_day)

    employee = db.query(Employee).filter_by(id=employee_id).first()
    if not employee:
        return HTMLResponse("Employee not found", status_code=404)
    verifiers = db.query(Verifier).order_by(Verifier.is_default.desc(), Verifier.name).all()
    default_verifier = next((verifier for verifier in verifiers if verifier.is_default), None)

    same_type_employees = (
        db.query(Employee)
        .filter(Employee.employment_type == employee.employment_type)
        .order_by(Employee.full_name)
        .all()
    )
    emp_ids = [e.id for e in same_type_employees]
    current_index = emp_ids.index(employee_id) if employee_id in emp_ids else -1
    prev_employee = same_type_employees[current_index - 1] if current_index > 0 else None
    next_employee = same_type_employees[current_index + 1] if current_index >= 0 and current_index < len(same_type_employees) - 1 else None

    dates = [date(year, month, d) for d in range(start_day, end_day + 1)]
    cells = (
        db.query(DTRCell)
        .filter(
            DTRCell.employee_id == employee_id,
            DTRCell.work_date >= dates[0],
            DTRCell.work_date <= dates[-1],
        )
        .all()
    )

    # Build lookup: {date: {slot: cell}}
    cell_map = {}
    for c in cells:
        cell_map.setdefault(c.work_date, {})[c.slot] = c

    # Precompute per-day undertime (hours, minutes, total_minutes)
    undertime_map = {}
    for d in dates:
        day = cell_map.get(d, {})
        slots = {s: (day[s].display_time if day.get(s) else "") for s in SLOTS}
        undertime_map[d] = undertime_hm(slots)

    return templates.TemplateResponse(
        request,
        "dtr_grid.html",
        {
            "employee": employee,
            "dates": dates,
            "cell_map": cell_map,
            "undertime_map": undertime_map,
            "slots": SLOTS,
            "year": year,
            "month": month,
            "start_day": start_day,
        "end_day": end_day,
        "month_name": calendar.month_name[month],
        "verifiers": verifiers,
        "default_verifier": default_verifier,
        "prev_employee": prev_employee,
        "next_employee": next_employee,
        },
    )


@router.post("/cell/update")
def update_cell(payload: dict, db: Session = Depends(get_db)):
    """Called by JS when HR manually edits a cell."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid request body.")
    try:
        employee_id = int(payload.get("employee_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid employee ID.")
    if not db.query(Employee.id).filter_by(id=employee_id).first():
        raise HTTPException(status_code=404, detail="Employee not found.")

    work_date_str = payload.get("work_date")
    slot = payload.get("slot")
    if slot not in SLOTS:
        raise HTTPException(status_code=400, detail="Invalid DTR slot.")
    try:
        work_date = date.fromisoformat(work_date_str)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid work date.")

    raw_value = payload.get("new_value", "")
    if not isinstance(raw_value, str):
        raise HTTPException(status_code=400, detail="Time must be text in H:MM format.")
    new_value = raw_value.strip() or None
    if new_value and not re.fullmatch(r"(?:[1-9]|1[0-2]):[0-5]\d", new_value):
        raise HTTPException(status_code=400, detail="Time must use H:MM in 12-hour format.")

    admin_user = payload.get("admin_user", "HR Admin")
    if not isinstance(admin_user, str) or not admin_user.strip():
        raise HTTPException(status_code=400, detail="Editor name is required.")
    admin_user = admin_user.strip()
    if len(admin_user) > 80:
        raise HTTPException(status_code=400, detail="Editor name is too long.")

    cell = db.query(DTRCell).filter_by(
        employee_id=employee_id, work_date=work_date, slot=slot
    ).first()

    is_flagged = _is_schedule_flag(slot, new_value)

    if not cell:
        cell = DTRCell(
            employee_id=employee_id,
            work_date=work_date,
            slot=slot,
            time_value=new_value,
            is_flagged=is_flagged,
        )
        db.add(cell)
        db.flush()
        original_value = None
    else:
        original_value = cell.time_value
        cell.time_value = new_value
        cell.is_flagged = is_flagged

    # Write audit trail
    audit = AuditLog(
        dtr_cell_id=cell.id,
        admin_user=admin_user,
        original_value=original_value,
        new_value=new_value,
        changed_at=datetime.utcnow(),
    )
    db.add(audit)
    db.commit()

    # Recompute the day's undertime from all four slots so the grid can refresh
    day_cells = db.query(DTRCell).filter_by(
        employee_id=employee_id, work_date=work_date
    ).all()
    day_slots = {c.slot: c.display_time for c in day_cells}
    hours, minutes, total = undertime_hm(day_slots)

    return JSONResponse({
        "success": True,
        "cell_id": cell.id,
        "flagged": is_flagged,
        "undertime": {"hours": hours, "minutes": minutes, "total": total},
    })


@router.post("/verifiers")
def create_verifier(payload: dict, db: Session = Depends(get_db)):
    name = str(payload.get("name", "")).strip()
    position = str(payload.get("position", "")).strip()
    make_default = bool(payload.get("make_default", True))
    if not name or not position:
        raise HTTPException(status_code=400, detail="Verifier name and designation are required.")

    verifier = Verifier(name=name, position=position, is_default=False)
    db.add(verifier)
    db.flush()
    if make_default:
        _set_default_verifier(db, verifier)
    db.commit()
    db.refresh(verifier)

    return JSONResponse(
        {
            "success": True,
            "verifier": {
                "id": verifier.id,
                "name": verifier.name,
                "position": verifier.position,
                "is_default": verifier.is_default,
            },
        }
    )


@router.post("/verifiers/{verifier_id}/default")
def set_default_verifier(verifier_id: int, db: Session = Depends(get_db)):
    verifier = db.query(Verifier).filter_by(id=verifier_id).first()
    if not verifier:
        raise HTTPException(status_code=404, detail="Verifier not found.")
    _set_default_verifier(db, verifier)
    db.commit()
    return JSONResponse({"success": True})


@router.get("/pdf")
def export_pdf(
    employee_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    start_day: int = Query(1),
    end_day: int = Query(None),
    verifier_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    if end_day is None:
        end_day = calendar.monthrange(year, month)[1]
    _validate_period(year, month, start_day, end_day)

    employee = db.query(Employee).filter_by(id=employee_id).first()
    if not employee:
        return JSONResponse(status_code=404, content={"error": "Employee not found."})

    dates = [date(year, month, d) for d in range(start_day, end_day + 1)]
    cells = (
        db.query(DTRCell)
        .filter(
            DTRCell.employee_id == employee_id,
            DTRCell.work_date >= dates[0],
            DTRCell.work_date <= dates[-1],
        )
        .all()
    )

    dtr_data = {}
    for c in cells:
        ds = c.work_date.isoformat()
        dtr_data.setdefault(ds, {"AM_IN": "", "AM_OUT": "", "PM_IN": "", "PM_OUT": "", "flags": []})
        dtr_data[ds][c.slot] = format_display_time(c.time_value)
        if c.is_flagged:
            dtr_data[ds]["flags"].append(c.slot)

    emp_dict = {
        "employee_number": employee.employee_number,
        "full_name": employee.full_name,
        "position": employee.position,
        "office_division": employee.office_division,
    }

    verifier = None
    if verifier_id:
        verifier = db.query(Verifier).filter_by(id=verifier_id).first()
    if not verifier:
        verifier = db.query(Verifier).filter_by(is_default=True).first()
    certifier = {
        "name": verifier.name if verifier else "",
        "position": verifier.position if verifier else "",
    }

    pdf_bytes = generate_form48_pdf(
        emp_dict,
        dtr_data,
        year,
        month,
        start_day,
        end_day,
        certifier,
    )

    month_name = calendar.month_name[month]
    filename = f"{employee.full_name} - {month_name} {year}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/pdf/batch")
def batch_export_pdf(
    employment_type: str = Query(...),  # "PERMANENT" or "COS_JO"
    year: int = Query(...),
    month: int = Query(...),
    start_day: int = Query(1),
    end_day: int = Query(None),
    verifier_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    if end_day is None:
        end_day = calendar.monthrange(year, month)[1]
    _validate_period(year, month, start_day, end_day)

    if employment_type not in ("PERMANENT", "COS_JO"):
        raise HTTPException(status_code=400, detail="employment_type must be PERMANENT or COS_JO")

    employees = (
        db.query(Employee)
        .filter(Employee.employment_type == employment_type)
        .order_by(Employee.full_name)
        .all()
    )
    if not employees:
        raise HTTPException(status_code=404, detail="No employees found for the selected type.")

    verifier = None
    if verifier_id:
        verifier = db.query(Verifier).filter_by(id=verifier_id).first()
    if not verifier:
        verifier = db.query(Verifier).filter_by(is_default=True).first()
    certifier = {
        "name": verifier.name if verifier else "",
        "position": verifier.position if verifier else "",
    }

    dates = [date(year, month, d) for d in range(start_day, end_day + 1)]
    writer = PdfWriter()

    for employee in employees:
        cells = (
            db.query(DTRCell)
            .filter(
                DTRCell.employee_id == employee.id,
                DTRCell.work_date >= dates[0],
                DTRCell.work_date <= dates[-1],
            )
            .all()
        )
        dtr_data = {}
        for c in cells:
            ds = c.work_date.isoformat()
            dtr_data.setdefault(ds, {"AM_IN": "", "AM_OUT": "", "PM_IN": "", "PM_OUT": "", "flags": []})
            dtr_data[ds][c.slot] = format_display_time(c.time_value)
            if c.is_flagged:
                dtr_data[ds]["flags"].append(c.slot)

        emp_dict = {
            "employee_number": employee.employee_number,
            "full_name": employee.full_name,
            "position": employee.position,
            "office_division": employee.office_division,
        }
        pdf_bytes = generate_form48_pdf(emp_dict, dtr_data, year, month, start_day, end_day, certifier)
        writer.append(io.BytesIO(pdf_bytes))

    out = io.BytesIO()
    writer.write(out)
    merged_bytes = out.getvalue()

    month_name = calendar.month_name[month]
    type_label = "COS-JO" if employment_type == "COS_JO" else "Permanent"
    filename = f"DTR Batch - {type_label} - {month_name} {year}.pdf"

    return Response(
        content=merged_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/audit")
def audit_log(employee_id: int = Query(...), db: Session = Depends(get_db)):
    logs = (
        db.query(AuditLog)
        .join(DTRCell)
        .filter(DTRCell.employee_id == employee_id)
        .order_by(AuditLog.changed_at.desc())
        .limit(200)
        .all()
    )
    result = [
        {
            "cell_id": l.dtr_cell_id,
            "admin": l.admin_user,
            "original": _time_with_period(l.original_value, l.dtr_cell.slot),
            "new": _time_with_period(l.new_value, l.dtr_cell.slot),
            "changed_at": l.changed_at.isoformat(),
            "work_date": l.dtr_cell.work_date.isoformat(),
            "slot": l.dtr_cell.slot,
        }
        for l in logs
    ]
    return JSONResponse(result)


def _time_with_period(value: str | None, slot: str = "") -> str | None:
    """Return a time string with AM/PM appended, slot-aware."""
    display = format_display_time(value)
    if not display or ":" not in display:
        return display or None
    try:
        hour = int(display.split(":")[0])
        if slot in ("PM_IN", "PM_OUT") or hour == 12:
            period = "PM"
        else:
            period = "AM"
        return f"{display} {period}"
    except ValueError:
        return display


def _validate_period(year: int, month: int, start_day: int, end_day: int) -> None:
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Month must be between 1 and 12.")
    max_day = calendar.monthrange(year, month)[1]
    if start_day < 1 or end_day > max_day or start_day > end_day:
        raise HTTPException(status_code=400, detail="Invalid date range.")


def _set_default_verifier(db: Session, verifier: Verifier) -> None:
    db.query(Verifier).update({Verifier.is_default: False})
    verifier.is_default = True


def _is_schedule_flag(slot: str, value: str | None) -> bool:
    """
    Returns True if the entered time violates the standard schedule:
      AM_IN  : arrival after 08:00
      AM_OUT : departure before 12:00
      PM_IN  : arrival after 13:00
      PM_OUT : departure before 17:00

    Times are stored as 12-hour strings without an AM/PM suffix (e.g. "8:05",
    "12:00", "1:30").  We must infer the 24-hour hour from the slot context:
      AM slots → hours 1-11 stay as-is; 12 means noon (12:xx)
      PM slots → hours 1-11 are post-noon (+12); 12 means noon (12:xx)
    """
    if not value:
        return False
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text[:2])
    except (ValueError, AttributeError):
        return False

    # Convert stored 12-hour display value to 24-hour for comparison
    if slot in ("PM_IN", "PM_OUT"):
        # 12 → 12 (noon/early-PM), 1-11 → 13-23
        if hour != 12:
            hour += 12
    elif slot == "AM_IN":
        # AM_IN: 12 would mean midnight — treat as 0 as a guard
        if hour == 12:
            hour = 0
    # AM_OUT: 12 means noon (12:00), leave as-is

    minutes_total = hour * 60 + minute

    if slot == "AM_IN":
        return minutes_total > 8 * 60          # late if after 08:00
    if slot == "AM_OUT":
        return minutes_total < 12 * 60         # undertime if before 12:00
    if slot == "PM_IN":
        return minutes_total > 13 * 60         # late if after 13:00
    if slot == "PM_OUT":
        return minutes_total < 17 * 60         # undertime if before 17:00
    return False
