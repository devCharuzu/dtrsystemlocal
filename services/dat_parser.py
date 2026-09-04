"""
Parses attlog.dat biometric export files.
Standard format: EMP_NO  YYYY-MM-DD HH:MM:SS  VERIFY_TYPE  IN_OUT  DEVICE_ID
Collision rule: same employee, same half-day (AM/PM), within 5 minutes → blank + flag.
"""
import pandas as pd
from datetime import datetime
from sqlalchemy.orm import Session
from models import Employee, RawLog, DTRCell


COLLISION_WINDOW_MINUTES = 5
DATETIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y %H:%M",
]


def parse_dat_file(file_bytes: bytes, source_filename: str, db: Session) -> dict:
    """Ingest raw .dat bytes → store raw logs → resolve DTR cells.

    NOTE: Duplicate-file blocking is handled upstream in the router.
          This function no longer deletes existing records for the same
          filename — that behaviour was the source of the data-loss bug.
    """
    lines = file_bytes.decode("utf-8", errors="ignore").strip().splitlines()
    records = []
    skipped = 0

    for line in lines:
        record = _parse_line(line)
        if not record:
            skipped += 1
            continue
        records.append(record)

    if not records:
        return {
            "parsed": 0,
            "skipped": skipped,
            "unmatched_employees": [],
            "collisions": 0,
            "cells_written": 0,
        }

    df = pd.DataFrame(records)
    df.sort_values(["employee_number", "punch_datetime"], inplace=True)

    collision_count = 0
    cells_written = 0
    unmatched_employees = set()
    employee_lookup = _employee_lookup(db)
    store_raw_logs = not db.query(RawLog.id).filter_by(source_file=source_filename).first()

    for emp_no, group in df.groupby("employee_number"):
        employee = employee_lookup.get(emp_no) or employee_lookup.get(_normalize_emp_no(emp_no))
        if not employee:
            unmatched_employees.add(emp_no)
            continue

        # Store raw logs
        if store_raw_logs:
            for _, row in group.iterrows():
                db.add(
                    RawLog(
                        employee_id=employee.id,
                        punch_datetime=row["punch_datetime"],
                        source_file=source_filename,
                    )
                )

        # Resolve DTR cells per day
        group["date"] = group["punch_datetime"].dt.date
        for work_date, day_group in group.groupby("date"):
            resolved, day_collisions = _resolve_day_punches(
                sorted(
                    day_group[["punch_datetime", "punch_state"]].to_dict("records"),
                    key=lambda row: row["punch_datetime"],
                )
            )
            collision_count += day_collisions
            for slot_name, cell_data in resolved.items():
                _upsert_cell(
                    db,
                    employee.id,
                    work_date,
                    slot_name,
                    cell_data["time_value"],
                    cell_data["is_flagged"],
                )
                cells_written += 1

    return {
        "parsed": len(records),
        "skipped": skipped,
        "unmatched_employees": sorted(unmatched_employees),
        "collisions": collision_count,
        "cells_written": cells_written,
    }


def _parse_line(line: str) -> dict | None:
    parts = line.strip().replace(",", " ").split()
    if len(parts) < 3:
        return None

    emp_no = parts[0].strip()
    dt_candidates = [
        f"{parts[1]} {parts[2]}",
        " ".join(parts[1:3]),
    ]

    for dt_str in dt_candidates:
        punch_dt = _parse_datetime(dt_str)
        if punch_dt:
            punch_state = parts[4].strip() if len(parts) > 4 else None
            return {
                "employee_number": emp_no,
                "punch_datetime": punch_dt,
                "punch_state": punch_state,
            }
    return None


def _parse_datetime(value: str) -> datetime | None:
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _employee_lookup(db: Session) -> dict:
    lookup = {}
    for employee in db.query(Employee).all():
        lookup[employee.employee_number] = employee
        lookup[_normalize_emp_no(employee.employee_number)] = employee
    return lookup


def _normalize_emp_no(value: str) -> str:
    value = str(value).strip()
    return value.lstrip("0") or "0"


def _resolve_day_punches(punches: list[dict]) -> tuple[dict, int]:
    slots = {
        "AM_IN": {"time_value": None, "is_flagged": False},
        "AM_OUT": {"time_value": None, "is_flagged": False},
        "PM_IN": {"time_value": None, "is_flagged": False},
        "PM_OUT": {"time_value": None, "is_flagged": False},
    }
    if not punches:
        return slots, 0

    collision_indexes = set()
    for idx in range(1, len(punches)):
        delta = (
            punches[idx]["punch_datetime"] - punches[idx - 1]["punch_datetime"]
        ).total_seconds() / 60
        if delta <= COLLISION_WINDOW_MINUTES:
            collision_indexes.update([idx - 1, idx])

    clean = [p for idx, p in enumerate(punches) if idx not in collision_indexes]
    collision_count = 1 if collision_indexes else 0
    state_slots = _resolve_by_device_state(clean)
    if state_slots:
        for slot, punch in state_slots.items():
            _assign_slot(slots, slot, punch["punch_datetime"])
    else:
        _resolve_by_sequence(clean, slots)

    for idx in collision_indexes:
        slot = _slot_for_punch(punches[idx], idx, len(punches))
        slots[slot]["time_value"] = None
        slots[slot]["is_flagged"] = True

    return slots, collision_count


