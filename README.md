# CSC Form 48 DTR System

This app is a simple web system that helps you manage employee daily time records (DTR) and prepare CSC Form 48 reports.

You can use it to:

- upload employee attendance files in `.dat` format or Excel 97-2003 `.xls` format,
- create employee records in the system,
- match each employee ID from the `.dat` file to the correct employee in the app,
- view the generated DTR entries for each employee,
- fix or edit values when needed,
- export the final Form 48 PDF.

The app runs on your computer and stores data locally in SQLite.

## What this system is for

This is not only a PDF tool. It is a full DTR workflow system.

The usual flow is:

1. Add employees in the Employees page.
2. Upload the attendance `.dat` file, or import the biometric software's `.xls` Logs report.
3. The system reads the employee ID from the file and connects it to the matching employee record.
4. The app converts the raw time logs into DTR slots.
5. You review and edit the DTR grid if needed.
6. You export the monthly CSC Form 48 PDF.

## Before you start

Make sure your computer has the following installed:

- Python 3.10 or newer
- `pip`
- a terminal or command prompt
- a web browser

You should also know the folder where you saved this project.

## Install Python

### Windows

1. Open your browser and go to the official Python download page:
   https://www.python.org/downloads/
2. Download the latest Python 3 release for Windows.
3. Run the installer.
4. Important: check the box that says "Add Python to PATH" before you click Install.
5. After installation, open Command Prompt and verify Python is installed:

```cmd
python --version
```

If that works, you can continue.

### macOS

1. Open your browser and go to the official Python download page:
   https://www.python.org/downloads/
2. Download the latest Python 3 release for macOS.
3. Run the installer and follow the steps.
4. Open Terminal and verify Python is installed:

```bash
python3 --version
```

If that works, you can continue.

## Setup instructions

Open your terminal and go to the project folder.

```bash
cd <project-folder>
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

If you are using Windows PowerShell, the activation command is usually:

```powershell
.\venv\Scripts\Activate.ps1
```

## Run the system in the browser

After the packages are installed, start the app with:

```bash
uvicorn main:app --reload
```

Then open this address in your browser:

```text
http://127.0.0.1:8000
```

## Very important: the employee ID must match

This is the key step that makes the system work correctly.

The `.dat` attendance file contains an employee number in each line. The app reads that number and looks for the same employee number in the system.

If the employee ID in the `.dat` file does not match the employee record you created in the app, the attendance data will not be connected to that employee.

### Matching rule

- The employee number in the `.dat` file must match the employee record in the system.
- Leading zeroes are handled automatically, so `00012` and `12` are treated as the same number.
- Always create the employee first before uploading the file.

### Example

If your `.dat` file contains this employee ID:

```text
00012
```

then create an employee in the app with the same number, such as:

- `employee_number = 00012` or `12`
- `full_name = <employee name>`

Once the numbers match, the system can fetch and show the time data correctly.

## Step-by-step tutorial

### 1. Create employees first

Go to the Employees page and add each employee.

Enter these details:

- employee number
- full name
- position
- office or division
- employment type

Make sure the employee number matches the ID in the attendance `.dat` file.

### 2. Upload the attendance file

Go to the Dat Logs page to upload a `.dat` file, or use Import Excel for a biometric
software `.xls` report containing a `Logs` sheet.

The system will:

- save the file locally,
- read the attendance lines,
- match the employee IDs,
- create the DTR entries.

### 3. Check if any employee IDs are unmatched

If an ID is not found in the employee list, the app will not attach the time data to that person.

In that case:

- create the missing employee record, or
- edit the employee number so it matches the `.dat` file.

### 4. Open the DTR page

After the upload, go to the DTR page.

Choose the employee, month, and date range to review the entries.

You will see the time slots for:

- AM IN
- AM OUT
- PM IN
- PM OUT

### 5. Edit the DTR if needed

Some entries may be wrong or flagged because of duplicate or unusual punches.

You can correct them in the grid.

Every change is tracked in the audit log.

### 6. Export the Form 48 PDF

Once the DTR is correct, export the report as a PDF.

This final PDF is the output you can print or submit.

## Simple workflow

A good workflow is:

1. Create all employee records.
2. Confirm that each employee number matches the `.dat` file.
3. Upload the `.dat` file.
4. Review the upload result.
5. Fix any unmatched or wrong employee IDs.
6. Open the DTR page and check the records.
7. Edit any incorrect entries.
8. Export the PDF.

## Main files in the project

- `main.py` starts the FastAPI app
- `database.py` sets up the local SQLite database
- `models.py` defines the employee and DTR database tables
- `services/dat_parser.py` reads and resolves the `.dat` file
- `routers/employees.py` handles employee creation and editing
- `routers/datlogs.py` handles `.dat` upload and storage
- `routers/xlslogs.py` handles `.xls` upload and storage
- `routers/dtr.py` handles the DTR grid and PDF export

## Notes

- The system creates its own local database called `form48.db`.
- Uploaded files are stored locally in `dat_uploads/` and `xls_uploads/`.
- The database and uploaded attendance files are intentionally excluded from Git.
- The matching of employee IDs is the most important part of the import process.
