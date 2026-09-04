"""
Renders CSC Form 48 as a dual-copy A4 portrait PDF via WeasyPrint.
"""
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
os.environ.setdefault("XDG_CACHE_HOME", str(APP_DIR / ".cache"))

from weasyprint import HTML, CSS
from jinja2 import Environment, FileSystemLoader
import calendar
from datetime import date
from models import undertime_hm

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
env.globals["undertime_hm"] = undertime_hm


def build_date_range(year: int, month: int, start_day: int, end_day: int):
    """Return list of date objects for the given range."""
    return [date(year, month, d) for d in range(start_day, end_day + 1)]


def generate_form48_pdf(
    employee: dict,
    dtr_data: dict,      # {date_str: {AM_IN, AM_OUT, PM_IN, PM_OUT, flagged_slots}}
    year: int,
    month: int,
    start_day: int,
    end_day: int,
    certifier: dict | None = None,
) -> bytes:
    template = env.get_template("form48_pdf.html")
    dates = build_date_range(year, month, start_day, end_day)
    month_name = calendar.month_name[month]

    html_str = template.render(
        employee=employee,
        dates=dates,
        dtr_data=dtr_data,
        year=year,
        month_name=month_name,
        period=f"{month_name} {start_day} - {end_day}, {year}",
        certifier=certifier or {},
    )

    pdf_bytes = HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(
        stylesheets=[CSS(string=_pdf_css())]
    )
    return pdf_bytes


def _pdf_css():
    return """
    @page {
        size: A4 portrait;
        margin: 14mm 13mm;
    }
    body { font-family: Arial, sans-serif; font-size: 9pt; margin: 0; }
    .wrapper { display: flex; gap: 0; align-items: stretch; height: 269mm; }
    .form-copy { width: 50%; height: 269mm; box-sizing: border-box; border: none; padding: 2mm 5mm; padding-bottom: 55mm; page-break-inside: avoid; position: relative; }
    .form-copy:first-child { border-right: 1px solid #000; }
    .bold { font-weight: bold; }

    /* ── Header ─────────────────────────────────────────────── */
    .header-block { text-align: center; margin-bottom: 2.5mm; }
    .header-block p { margin: 0; }
    .title { font-size: 12pt; letter-spacing: 0.3px; }
    .emp-name { font-size: 10.5pt; margin-top: 2.5mm !important; }
    .name-label { font-size: 9pt; }
    .date-from { font-size: 10pt; text-align: left; margin-top: 1.5mm !important; }

    /* ── Table ──────────────────────────────────────────────── */
    table { width: 100%; border-collapse: collapse; }
    th, td { border: 1px solid #000; padding: 1.5px 1px; text-align: center; }
    th { background: #fff; font-size: 8.5pt; font-weight: bold; }
    .col-day { width: 9%; }
    .day-num { font-size: 9pt; }
    .time-cell { font-size: 9pt; line-height: 1.05; white-space: nowrap; }
    .ut-cell { font-size: 9pt; line-height: 1.05; }

    /* ── Weekend rows (spaced letters spanning time columns) ── */
    .weekend-label {
        font-size: 9pt;
        text-align: justify;
        text-align-last: justify;
        padding-left: 4mm;
        padding-right: 4mm;
        white-space: nowrap;
    }
    .sunday-label { color: #cc0000; }
    .sunday-row .day-num { color: #cc0000; }

    /* ── Bottom block ───────────────────────────────────────── */
    .bottom-block { position: absolute; left: 5mm; right: 5mm; bottom: 2mm; }
    .legend-line { border-top: 1px solid #000; height: 0; }
    .legend { font-size: 7.5pt; line-height: 1.3; padding: 1mm 0; text-align: center; white-space: nowrap; }
    .certification { margin: 2.5mm 0; text-align: justify; font-size: 9pt; line-height: 1.35; }
    .sig-block { text-align: center; margin-top: 2mm; font-size: 9.5pt; }
    .signature-space { height: 4mm; }
    .sig-line-thin { border-top: 1px solid #000; margin-top: 0.5mm; }
    .verified { font-size: 9pt; margin: 3mm 0 0; }
    .verifier-name { text-decoration: underline; }
    .verifier-pos { font-size: 9pt; }
    """
