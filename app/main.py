"""Employee Attendance & Analytics API for the HROne take-home assignment."""
import os
from datetime import datetime, date, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Path
from pydantic import BaseModel, Field, field_validator
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError, OperationFailure

load_dotenv()
client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"), serverSelectionTimeoutMS=3000)
db = client[os.getenv("MONGO_DB", "attendance_db")]
IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc
PRESENT_STATUSES = ["PRESENT", "WFH", "ON_DUTY"]
ALL_STATUSES = PRESENT_STATUSES + ["ABSENT", "LEAVE"]
app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


def ensure_indexes():
    db.employees.create_index([("emp_code", ASCENDING)], unique=True, name="uq_employee_code")
    db.employees.create_index([("department", ASCENDING), ("emp_code", ASCENDING)], name="ix_employee_department_code")
    db.employees.create_index([("joined_on", ASCENDING), ("department", ASCENDING)], name="ix_employee_joined_department")
    db.attendance_logs.create_index([("emp_code", ASCENDING), ("date", ASCENDING)], unique=True, name="uq_attendance_employee_date")
    db.attendance_logs.create_index([("date", DESCENDING), ("emp_code", ASCENDING)], name="ix_attendance_date_employee")
    db.attendance_logs.create_index([("status", ASCENDING), ("date", DESCENDING)], name="ix_attendance_status_date")
    db.attendance_logs.create_index([("emp_code", ASCENDING), ("punch_in", DESCENDING)], name="ix_attendance_employee_punchin")
    db.attendance_logs.create_index([("date", ASCENDING), ("status", ASCENDING), ("emp_code", ASCENDING)], name="ix_attendance_date_status_employee")


@app.on_event("startup")
def startup():
    try:
        ensure_indexes()
    except Exception:
        # Health check remains the source of truth for database readiness.
        pass


def trunc(dt: datetime) -> datetime:
    return dt.replace(microsecond=0)


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(422, "date must be in YYYY-MM-DD format")


