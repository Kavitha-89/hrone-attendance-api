# Employee Attendance & Analytics API

A FastAPI application backed by MongoDB for employee management, attendance punch-in and punch-out, attendance regularization, and attendance analytics.

## Features

- Create and list employees.
- Record punch-in and punch-out timestamps.
- Calculate late minutes, work hours, overtime, and half-day status.
- List and paginate attendance records.
- Correct attendance records with a regularization history.
- Provide monthly employee analytics, department summaries, a late-arrival leaderboard, department trends, and query-plan inspection.
- Check database readiness through `/health`.

## Requirements

- Python 3.13 recommended.
- MongoDB 6.0 or newer.
- A MongoDB Atlas cluster or an accessible local MongoDB instance.

## Setup on Windows PowerShell

Open PowerShell in the project directory.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create a file named `.env` in the project root with these settings:

```dotenv
MONGO_URI=your_mongodb_connection_string
MONGO_DB=attendance_db
```

Replace the example value with your own MongoDB connection string. Never commit `.env` or share database credentials.

## Run the API

```powershell
uvicorn app.main:app --port 8000
```

Open the interactive documentation at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) and check database readiness at [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health).

## Sample data

`sample_data/` contains example employee and attendance documents. To load them, run:

```powershell
python sample_seed.py
```

**Warning:** The seed script deletes the existing `employees` and `attendance_logs` documents in the configured database before loading the samples. Use a disposable test database, not a database containing records you need to keep.

## Testing and limitations

The API has been manually exercised through Swagger for employee creation, punch-in, punch-out, attendance listing, analytics, and regularization. Automated tests have not yet been added, and additional edge-case verification is still needed for overnight shifts, weekend analytics, and query-plan behavior.

See `REVIEW.md` for known issues and `DECISIONS.md` for implementation decisions. The sample data is not a substitute for testing the complete set of assignment rules against a larger dataset.