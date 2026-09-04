"""Regression tests for data-integrity and upload safety fixes."""
import asyncio
import io
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import DTRCell, Employee, RawLog, UploadedDatFile
from routers.datlogs import delete_dat_file, rename_dat_file, upload_dat
from routers.employees import delete_employee
from routers.dtr import update_cell
from routers.xlslogs import upload_xls
from services.dat_parser import _resolve_day_punches, parse_dat_file
from services.xls_parser import parse_xls_file


class FakeSheet:
    name = "Logs"

    def __init__(self, rows):
        self.rows = rows
        self.nrows = len(rows)
        self.ncols = max(len(row) for row in rows)

    def cell_value(self, row, col):
        return self.rows[row][col] if col < len(self.rows[row]) else ""


class FakeWorkbook:
    def __init__(self, sheet):
        self.sheet = sheet

    def sheets(self):
        return [self.sheet]


def memory_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def workbook_with_employee(number, short_name):
    period = ["Duration: 2026/07/01 ~ 07/31"]
    header = ["No.", "Name", "Department", *range(1, 32)]
    employee = [number, short_name, "Office", "08:00\n12:00\n12:00\n17:00"]
    return FakeWorkbook(FakeSheet([period, header, employee]))


class AttendanceResolutionTests(unittest.TestCase):
    def test_duplicate_device_punch_flags_only_its_own_slot(self):
        punches = [
            {"punch_datetime": datetime(2026, 7, 1, 7, 55), "punch_state": "0"},
            {"punch_datetime": datetime(2026, 7, 1, 7, 56), "punch_state": "0"},
            {"punch_datetime": datetime(2026, 7, 1, 12, 0), "punch_state": "2"},
            {"punch_datetime": datetime(2026, 7, 1, 13, 0), "punch_state": "3"},
            {"punch_datetime": datetime(2026, 7, 1, 17, 0), "punch_state": "1"},
        ]

        slots, collisions = _resolve_day_punches(punches)

        self.assertEqual(collisions, 1)
        self.assertEqual(slots["AM_IN"], {"time_value": None, "is_flagged": True})
        self.assertEqual(slots["AM_OUT"], {"time_value": "12:00", "is_flagged": False})
        self.assertEqual(slots["PM_IN"], {"time_value": "1:00", "is_flagged": False})
        self.assertEqual(slots["PM_OUT"], {"time_value": "5:00", "is_flagged": False})

    def test_first_import_preserves_identical_raw_device_events(self):
        db = memory_session()
        db.add(Employee(employee_number="1", full_name="ALICE SMITH"))
        db.commit()
        content = (
            b"1 2026-07-01 08:00:00 1 0 1\n"
            b"1 2026-07-01 08:00:00 1 0 1\n"
        )

        parse_dat_file(content, "attendance.dat", db)

        self.assertEqual(db.query(RawLog).count(), 2)


class XlsImportTests(unittest.TestCase):
    def test_conflicting_name_and_employee_number_is_not_imported(self):
        db = memory_session()
        db.add_all(
            [
                Employee(employee_number="1", full_name="ALICE SMITH"),
                Employee(employee_number="2", full_name="BOB JONES"),
            ]
        )
        db.commit()
        workbook = workbook_with_employee("2", "ASmith")

        with patch("services.xls_parser.xlrd.open_workbook", return_value=workbook):
            result = parse_xls_file(b"workbook", "attendance.xls", db)

        self.assertEqual(result["parsed"], 0)
        self.assertEqual(result["conflicting_employees"], ["2 - ASmith"])
        self.assertEqual(db.query(RawLog).count(), 0)

    def test_reimport_does_not_duplicate_raw_logs(self):
        db = memory_session()
        db.add(Employee(employee_number="1", full_name="ALICE SMITH"))
        db.commit()
        workbook = workbook_with_employee("1", "ASmith")

        with patch("services.xls_parser.xlrd.open_workbook", return_value=workbook):
            parse_xls_file(b"workbook", "attendance.xls", db)
            first_count = db.query(RawLog).count()
            parse_xls_file(b"workbook", "attendance.xls", db)

        self.assertEqual(first_count, 3)
        self.assertEqual(db.query(RawLog).count(), 3)