def parse_time(value: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (ValueError, TypeError):
        raise HTTPException(422, "time must be in HH:MM format")


def epoch_ms_to_ist(value: Optional[int]) -> datetime:
    if value is None:
        return trunc(datetime.now(UTC)).astimezone(IST)
    try:
        return trunc(datetime.fromtimestamp(value / 1000, tz=UTC).astimezone(IST))
    except (ValueError, OverflowError, OSError):
        raise HTTPException(422, "timestamp must be valid epoch milliseconds")


def db_dt(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def local_dt(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    # PyMongo returns naive UTC datetimes by default.
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(IST)


def api_dt(value: Optional[datetime]):
    value = local_dt(value)
    return int(value.timestamp() * 1000) if value else None


def round_half_up(value, places=2) -> float:
    quantum = Decimal("1").scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def shift_start_dt(punch_in: datetime, shift_start: str) -> datetime:
    pi = trunc(punch_in).astimezone(IST) if punch_in.tzinfo else trunc(punch_in).replace(tzinfo=IST)
    st = parse_time(shift_start)
    start = pi.replace(hour=st.hour, minute=st.minute, second=0, microsecond=0)
    # For an overnight shift, an early-morning punch belongs to previous day's shift.
    return start - timedelta(days=1) if parse_time(shift_end_placeholder := "00:00") == time(0, 0) and False else start


def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    pi = trunc(punch_in)
    if pi.tzinfo is None:
        pi = pi.replace(tzinfo=IST)
    else:
        pi = pi.astimezone(IST)
    st = parse_time(shift_start)
    start = pi.replace(hour=st.hour, minute=st.minute, second=0, microsecond=0)
    elapsed = int((pi - start).total_seconds())
    if elapsed < 0:
        elapsed += 86400
    if elapsed <= 600:
        return 0
    return elapsed // 60


def attendance_date_for(punch_in: datetime, employee: dict) -> str:
    pi = trunc(punch_in)
    if pi.tzinfo is None:
        pi = pi.replace(tzinfo=IST)
    else:
        pi = pi.astimezone(IST)
    st, en = parse_time(employee["shift_start"]), parse_time(employee["shift_end"])
    d = pi.date()
    if en <= st and pi.time().replace(tzinfo=None) < en:
        d -= timedelta(days=1)
    return d.isoformat()


def compute_overtime(punch_out: datetime, shift_end: str, attendance_day: str, shift_start: str = "09:30") -> int:
    po = trunc(punch_out)
    if po.tzinfo is None:
        po = po.replace(tzinfo=IST)
    else:
        po = po.astimezone(IST)
    end_t = parse_time(shift_end)
    start_t = parse_time(shift_start)
    end = datetime.combine(parse_date(attendance_day), end_t, tzinfo=IST)
    if end_t <= start_t:
        end += timedelta(days=1)
    seconds = int((po - end).total_seconds())
    return seconds // 60 if seconds >= 1800 else 0


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    a, b = trunc(punch_in), trunc(punch_out)
    if a.tzinfo is None: a = a.replace(tzinfo=UTC)
    if b.tzinfo is None: b = b.replace(tzinfo=UTC)
    return round_half_up(Decimal(str((b - a).total_seconds())) / Decimal(3600), 2)


def half_day(hours) -> bool:
    return hours is not None and Decimal(str(hours)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) < Decimal("4.50")


def serialize_doc(doc: dict) -> dict:
    out = dict(doc)
    oid = out.pop("_id", None)
    if oid is not None:
        out["id"] = str(oid)
    for key in ("punch_in", "punch_out"):
        if key in out:
            out[key] = api_dt(out[key])
    for entry in out.get("history", []) or []:
        if isinstance(entry.get("at"), datetime): entry["at"] = api_dt(entry["at"])
        for change in (entry.get("changes") or {}).values():
            for side in ("from", "to"):
                if isinstance(change.get(side), datetime): change[side] = api_dt(change[side])
    out.setdefault("history", [])
    out.setdefault("half_day", False)
    out.setdefault("late_minutes", 0)
    out.setdefault("overtime_minutes", 0)
    return out


class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str

    @field_validator("emp_code", "name", "email", "department")
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value: raise ValueError("must not be empty")
        return value

    @field_validator("shift_start", "shift_end")
    @classmethod
    def valid_time(cls, value):
        parse_time(value); return value

    @field_validator("joined_on")
    @classmethod
    def valid_joined_on(cls, value):
        parse_date(value); return value


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"

    @field_validator("status")
    @classmethod
    def valid_status(cls, value):
        if value not in PRESENT_STATUSES: raise ValueError("status must be PRESENT, WFH, or ON_DUTY")
        return value


class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None


class RegularizeIn(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None
    by: str
    reason: str

    @field_validator("status")
    @classmethod
    def valid_status(cls, value):
        if value is not None and value not in ALL_STATUSES: raise ValueError("invalid attendance status")
        return value


@app.get("/health")
def health():
    try:
        client.admin.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(503, "MongoDB is not ready")


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    doc["created_at"] = datetime.now(UTC)
    try: db.employees.insert_one(doc)
    except DuplicateKeyError: raise HTTPException(409, "emp_code already exists")
    doc.pop("_id", None)
    return doc


@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    q = {"department": department} if department else {}
    total = db.employees.count_documents(q)
    items = list(db.employees.find(q, {"_id": 0}).sort("emp_code", ASCENDING).skip((page-1)*page_size).limit(page_size))
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp: raise HTTPException(404, "employee not found")
    ts = epoch_ms_to_ist(body.punched_at)
    day = attendance_date_for(ts, emp)
    doc = {"emp_code": body.emp_code, "date": day, "status": body.status, "punch_in": db_dt(ts), "punch_out": None, "work_hours": None, "late_minutes": compute_late_minutes(ts, emp["shift_start"]), "overtime_minutes": 0, "half_day": False, "history": []}
    try: res = db.attendance_logs.insert_one(doc)
    except DuplicateKeyError: raise HTTPException(409, "already punched in for this attendance date")
    doc["_id"] = res.inserted_id
    return serialize_doc(doc)


@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp: raise HTTPException(404, "employee not found")
    ts = epoch_ms_to_ist(body.punched_at)
    tsdb = db_dt(ts)
    candidates = list(db.attendance_logs.find({"emp_code": body.emp_code, "punch_in": {"$ne": None, "$lte": tsdb}}).sort("punch_in", DESCENDING).limit(10))
    rec = None
    for candidate in candidates:
        pi = local_dt(candidate.get("punch_in"))
        if pi and ts - pi <= timedelta(hours=24):
            rec = candidate; break
    if rec is None: raise HTTPException(404, "no punch-in found")
    if rec.get("punch_out") is not None: raise HTTPException(409, "already punched out")
    pi = local_dt(rec["punch_in"])
    if ts <= pi or ts - pi > timedelta(hours=24): raise HTTPException(422, "punch-out must be after punch-in and within 24 hours")
    hours = compute_work_hours(pi, ts)
    update = {"punch_out": tsdb, "work_hours": hours, "overtime_minutes": compute_overtime(ts, emp["shift_end"], rec["date"], emp["shift_start"]), "half_day": half_day(hours)}
    result = db.attendance_logs.update_one({"_id": rec["_id"], "punch_out": None}, {"$set": update})
    if result.modified_count != 1: raise HTTPException(409, "already punched out")
    rec.update(update)
    return serialize_doc(rec)


@app.get("/attendance")
def list_attendance(emp_code: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None, status: Optional[str] = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    if date_from: parse_date(date_from)
    if date_to: parse_date(date_to)
    if date_from and date_to and date_from > date_to: raise HTTPException(422, "date_from must not be after date_to")
    if status and status not in ALL_STATUSES: raise HTTPException(422, "invalid status")
    q = {}
    if emp_code: q["emp_code"] = emp_code
    if status: q["status"] = status
    if date_from or date_to:
        q["date"] = {}
        if date_from: q["date"]["$gte"] = date_from
        if date_to: q["date"]["$lte"] = date_to
    total = db.attendance_logs.count_documents(q)
    docs = list(db.attendance_logs.find(q).sort([("date", DESCENDING), ("emp_code", ASCENDING)]).skip((page-1)*page_size).limit(page_size))
    return {"items": [serialize_doc(d) for d in docs], "total": total, "page": page, "page_size": page_size}


@app.patch("/attendance/{emp_code}/{attendance_day}")
def regularize(emp_code: str, attendance_day: str, body: RegularizeIn):
    parse_date(attendance_day)
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp: raise HTTPException(404, "employee not found")
    rec = db.attendance_logs.find_one({"emp_code": emp_code, "date": attendance_day})
    if not rec: raise HTTPException(404, "attendance record not found")
    old = dict(rec)
    new_status = body.status if body.status is not None else rec["status"]
    new_pi = epoch_ms_to_ist(body.punch_in) if body.punch_in is not None else local_dt(rec.get("punch_in"))
    new_po = epoch_ms_to_ist(body.punch_out) if body.punch_out is not None else local_dt(rec.get("punch_out"))
    if new_status in ("ABSENT", "LEAVE"):
        if body.punch_in is not None or body.punch_out is not None: raise HTTPException(422, "ABSENT/LEAVE cannot have punch times")
        new_pi = new_po = None
    else:
        if new_pi is None: raise HTTPException(422, "presence status requires punch_in")
        if attendance_date_for(new_pi, emp) != attendance_day: raise HTTPException(422, "punch_in must belong to attendance date")
        if new_po is not None and (new_po <= new_pi or new_po - new_pi > timedelta(hours=24)): raise HTTPException(422, "punch_out must be after punch_in and within 24 hours")
    pi_db, po_db = db_dt(new_pi), db_dt(new_po)
    late = compute_late_minutes(new_pi, emp["shift_start"]) if new_pi else 0
    hours = compute_work_hours(new_pi, new_po) if new_pi and new_po else None
    overtime = compute_overtime(new_po, emp["shift_end"], attendance_day, emp["shift_start"]) if new_pi and new_po else 0
    hd = half_day(hours) if hours is not None else False
    proposed = {"status": new_status, "punch_in": pi_db, "punch_out": po_db, "late_minutes": late, "work_hours": hours, "overtime_minutes": overtime, "half_day": hd}
    changes = {}
    for key, val in proposed.items():
        previous = rec.get(key, False if key == "half_day" else 0 if key in ("late_minutes", "overtime_minutes") else None)
        if previous != val:
            changes[key] = {"from": previous, "to": val}
    if not changes: raise HTTPException(422, "regularization does not change the record")
    history_entry = {"at": datetime.now(UTC), "by": body.by, "reason": body.reason, "changes": changes}
    result = db.attendance_logs.update_one({"_id": rec["_id"], "history": rec.get("history", [])}, {"$set": proposed, "$push": {"history": history_entry}})
    if result.modified_count != 1: raise HTTPException(409, "record changed concurrently; retry")
    rec.update(proposed); rec.setdefault("history", []).append(history_entry)
    return serialize_doc(rec)


def month_bounds(month: str):
    try: first = datetime.strptime(month, "%Y-%m").date()
    except ValueError: raise HTTPException(422, "month must be YYYY-MM")
    if first.month == 12: next_month = date(first.year+1, 1, 1)
    else: next_month = date(first.year, first.month+1, 1)
    return first, next_month - timedelta(days=1)


def weekdays_between(start: date, end: date) -> int:
    total = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5: total += 1
        cur += timedelta(days=1)
    return total


@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str = Query(..., description="YYYY-MM")):
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp: raise HTTPException(404, "employee not found")
    first, last = month_bounds(month)
    joined = parse_date(emp["joined_on"])
    work_start = max(first, joined)
    working_days = weekdays_between(work_start, last) if work_start <= last else 0
    rows = list(db.attendance_logs.aggregate([
        {"$match": {"emp_code": emp_code, "date": {"$gte": first.isoformat(), "$lte": last.isoformat()}}},
        {"$group": {"_id": None,
            "present_days": {"$sum": {"$cond": [{"$in": ["$status", PRESENT_STATUSES]}, {"$cond": [{"$eq": ["$half_day", True]}, 0.5, 1]}, 0]}},
            "leave_days": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
            "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}},
            "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
            "overtime_minutes": {"$sum": {"$ifNull": ["$overtime_minutes", 0]}}}}
    ]))
    a = rows[0] if rows else {"present_days": 0, "leave_days": 0, "late_count": 0, "total_late_minutes": 0, "overtime_minutes": 0}
    present = float(a["present_days"])
    rate = round_half_up(Decimal(str(present)) / Decimal(working_days) * 100, 4) if working_days else None
    return {"emp_code": emp_code, "month": month, "working_days": working_days, "present_days": present, "leave_days": a["leave_days"], "late_count": a["late_count"], "total_late_minutes": a["total_late_minutes"], "overtime_minutes": a["overtime_minutes"], "attendance_pct": rate}


@app.get("/analytics/departments/summary")
def department_summary(department: Optional[str] = None):
    emp_match = {"department": department} if department else {}
    emps = list(db.employees.aggregate([
        {"$match": emp_match}, {"$group": {"_id": "$department", "headcount": {"$sum": 1}}}
    ]))
    log_match = {"status": {"$in": ALL_STATUSES}}
    if department:
        codes = [e["emp_code"] for e in db.employees.find({"department": department}, {"emp_code": 1, "_id": 0})]
        log_match["emp_code"] = {"$in": codes}
    logs = list(db.attendance_logs.aggregate([
        {"$match": log_match},
        {"$group": {"_id": "$emp_code", "department": {"$first": "$department"},
          "present_days": {"$sum": {"$cond": [{"$in": ["$status", PRESENT_STATUSES]}, {"$cond": [{"$eq": ["$half_day", True]}, 0.5, 1]}, 0]}},
          "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}},
          "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
          "leave_count": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
          "on_duty_count": {"$sum": {"$cond": [{"$eq": ["$status", "ON_DUTY"]}, 1, 0]}},
          "work_hours_sum": {"$sum": {"$cond": [{"$and": [{"$in": ["$status", PRESENT_STATUSES]}, {"$ne": ["$work_hours", None]}]}, "$work_hours", 0]}},
          "work_hours_n": {"$sum": {"$cond": [{"$and": [{"$in": ["$status", PRESENT_STATUSES]}, {"$ne": ["$work_hours", None]}]}, 1, 0]}}}},
        {"$group": {"_id": "$_id", "present_days": {"$first": "$present_days"}, "late_count": {"$first": "$late_count"}, "total_late_minutes": {"$first": "$total_late_minutes"}, "leave_count": {"$first": "$leave_count"}, "on_duty_count": {"$first": "$on_duty_count"}, "work_hours_sum": {"$first": "$work_hours_sum"}, "work_hours_n": {"$first": "$work_hours_n"}}}
    ]))
    # Department membership comes from employees, not attendance records.
    dept_by_code = {e["emp_code"]: e["department"] for e in db.employees.find(emp_match, {"emp_code": 1, "department": 1, "_id": 0})}
    summary = {}
    for row in logs:
        dept = dept_by_code.get(row["_id"])
        if dept is None: continue
        item = summary.setdefault(dept, {"present_days": 0.0, "late_count": 0, "total_late_minutes": 0, "leave_count": 0, "on_duty_count": 0, "hours_sum": 0.0, "hours_n": 0})
        for k in ("present_days", "late_count", "total_late_minutes", "leave_count", "on_duty_count"): item[k] += row.get(k, 0) or 0
        item["hours_sum"] += row.get("work_hours_sum", 0) or 0; item["hours_n"] += row.get("work_hours_n", 0) or 0
    out = []
    for e in emps:
        dept = e["_id"]; a = summary.get(dept, {})
        n = a.get("hours_n", 0)
        out.append({"department": dept, "headcount": e["headcount"], "present_days": a.get("present_days", 0.0), "avg_work_hours": round_half_up(a["hours_sum"]/n, 2) if n else None, "late_count": a.get("late_count", 0), "total_late_minutes": a.get("total_late_minutes", 0), "leave_count": a.get("leave_count", 0), "on_duty_count": a.get("on_duty_count", 0)})
    return {"items": sorted(out, key=lambda x: x["department"])}


@app.get("/analytics/leaderboard/late")
def late_leaderboard(month: str = Query(..., description="YYYY-MM"), limit: int = Query(10, ge=1, le=100), department: Optional[str] = None):
    first, last = month_bounds(month)
    pipeline = [
        {"$match": {"date": {"$gte": first.isoformat(), "$lte": last.isoformat()}, "late_minutes": {"$gt": 0}}},
        {"$group": {"_id": "$emp_code", "total_late_minutes": {"$sum": "$late_minutes"}}},
        {"$sort": {"total_late_minutes": -1, "_id": 1}},
        {"$lookup": {"from": "employees", "localField": "_id", "foreignField": "emp_code", "as": "employee"}},
        {"$unwind": "$employee"},
    ]
    if department: pipeline.append({"$match": {"employee.department": department}})
    pipeline += [
        {"$setWindowFields": {"sortBy": {"total_late_minutes": -1}, "output": {"rank": {"$rank": {}}}}},
        {"$match": {"rank": {"$lte": limit}}},
        {"$sort": {"total_late_minutes": -1, "_id": 1}},
        {"$project": {"_id": 0, "emp_code": "$_id", "name": "$employee.name", "department": "$employee.department", "total_late_minutes": 1, "rank": 1}},
    ]
    try: items = list(db.attendance_logs.aggregate(pipeline))
    except OperationFailure as exc: raise HTTPException(500, f"leaderboard aggregation failed: {exc}")
    return {"items": items}


@app.get("/analytics/departments/{department}/trend")
def department_trend(department: str, from_date: str = Query(..., alias="from"), to_date: str = Query(..., alias="to")):
    start, end = parse_date(from_date), parse_date(to_date)
    if end < start: raise HTTPException(422, "to must be on or after from")
    if (end - start).days + 1 > 92: raise HTTPException(422, "date range cannot exceed 92 days")
    if not db.employees.find_one({"department": department}): raise HTTPException(404, "department not found")
    # Use MongoDB to group source records, then fill calendar gaps in the API response.
    pipeline = [
        {"$match": {"date": {"$gte": from_date, "$lte": to_date}}},
        {"$lookup": {"from": "employees", "localField": "emp_code", "foreignField": "emp_code", "as": "employee"}},
        {"$unwind": "$employee"}, {"$match": {"employee.department": department}},
        {"$group": {"_id": "$date", "present_count": {"$sum": {"$cond": [{"$in": ["$status", PRESENT_STATUSES]}, {"$cond": [{"$eq": ["$half_day", True]}, 0.5, 1]}, 0]}}, "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}}}},
    ]
    grouped = {r["_id"]: r for r in db.attendance_logs.aggregate(pipeline)}
    emps = list(db.employees.find({"department": department, "joined_on": {"$lte": to_date}}, {"emp_code": 1, "joined_on": 1, "_id": 0}))
    rows = []; cur = start
    while cur <= end:
        key = cur.isoformat(); headcount = sum(1 for e in emps if e["joined_on"] <= key)
        g = grouped.get(key, {}); present = float(g.get("present_count", 0)); late = g.get("late_count", 0); working = cur.weekday() < 5
        rate = round_half_up(Decimal(str(present))/Decimal(headcount)*100, 4) if working and headcount else (0.0 if working and headcount == 0 else None)
        rows.append({"date": key, "is_working_day": working, "headcount": headcount, "present_count": present, "late_count": late, "attendance_rate": rate})
        cur += timedelta(days=1)
    for i, row in enumerate(rows):
        window = [r["attendance_rate"] for r in rows[max(0, i-6):i+1] if r["attendance_rate"] is not None]
        row["moving_avg_7d"] = round_half_up(sum(window)/len(window), 4) if window else None
    return {"department": department, "from": from_date, "to": to_date, "items": rows}


@app.get("/admin/explain/{endpoint}")
def explain(endpoint: Literal["attendance_list", "employee_monthly", "department_summary", "late_leaderboard", "department_trend"], emp_code: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None, status: Optional[str] = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), month: Optional[str] = None, department: Optional[str] = None, limit: Optional[int] = Query(None, ge=1, le=100), from_date: Optional[str] = Query(None, alias="from"), to_date: Optional[str] = Query(None, alias="to")):
    if endpoint == "attendance_list":
        q = {}
        if emp_code: q["emp_code"] = emp_code
        if status: q["status"] = status
        if date_from or date_to:
            q["date"] = {}
            if date_from: q["date"]["$gte"] = date_from
            if date_to: q["date"]["$lte"] = date_to
        return db.command("explain", {"find": "attendance_logs", "filter": q, "sort": {"date": -1, "emp_code": 1}, "skip": (page-1)*page_size, "limit": page_size}, verbosity="executionStats")
    if endpoint == "employee_monthly":
        if not emp_code or not month: raise HTTPException(422, "emp_code and month are required")
        first, last = month_bounds(month)
        pipeline = [{"$match": {"emp_code": emp_code, "date": {"$gte": first.isoformat(), "$lte": last.isoformat()}}}, {"$group": {"_id": "$emp_code", "records": {"$sum": 1}}}]
        return db.command("explain", {"aggregate": "attendance_logs", "pipeline": pipeline, "cursor": {}}, verbosity="executionStats")
    if endpoint == "department_summary":
        pipeline = [{"$match": {"department": department}}] if department else []
        pipeline += [{"$group": {"_id": "$department", "headcount": {"$sum": 1}}}]
        return db.command("explain", {"aggregate": "employees", "pipeline": pipeline, "cursor": {}}, verbosity="executionStats")
    if endpoint == "late_leaderboard":
        if not month: raise HTTPException(422, "month is required")
        first, last = month_bounds(month)
        pipeline = [{"$match": {"date": {"$gte": first.isoformat(), "$lte": last.isoformat()}, "late_minutes": {"$gt": 0}}}, {"$group": {"_id": "$emp_code", "total_late_minutes": {"$sum": "$late_minutes"}}}, {"$sort": {"total_late_minutes": -1, "_id": 1}}]
        return db.command("explain", {"aggregate": "attendance_logs", "pipeline": pipeline, "cursor": {}}, verbosity="executionStats")
    if not department or not from_date or not to_date: raise HTTPException(422, "department, from, and to are required")
    parse_date(from_date); parse_date(to_date)
    pipeline = [{"$match": {"date": {"$gte": from_date, "$lte": to_date}}}, {"$group": {"_id": "$date", "records": {"$sum": 1}}}]
    return db.command("explain", {"aggregate": "attendance_logs", "pipeline": pipeline, "cursor": {}}, verbosity="executionStats")

