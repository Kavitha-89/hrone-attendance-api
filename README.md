# Employee Attendance & Analytics API

A FastAPI application backed by MongoDB for employee management, attendance punch-in and punch-out, attendance regularization, and workforce analytics.

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
- MongoDB Atlas or an accessible local MongoDB instance.

## Setup on Windows PowerShell

Open PowerShell in the project directory.

Create a virtual environment and install dependencies:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create a `.env` file in the project root with your own database settings:

```dotenv
MONGO_URI=your_mongodb_connection_string
MONGO_DB=attendance_db
```

Replace the example URI with your actual MongoDB connection string. Never commit `.env` or share database credentials.

## Run the API

```powershell
uvicorn app.main:app --port 8000
```

Interactive API documentation: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

Health check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

## Sample data

`sample_data/` contains example employee and attendance documents. To load the samples, run:

```powershell
python sample_seed.py
```

**Warning:** The seed script deletes existing documents from the `employees` and `attendance_logs` collections in the configured database before loading sample data. Use a disposable test database.

## Testing and limitations

Eight automated calculation tests currently pass, covering late-arrival grace boundaries, overtime thresholds, overnight shifts, work-hour rounding, half-day status, and attendance-date assignment. Employee creation, punch-in, punch-out, attendance listing, analytics, and regularization have also been manually exercised through Swagger UI.

Additional verification is still needed for weekend analytics, boundary conditions, concurrent requests, and query-plan behavior. See REVIEW.md for known issues and DECISIONS.md for design decisions. Passing these tests does not establish that every assignment requirement has been verified.