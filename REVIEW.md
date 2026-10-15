# Code Review

## Defects Found in the Starter

| # | Where | What is wrong | How to notice it | How it was addressed |
|---|---|---|---|---|
| 1 | `health()` | The starter returns healthy even if MongoDB is unavailable. | Stop MongoDB or use an invalid connection and call `/health`. | Added a database ping and HTTP 503 on failure. |
| 2 | `create_employee()` | Checking for duplicates before inserting is vulnerable to concurrent requests. | Send two simultaneous requests with the same employee code. | Added a unique employee-code index and handling for duplicate-key errors. |
| 3 | Date and time helpers | The starter relies on local system time and does not consistently apply IST attendance-day rules. | Test timestamps around midnight and UTC/IST boundaries. | Added epoch-millisecond conversion, IST date handling, and UTC storage helpers. Overnight edge cases still require further testing. |
| 4 | `compute_late_minutes()` | The starter truncates elapsed minutes and does not correctly implement the strict 10-minute grace boundary. | Test punches at 09:40:00 and 09:40:01 for a 09:30 shift. | Added second-level comparison and floor-based minute calculation. Overnight shift edge cases still require testing. |
| 5 | `compute_work_hours()` | The starter uses Python's standard rounding rather than the required ROUND_HALF_UP rule. | Test durations that fall exactly on rounding boundaries. | Added decimal ROUND_HALF_UP rounding to two decimal places. |
| 6 | `compute_overtime()` | The starter does not enforce the 30-minute minimum and does not correctly handle overnight shifts. | Test an overtime duration of 29 minutes, 30 minutes, and an overnight shift. | Added a 30-minute threshold and overnight shift-end calculation. Boundary tests remain necessary. |
| 7 | `list_employees()` | Pagination skips the first page incorrectly, and the total ignores the department filter. | Compare page 1 and page 2 and filter by department. | Added validated, database-side pagination, filtered counts, and deterministic sorting. |
| 8 | `list_attendance()` | The starter loads all matching records into Python before sorting and paginating. | Inspect behavior with a large dataset and compare page results. | Moved filtering, sorting, and pagination into MongoDB. |
| 9 | Request validation | The starter does not sufficiently validate statuses, dates, timestamps, or pagination parameters. | Send invalid values through Swagger UI. | Added validation for attendance statuses, date/time strings, timestamp conversion, and pagination bounds. |
| 10 | Missing API operations | The starter leaves punch-out, regularization, analytics, and query-plan endpoints unimplemented. | Compare the registered routes with `openapi.yaml`. | Added the missing endpoint implementations. Their business-rule correctness still needs additional testing. |

## Known Issues Requiring Further Work

- Fixed regularization history comparison by normalizing punch timestamps to UTC at second precision. Manually verified that unchanged punch-in values are omitted from new history entries. Calculation regression tests are included; automated integration tests for regularization history are still needed.
- Monthly and department-summary present-day calculations need to exclude weekend records while still counting weekend lateness and overtime where required.
- Punch-out searches only the ten most recent candidate records, which can miss a valid earlier record in edge cases.
- Department trend fills calendar gaps in Python rather than performing all required aggregation in MongoDB.
- The explain endpoint needs verification to ensure its query plan reflects the actual filters and pagination of each corresponding endpoint.
- Added 8 automated calculation tests; `python -m pytest -v` reports 8 passed. Automated endpoint integration tests and further edge-case checks are still needed.

## Items Reviewed That Are Not Defects

- Returning HTTP 201 for employee creation and punch-in is intentional.
- Returning HTTP 200 for successful punch-out, attendance retrieval, and regularization is intentional.
- An attendance record with a short completed work duration can correctly have `half_day: true`.
- MongoDB's unique indexes are necessary for duplicate protection under concurrent requests; a preliminary application-level lookup alone is insufficient.

