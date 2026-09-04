"""
Parses the biometric software's Excel attendance export (.xls).

The workbook's "Logs" sheet holds one row per employee and one column per day
of the month; each cell contains that day's raw punches separated by newlines
(e.g. "08:47\n12:08\n12:08\n18:04"). Those punches are handed to the SAME
resolver the .dat pipeline uses, so both import paths write identical DTRCell
rows (same collision window, same slot rules, same schedule flags).

The one export-specific rule: employees scan ONCE at lunch, so that single
punch is both the AM time-out and the PM time-in. The report prints it twice
in the day cell; this parser collapses the repeat and then writes the time to
both noon slots (see `_mirror_lunch_punch`).

Employee linking: the report prints a "No." and a short name ("ASantos").
The short name is matched against the employee directory first (initial +
surname, then surname alone), because this report's "No." column is a print
sequence in some exports and the biometric number in others. If the name
resolves nothing, "No." is tried as the biometric number — the same key the
.dat importer uses. Every row's outcome is reported back so HR can confirm the
link before trusting the grid; nothing is guessed silently.
"""
import re
from datetime import datetime, time

import xlrd
from sqlalchemy.orm import Session

from models import Employee, RawLog, slot_to_minutes
from services.dat_parser import (
    _employee_lookup,
    _format_time,
    _is_schedule_flag,
    _normalize_emp_no,
    _resolve_day_punches,
    _upsert_cell,
)

LOGS_SHEET = "logs"
PERIOD_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")
TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
NAME_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V"}
# A punch this close to noon is the lunch punch (AM out == PM in).
LUNCH_START_MIN = 11 * 60
LUNCH_END_MIN = 14 * 60


class XlsFormatError(ValueError):
    """The workbook is not the expected attendance export."""


def parse_xls_file(file_bytes: bytes, source_filename: str, db: Session) -> dict:
    """Ingest an .xls attendance export -> raw logs -> resolved DTR cells."""
    sheet = _logs_sheet(file_bytes)
    year, month = _read_period(sheet)
    header_row, day_columns = _read_day_columns(sheet)

    number_lookup = _employee_lookup(db)
    name_lookup = _name_lookup(db)
    store_raw_logs = not db.query(RawLog.id).filter_by(source_file=source_filename).first()

    parsed = 0
    skipped = 0
    collisions = 0
    cells_written = 0
    matches = []          # rows linked to an employee (shown to HR for review)
    unmatched = []        # rows with punches that linked to nobody
    conflicting = []      # name and biometric number point to different people

    for row in range(header_row + 1, sheet.nrows):
        emp_no = _cell_text(sheet, row, 0)
        emp_name = _cell_text(sheet, row, 1)
        if not emp_no and not emp_name:
            continue

        day_punches = {
            day: punches
            for day, col in day_columns.items()
            if (punches := _read_punches(_cell_text(sheet, row, col), year, month, day))
        }
        punch_total = sum(len(p) for p in day_punches.values())
        if not punch_total:
            continue

        employee, matched_by = _match_employee(
            number_lookup, name_lookup, emp_no, emp_name
        )
        if not employee:
            label = f"{emp_no} - {emp_name}".strip(" -")
            if matched_by == "conflict":
                conflicting.append(label)
            else:
                unmatched.append(label)
            skipped += punch_total
            continue

        matches.append(
            {
                "file_no": emp_no,
                "file_name": emp_name,
                "employee_number": employee.employee_number,
                "full_name": employee.full_name,
                "matched_by": matched_by,
                "punches": punch_total,
            }
        )
        parsed += punch_total

        for day, punches in day_punches.items():
            if store_raw_logs:
                for punch in punches:
                    db.add(
                        RawLog(
                            employee_id=employee.id,
                            punch_datetime=punch["punch_datetime"],
                            source_file=source_filename,
                        )
                    )
            resolved, day_collisions = _resolve_day_punches(punches)
            collisions += day_collisions
            _mirror_lunch_punch(resolved, datetime(year, month, day))
            for slot_name, cell in resolved.items():
                _upsert_cell(
                    db,
                    employee.id,
                    datetime(year, month, day).date(),
                    slot_name,
                    cell["time_value"],
                    cell["is_flagged"],
                )
                cells_written += 1

    return {
        "parsed": parsed,
        "skipped": skipped,
        "unmatched_employees": unmatched,
        "conflicting_employees": conflicting,
        "matches": matches,
        "collisions": collisions,
        "cells_written": cells_written,
        "period": f"{year}-{month:02d}",
    }


# ── sheet reading ────────────────────────────────────────────────────────────

def _logs_sheet(file_bytes: bytes):
    try:
        book = xlrd.open_workbook(file_contents=file_bytes)
    except Exception as exc:  # xlrd raises several unrelated types
        raise XlsFormatError(
            "Could not read this workbook. Export it as Excel 97-2003 (.xls) "
            f"from your biometric software and try again. ({exc})"
        ) from exc

    sheet = next(
        (s for s in book.sheets() if s.name.strip().lower() == LOGS_SHEET), None
    )
    if sheet is None:
        raise XlsFormatError(
            "No 'Logs' sheet found in this workbook. Export the "
            "'List of Logs' report from your biometric software."
        )
    return sheet


