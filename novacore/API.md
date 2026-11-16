# NovaCore HR – Integration API (v1)

The HR module of the NovaCore ERP. Other modules (order management, warehouse /
fulfillment, delivery, customer support, finance) integrate with it over REST.

- **Base URL:** `http://localhost:8000` (local Docker). Production URL to be confirmed.
- **Endpoint path:** `/api/method/novacore_integrations.api.v1.<function>`
- **Format:** JSON. Successful responses are wrapped as `{"message": <result>}` (Frappe convention).
- **Errors:** HTTP 4xx/5xx with `{"exc_type": "...", "_server_messages": "..."}`.
  `403` = missing role, `404` = not found, `417` = validation error.

## Authentication

Each integrating system gets **its own API user**. The HR admin creates it and sends you
the key and secret:

1. User → new user with role **ERP Integration** (directory, incentives) and, for the
   Finance module only, **ERP Finance Integration** (payroll totals).
2. User → *Settings* → *API Access* → **Generate Keys**.

Send on every request:

```
Authorization: token <api_key>:<api_secret>
```

The demo site has `erp.integration@novacore.local` with both roles; generate its keys as above.

## Privacy

HR data is personal information under the Data Privacy Act (RA 10173). The API **never**
returns government IDs (SSS, PhilHealth, Pag-IBIG, TIN), salary, bank details or personal
contact details. Payroll data is only available in aggregate, never as one employee's pay.

---

## Endpoints

### `GET health`
No auth. Use it for uptime checks.
```json
{"message": {"status": "ok", "service": "novacore-hr", "api_version": "v1"}}
```

### `GET get_employees` — employee directory
Role: ERP Integration

| Param | Type | Notes |
|---|---|---|
| `status` | string | `Active`, `Inactive`, `Suspended`, `Left` |
| `department` | string | e.g. `Operations – Telco Campaign - NBSI` |
| `designation` | string | |
| `modified_since` | datetime | `2026-11-01 00:00:00`, for incremental sync |
| `limit` | int | default 100, max 500 |
| `offset` | int | for paging; follow `next_offset` until it is `null` |

```bash
curl -H "Authorization: token KEY:SECRET" \
  "http://localhost:8000/api/method/novacore_integrations.api.v1.get_employees?status=Active&limit=100"
```
```json
{"message": {
  "data": [{
    "employee_id": "HR-EMP-00005", "full_name": "Juan Reyes", "first_name": "Juan", "last_name": "Reyes",
    "status": "Active", "employment_stage": "Probationary", "company": "NovaCore Business Solutions Inc.",
    "department": "Operations – Telco Campaign - NBSI", "designation": "Customer Service Agent",
    "branch": null, "reports_to": "HR-EMP-00004", "work_email": "juan.reyes@novacore.local",
    "user_id": "juan.reyes@novacore.local", "date_of_joining": "2026-03-02", "relieving_date": null,
    "shift": "Night Shift", "modified": "2026-11-16 09:12:44.120391"}],
  "count": 1, "next_offset": null}}
```

`employment_stage` is one of `Probationary`, `Regular`, `On Leave`, `Suspended`,
`Notice Period`, `Separated`.

### `GET get_employee?employee_id=HR-EMP-00005`
Role: ERP Integration. Returns a single employee in the same shape as the directory.

### `GET get_departments?company=...`
Role: ERP Integration. Returns departments with `site` and `active_headcount`.

### `GET is_active_employee?user_or_employee=juan.reyes@novacore.local`
Role: ERP Integration. A fast check before assigning work (an order pick, a delivery, a
support ticket). `active` is false when the employee is Left, Suspended or Separated.
```json
{"message": {"active": true, "employee_id": "HR-EMP-00005", "status": "Active", "employment_stage": "Probationary"}}
```

### `POST post_incentives` — commissions and incentives into payroll
Role: ERP Integration. Use this for sales commissions, fulfillment bonuses and similar
amounts. Each entry becomes an *Additional Salary* that the next payroll run includes as
taxable pay.

```json
{
  "source_system": "Order Management",
  "payroll_date": "2026-11-15",
  "entries": [
    {"employee_id": "HR-EMP-00006", "amount": 1500.00, "reference": "COMM-2026-11-A-0006"},
    {"employee_id": "HR-EMP-00007", "amount": 800.00, "reference": "COMM-2026-11-A-0007",
     "component": "Sales Incentive"}
  ]
}
```
- `reference` is **required and must be unique per source system**. Re-sending the same
  reference is skipped, so retries are safe.
- `component` defaults to `Sales Incentive`. It must be an *Earning* salary component.
- Maximum 500 entries per call. Each entry succeeds or fails on its own:

```json
{"message": {
  "created": [{"reference": "COMM-2026-11-A-0006", "additional_salary": "HR-ADS-.2026.-00001"}],
  "skipped": [],
  "errors": [{"index": 1, "reference": "COMM-2026-11-A-0007", "error": "employee HR-EMP-00007 is not active"}]}}
```

### `GET list_payroll_runs?company=...&released_only=1`
Role: ERP Finance Integration. Lists payroll runs, newest first.

### `GET get_payroll_summary?payroll_entry=HR-PRUN-2026-00001`
Role: ERP Finance Integration. Aggregated totals for posting to the general ledger:
`totals` (employees, gross, deductions, net), `by_department`, `components` (each
earning and deduction), and `statutory` (SSS, PhilHealth, Pag-IBIG, BIR, with employee
and employer shares).

### `POST novacore_integrations.connectors.kpi.push_kpis`
Performance scores from fulfillment or support systems, attached to the employee's draft
appraisal: `{"appraisal_cycle": "Q4 2026", "scores": [{"employee": "HR-EMP-00005", "kpi_score": 92.4}]}`.
Scores range from 0 to 100. This needs the HR Manager role; ask HR for a user.

---

## Webhooks (HR → your system)

HR registers your endpoint in **ERP Event Subscription** (system name, URL, signing
secret, chosen events). Each event is POSTed after the HR change is committed.

| Event | When | `data` |
|---|---|---|
| `employee.created` | New employee record | employee object (same as directory) |
| `employee.updated` | Name, status, stage, department, designation, branch, manager, email or relieving date changed | employee object |
| `employee.separated` | Status changed to Left | employee object — **revoke the person's access in your system** |
| `payroll.released` | Payroll approved and slips submitted | payroll summary (same as `get_payroll_summary`) |
| `ping` | "Send Test Event" button | `{"message": ...}` |

Request:
```
POST <your endpoint>
Content-Type: application/json
X-NovaCore-Event: employee.separated
X-NovaCore-Delivery: 3f1c...          (unique; use it to ignore duplicates)
X-NovaCore-Signature: <hex HMAC-SHA256 of the raw body, keyed with the shared secret>

{"id": "3f1c...", "event": "employee.separated", "occurred_at": "2026-11-16T09:00:00", "data": {...}}
```

**Verify the signature before trusting the body.** Python example:
```python
import hashlib, hmac
expected = hmac.new(SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
if not hmac.compare_digest(expected, request.headers["X-NovaCore-Signature"]):
    return 401
```

Respond with any `2xx` within 30 seconds. Non-2xx responses and timeouts are retried
(2 retries by default). Every attempt is logged on the HR side in *Integration Request*.
Deliveries can arrive more than once, so de-duplicate on `X-NovaCore-Delivery`.
