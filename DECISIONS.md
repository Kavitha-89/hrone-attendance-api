# Design Decisions

## 1. Indexes

I created a unique index on `employees.emp_code` to prevent duplicate employee codes. The unique compound index on `attendance_logs.emp_code` and `date` prevents more than one attendance record per employee per day. Other compound indexes support department lookups, date sorting, status filters, and finding an employee's latest punch-in. I would avoid adding more indexes without checking query plans because indexes consume storage and make writes more expensive. A separate standalone status index was not added because existing compound indexes already cover status-leading queries.

## 2. Punch-in race

If two identical punch-in requests arrive together, both may pass the employee lookup. Both try to insert the same employee and attendance date. MongoDB's unique compound index allows only one insert. The other raises `DuplicateKeyError`, which the API converts to HTTP 409 Conflict.

## 3. Leaderboard ties

The leaderboard sorts employees by total late minutes and uses employee code for deterministic display order. Ranking is based on late minutes, not employee code. The query includes every employee whose rank is at or below the requested limit, so a tie at the cutoff can return more items than the limit.

## 4. Headcount

Department headcount is aggregated from the employees collection separately from attendance logs. Therefore, employees with no attendance records still contribute to headcount; their attendance metrics default to zero or null as appropriate.

## 5. Scaling to 100x data

I would benchmark the expensive analytics queries and consider pre-aggregated daily or monthly summaries. This would reduce repeated scans of attendance records while preserving the raw records for audit and regularization.