def _cell_text(sheet, row: int, col: int) -> str:
    if row >= sheet.nrows or col >= sheet.ncols:
        return ""
    value = sheet.cell_value(row, col)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _read_period(sheet) -> tuple[int, int]:
    """Pull year/month out of the 'Duration: 2026/07/01 ~ 07/31' header."""
    for row in range(min(sheet.nrows, 5)):
        for col in range(sheet.ncols):
            match = PERIOD_RE.search(_cell_text(sheet, row, col))
            if match:
                return int(match.group(1)), int(match.group(2))
    raise XlsFormatError(
        "Could not find the reporting period (e.g. '2026/07/01 ~ 07/31') "
        "in the Logs sheet header."
    )


def _read_day_columns(sheet) -> tuple[int, dict[int, int]]:
    """Find the 'No. | Name | Department | 1 | 2 | ...' row -> {day: column}."""
    for row in range(min(sheet.nrows, 8)):
        days = {}
        for col in range(sheet.ncols):
            text = _cell_text(sheet, row, col)
            if text.isdigit() and 1 <= int(text) <= 31:
                days.setdefault(int(text), col)
        if len(days) >= 28:
            return row, days
    raise XlsFormatError(
        "Could not find the day-of-month header row in the Logs sheet."
    )


def _read_punches(cell_text: str, year: int, month: int, day: int) -> list[dict]:
    """One day cell -> punch records in the shape the .dat resolver expects."""
    try:
        datetime(year, month, day)
    except ValueError:      # e.g. day 31 column on a 30-day month
        return []

    seen = set()
    punches = []
    for hour, minute in TIME_RE.findall(cell_text):
        hour, minute = int(hour), int(minute)
        if hour > 23 or minute > 59:
            continue
        # This report prints the noon punch twice (once as AM out, once as PM
        # in), and it only has minute resolution — so an exact repeat is the
        # same scan, not a second one. Collapsing it here keeps the shared
        # 5-minute collision rule from blanking both noon cells on every day.
        # The .dat file has second resolution, so its path is untouched.
        if (hour, minute) in seen:
            continue
        seen.add((hour, minute))
        punches.append(
            {
                "punch_datetime": datetime(year, month, day, hour, minute),
                # ponytail: the Excel report drops the device's in/out state
                # code, so the resolver falls back to its sequence heuristics.
                "punch_state": None,
            }
        )
    punches.sort(key=lambda p: p["punch_datetime"])
    return punches


def _mirror_lunch_punch(slots: dict, day_start: datetime) -> None:
    """
    One scan at lunch counts as both the AM departure and the PM arrival.

    The resolver can only put a lone noon punch in one of the two slots, so
    copy it across to the other and re-derive that slot's schedule flag with
    the .dat rule. A slot the collision rule blanked is left alone — HR has to
    settle those by hand.
    """
    for source, target in (("AM_OUT", "PM_IN"), ("PM_IN", "AM_OUT")):
        if not slots[source]["time_value"]:
            continue
        if slots[target]["time_value"] or slots[target]["is_flagged"]:
            continue
        minutes = slot_to_minutes(slots[source]["time_value"], source)
        if minutes is None or not LUNCH_START_MIN <= minutes <= LUNCH_END_MIN:
            continue

        punch_dt = datetime.combine(day_start.date(), time(minutes // 60, minutes % 60))
        mirrored = _format_time(punch_dt)
        # Times are stored 12-hour with no AM/PM, so each slot can only hold
        # part of the clock — AM_OUT reads "1:20" back as 1:20 AM, PM_IN reads
        # "11:45" back as 11:45 PM. Skip rather than write a time the target
        # slot would misread and charge as undertime.
        if slot_to_minutes(mirrored, target) != minutes:
            continue

        slots[target]["time_value"] = mirrored
        slots[target]["is_flagged"] = _is_schedule_flag(target, punch_dt)


# ── employee matching ────────────────────────────────────────────────────────

def _normalize_name(value: str) -> str:
    return "".join(ch for ch in str(value).upper() if ch.isalnum())


def _name_keys(full_name: str) -> list[str]:
    """
    The short names these reports print vary, so build every form the device
    is likely to use:
    'ALICE B. SANTOS' -> ['ASANTOS', 'ABSANTOS', 'SANTOS']
    """
    tokens = [t for t in str(full_name).replace(",", " ").split() if t.strip(" .")]
    while len(tokens) > 1 and tokens[-1].upper().strip(".") in NAME_SUFFIXES:
        tokens.pop()
    if not tokens:
        return []
    surname = _normalize_name(tokens[-1])
    if not surname:
        return []

    initials = "".join(_normalize_name(t)[:1] for t in tokens[:-1])
    keys = [f"{initials[:1]}{surname}", f"{initials}{surname}"] if initials else []
    keys.append(surname)
    return list(dict.fromkeys(keys))


def _name_lookup(db: Session) -> dict:
    """Name key -> employee. Keys claimed by two employees are dropped."""
    lookup = {}
    ambiguous = set()
    for employee in db.query(Employee).all():
        for key in _name_keys(employee.full_name):
            if key in lookup and lookup[key].id != employee.id:
                ambiguous.add(key)
            lookup.setdefault(key, employee)
    for key in ambiguous:
        lookup.pop(key, None)
    return lookup


def _match_employee(number_lookup: dict, name_lookup: dict, emp_no: str, emp_name: str):
    """Return a match only when the available name and ID signals agree."""
    name_match = name_lookup.get(_normalize_name(emp_name)) if emp_name else None
    number_match = None
    for key in (emp_no, _normalize_emp_no(emp_no) if emp_no else ""):
        if key and (number_match := number_lookup.get(key)):
            break
    if name_match and number_match and name_match.id != number_match.id:
        return None, "conflict"
    if name_match:
        return name_match, "name"
    if number_match:
        return number_match, "id"
    return None, None
