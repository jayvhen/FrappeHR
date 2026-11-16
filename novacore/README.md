# NovaCore HRIS (Frappe HR v15)

The **HR module of the NovaCore e-commerce ERP**. Other ERP modules (orders, warehouse,
delivery, support, finance) connect over REST. See **[API.md](API.md)** for the integration contract.

Implementation of the TO-BE design in `NovaCore Frappe HR – TO-BE System Diagrams/`.
Per the Package Diagram, NovaCore features live in two custom apps that run beside
the stock Frappe HR app (the upstream `hrms/` code stays untouched and upgradeable):

| App | Contents |
|---|---|
| `apps/novacore_ph` | PH Statutory Engine (SSS, PhilHealth, Pag-IBIG, BIR), night differential & overtime, employee lifecycle, 24h escalation, payroll approval workflow, HR Helpdesk, government reports, NovaCore HR workspace |
| `apps/novacore_integrations` | Biometric push API, Bank payroll API, KPI import, AD / M365 provisioning, job boards, e-signature, SMS notices |

## Run locally (Docker)

Requirements: Docker Desktop (WSL 2 backend), ~4 GB RAM for Docker, ~10 GB disk.

```powershell
cd docker
docker compose up -d
docker compose logs -f frappe     # first start takes 20-40 minutes
```

Open **http://localhost:8000** when the log prints `Ready`.

| User | Password | Role (diagram actor) |
|---|---|---|
| Administrator (username `Amin`) | set by the site owner | System Manager |
| hr.manager@novacore.local | `NovaCore@2026` | HR Staff / HR Manager |
| payroll@novacore.local | `NovaCore@2026` | Payroll Officer |
| finance@novacore.local | `NovaCore@2026` | HR / Finance Manager |
| teamlead@novacore.local | `NovaCore@2026` | Team Leader |
| juan.reyes@novacore.local | `NovaCore@2026` | Employee (agent, night shift) |

Change these passwords before any non-demo use. Settings live in `docker/.env` (see `.env.example`).

Useful commands:

```powershell
docker compose exec frappe bash -c "cd frappe-bench && bench --site novacore.localhost migrate"
docker compose exec frappe bash -c "cd frappe-bench && bench --site novacore.localhost execute novacore_ph.setup.demo.run"
docker compose exec frappe bash -c "cd frappe-bench && bench --site novacore.localhost run-tests --app novacore_ph"
docker compose down          # stop (data kept)
docker compose down -v       # stop and DELETE all data
```

`bench migrate` is the schema migration: it syncs the DocTypes and re-applies custom fields,
roles, permissions, salary components and statutory tables (all idempotent).

## Demo walkthrough (matches the diagrams)

1. **Payroll run (Activity 11 / Sequence 12)** – log in as `payroll@`, open Payroll Entry for
   Nov 1–15 2026, review **Payroll Approval → Exceptions Report**, then **Request Approval**.
   Log in as `finance@` → **Approve & Release** (or **Reject** with a reason). Approval submits
   the slips, posts the accrual journal entry to ERPNext and attaches the bank disbursement file
   (or calls the bank API when configured).
2. **Statutory deductions** – open any salary slip: SSS / PhilHealth / Pag-IBIG / withholding
   tax rows plus the *PH Statutory Contributions* table (employee + employer shares).
3. **Night differential (Timing 16)** – Juan Reyes' attendance on 2026-11-03 shows 7.0 ND hours,
   his Nov 5 overtime is paid because an Overtime Request was approved.
4. **Escalation (R1)** – Ana's open Overtime Request is escalated by the hourly job to the
   department manager once it is older than 24 hours.
5. **Government reports** – NovaCore HR workspace → SSS R-3, PhilHealth RF-1, Pag-IBIG MCRF,
   BIR 1601-C (October 2026 has released payroll data).
6. **Lifecycle (State Machine 13)** – Employee *Employment Stage*: Probationary → Regular on a
   submitted appraisal with score ≥ 3; Notice Period when an Employee Separation is created;
   Separated when the relieving date passes.

## Notes

- **Email:** notifications (approval requests, rejections, ticket updates, payslips) need an
  outgoing Email Account (*Settings → Email Account*). Without one, every action still works;
  the unsent notification is recorded in *Error Log*.
- **Who sees whom:** employees and Team Leaders only see their own Employee record (ERPNext
  default). HR Manager, HR User, Payroll Officer and HR Finance Manager users are exempted
  automatically so they can work with all employees. Team Leaders see the leave / overtime
  requests they must approve because those are shared with them.
- **Government IDs** (SSS, PhilHealth, Pag-IBIG, TIN) are visible only to HR and payroll roles.

## Configuration

- **PH Statutory Settings** – components, ND/OT rates, semi-monthly schedule, escalation hours.
- **PH Contribution Table** – versioned rate tables. A new circular = a new table with a later
  *Effective From*; nothing to code.
- **NovaCore Integration Settings** – endpoints/credentials. Disabled connectors fall back to a
  ToDo or downloadable file so steps are never silently skipped. Calls are logged in
  *Integration Request*.
- **Biometric devices** – create a user with the *Biometric Device* role, generate API keys, and
  have terminals POST to `/api/method/novacore_integrations.connectors.biometric.push_checkins`.

## Diagram traceability

| Requirement (Diagram 17) | Implemented in |
|---|---|
| R1 Automated approvals, 24h escalation | `novacore_ph/workflow/escalation.py`, Overtime Request, payroll approval |
| R2 Real-time attendance, failure alerts | `novacore_integrations/connectors/biometric.py`, Biometric Device |
| R3 PH payroll compliance | `novacore_ph/statutory/engine.py`, `payroll/salary_slip.py` |
| R3.1 Night diff & OT from check-ins | `novacore_ph/attendance/attendance.py` |
| R4 Bank disbursement | `novacore_integrations/connectors/bank.py` |
| R5 Account provisioning | `novacore_integrations/connectors/provisioning.py` |
| R6 KPI-based appraisal | `novacore_integrations/connectors/kpi.py`, Appraisal *KPI Score* |
| R7 Data privacy (RA 10173) | Government IDs at permission level 1 (HR/payroll only), secrets in Password fields, redacted integration logs |

Out of scope / external: the diagrams' production topology (Nginx + SSL, MariaDB replica, NAS and
off-site backups, AD domain controller) is infrastructure, not app code. This Docker stack is
for local development.
