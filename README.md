# Smart Boarding & Billing System

An NDT Information Technology Software Engineering project for finding student boarding and managing a stay, from the first join request to rent collection and maintenance.

| Role | What they can do |
| --- | --- |
| Guest | Browse live published listings, search by location or name, and see current availability and rent. |
| Student | Request a stay, view the assigned boarding and bills, upload or withdraw a pending payment slip, download verified receipts, and request maintenance. |
| Owner | Publish a boarding, manage rooms and tenancies, issue bills, verify transfers or record cash payments, and manage expenses, maintenance and reports. |
| Admin | Moderate users and listings, review account access and tenancy-removal requests, and view platform activity. |

## Requirements

Python 3.14, MySQL 8.4, and SMTP credentials for email OTP and notifications. The app uses Flask, Waitress, Jinja, HTML, CSS and JavaScript.

## Local setup on Windows

1. Start MySQL. On a **fresh installation**, run [database/fresh-schema.sql](database/fresh-schema.sql) in MySQL Workbench using a setup account. It creates the schema without user records. Create a dedicated local runtime account and apply the table-specific permissions in [database/README.md](database/README.md). Keep an existing working database as-is.
2. In PowerShell, from the project folder, set up Python and copy the configuration template.

   ```powershell
   py -3.14 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
   .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
   ```

3. Put the generated value in `SECRET_KEY` in the new `.env` and fill in the database settings. For Gmail OTP and notifications, set `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER` and `SMTP_FROM` to your sending address, and `SMTP_PASSWORD` to its Google App Password. Keep `.env` outside Git. Registration uses Gmail addresses.
4. Start the application with Waitress.

   ```powershell
   .\.venv\Scripts\python.exe -B tools\run_main_wsgi.py
   ```

5. Open [the local application](http://127.0.0.1:5000). For first-time Admin provisioning, use the interactive instructions in [the Admin setup guide](docs/admin-portal.md).

## Payments and demo checklist

- **Guest** — Search for a published boarding and open its details page.
- **Student** — Log in or create a Gmail-verified account. Submit a join request. On a payable bill, choose **Upload from Computer** and select a JPG, PNG or static PDF within the displayed limit. A submitted slip can be withdrawn while it is **Pending Verification**.
- **Owner** — Approve a request and assign an available room or bed. Issue an invoice, verify the corresponding transfer, and check that the Student can view a receipt.
- **Admin** — Log in through the usual Login page, view the moderation dashboard, and check access controls.

Use separate browser profiles or one private window to keep two roles signed in during a demonstration.

Mobile QR upload needs a current, phone-reachable HTTPS origin routed through the upload-only gateway. Check the origin shortly before the demonstration because temporary addresses expire. Computer upload works independently. [Mobile upload setup](docs/mobile-payment-upload.md)

On an existing database, allocating a paid expense to a different accounting month requires migration 024. Fresh installations already include the column. [Database setup and upgrade notes](database/README.md)

The homepage and authentication photo is an AI-generated illustration. Boarding listings use the Owner's uploaded cover or a **No Image** placeholder.