class UploadEndpointTests(unittest.TestCase):
    def test_dat_upload_rejects_a_filename_outside_the_upload_directory(self):
        db = memory_session()
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Path(temp_dir) / "uploads"
            store.mkdir()
            upload = UploadFile(filename="../outside.dat", file=io.BytesIO(b"junk"))

            with patch("routers.datlogs.DAT_STORE", store):
                response = asyncio.run(upload_dat(upload, db))

            self.assertEqual(response.status_code, 400)
            self.assertFalse((Path(temp_dir) / "outside.dat").exists())

    def test_dat_upload_rejects_a_file_with_no_attendance_records(self):
        db = memory_session()
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Path(temp_dir)
            upload = UploadFile(filename="empty.dat", file=io.BytesIO(b"not attendance"))

            with patch("routers.datlogs.DAT_STORE", store):
                response = asyncio.run(upload_dat(upload, db))

            self.assertEqual(response.status_code, 400)
            self.assertEqual(db.query(UploadedDatFile).count(), 0)
            self.assertFalse((store / "empty.dat").exists())

    def test_dat_rename_rejects_a_filename_outside_the_upload_directory(self):
        db = memory_session()
        with tempfile.TemporaryDirectory() as temp_dir:
            original = Path(temp_dir) / "attendance.dat"
            original.write_bytes(b"attendance")
            record = UploadedDatFile(
                filename="attendance.dat",
                stored_path=str(original),
                file_size_bytes=10,
            )
            db.add(record)
            db.commit()

            response = asyncio.run(
                rename_dat_file(record.id, {"new_filename": "../outside.dat"}, db)
            )

            self.assertEqual(response.status_code, 400)
            self.assertTrue(original.exists())

    def test_dat_delete_never_unlinks_a_file_outside_the_upload_directory(self):
        db = memory_session()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = root / "uploads"
            store.mkdir()
            external = root / "important.dat"
            external.write_bytes(b"keep")
            record = UploadedDatFile(
                filename="important.dat",
                stored_path=str(external),
                file_size_bytes=4,
            )
            db.add(record)
            db.commit()

            with patch("routers.datlogs.DAT_STORE", store):
                response = asyncio.run(delete_dat_file(record.id, db))

            self.assertEqual(response.status_code, 400)
            self.assertTrue(external.exists())

    def test_xls_import_rolls_back_when_the_file_cannot_be_saved(self):
        db = memory_session()
        db.add(Employee(employee_number="1", full_name="ALICE SMITH"))
        db.commit()
        workbook = workbook_with_employee("1", "ASmith")
        upload = UploadFile(filename="attendance.xls", file=io.BytesIO(b"workbook"))

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("routers.xlslogs.XLS_STORE", Path(temp_dir)),
                patch("services.xls_parser.xlrd.open_workbook", return_value=workbook),
                patch.object(Path, "write_bytes", side_effect=OSError("disk full")),
                self.assertRaises(OSError),
            ):
                asyncio.run(upload_xls(upload, db))

        self.assertEqual(db.query(RawLog).count(), 0)

    def test_dat_import_rolls_back_when_the_file_cannot_be_saved(self):
        db = memory_session()
        db.add(Employee(employee_number="1", full_name="ALICE SMITH"))
        db.commit()
        content = b"1 2026-07-01 08:00:00 1 0 1\n"
        upload = UploadFile(filename="attendance.dat", file=io.BytesIO(content))

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("routers.datlogs.DAT_STORE", Path(temp_dir)),
                patch.object(Path, "write_bytes", side_effect=OSError("disk full")),
                self.assertRaises(OSError),
            ):
                asyncio.run(upload_dat(upload, db))

        self.assertEqual(db.query(RawLog).count(), 0)


class EmployeeEndpointTests(unittest.TestCase):
    def test_deleting_an_employee_removes_their_raw_attendance(self):
        db = memory_session()
        employee = Employee(employee_number="1", full_name="ALICE SMITH")
        db.add(employee)
        db.flush()
        db.add(
            RawLog(
                employee_id=employee.id,
                punch_datetime=datetime(2026, 7, 1, 8, 0),
                source_file="attendance.dat",
            )
        )
        db.commit()

        response = delete_employee(employee.id, db)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(db.query(RawLog).count(), 0)


class DtrEndpointTests(unittest.TestCase):
    def test_cell_update_rejects_an_unknown_employee(self):
        db = memory_session()

        with self.assertRaises(HTTPException) as raised:
            update_cell(
                {
                    "employee_id": 999,
                    "work_date": "2026-07-01",
                    "slot": "AM_IN",
                    "new_value": "8:00",
                    "admin_user": "HR Admin",
                },
                db,
            )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(db.query(DTRCell).count(), 0)

    def test_cell_update_rejects_an_invalid_time(self):
        db = memory_session()
        employee = Employee(employee_number="1", full_name="ALICE SMITH")
        db.add(employee)
        db.commit()

        with self.assertRaises(HTTPException) as raised:
            update_cell(
                {
                    "employee_id": employee.id,
                    "work_date": "2026-07-01",
                    "slot": "AM_IN",
                    "new_value": "99:99",
                    "admin_user": "HR Admin",
                },
                db,
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(db.query(DTRCell).count(), 0)

if __name__ == "__main__":
    unittest.main()
