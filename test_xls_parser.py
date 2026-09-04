"""Self-check for the .xls attendance import. Run: python test_xls_parser.py"""
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import database
from database import Base
from services.xls_parser import (
    XlsFormatError,
    _mirror_lunch_punch,
    _name_keys,
    _read_punches,
    parse_xls_file,
)


def _memory_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_name_keys():
    assert _name_keys("ALICE BEATRICE A. SANTOS") == [
        "ASANTOS", "ABASANTOS", "SANTOS",
    ]
    assert _name_keys("CARLA DIANE REYES") == ["CREYES", "CDREYES", "REYES"]
    assert _name_keys("DANIEL E. CRUZ, JR") == ["DCRUZ", "DECRUZ", "CRUZ"]
    assert _name_keys("ELENA F. PEÑA") == ["EPEÑA", "EFPEÑA", "PEÑA"]
    assert _name_keys("MONROE") == ["MONROE"]
    assert _name_keys("") == []


def test_read_punches():
    # the repeated 12:08 is the same scan printed twice by the report
    punches = _read_punches("08:47\n12:08\n12:08\n18:04\n", 2026, 7, 1)
    assert [p["punch_datetime"].strftime("%H:%M") for p in punches] == [
        "08:47", "12:08", "18:04",
    ]
    # near-duplicates a minute apart are kept — the collision rule judges them
    punches = _read_punches("07:06\n07:07\n", 2026, 7, 1)
    assert len(punches) == 2
    assert _read_punches("", 2026, 7, 1) == []
    assert _read_punches("08:00", 2026, 2, 31) == []      # invalid calendar day
    assert _read_punches("99:99", 2026, 7, 1) == []       # junk time


def _slots(**values):
    return {
        slot: {"time_value": values.get(slot), "is_flagged": False}
        for slot in ("AM_IN", "AM_OUT", "PM_IN", "PM_OUT")
    }


def test_mirror_lunch_punch():
    noon = datetime(2026, 7, 1)

    # AM departure -> PM arrival
    slots = _slots(AM_OUT="12:08")
    _mirror_lunch_punch(slots, noon)
    assert slots["PM_IN"]["time_value"] == "12:08"
    assert slots["PM_IN"]["is_flagged"] is False        # not later than 1:00 PM

    # PM arrival -> AM departure (employee never punched in that morning)
    slots = _slots(PM_IN="12:08")
    _mirror_lunch_punch(slots, noon)
    assert slots["AM_OUT"]["time_value"] == "12:08"

    # Stored times are 12-hour with no AM/PM, so a slot that would read the
    # mirrored value back as the wrong half of the day is left alone.
    slots = _slots(PM_IN="1:20")            # 1:20 PM — AM_OUT would read 1:20 AM
    _mirror_lunch_punch(slots, noon)
    assert slots["AM_OUT"]["time_value"] is None
    slots = _slots(AM_OUT="11:45")          # 11:45 AM — PM_IN would read 11:45 PM
    _mirror_lunch_punch(slots, noon)
    assert slots["PM_IN"]["time_value"] is None

    # both halves already punched -> nothing to mirror
    slots = _slots(AM_OUT="12:02", PM_IN="12:34")
    _mirror_lunch_punch(slots, noon)
    assert slots["AM_OUT"]["time_value"] == "12:02"
    assert slots["PM_IN"]["time_value"] == "12:34"

    # outside the lunch window -> not a lunch punch, leave it alone
    slots = _slots(PM_IN="4:30")
    _mirror_lunch_punch(slots, noon)
    assert slots["AM_OUT"]["time_value"] is None

    # a slot the collision rule blanked stays blank for HR to settle
    slots = _slots(AM_OUT="12:08")
    slots["PM_IN"]["is_flagged"] = True
    _mirror_lunch_punch(slots, noon)
    assert slots["PM_IN"]["time_value"] is None


def test_bad_workbook():
    try:
        parse_xls_file(b"not an excel file", "x.xls", _memory_session())
    except XlsFormatError:
        return
    raise AssertionError("expected XlsFormatError")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all passed")
