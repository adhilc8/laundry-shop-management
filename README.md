# Aseel Fabric Care Laundry

Flask web app for customers, administrators, laundry staff, and delivery agents. The app uses MySQL for its database and runs locally on this computer.

## Run locally on Windows
1. Install Python 3.10+ and MySQL 8+.
2. In PowerShell, open this project folder and create/activate a virtual environment:
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```
3. Install packages: `python -m pip install -r requirements.txt`.
4. Copy `.env.example` to `.env`. Set a random `SECRET_KEY`, MySQL `DATABASE_URL`, and a unique `SEED_ADMIN_PASSWORD` of at least 12 characters.
5. Create the MySQL database with `CREATE DATABASE aseel_laundry CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;`.
6. For a new, empty database run `flask --app run db upgrade`. For an existing database with the current app tables but no Alembic history, back it up first, then run `flask --app run db stamp head` instead. If Alembic history already exists, run `flask --app run db upgrade`.
7. Run `python seed.py` once to create missing starter services and, if no admin exists, the initial admin from the seed environment variables.
8. Start the local app with `python run.py` and visit `http://127.0.0.1:5000` on this computer. Stop it with `Ctrl+C` in the terminal.

## Share a temporary test link with Cloudflare Quick Tunnel
This exposes the app running on this computer through a temporary public URL. A Cloudflare account and domain are not required. Quick Tunnels are for testing, not production. Anyone with the generated URL can reach the app, so use test data only.

### Before starting
- Start the MySQL service and confirm the database in `.env` is reachable.
- Complete the database setup and run `python seed.py` as described above if this is the first run.
- Install `cloudflared` for Windows from the [official Cloudflare downloads page](https://developers.cloudflare.com/tunnel/downloads/) if it is not already installed. Open a new PowerShell terminal after installation so it can find `cloudflared`.

### Start the app and tunnel
1. In VS Code, open this project folder. Open a terminal, activate the virtual environment, and start Flask:
   ```powershell
   .\venv\Scripts\Activate.ps1
   flask --app run run --host 127.0.0.1 --port 5000
   ```
   Leave this terminal running. Check that `http://127.0.0.1:5000` opens on this computer.
2. Open a **second** VS Code terminal in the same project folder. Start the Quick Tunnel:
   ```powershell
   cloudflared tunnel --url http://127.0.0.1:5000
   ```
3. In the Cloudflare terminal, find the address printed after `Your quick Tunnel has been created! Visit it at`. It will look like `https://something.trycloudflare.com`. Open or share that URL on the other device.

Keep MySQL, the Flask terminal, and the Cloudflare terminal running while testing. Stop the tunnel with `Ctrl+C`; its URL will stop working and a new URL is generated next time. Quick Tunnel details and limitations are in [Cloudflare's documentation](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

## Accounts and data
- The seed admin phone defaults to `9999999999` (override with `SEED_ADMIN_PHONE`). Its password comes from `SEED_ADMIN_PASSWORD`; the script never embeds or prints a default password.
- Staff and delivery accounts are created under Admin > Team. Orders can be managed under Admin > Orders.
- Uploaded order photos are validated as real image files and served only to the order's customer, assigned team members, or an admin.
- Phone numbers accept 7–15 digits with an optional leading `+`.
- Login attempts are rate limited.
- Payments cannot exceed the outstanding balance. Customer order details and the admin payments page show paid and due amounts.
- Set real service prices before accepting bookings. Payment recording is manual, not a payment gateway.
