"""R3.1 - Night differential (22:00-06:00) and overtime computed from check-ins.

Attendance `validate` hook. Uses the in/out times HRMS sets when auto-attendance
processes Employee Checkins (or the times entered on a manual attendance).

  worked  = [in_time, out_time] minus the shift's unpaid break
  ND      = worked time inside 22:00-06:00 windows (only if the shift is ND-eligible)
  OT      = worked time after the scheduled shift end, rounded down
"""

from datetime import datetime, time, timedelta

import frappe
from frappe.utils import cint, flt, get_datetime, getdate

ND_START = time(22, 0)
ND_END = time(6, 0)


def to_time(value) -> time | None:
	if value is None or value == "":
		return None
	if isinstance(value, time):
		return value
	if isinstance(value, timedelta):
		return (datetime.min + value).time()
	return datetime.strptime(str(value).split(".")[0], "%H:%M:%S").time()


def overlap_hours(a_start, a_end, b_start, b_end) -> float:
	start, end = max(a_start, b_start), min(a_end, b_end)
	return max((end - start).total_seconds(), 0) / 3600


def subtract_interval(start, end, cut_start, cut_end) -> list[tuple]:
	if not cut_start or cut_end <= start or cut_start >= end:
		return [(start, end)]
	parts = []
	if cut_start > start:
		parts.append((start, cut_start))
	if cut_end < end:
		parts.append((cut_end, end))
	return parts


def get_shift_window(attendance_date, shift):
	start = datetime.combine(getdate(attendance_date), to_time(shift.start_time))
	end = datetime.combine(getdate(attendance_date), to_time(shift.end_time))
	if end <= start:
		end += timedelta(days=1)
	return start, end


def get_break_window(shift_start, shift_end, shift):
	break_start = to_time(shift.get("ph_break_start"))
	break_hours = flt(shift.get("ph_break_hours"))
	if not break_start or break_hours <= 0:
		return None, None
	start = datetime.combine(shift_start.date(), break_start)
	if start < shift_start:
		start += timedelta(days=1)
	if start >= shift_end:
		return None, None
	return start, start + timedelta(hours=break_hours)


def night_windows(start, end):
	day = start.date() - timedelta(days=1)
	while day <= end.date():
		yield datetime.combine(day, ND_START), datetime.combine(day + timedelta(days=1), ND_END)
		day += timedelta(days=1)


def round_down(hours: float, minutes: int) -> float:
	if minutes <= 0:
		return flt(hours, 2)
	step = minutes / 60
	return flt(int(hours / step + 1e-9) * step, 2)


def compute(in_time, out_time, attendance_date, shift, rounding_minutes: int) -> tuple[float, float]:
	"""Return (night_diff_hours, overtime_hours)."""
	in_time, out_time = get_datetime(in_time), get_datetime(out_time)
	if out_time <= in_time:
		return 0.0, 0.0

	shift_start, shift_end = get_shift_window(attendance_date, shift)
	break_start, break_end = get_break_window(shift_start, shift_end, shift)
	worked = subtract_interval(in_time, out_time, break_start, break_end)

	nd = 0.0
	if cint(shift.get("ph_night_diff_eligible")):
		for w_start, w_end in worked:
			for n_start, n_end in night_windows(w_start, w_end):
				nd += overlap_hours(w_start, w_end, n_start, n_end)

	ot = sum(overlap_hours(w_start, w_end, shift_end, out_time) for w_start, w_end in worked)
	return flt(nd, 2), round_down(ot, rounding_minutes)


def compute_night_diff_and_overtime(doc, method=None):
	doc.ph_night_diff_hours = 0
	doc.ph_overtime_hours = 0
	if not (doc.in_time and doc.out_time and doc.shift):
		return
	if doc.status not in ("Present", "Half Day", "Work From Home"):
		return

	shift = frappe.get_cached_doc("Shift Type", doc.shift)
	rounding = cint(frappe.db.get_single_value("PH Statutory Settings", "ot_rounding_minutes"))
	doc.ph_night_diff_hours, doc.ph_overtime_hours = compute(
		doc.in_time, doc.out_time, doc.attendance_date, shift, rounding
	)
