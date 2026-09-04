from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from models import AuditLog, DTRCell, Employee, RawLog
from pathlib import Path

router = APIRouter(prefix="/employees", tags=["employees"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

VALID_EMPLOYMENT_TYPES = {"PERMANENT", "COS_JO"}


@router.get("/", response_class=HTMLResponse)
def list_employees(request: Request, db: Session = Depends(get_db)):
    employees = db.query(Employee).order_by(Employee.full_name).all()
    return templates.TemplateResponse(
        request,
        "employees.html",
        {"employees": employees},
    )


@router.post("/add")
def add_employee(
    employee_number: str = Form(...),
    full_name: str = Form(...),
    position: str = Form(""),
    office_division: str = Form(""),
    employment_type: str = Form("PERMANENT"),
    db: Session = Depends(get_db),
):
    employee_number = employee_number.strip()
    full_name = full_name.strip()
    position = position.strip()
    office_division = office_division.strip()
    employment_type = employment_type.strip().upper()
    if employment_type not in VALID_EMPLOYMENT_TYPES:
        employment_type = "PERMANENT"

    if _employee_number_exists(db, employee_number):
        raise HTTPException(status_code=400, detail="Employee number already exists.")

    emp = Employee(
        employee_number=employee_number,
        full_name=full_name,
        position=position,
        office_division=office_division,
        employment_type=employment_type,
    )
    db.add(emp)
    db.commit()
    return RedirectResponse("/employees/", status_code=303)


@router.post("/edit/{emp_id}")
def edit_employee(
    emp_id: int,
    employee_number: str = Form(...),
    full_name: str = Form(...),
    position: str = Form(""),
    office_division: str = Form(""),
    employment_type: str = Form("PERMANENT"),
    db: Session = Depends(get_db),
):
    emp = db.query(Employee).filter_by(id=emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Not found.")

    employee_number = employee_number.strip()
    full_name = full_name.strip()
    position = position.strip()
    office_division = office_division.strip()
    employment_type = employment_type.strip().upper()
    if employment_type not in VALID_EMPLOYMENT_TYPES:
        employment_type = "PERMANENT"

    if _employee_number_exists(db, employee_number, exclude_id=emp_id):
        raise HTTPException(status_code=400, detail="Employee number already exists.")

    emp.employee_number = employee_number
    emp.full_name = full_name
    emp.position = position
    emp.office_division = office_division
    emp.employment_type = employment_type
    db.commit()
    return RedirectResponse("/employees/", status_code=303)


@router.post("/delete/{emp_id}")
def delete_employee(emp_id: int, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter_by(id=emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Not found.")

    cell_ids = [row.id for row in db.query(DTRCell.id).filter_by(employee_id=emp_id).all()]
    if cell_ids:
        db.query(AuditLog).filter(AuditLog.dtr_cell_id.in_(cell_ids)).delete(synchronize_session=False)
    db.query(DTRCell).filter_by(employee_id=emp_id).delete(synchronize_session=False)
    db.query(RawLog).filter_by(employee_id=emp_id).delete(synchronize_session=False)
    db.query(Employee).filter_by(id=emp_id).delete(synchronize_session=False)
    db.commit()
    return RedirectResponse("/employees/", status_code=303)


def _employee_number_exists(db: Session, employee_number: str, exclude_id: int | None = None) -> bool:
    normalized = _normalize_employee_number(employee_number)
    query = db.query(Employee)
    if exclude_id is not None:
        query = query.filter(Employee.id != exclude_id)
    for employee in query.all():
        if _normalize_employee_number(employee.employee_number) == normalized:
            return True
    return False


def _normalize_employee_number(value: str) -> str:
    value = str(value).strip()
    return value.lstrip("0") or "0"
