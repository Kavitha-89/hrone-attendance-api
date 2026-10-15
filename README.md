
# Employee Attendance & Analytics API

A FastAPI application backed by MongoDB for employee management, attendance punch-in and punch-out, attendance regularization, and analytics.

## Features

- Create and list employees.
- Record attendance punch-in and punch-out.
- Calculate late minutes, work hours, overtime, and half-day status.
- List and paginate attendance records.
- Regularize attendance and maintain a change history.
- Provide monthly employee analytics, department summaries, a late-arrival leaderboard, department trends, and query-plan inspection.
- Check database readiness through `/health`.

## Requirements

- Python 3.13 recommended.
- MongoDB 6.0 or newer.
- MongoDB Atlas or an accessible local MongoDB instance.

## Setup on Windows PowerShell

Run these commands from the project directory:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
