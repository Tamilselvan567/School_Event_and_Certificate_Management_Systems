from database import transaction


def set_deadline(assignment_id=None, event_id=None, when="2020-01-01 00:00"):
    """Pretend time has passed by moving a deadline into the past."""
    with transaction() as conn:
        if assignment_id:
            conn.execute("UPDATE event_class_assignments SET deadline=? WHERE id=?", (when, assignment_id))
            conn.execute("UPDATE events SET deadline=? WHERE id=(SELECT event_id FROM event_class_assignments WHERE id=?)",
                         (when, assignment_id))
        if event_id:
            conn.execute("UPDATE events SET deadline=? WHERE id=?", (when, event_id))
