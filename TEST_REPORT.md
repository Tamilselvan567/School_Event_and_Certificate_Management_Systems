# Test Report — Motilal School Event Management System

All results below come from a real run of `pytest tests` on the final code (151 tests, 4 min 20 s, one run, Linux container, Chromium via Playwright). Nothing is simulated or estimated.

## Summary

| Total | Passed | Failed | Blocked | Not executed |
|---|---|---|---|---|
| 151 | 151 | 0 | 0 | see list below |

Groups: A = admin services, B/C = teacher/student services, D = workflow, E = persistence (incl. real process restarts), F = security, H = edge cases, U = utilities, G = real-browser tests.

## Defects found during testing and fixed

- Backup/restore service functions had no admin check (only the UI hid them) → admin-checked wrappers added.
- A reference-file lookup revealed whether another class's task had an attachment → permission check now runs first.
- A broken optional folder stopped all database access → folder setup made tolerant, backup shows a friendly error.
- Mobile menu button was hidden by CSS → fixed; mobile header no longer overlaps the banner.
- Forms erased typed input after a validation error / kept old values after success → fixed.
- Error messages vanished when the page layout shifted → message area is now always present.
- Certificate footer overlapped corner artwork → moved.
- README mentioned admin password recovery that did not exist → `manage.py reset-password` added and documented.
- CSV export columns were in a different order from the on-screen table → fixed.

## Unresolved issues

None known from the executed tests. This does not prove there are no bugs.

## NOT executed (do not assume these work)

- **Public deployment**: the app was never deployed. `render.yaml` parses as YAML but was not run on Render.
- Persistent-disk behaviour on the hosting service (data was verified to survive restarts only locally).
- Installing and running on Windows or macOS (tested on Linux only).
- Browsers other than Chromium (Firefox, Safari); real phones (only 390 px and 768 px emulated viewports).
- Visual check of loading spinners / upload progress bars.
- Every button in the browser: event Close / Reopen / Archive / Delete and several admin edit buttons were tested through the service layer only, not clicked.
- Load testing with many simultaneous users.
- Off-site backups are not implemented; downloaded ZIPs must be stored by the school. No Dockerfile is provided.

## Detailed results