def _resolve_by_device_state(punches: list[dict]) -> dict:
    state_to_slot = {
        "0": "AM_IN",
        "2": "AM_OUT",
        "3": "PM_IN",
        "1": "PM_OUT",
    }
    resolved = {}
    for punch in punches:
        slot = state_to_slot.get(str(punch.get("punch_state", "")).strip())
        if not slot:
            continue
        if slot in ("AM_IN", "PM_IN"):
            current = resolved.get(slot)
            if current is None or punch["punch_datetime"] < current["punch_datetime"]:
                resolved[slot] = punch
        else:
            current = resolved.get(slot)
            if current is None or punch["punch_datetime"] > current["punch_datetime"]:
                resolved[slot] = punch
    return resolved


def _resolve_by_sequence(clean: list[dict], slots: dict) -> None:
    datetimes = [p["punch_datetime"] for p in clean]
    if len(datetimes) >= 4:
        ordered = ["AM_IN", "AM_OUT", "PM_IN", "PM_OUT"]
        selected = [datetimes[0], datetimes[1], datetimes[2], datetimes[-1]]
        for slot, punch_dt in zip(ordered, selected):
            _assign_slot(slots, slot, punch_dt)
    elif len(datetimes) == 3:
        first, second, third = datetimes
        if first.hour >= 12:
            _assign_slot(slots, "AM_OUT", first)
            _assign_slot(slots, "PM_IN", second)
            _assign_slot(slots, "PM_OUT", third)
        else:
            _assign_slot(slots, "AM_IN", first)
            _assign_slot(slots, "AM_OUT", second)
            _assign_slot(slots, "PM_OUT", third)
    elif len(datetimes) == 2:
        first, second = datetimes
        if first.hour < 12 and second.hour < 13:
            _assign_slot(slots, "AM_IN", first)
            _assign_slot(slots, "AM_OUT", second)
        elif first.hour >= 12:
            _assign_slot(slots, "PM_IN", first)
            _assign_slot(slots, "PM_OUT", second)
        else:
            _assign_slot(slots, "AM_IN", first)
            _assign_slot(slots, "PM_OUT", second)
    elif len(datetimes) == 1:
        punch_dt = datetimes[0]
        slot = "AM_IN" if punch_dt.hour < 12 else "PM_IN"
        _assign_slot(slots, slot, punch_dt)


def _slot_for_index(index: int, total: int) -> str:
    if total >= 4:
        if index == 0:
            return "AM_IN"
        if index == 1:
            return "AM_OUT"
        if index == 2:
            return "PM_IN"
        return "PM_OUT"
    return ["AM_IN", "AM_OUT", "PM_IN", "PM_OUT"][min(index, 3)]


def _slot_for_punch(punch: dict, index: int, total: int) -> str:
    """Use the device's explicit slot before falling back to sequence position."""
    state_to_slot = {
        "0": "AM_IN",
        "2": "AM_OUT",
        "3": "PM_IN",
        "1": "PM_OUT",
    }
    return state_to_slot.get(str(punch.get("punch_state", "")).strip()) or _slot_for_index(
        index, total
    )


def _format_time(value: datetime) -> str:
    return f"{value.hour % 12 or 12}:{value.minute:02d}"


def _assign_slot(slots: dict, slot: str, punch_dt: datetime) -> None:
    slots[slot]["time_value"] = _format_time(punch_dt)
    if _is_schedule_flag(slot, punch_dt):
        slots[slot]["is_flagged"] = True


def _is_schedule_flag(slot: str, punch_dt: datetime) -> bool:
    minutes = punch_dt.hour * 60 + punch_dt.minute
    if slot == "AM_IN":
        return minutes > 8 * 60
    if slot == "AM_OUT":
        return minutes < 12 * 60
    if slot == "PM_IN":
        return minutes > 13 * 60
    if slot == "PM_OUT":
        return minutes < 17 * 60
    return False


def _upsert_cell(db, employee_id, work_date, slot, time_val, flagged):
    cell = db.query(DTRCell).filter_by(
        employee_id=employee_id, work_date=work_date, slot=slot
    ).first()
    if cell:
        cell.time_value = time_val
        cell.is_flagged = flagged
    else:
        cell = DTRCell(
            employee_id=employee_id,
            work_date=work_date,
            slot=slot,
            time_value=time_val,
            is_flagged=flagged,
        )
        db.add(cell)
