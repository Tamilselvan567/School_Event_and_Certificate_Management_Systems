"""Command-line helper for the person who runs the server (no login needed - it works on the data folder directly).

    python manage.py backup            make a full backup (database + uploads + certificates)
    python manage.py list              list the backups
    python manage.py restore FILE.zip  replace the current data with a backup
    python manage.py check             check that the database and the stored files are healthy
    python manage.py reset-password USERNAME   set a new password for a forgotten login (asks you to type it)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv: list[str]) -> int:
    from database import init_db, integrity_check
    from services import backup_service as bk
    from utils.errors import AppError
    cmd = argv[1] if len(argv) > 1 else ""
    try:
        if cmd == "backup":
            init_db()
            print("Backup created:", bk.create_backup("manual", include_files=True))
        elif cmd == "list":
            for b in bk.list_backups():
                print(f"{b['name']}  {b['size'] / 1024:.0f} KB  {b['modified']} UTC")
        elif cmd == "restore" and len(argv) > 2:
            data = Path(argv[2]).read_bytes()
            result = bk.restore_backup(data)
            print(f"Restore finished. {result['files_restored']} file(s) restored. Safety copy: {result['safety_backup']}")
        elif cmd == "check":
            init_db()
            problems = integrity_check()
            print("Database:", "healthy" if not problems else "PROBLEMS: " + "; ".join(problems))
            report = bk.check_consistency()
            print("Missing uploads:", len(report["missing_uploads"]), "| missing certificates:",
                  len(report["missing_certificates"]), "| unknown files:", report["orphan_files"])
            return 1 if problems else 0
        elif cmd == "reset-password" and len(argv) > 2:
            import getpass
            from database import audit, transaction
            from utils.security import hash_password
            from utils.validators import validate_password
            init_db()
            username = argv[2]
            password = validate_password(getpass.getpass("New password: "))
            if password != getpass.getpass("Type it again: "):
                print("The two passwords are not the same. Nothing was changed.")
                return 1
            with transaction() as conn:
                row = conn.execute("SELECT id, role FROM users WHERE username=?", (username,)).fetchone()
                if not row:
                    print(f"There is no account called '{username}'.")
                    return 1
                conn.execute("UPDATE users SET password_hash=?, failed_attempts=0, locked_until=NULL, is_active=1 WHERE id=?",
                             (hash_password(password), row["id"]))
                audit(conn, None, "password_reset_cli", "user", row["id"], username)
            print(f"Password changed for '{username}'. The account is unlocked and active.")
        else:
            print(__doc__)
            return 2
    except (AppError, OSError) as exc:
        print("Error:", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
