from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    employee_number = Column(String(20), unique=True, nullable=False, index=True)
    full_name = Column(String(100), nullable=False)
    position = Column(String(100))
    office_division = Column(String(100))
    # "PERMANENT" or "COS_JO"  (defaults to PERMANENT for existing records)
    employment_type = Column(String(20), nullable=False, default="PERMANENT", server_default="PERMANENT")

    raw_logs = relationship("RawLog", back_populates="employee", cascade="all, delete-orphan")
    dtr_cells = relationship("DTRCell", back_populates="employee", cascade="all, delete-orphan")


class Verifier(Base):
    __tablename__ = "verifiers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    position = Column(String(100), nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class RawLog(Base):
    __tablename__ = "raw_logs"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    punch_datetime = Column(DateTime, nullable=False)
    source_file = Column(String(200))
    is_collision = Column(Boolean, default=False)

    employee = relationship("Employee", back_populates="raw_logs")


class DTRCell(Base):
    """Stores the final resolved time per slot per day per employee."""
    __tablename__ = "dtr_cells"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    work_date = Column(Date, nullable=False)
    slot = Column(String(10), nullable=False)        # AM_IN, AM_OUT, PM_IN, PM_OUT
    time_value = Column(String(8), nullable=True)   # HH:MM or None/blank
    is_flagged = Column(Boolean, default=False)     # collision flag → red highlight

    employee = relationship("Employee", back_populates="dtr_cells")
    audit_logs = relationship("AuditLog", back_populates="dtr_cell", cascade="all, delete-orphan")

    @property
    def display_time(self):
        return format_display_time(self.time_value)


class AuditLog(Base):
    """Tracks every manual HR edit to DTR cells."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    dtr_cell_id = Column(Integer, ForeignKey("dtr_cells.id", ondelete="CASCADE"), nullable=False)
    admin_user = Column(String(80), nullable=False)
    original_value = Column(String(8), nullable=True)
    new_value = Column(String(8), nullable=True)
    changed_at = Column(DateTime, default=datetime.utcnow)
    note = Column(Text, nullable=True)

    dtr_cell = relationship("DTRCell", back_populates="audit_logs")


class UploadedDatFile(Base):
    """
    Records every .dat file that has been successfully ingested.
    Used to block duplicate uploads by filename.
    The raw file bytes are also saved to disk at `stored_path`.
    """
    __tablename__ = "uploaded_dat_files"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(200), unique=True, nullable=False, index=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    file_size_bytes = Column(Integer, nullable=True)
    stored_path = Column(String(500), nullable=True)  # absolute path on disk


class UploadedXlsFile(Base):
    """
    Same idea as UploadedDatFile, but for the biometric software's Excel
    attendance export. Kept in its own table so the .dat upload history and
    its duplicate guard are untouched by this import path.
    """
    __tablename__ = "uploaded_xls_files"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(200), unique=True, nullable=False, index=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    file_size_bytes = Column(Integer, nullable=True)
    stored_path = Column(String(500), nullable=True)  # absolute path on disk
    period = Column(String(7), nullable=True)         # "YYYY-MM" from the report


def format_display_time(value):
    if not value:
        return ""
    text = str(value).strip()
    if ":" not in text:
        return text
    hour_text, minute_text = text.split(":", 1)
    if not hour_text.isdigit() or not minute_text[:2].isdigit():
        return text
    hour = int(hour_text)
    minute = minute_text[:2]
    display_hour = hour % 12 or 12
    return f"{display_hour}:{minute}"


# ── Undertime calculation ────────────────────────────────────────────────────
# Prescribed office hours (CSCRO XIII standard):
#   AM arrival  — not later than 8:00 AM   (later  → undertime)
#   AM departure— not earlier than 12:00 NN (earlier → undertime)
#   PM arrival  — not later than 1:00 PM    (later  → undertime)
#   PM departure— not earlier than 5:00 PM  (earlier → undertime)
STD_AM_IN_MIN = 8 * 60      # 08:00
STD_AM_OUT_MIN = 12 * 60    # 12:00
STD_PM_IN_MIN = 13 * 60     # 13:00
STD_PM_OUT_MIN = 17 * 60    # 17:00


def slot_to_minutes(value, slot):
    """
    Convert a stored 12-hour display string (e.g. "8:15", "12:03", "1:30")
    into minutes-since-midnight in 24-hour terms, using the slot for context.
    Returns None if the value is blank/unparseable.
    """
    if not value:
        return None
    text = str(value).strip()
    if ":" not in text:
        return None
    hour_text, minute_text = text.split(":", 1)
    try:
        hour = int(hour_text)
        minute = int(minute_text[:2])
    except (ValueError, AttributeError):
        return None

    if slot in ("PM_IN", "PM_OUT"):
        # 12 → noon (12:xx); 1–11 → 13:00–23:00
        if hour != 12:
            hour += 12
    elif slot == "AM_IN":
        # 12 would mean midnight — guard to 0
        if hour == 12:
            hour = 0
    # AM_OUT: 12 stays noon (12:xx), 1–11 stay as-is
    return hour * 60 + minute


def _halfday_undertime(in_val, in_slot, out_val, out_slot, std_in, std_out) -> int:
    """
    Undertime minutes for one half-day (morning or afternoon).

    Normal pair: late-arrival deficit (past std_in) + early-departure deficit
    (before std_out), each counted independently.

    Degenerate pair — a single duplicated punch where IN and OUT are the same
    time (or OUT is not after IN): treat it as a lone DEPARTURE punch. Count
    only the early-departure deficit and never the late-arrival penalty, so the
    employee is not charged twice for the same instant. Example: PM 1:09 / 1:09
    → 5:00 − 1:09 = 3h51m (not the full 4h afternoon).
    """
    t_in = slot_to_minutes(in_val, in_slot)
    t_out = slot_to_minutes(out_val, out_slot)

    if t_in is not None and t_out is not None and t_out <= t_in:
        # Single-punch / degenerate pair → departure-only.
        return max(0, std_out - t_out)

    total = 0
    if t_in is not None and t_in > std_in:
        total += t_in - std_in            # late arrival
    if t_out is not None and t_out < std_out:
        total += std_out - t_out          # early departure
    return total


def compute_undertime_minutes(slots: dict) -> int:
    """
    Total undertime minutes for one day given {slot: display_time}.
    Only slots that carry a value contribute; blanks are ignored.
    """
    total = 0
    total += _halfday_undertime(
        slots.get("AM_IN"), "AM_IN", slots.get("AM_OUT"), "AM_OUT",
        STD_AM_IN_MIN, STD_AM_OUT_MIN,
    )
    total += _halfday_undertime(
        slots.get("PM_IN"), "PM_IN", slots.get("PM_OUT"), "PM_OUT",
        STD_PM_IN_MIN, STD_PM_OUT_MIN,
    )
    return total


def undertime_hm(slots: dict):
    """Return (hours, minutes, total_minutes) of undertime for one day."""
    total = compute_undertime_minutes(slots)
    return total // 60, total % 60, total
