# Motilal School – Event Management System

A website where **teachers** create school events, give **each class its own topic**, review student uploads and approve them, and where **students** (no password needed) upload their work and download a **certificate** once the teacher approves.

* Python + Streamlit website · SQLite database (created automatically) · PDF certificates with QR code
* Everything is saved permanently – closing VS Code or restarting the computer does **not** delete anything.

> You do **not** need to know anything about databases. The application creates and upgrades its own database.
> Read the sections in order. Every command is written out exactly.

---

## Contents

1. [What you need](#1-what-you-need)
2. [Install and run on your computer (Steps 1–12)](#2-install-and-run-on-your-computer)
3. [Where is my data? (database, uploads, certificates, backups)](#3-where-is-my-data)
4. [Daily use: who does what](#4-daily-use-who-does-what)
5. [Restarting, updating, backing up, restoring](#5-restarting-updating-backing-up-restoring)
6. [Putting the website on the internet](#6-putting-the-website-on-the-internet)
7. [Troubleshooting](#7-troubleshooting)
8. [Running the automated tests](#8-running-the-automated-tests)
9. [Honest list of limits](#9-honest-list-of-limits)

---

## 1. What you need

* A computer with Windows 10/11 (macOS and Linux also work – commands for them are shown too).
* An internet connection for the installation.
* About 15 minutes.

## 2. Install and run on your computer

### STEP 1 – Install Python
1. Go to <https://www.python.org/downloads/> and download Python **3.11 or newer** (3.12 is a good choice).
2. Run the installer. **Tick the box “Add python.exe to PATH”** on the first screen, then click *Install Now*.
3. Check it worked: open **Command Prompt** (press the Windows key, type `cmd`, press Enter) and type:
   ```
   python --version
   ```
   You should see something like `Python 3.12.x`.
   (macOS/Linux: use `python3 --version`.)

### STEP 2 – Install VS Code
Download it from <https://code.visualstudio.com/> and install it with the default options.

### STEP 3 – Get the project folder
Unzip `motilal_school_event_system.zip` (right-click → *Extract All*). You will get a folder called **`motilal_school_event_system`**. Put it somewhere easy, for example `C:\SchoolApp\motilal_school_event_system`.

### STEP 4 – Open the project folder in VS Code
Start VS Code → **File → Open Folder…** → choose the **`motilal_school_event_system`** folder (the one that contains `app.py`) → *Select Folder*. Click “Yes, I trust the authors” if asked.

### STEP 5 – Open the terminal
In VS Code choose **Terminal → New Terminal**. A panel opens at the bottom. It must already be inside the project folder (you see `...\motilal_school_event_system>`).

> If the terminal is PowerShell and later commands complain about “running scripts is disabled”, run this once and try again:
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

### STEP 6 – Create and switch on a virtual environment
A virtual environment is a private box of libraries for this project.

| | Windows | macOS / Linux |
|---|---|---|
| Create (once) | `python -m venv .venv` | `python3 -m venv .venv` |
| Switch on (every new terminal) | `.venv\Scripts\activate` | `source .venv/bin/activate` |

After switching on, the line starts with `(.venv)`.
If VS Code asks “We noticed a new environment… use it?”, click **Yes**.

### STEP 7 – Install the requirements
```
pip install -r requirements.txt
```
Wait until it says *Successfully installed …*.

### STEP 8 – Run the application
```
streamlit run app.py
```
Your browser opens at **http://localhost:8501**. (If it does not, open that address yourself.)
Keep the terminal open while using the app. To stop the app press **Ctrl + C** in the terminal.

The files you run: **`app.py`** (always this one, from the project folder).

### STEP 9 – First administrator setup
The very first time you see the “Welcome! Let’s set up your school” page:
1. School name (already filled in as *Motilal School*), principal name, current academic year (for example `2026-27`).
2. Your name, a **username** and a **password** (at least 8 characters with letters and numbers). Write them down safely.
3. Click **Create administrator account**.

This page appears only once. After that the normal login page is shown.

### STEP 10 – Create teacher accounts
Log in (tab **Teacher / Admin Login**) → left menu **👥 User Management** → tab **Create account**. Enter name, username and a temporary password for each teacher. Give them their username and password privately; they can change the password under **🙍 My Profile**.
You can later edit a teacher, reset a forgotten password, or deactivate an account on the same page.

### STEP 11 – Create classes and sections
Left menu **🏫 Classes & Students**:
1. **Classes** tab → type `6` → *Add class* (repeat for 7, 8, 9, 10 – or any names, e.g. `Nursery`).
2. **Sections** tab → choose a class → type `A` → *Add section*.
3. **Students** tab → add each student (name, class, section, roll number) **or** import many at once from a CSV file with the columns `name,class,section,roll`.

A new class, section or academic year can be added **any time** – no change to the program is needed.

### STEP 12 – Start using it
* Teacher: **📅 Events** → *Create new event* → **🎯 Class Assignments** → add a different topic for each class → back in **📅 Events** click **🚀 Publish**.
* Students: open the website → tab **Student Login** → choose class and section, type name and roll number.
* Teacher: **📥 Submission Review** → open the work → **✅ Approve**, **🔁 Request corrections** or **❌ Reject** (feedback is required for the last two).
* Student: after approval the **🏅 Certificate** download appears.

---

## 3. Where is my data?

Everything lives inside the project folder and is created automatically on the first run. In VS Code’s *Explorer* (left side) you can see these folders:

| What | Where | Notes |
|---|---|---|
| **The database** (all accounts, events, topics, submissions, feedback, certificate records, settings) | `data/school_events.db` | One file. You never need to open it. |
| **Student uploads** | `uploads/submissions/` | One file per upload version. |
| Event posters and reference files | `uploads/events/` | |
| **Certificates (PDF)** | `certificates/` | One PDF per certificate. |
| **Backups** | `backups/` | ZIP files. |
| School logo and signatures | `assets/` | |
| Error/activity log | `logs/app.log` | Useful if something goes wrong. |

> ⚠️ The database holds the **records**; the uploads and certificates are **separate files**. A good backup contains **both** – the app’s *Backup* button does this for you.

These folders are **not** sent to Git (see `.gitignore`), so real student data is never published by accident.

To store the data somewhere else (for example on a hosting disk) set the environment variable `MSES_STORAGE_ROOT` – see `.env.example`.

---

## 4. Daily use: who does what

**Administrator** – everything below, plus: teacher accounts, **⚙️ Settings** (school name, **logo**, principal name and signature picture, default academic year, certificate colours, upload size limit, allowed file types, backups), **💾 Backup & Restore**, activity log.

**Teacher** – creates events and class topics, adds students/classes, reviews work of **their own events**, manages their certificates, sees reports. One teacher cannot see or change another teacher’s events (the administrator can see all).

**Student** – logs in with name + class + section + roll number (no password). Sees only the tasks of their own class and section, uploads PDF / DOCX / PPTX / JPG / JPEG / PNG files, reads feedback, uploads a corrected version if needed and downloads the certificate once approved.

Submission statuses: **Not Started → Submitted → Under Review → Approved / Rejected / Resubmission Required → Resubmitted**.
Old versions of a student’s file are always kept.

**Certificates** show the school name, student name, class, section, roll number, event, topic, a unique certificate ID, issue date, teacher and principal signature areas, the school logo (if you uploaded one) and a **QR code**. Scanning it (or typing the ID in the *Verify a Certificate* tab on the login page) shows whether it is valid. A revoked certificate is shown as **revoked**, never valid.
A teacher or administrator can upload a **picture of a signature** (My Profile / Settings). The system never invents signatures – without a picture an empty line is printed.

**Reports** (📊 Reports) – participation by event and class, status counts, pending/approved/rejected lists, certificate statistics, deadline completion – each with **CSV download**.

---

## 5. Restarting, updating, backing up, restoring

### Restart the application
Press **Ctrl + C** in the terminal, then run again:
```
streamlit run app.py
```
(Open the terminal in the project folder and switch on the virtual environment first: `.venv\Scripts\activate`.)
All data is still there.

### Update the application without losing data
1. **Make a backup first** (below).
2. Close the app (Ctrl + C).
3. Copy the new program files over the old ones **but do NOT delete or replace** the folders `data`, `uploads`, `certificates`, `backups`, `assets`, `logs`.
4. Run `pip install -r requirements.txt` again, then `streamlit run app.py`.
The app upgrades the database structure by itself and makes a safety backup before doing so. It never recreates or empties an existing database.

### Back up
* **Easiest:** log in as administrator → **💾 Backup & Restore** → **Create a backup now** → then **Download this backup** and keep the ZIP on another computer or a cloud drive.
* The app also makes an **automatic backup** about once a day (change this in ⚙️ Settings) and keeps the newest 14.
* From the terminal: `python manage.py backup` (also `python manage.py list` and `python manage.py check`).

### Restore a backup
* **In the app:** administrator → **💾 Backup & Restore → ♻️ Restore** → choose the backup ZIP → tick the box → type `RESTORE` → click the button. A safety copy of the current data is made first, and a damaged or wrong file is refused without touching your data.
* **If the app will not start:** stop it, then run `python manage.py restore backups\backup_manual_YYYYMMDD_HHMMSS.zip` (use `/` instead of `\` on macOS/Linux).
* Manual last resort: stop the app, delete `data/school_events.db`, `data/school_events.db-wal` and `data/school_events.db-shm`, unzip the backup and copy `database/school_events.db` to `data/`, and copy the `uploads`, `certificates` and `assets` folders from the ZIP into the project folder.

---

## 6. Putting the website on the internet

### Local files vs hosted storage – the one idea you must understand
On your own computer the folders `data/`, `uploads/` and `certificates/` are on your hard disk, so they stay.
On a hosting service the program runs in a **container** that is thrown away and rebuilt every time you update or the service restarts. Anything written to the container’s normal disk **disappears**. To keep data you must attach a **persistent disk** (a separate drive that survives) and tell the app to store everything there. The app does this through **one setting: `MSES_STORAGE_ROOT`**.

**Therefore: never use a free hosting plan without a persistent disk for real school data.**

### Recommended: Render.com with a persistent disk (included configuration)
The file **`render.yaml`** in this folder is a ready configuration:
* a Python web service started with `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`
* a **5 GB persistent disk mounted at `/var/data`**
* `MSES_STORAGE_ROOT=/var/data`, so the database, uploads, certificates, backups, logo and logs all live on the disk
* **one instance only** (SQLite needs a single server; a Render disk can only be attached to one anyway)
* HTTPS (a `https://….onrender.com` address) is included by Render.

**Cost note:** Render offers persistent disks only on paid instance types (“Starter” and above, roughly a few US dollars per month at the time of writing – check their price page). That is why `plan: starter` is set.

Steps:
1. Create a **private** repository on GitHub and upload this project folder (the `.gitignore` keeps `data/`, `uploads/`, etc. out). Use *GitHub Desktop* if you do not like the command line.
2. Create an account at <https://render.com> and add a payment method.
3. **New → Blueprint** → connect your GitHub repo → Render reads `render.yaml`.
4. When asked for the two secret values:
   * `MSES_SETUP_CODE` – choose any code (for example 6+ random characters). Whoever creates the first administrator must type it, so nobody else can grab your empty site.
   * `MSES_PUBLIC_URL` – the website address you will get, e.g. `https://motilal-school-events.onrender.com` (you can fill it in after the first deploy; it is printed on the certificate QR codes).
5. Click **Apply** and wait for the first deploy to turn green. Open the address Render shows.
6. Do **STEP 9–12** above on the website.
7. **Test that the disk really works before trusting it:** create a test class, then in Render choose **Manual Deploy → Deploy latest commit** (or *Restart service*). Open the site again – the class must still be there. If it is not, the disk is not attached – check the *Disks* tab.
8. Download a backup from **💾 Backup & Restore** regularly (the disk can be lost if the service is deleted). Consider also copying backups to Google Drive or similar – the app does not do off-site backups by itself.

**Updating the live site:** push your changes to GitHub; Render redeploys. The disk and database are untouched; the app upgrades the database structure itself.

Other hosts that offer **volumes** (Railway, Fly.io, a small VPS) also work: start the same command, mount a volume and set `MSES_STORAGE_ROOT` to its path. Hosts without a persistent volume (Streamlit Community Cloud, Heroku, free tiers) are **not suitable** for this application.

> This project was **not deployed by its author to Render** – the deployment file is provided and its structure checked, but you must follow the steps above and run the persistence test in step 7 yourself.

---

## 7. Troubleshooting

| Problem | What to do |
|---|---|
| `'python' is not recognized` | Python was installed without “Add to PATH”. Re-run the installer → *Modify* / reinstall with the box ticked. Close and reopen VS Code. |
| `'streamlit' is not recognized` | The virtual environment is not switched on. Run `.venv\Scripts\activate`, then try again. |
| Script execution disabled (PowerShell) | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` then activate again; or use *Command Prompt* instead. |
| `No module named …` | Run `pip install -r requirements.txt` with the virtual environment switched on. |
| Port 8501 already in use | Another copy is running. Close it, or run `streamlit run app.py --server.port 8502`. |
| Browser shows “Connection error” | The terminal running the app was closed. Start it again. |
| “The system is busy right now” | Two people saved at the same moment; wait a second and click again. |
| Student cannot log in | Name, class, section and roll number must all match the teacher’s record (spelling and spaces matter little, capital letters do not). Check the student exists in *Classes & Students → Students*. |
| Teacher locked out | After 5 wrong passwords the account is locked for 15 minutes; or the administrator resets the password. |
| Forgot the administrator password | With the virtual environment on, run `python manage.py reset-password YOUR_USERNAME` in the project folder (on a hosted site: open the service’s *Shell* and run the same command). It asks you to type a new password and unlocks the account. (There is deliberately no “forgot password” e-mail.) |
| Certificate button missing | The teacher has not approved the work yet – this is by design. |
| “The stored file could not be found” | A file was deleted from `uploads/`. Restore a backup, or ask the student to upload again. Run `python manage.py check` to list problems. |
| Something went wrong + a reference code | Open `logs/app.log` and search for the code to see the technical details. |

---

## 8. Running the automated tests

These are for developers; schools do not need them.
```
pip install -r requirements-dev.txt
playwright install chromium
pytest tests/unit tests/integration        # fast: services, security, persistence, backups
pytest tests/e2e                           # real browser against a real running server
```
The tests always use a **temporary empty storage folder**, never your real data. See **`TEST_REPORT.md`** for the results of the run done when this package was produced, and **`docs/DATABASE_DESIGN.md`** for the database diagram and table descriptions.

## 9. Honest list of limits

* **Not deployed** by the author: no hosting account was available. Only the local application was run and tested (Linux, Chromium).
* Tested in **Chromium** only (not Firefox/Safari) and on **Linux**; the Windows/macOS commands above are the standard ones but were not run on those systems.
* **Off-site/automatic cloud backups are not included** – backups are ZIP files on the same disk plus manual download. For a real school, copy them elsewhere regularly.
* SQLite is meant for **one server instance** and a few hundred simultaneous users at most (a school). Running several copies of the app against one database file is not supported.
* Student login has no password by design: anyone who knows a student’s name, class, section and roll number can open that student’s page. Students can only see their own tasks and files; they cannot change anything about other students or approve anything.
* Teacher PDF/Word/PowerPoint files are **downloaded** for review (browsers cannot preview them inside the page); images are previewed.
* The very first administrator can be created by anyone who opens a brand-new public site first – set `MSES_SETUP_CODE` when hosting publicly.

#cd motilal_school_event_system
#pip install -r requirements.txt
#streamlit run app.py