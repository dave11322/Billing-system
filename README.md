# Digital Billing System for an Energy Company (Django)

Built from the proposal: customer accounts, meter readings, automated bill calculation,
payment recording and tracking, reconciliation, role-based access, audit trail and reports.

## Setup (Windows, PowerShell or VS Code terminal)
```
cd billing_system
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python manage.py makemigrations billing
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```
Open http://127.0.0.1:8000/

macOS / Linux: use `python3` and `source venv/bin/activate`.

## Demo logins (created by `seed_demo`, change them before real use)
| Username   | Password     | Role                 |
|------------|--------------|----------------------|
| admin      | Admin@12345  | System administrator |
| billing1   | Pass@12345   | Billing staff        |
| accounts1  | Pass@12345   | Accounts staff       |
| manager1   | Pass@12345   | Management           |

## Role permissions
- Administrator: everything, plus the Django admin panel at /admin/
- Billing staff: register customers, record readings (bills are generated automatically)
- Accounts staff: record payments, reconcile
- Management: view everything, reports, audit trail

## Billing rule
Energy charge = units used x tariff rate; add fixed charge; add VAT (16% default) on the sum.
Change tariffs in /admin/ > Tariffs.

## Accuracy controls
Previous reading is taken from the last stored reading; current reading cannot be lower;
one reading per customer per month; payment reference must be unique (blocks duplicates);
payment can only be applied to the same customer's bill; every key action is written to the audit trail.

## Backup
Copy `db.sqlite3` regularly. To back up as JSON: `python manage.py dumpdata billing > backup.json`
