# CSC Form 48 DTR System

This program helps HR staff prepare employee Daily Time Records and CSC Form 48
reports.

You can use it to:

- register employees,
- import attendance from a biometric `.dat` file,
- import an Excel 97-2003 `.xls` attendance report,
- review and correct time entries,
- keep a record of manual corrections, and
- create individual or batch Form 48 PDF files.

Everything is stored only on the computer where the program is running.

> **Important:** This program has no login page. Use it only on your own computer
> at `http://127.0.0.1:8000`. Do not make it publicly accessible on the internet.

## What you need

This guide is for a **64-bit Windows 10 or Windows 11 computer**. Before
installing the program, you need:

- an internet connection for the first installation,
- permission to install programs,
- Python 3.10 or newer,
- Git for Windows,
- MSYS2 and Pango for creating PDF files, and
- a web browser such as Chrome, Edge, Firefox, or Safari.

You do not need to install a separate database. Python already includes the
SQLite database used by this program.

## Windows installation

You do **not** need Docker or a separate database.

### Step 1: Install Python

1. Open the **Microsoft Store**.
2. Search for **Python 3.13** and install it.
3. Close the Microsoft Store when installation finishes.

### Step 2: Install Git

1. Download [Git for Windows](https://git-scm.com/download/win).
2. Open the downloaded installer.
3. Keep the recommended settings and complete the installation.

### Step 3: Install the PDF requirements

The system uses Pango to create Form 48 PDF files.

1. Download [MSYS2](https://www.msys2.org/).
2. Open the installer and keep its default installation folder:
   `C:\msys64`.
3. After installation, open **MSYS2 UCRT64** from the Start menu. Make sure the
   window title includes `UCRT64`.
4. Paste this command into that window and press Enter:

```bash
pacman -S mingw-w64-ucrt-x86_64-pango
```

5. Press `Y`, then Enter, when asked to continue.
6. Wait for the installation to finish, then close the MSYS2 window.

### Step 4: Open PowerShell and check the installations

1. Open the Start menu, search for **PowerShell**, and open it normally.
2. Run these commands one at a time:

```powershell
python --version
```

```powershell
git --version
```

Both commands should display a version number. If a command is not recognized,
restart the computer and try again.

### Step 5: Download the DTR system

In PowerShell, run these commands one at a time:

```powershell
cd $HOME\Documents
```

```powershell
git clone https://github.com/devCharuzu/dtrsystemlocal.git
```

```powershell
cd dtrsystemlocal
```

### Step 6: Install the DTR system

Continue in the same PowerShell window:

```powershell
python -m venv .venv
```

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Check that PDF support is ready:

```powershell
.\.venv\Scripts\python.exe -m weasyprint --info
```

If this displays WeasyPrint and system information without an error, the
installation is complete.

## Start the DTR system

You must start the program each time you want to use it.

1. Open **PowerShell** from the Start menu.
2. Run these commands:

```powershell
cd $HOME\Documents\dtrsystemlocal
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

When PowerShell displays `Uvicorn running on http://127.0.0.1:8000`, open this
address in your browser:

```text
http://127.0.0.1:8000
```

Keep the PowerShell window open while using the program.

To stop the program, return to PowerShell and press `Ctrl+C`.

## First-time setup

The program automatically creates these local items the first time it starts:

- `form48.db` — employee and attendance records,
- `dat_uploads` — uploaded `.dat` files, and
- `xls_uploads` — uploaded `.xls` files.

Do not delete these items if you want to keep your records.

## How to use the DTR system

### 1. Register the employees

Register employees before importing an attendance file.

1. Open **Employees** from the top menu.
2. Enter the employee number.
3. Enter the employee's full name.
4. Enter the position and office or division.
5. Choose **Permanent** or **COS/JO**.
6. Select **Save Employee**.
7. Repeat these steps for every employee.

The employee number must match the number used by the biometric device. Leading
zeroes do not matter: `00012` and `12` are treated as the same number.

### 2. Import attendance

Use either a DAT file or an Excel file.

#### Option A: Import a DAT file

1. Open **Upload DAT**.
2. Click the upload area and choose the `.dat` file from the biometric device.
   You can also drag the file into the upload area.
3. Select **Upload & Process**.
4. Wait for the result.
5. Review the number of parsed records, skipped records, collisions, and
   unmatched employees.

#### Option B: Import an Excel file

The system accepts only the older Excel `.xls` format.

1. In the biometric software, export the **List of Logs** report.
2. Save it as **Excel 97-2003 Workbook (`.xls`)**.
3. Make sure the workbook contains a sheet named `Logs`.
4. Open **Import Excel** in the DTR system.
5. Choose the `.xls` file.
6. Select **Upload & Process**.
7. Review the employee matches before using the DTR results.

An `.xlsx` file will not work. Open it in Microsoft Excel or LibreOffice and use
**Save As → Excel 97-2003 Workbook (`.xls`)**.

If the name and employee number point to two different employees, the system
will skip that row and show a conflict. Correct the employee information before
trying again.

### 3. Resolve import problems

- **Unmatched employee:** Add the missing employee or correct the employee
  number in the Employees page.
- **Conflicting employee:** Check both the name and employee number. They must
  identify the same person.
- **Collision:** The employee made two very close scans. Review the red blank
  cell and enter the correct time manually.
- **Duplicate filename:** The filename was previously imported. Confirm that
  you selected the correct file. Give a genuinely new export a unique filename.

### 4. Review the DTR

1. Open **DTR Grid**.
2. Choose the correct year and month.
3. Choose a period:
   - **1–15** for the first COS/JO period,
   - **16–End** for the second COS/JO period, or
   - **Full Month** for permanent employees.
4. Select **Open DTR Grid**.
5. Review the AM arrival, AM departure, PM arrival, and PM departure entries.
6. Use **Prev** and **Next** to review the other employees.

### 5. Correct a time entry

1. Double-click the weekday cell you want to change.
2. Enter the time using 12-hour `H:MM` format.
   Examples: `8:05`, `12:10`, or `5:02`.
3. Press Enter or click outside the cell.
4. Wait for the green saved message.

Only successfully saved changes appear in the audit log. If a save fails, the
cell returns to its previous value so you can try again.

### 6. Add or select a verifier

1. Open an employee's DTR Grid.
2. Choose an existing verifier from the **Verifier** list.
3. To add one, select **Add verifier**.
4. Enter the verifier's name and designation, then save.
5. Use **Set Default** if that person should be selected automatically.

### 7. Export the Form 48 PDF

For one employee:

1. Open that employee's DTR Grid.
2. Check the period, time entries, and verifier.
3. Select **Export PDF**.
4. Review the preview and download the file.

For multiple employees:

1. Return to **DTR Grid**.
2. Choose `1–15`, `16–End`, or `Full Month`.
3. Select **Batch Export**.
4. Wait while the combined PDF is created.

## Back up your records

Attendance records may contain personal information. Keep backups in a secure
location.

1. Stop the program by pressing `Ctrl+C` in PowerShell.
2. Open the `dtrsystemlocal` folder.
3. Copy these items to a secure USB drive or backup folder:

```text
form48.db
dat_uploads
xls_uploads
```

To restore the backup, stop the program and copy those items back into the
`dtrsystemlocal` folder.

## Update the program without losing records

1. Back up the three items listed above.
2. Stop the running program.
3. Open PowerShell.
4. Enter the program folder:

```powershell
cd $HOME\Documents\dtrsystemlocal
```

5. Download the update and refresh the required packages:

```powershell
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

6. Start the program again:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Updates do not include or remove your local database and attendance files.

## Common problems

### The browser says the page cannot be reached

- Make sure the PowerShell window is still open.
- Check that it says `Uvicorn running on http://127.0.0.1:8000`.
- Open exactly `http://127.0.0.1:8000` in the browser.
- If the program stopped, start it again using the instructions above.

### `python` or `git` is not recognized

The required program was not installed correctly, or PowerShell was open during
installation. Close PowerShell, open it again, and retry. If it still fails,
restart Windows and repeat the relevant installation step.

### `No module named ...`

Open PowerShell in the program folder and reinstall the required packages:

```powershell
cd $HOME\Documents\dtrsystemlocal
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### PDF export does not work

Check that WeasyPrint can start:

```powershell
cd $HOME\Documents\dtrsystemlocal
.\.venv\Scripts\python.exe -m weasyprint --info
```

If this reports a Pango or missing-library error:

1. Confirm that MSYS2 is installed in `C:\msys64`.
2. Open **MSYS2 UCRT64** from the Start menu.
3. Run `pacman -S mingw-w64-ucrt-x86_64-pango` again.
4. Close MSYS2 and PowerShell, reopen PowerShell, and retry the check.

### Port 8000 is already being used

Start the program on port 8001:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8001
```

Then open `http://127.0.0.1:8001`.

### PowerShell says script execution is disabled

The commands in this guide do not activate a PowerShell script. Make sure you
typed `.\.venv\Scripts\python.exe` exactly as shown instead of running
`Activate.ps1`.

## Data privacy when using Git

The database, uploaded attendance files, PDF files, and environment files are
excluded from normal Git commits. Before pushing an update, always run:

```bash
git status
```

Do not use `git add -f` on `form48.db`, `dat_uploads`, or `xls_uploads`.
