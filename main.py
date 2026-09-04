from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from database import engine, Base
from routers import employees, datlogs, dtr, xlslogs

APP_DIR = Path(__file__).resolve().parent

# Create all tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(title="CSC Form 48 DTR System", version="1.0")

app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")

app.include_router(employees.router)
app.include_router(datlogs.router)
app.include_router(dtr.router)
app.include_router(xlslogs.router)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {})