| ID | Description | Expected | Actual | Result |
|---|---|---|---|---|
| A01 | Initial administrator setup | First run asks for setup; after it, setup is closed and settings are saved | As expected | PASS |
| A02 | Setup code on public sites | When MSES_SETUP_CODE is set, setup needs the right code | As expected | PASS |
| A03 | Admin login + incorrect password | Right password logs in; wrong password and unknown user give the same generic message | As expected | PASS |
| A04 | Brute-force protection | After 5 wrong passwords the account is locked even for the right password | As expected | PASS |
| A05 | Create teacher | Teacher is created; duplicate username (any letter case) is refused; weak password refused | As expected | PASS |
| A06 | Edit teacher | Name and designation change and persist | As expected | PASS |
| A07 | Deactivate teacher | Cannot log in, and an already-open session stops working immediately | As expected | PASS |
| A08 | Reset teacher password | Old password stops working, new one works | As expected | PASS |
| A09 | Admin safety | An administrator cannot deactivate themselves or the last administrator | As expected | PASS |
| A10 | Classes, sections, academic years | Add, duplicate refusal, edit, deactivate and hide from login lists | As expected | PASS |
| A11 | Settings updates | Valid settings persist; invalid values and unknown keys are refused | As expected | PASS |
| A12 | Logo and signature images | Valid PNG is saved and used; non-images are refused | As expected | PASS |
| A13 | Unauthorized admin operations | Teachers and students are refused every administrator-only action | As expected | PASS |
| A14 | Passwords stored securely | No plain-text password appears anywhere in the database file | As expected | PASS |
| A15 | Change own password | Needs the current password; new password works afterwards | As expected | PASS |
| A16 | Student CSV import | Valid rows are added; duplicates and unknown classes are reported per row | As expected | PASS |
| B01 | Teacher login / invalid login | Valid teacher logs in; wrong password or student-only data is refused | As expected | PASS |
| B02 | Create / edit event | Event saved as draft and editable; empty name, past deadline, deadline before opening date refused | As expected | PASS |
| B03 | Event poster | PNG poster is stored and returned; a PDF poster is refused | As expected | PASS |
| B04 | Publish / unpublish / close / reopen / archive | Allowed moves work, invalid moves are refused, publish needs an assignment | As expected | PASS |
| B05 | Different topics for different classes | One event holds five class topics; each class sees only its own | As expected | PASS |
| B06 | Section-specific assignment | A topic for section A is not visible to section B students | As expected | PASS |
| B07 | Assignment deadlines and formats | Invalid formats, past deadlines and inactive classes are refused; custom deadline is kept | As expected | PASS |
| B08 | Reference materials | Reference file is stored; only that class's students and the owner can fetch it | As expected | PASS |
| B09 | View submissions + download | Teacher sees student, event and topic details and downloads the exact uploaded file | As expected | PASS |
| B10 | Approve / reject / request corrections | Each action sets the right status, stores feedback, and needs feedback when rejecting | As expected | PASS |
| B11 | Marks validation | Marks above the maximum, negative or non-numeric are refused | As expected | PASS |
| B12 | Review resubmissions | A corrected upload returns to the teacher as 'Resubmitted' and can then be approved | As expected | PASS |
| B13 | Review audit trail | Every decision records reviewer, action, time, feedback, previous and new status | As expected | PASS |
| B14 | Reports and CSV export | Report numbers match the real data; CSV cells cannot run as spreadsheet formulas | As expected | PASS |
| B15 | Delete event safeguards | Only draft/archived events without submissions, after typing the exact name, can be deleted | As expected | PASS |
| B16 | Teacher dashboard numbers | Totals for events, students, submissions, pending, approved, rejected and deadlines are correct | As expected | PASS |
| C01 | Student login with correct details | Works without a password; name is not case or spacing sensitive | As expected | PASS |
| C02[kw0] | Student login with incorrect details | A wrong name, section or roll number gives one generic 'not found' message | As expected | PASS |
| C02[kw1] | Student login with incorrect details | A wrong name, section or roll number gives one generic 'not found' message | As expected | PASS |
| C02[kw2] | Student login with incorrect details | A wrong name, section or roll number gives one generic 'not found' message | As expected | PASS |
| C02[kw3] | Student login with incorrect details | A wrong name, section or roll number gives one generic 'not found' message | As expected | PASS |
| C03 | Right name/roll but wrong class | Refused (identity is name + class + section + roll) | As expected | PASS |
| C04[class] | Missing name / class / section / roll | Each missing field gives a clear message asking for it | As expected | PASS |
| C04[name] | Missing name / class / section / roll | Each missing field gives a clear message asking for it | As expected | PASS |
| C04[roll] | Missing name / class / section / roll | Each missing field gives a clear message asking for it | As expected | PASS |
| C04[section] | Missing name / class / section / roll | Each missing field gives a clear message asking for it | As expected | PASS |
| C05 | Inactive student / hostile input | Deactivated students cannot log in; SQL-looking input just fails safely | As expected | PASS |
| C06 | Only assigned events visible | Each student sees exactly one task (their class's topic); unrelated classes are hidden | As expected | PASS |
| C07 | Draft events are hidden | Students never see unpublished events | As expected | PASS |
| C08 | Open assigned topic + read instructions | Student sees topic, description, formats, deadline and marks | As expected | PASS |
| C09[docx] | Upload PDF / DOCX / PPTX / JPG / PNG | Each supported real file is accepted, saved and set to Submitted | As expected | PASS |
| C09[jpg] | Upload PDF / DOCX / PPTX / JPG / PNG | Each supported real file is accepted, saved and set to Submitted | As expected | PASS |
| C09[pdf] | Upload PDF / DOCX / PPTX / JPG / PNG | Each supported real file is accepted, saved and set to Submitted | As expected | PASS |
| C09[png] | Upload PDF / DOCX / PPTX / JPG / PNG | Each supported real file is accepted, saved and set to Submitted | As expected | PASS |
| C09[pptx] | Upload PDF / DOCX / PPTX / JPG / PNG | Each supported real file is accepted, saved and set to Submitted | As expected | PASS |
| C10[a.pdf.exe] | Upload unsupported file | Unsupported or disguised file types are rejected and nothing is saved | As expected | PASS |
| C10[archive.zip] | Upload unsupported file | Unsupported or disguised file types are rejected and nothing is saved | As expected | PASS |
| C10[image.svg] | Upload unsupported file | Unsupported or disguised file types are rejected and nothing is saved | As expected | PASS |
| C10[macro.docm] | Upload unsupported file | Unsupported or disguised file types are rejected and nothing is saved | As expected | PASS |
| C10[noext] | Upload unsupported file | Unsupported or disguised file types are rejected and nothing is saved | As expected | PASS |
| C10[notes.txt] | Upload unsupported file | Unsupported or disguised file types are rejected and nothing is saved | As expected | PASS |
| C10[page.html] | Upload unsupported file | Unsupported or disguised file types are rejected and nothing is saved | As expected | PASS |
| C10[photo.gif] | Upload unsupported file | Unsupported or disguised file types are rejected and nothing is saved | As expected | PASS |
| C10[script.js] | Upload unsupported file | Unsupported or disguised file types are rejected and nothing is saved | As expected | PASS |
| C10[virus.exe] | Upload unsupported file | Unsupported or disguised file types are rejected and nothing is saved | As expected | PASS |
| C11 | Upload oversized file | A file over the size limit is rejected with a clear message | As expected | PASS |
| C12[broken.docx-PK\x03\x04junkjunk] | Corrupted / fake uploads | Files whose content does not match their type are rejected | As expected | PASS |
| C12[empty.pdf-] | Corrupted / fake uploads | Files whose content does not match their type are rejected | As expected | PASS |
| C12[fake.pdf-not a pdf at all] | Corrupted / fake uploads | Files whose content does not match their type are rejected | As expected | PASS |
| C12[fake.png-GIF89a.....] | Corrupted / fake uploads | Files whose content does not match their type are rejected | As expected | PASS |
| C13 | Submit work + pending status | Student sees Submitted with upload time; never auto-approved; certificate unavailable | As expected | PASS |
| C14 | View feedback, correct and resubmit | Student reads the teacher's feedback, uploads version 2; history keeps version 1 | As expected | PASS |
| C15 | No uploads while waiting or after approval | Pending and approved work cannot be replaced by the student | As expected | PASS |
| C16 | Certificate unavailable before approval, available after | Download works only for approved work | As expected | PASS |
| C17 | Submission after deadline / closed / not yet open | Each case is refused with a clear message | As expected | PASS |
| D01 | Complete end-to-end workflow (24 steps) | Admin, teachers, event, five class topics, uploads, review, rejection, resubmission, approval, certificates and verification all work together | As expected | PASS |
| E01 | Data survives stopping and restarting (separate Python processes) | Event, submissions, teacher login, feedback, certificate and uploaded file are all still there | As expected | PASS |
| E02 | Database created automatically when missing | Deleting the database file and starting again builds a fresh complete database | As expected | PASS |
| E03 | Existing database preserved, repeated initialisation safe | Running init many times keeps all data and customised settings | As expected | PASS |
| E04 | Data integrity | Foreign keys are enforced, duplicates and orphan rows are impossible | As expected | PASS |
| E05 | Interrupted database operation | A failure in the middle of a change leaves no half-saved data | As expected | PASS |
| E06 | File and database stay consistent on failure | If saving the record fails, the uploaded file is removed again | As expected | PASS |
| E07 | Backup creation and restoration | A backup ZIP restores database, uploads and certificates exactly as they were | As expected | PASS |
| E08[bad_db] | Restore failure | Bad, damaged, foreign or too-new backups are refused and current data is untouched | As expected | PASS |
| E08[empty] | Restore failure | Bad, damaged, foreign or too-new backups are refused and current data is untouched | As expected | PASS |
| E08[garbage] | Restore failure | Bad, damaged, foreign or too-new backups are refused and current data is untouched | As expected | PASS |
| E08[newer_version] | Restore failure | Bad, damaged, foreign or too-new backups are refused and current data is untouched | As expected | PASS |
| E08[other_app_db] | Restore failure | Bad, damaged, foreign or too-new backups are refused and current data is untouched | As expected | PASS |
| E08[zip_without_db] | Restore failure | Bad, damaged, foreign or too-new backups are refused and current data is untouched | As expected | PASS |
| E09 | Malicious backup ZIP | File names that try to leave the data folders are skipped, not written | As expected | PASS |
| E10 | Backup failure | A failing backup gives a friendly message, leaves no half-made file, and the app keeps working | As expected | PASS |
| E11 | Automatic backups | An automatic backup is made when due, not repeated too soon, and old ones are pruned | As expected | PASS |
| E12 | Migration from an older schema | A version-1 database is upgraded to the latest, keeping data and making a safety backup | As expected | PASS |
| E13 | Missing upload / certificate file | Missing upload gives a friendly message (no paths); missing certificate is rebuilt with the same ID | As expected | PASS |
| E14 | Missing folders | Deleted upload / certificate folders are recreated automatically | As expected | PASS |
| E15 | Database locked | While another writer holds the database, the user gets a friendly 'busy' message; it works again afterwards | As expected | PASS |
| E16 | manage.py command-line tool | backup, list, check, restore and reset-password work from the terminal, including for a locked-out administrator | As expected | PASS |
| F01 | Student cannot reach teacher features | Every staff-only action refuses a student | As expected | PASS |
| F02 | Student cannot approve their own submission | No route lets a student change a status; status stays pending | As expected | PASS |
| F03 | Student cannot download another student's private submission | Other students and other teachers are refused; the owner is allowed | As expected | PASS |
| F04 | Student cannot alter identity or class to reach another assignment | Submitting to another class's task is refused, forged session data is ignored | As expected | PASS |
| F05 | Certificate access | No certificate before approval; only the owner, the event's teacher and admin may download; revoked ones are blocked | As expected | PASS |
| F06 | One teacher cannot touch another teacher's data | Other teacher's events, assignments, reviews, files and reports are off limits | As expected | PASS |
| F07 | Malicious file names | Traversal, null bytes and HTML in names are neutralised; files stay inside the uploads folder | As expected | PASS |
| F08 | Errors never reveal internals | Error messages contain no SQL, file paths or stack traces | As expected | PASS |
| F09 | SQL injection | Hostile text in search boxes and forms is treated as plain text; tables stay intact | As expected | PASS |
| F10 | Verification page privacy | Only validity, student name, event, topic, date and ID are exposed | As expected | PASS |
| F11 | Server-side permission re-check | A deactivated student or a forged role is rejected immediately | As expected | PASS |
| F12 | Audit logging | Logins, failed logins, user changes and reviews are recorded with actor and time | As expected | PASS |
| G01 | First-run administrator setup in the browser | Setup form creates the admin and opens the dashboard; mismatched passwords are refused | As expected | PASS |
| G02 | Staff login screen | Wrong password shows a friendly message; right password opens the administrator dashboard; logout returns to login | As expected | PASS |
| G03 | Admin forms: create teacher, class, section, student | Each form saves and the new record appears in its list | As expected | PASS |
| G04 | Every administrator navigation item | All 11 menu pages open without an error | As expected | PASS |
| G05 | Settings page | School name and principal change, persist after a page reload, and appear in the sidebar | As expected | PASS |
| G06 | Backup and restore through the screen (browser) | Backup is created and downloaded as a valid ZIP; restoring it brings back deleted data; a wrong file is refused | As expected | PASS |
| G07 | Report CSV export (browser) | The class participation report downloads as a CSV with the real student numbers | As expected | PASS |
| G10 | Teacher creates an event and gives Classes 6, 7 and 8 different topics (browser) | Event and three class topics are saved, then published | As expected | PASS |
| G11 | Student login, own task only, upload, pending status (browser) | Student sees only their class topic, uploads a PDF, sees Submitted, and the certificate stays locked | As expected | PASS |
| G12 | Upload errors shown to the student (browser) | Wrong type, fake content and oversized files each show a clear message and nothing is saved | As expected | PASS |
| G13 | Review, rejection with feedback, resubmission, approval, certificate download (browser) | The complete loop works and the downloaded PDF is a valid A4 landscape certificate with the student's details | As expected | PASS |
| G20 | Every teacher and student navigation item | All menu pages open without any error | As expected | PASS |
| G21 | Status indicators and download buttons (browser) | Approved student sees the Approved badge and a working certificate download; pending student sees none | As expected | PASS |
| G22 | Empty states | A class with no tasks, and a teacher with no events, show friendly empty messages | As expected | PASS |
| G23 | Login form messages | Empty, wrong and incomplete student details each show a clear message | As expected | PASS |
| G24[size0] | Responsive layout on phone and tablet sizes | Login, dashboard and task pages fit the screen width (no sideways scrolling) | As expected | PASS |
| G24[size1] | Responsive layout on phone and tablet sizes | Login, dashboard and task pages fit the screen width (no sideways scrolling) | As expected | PASS |
| G25 | Session expiry and logout | An idle session ends with a message; logging out and reloading never shows private pages | As expected | PASS |
| G26 | Public certificate verification page (no login) | Shows VALID with only safe details; a revoked certificate shows REVOKED and never VALID | As expected | PASS |
| G27 | Network interruption | After the connection drops for a few seconds and returns, the app recovers and keeps working without errors | As expected | PASS |
| G28 | Hosting restart: stop and start the real web server | All accounts, events, submissions, feedback and the certificate are still there afterwards | As expected | PASS |
| H01 | Duplicate student identities | Same class+section+roll is refused; same names with different rolls log in correctly; deactivated roll can be reused | As expected | PASS |
| H02 | Duplicate teacher usernames | Refused regardless of letter case | As expected | PASS |
| H03 | Empty forms | Blank input gives friendly validation errors, never a crash | As expected | PASS |
| H04 | Invalid dates and past deadlines | Impossible dates, reversed ranges and past deadlines are refused | As expected | PASS |
| H05 | Submission after the deadline | Refused with a clear message; earlier work stays safe | As expected | PASS |
| H06 | Event with no assignments / assignment with no students | Publishing an empty event is refused; an assignment with no students shows 0 students | As expected | PASS |
| H07 | Two (or five) students submitting at the same moment | Every submission is saved with its own file; nothing is lost or mixed up | As expected | PASS |
| H08 | One student double-clicking Submit | Exactly one upload is accepted; no duplicate version or stray file | As expected | PASS |
| H09 | Reviewing the same submission twice / double-clicking Approve | Only the first decision counts; the second changes nothing | As expected | PASS |
| H10 | Undoing an approval | Status returns to review, any certificate is revoked, the student can no longer download it | As expected | PASS |
| H11 | Repeated / simultaneous certificate generation | Always the same single certificate and ID; admin regenerate keeps the ID | As expected | PASS |
| H12 | Logo, signature images and colours on the certificate | Configured images and colours are used without breaking the PDF | As expected | PASS |
| H13 | Names in Tamil / Kannada letters | Non-English names work for login, review and certificates | As expected | PASS |
| U01 | Password hashing | Hash is salted scrypt, never the plain text; correct password verifies, wrong one does not | As expected | PASS |
| U02[-file] | Unsafe file names | Folders, control characters and odd symbols are removed | As expected | PASS |
| U02[....-file] | Unsafe file names | Folders, control characters and odd symbols are removed | As expected | PASS |
| U02[../../etc/passwd-passwd] | Unsafe file names | Folders, control characters and odd symbols are removed | As expected | PASS |
| U02[..\\..\\windows\\system32\\cmd.exe-cmd.exe] | Unsafe file names | Folders, control characters and odd symbols are removed | As expected | PASS |
| U02[a\x00b.pdf-ab.pdf] | Unsafe file names | Folders, control characters and odd symbols are removed | As expected | PASS |
| U02[my report (final).pdf-my report _final_.pdf] | Unsafe file names | Folders, control characters and odd symbols are removed | As expected | PASS |
| U03 | Path traversal guard | Paths that leave the base folder raise an error | As expected | PASS |
| U04 | CSV export safety | Cells starting with = + - @ are neutralised | As expected | PASS |
| U05 | Input validators | Bad usernames, passwords, roll numbers, colours and dates are rejected with friendly errors | As expected | PASS |
| U06 | File content check | Real files pass; renamed, truncated or fake files are rejected | As expected | PASS |
| U07 | Zip bomb guard | A DOCX that would unpack to a huge size is rejected | As expected | PASS |
