from flask import Flask, render_template, request, redirect, url_for
import os
import oracledb

app = Flask(__name__)

# Oracle Instant Client
oracledb.init_oracle_client(
    lib_dir=r"C:\Users\Admin\Downloads\instantclient_23_26"
)

# Oracle Database connection
DB_USER = os.environ.get("DB_USER", "YUVA")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "sky")
DB_DSN = os.environ.get("DB_DSN", "localhost:1521/xe")


def get_connection():
    return oracledb.connect(
        user=DB_USER,
        password=DB_PASSWORD,
        dsn=DB_DSN
    )


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------
@app.route("/")
def dashboard():
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("SELECT COUNT(*) FROM STUDENT")
        student_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM EVENT")
        event_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM REGISTRATION WHERE TRIM(STATUS) = 'Registered'")
        registration_count = cursor.fetchone()[0]

        cursor.execute("SELECT NVL(SUM(AMOUNT), 0) FROM EXPENSE")
        total_expense = cursor.fetchone()[0]

        cursor.execute("""
            SELECT EVENT_ID, EVENT_NAME, EVENT_DATE, VENUE, BUDGET,
                   CASE
                       WHEN EVENT_DATE < TRUNC(SYSDATE) THEN 'Completed'
                       ELSE 'Upcoming'
                   END AS EVENT_STATUS
            FROM EVENT
            ORDER BY EVENT_DATE
        """)
        events = cursor.fetchall()

        return render_template(
            "index.html",
            student_count=student_count,
            event_count=event_count,
            registration_count=registration_count,
            total_expense=total_expense,
            events=events
        )

    except oracledb.Error:
        app.logger.exception("Dashboard database error")
        return "Unable to load dashboard. Check the Flask terminal.", 500

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# --------------------------------------------------
# EVENTS
# --------------------------------------------------
@app.route("/events")
def manage_events():
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT EVENT_ID, EVENT_NAME, EVENT_DATE,
                   VENUE, BUDGET, ORGANIZER_ID,
                   CASE
                       WHEN EVENT_DATE < TRUNC(SYSDATE) THEN 'Completed'
                       ELSE 'Upcoming'
                   END AS EVENT_STATUS
            FROM EVENT
            ORDER BY EVENT_DATE
        """)
        events = cursor.fetchall()

        cursor.execute("""
            SELECT ORGANIZER_ID
            FROM ORGANIZER
            ORDER BY ORGANIZER_ID
        """)
        organizers = cursor.fetchall()

        return render_template(
            "events.html",
            events=events,
            organizers=organizers
        )

    except oracledb.Error:
        app.logger.exception("Events database error")
        return "Unable to load events. Check the Flask terminal.", 500

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# --------------------------------------------------
# ADD EVENT
# --------------------------------------------------
@app.route("/events/add", methods=["GET", "POST"])
def add_event():
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        if request.method == "POST":
            event_id = int(request.form["event_id"])
            event_name = request.form["event_name"].strip()
            event_date = request.form["event_date"]
            venue = request.form["venue"].strip()
            budget = float(request.form["budget"])
            organizer_id = int(request.form["organizer_id"])

            if not event_name or not venue:
                return "Event name and venue are required.", 400

            if budget < 0:
                return "Budget cannot be negative.", 400

            cursor.execute("""
                INSERT INTO EVENT (
                    EVENT_ID, EVENT_NAME, EVENT_DATE,
                    VENUE, BUDGET, ORGANIZER_ID
                )
                VALUES (
                    :event_id, :event_name,
                    TO_DATE(:event_date, 'YYYY-MM-DD'),
                    :venue, :budget, :organizer_id
                )
            """, {
                "event_id": event_id,
                "event_name": event_name,
                "event_date": event_date,
                "venue": venue,
                "budget": budget,
                "organizer_id": organizer_id
            })

            connection.commit()
            return redirect(url_for("manage_events"))

        cursor.execute("""
            SELECT ORGANIZER_ID
            FROM ORGANIZER
            ORDER BY ORGANIZER_ID
        """)
        organizers = cursor.fetchall()

        return render_template(
            "add_event.html",
            organizers=organizers
        )

    except ValueError:
        if connection:
            connection.rollback()
        return "Enter valid numeric IDs and budget.", 400

    except oracledb.IntegrityError:
        if connection:
            connection.rollback()
        app.logger.exception("Event integrity error")
        return "Could not add event. Check event and organizer IDs.", 400

    except oracledb.Error:
        if connection:
            connection.rollback()
        app.logger.exception("Add event database error")
        return "Unable to add event. Check the Flask terminal.", 500

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# --------------------------------------------------
# DELETE EVENT
# --------------------------------------------------
@app.route("/events/delete", methods=["POST"])
def delete_event():
    connection = None
    cursor = None

    try:
        event_id = int(request.form["event_id"])

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM EVENT WHERE EVENT_ID = :event_id",
            {"event_id": event_id}
        )
        if cursor.fetchone()[0] == 0:
            return "Event not found.", 404

        # 1. Attendance depends on registrations of this event
        cursor.execute("""
            DELETE FROM ATTENDANCE
            WHERE REGISTRATION_ID IN (
                SELECT REGISTRATION_ID
                FROM REGISTRATION
                WHERE EVENT_ID = :event_id
            )
        """, {"event_id": event_id})

        # 2. Any other table that has an EVENT_ID column
        #    (volunteer, expense, feedback...) except EVENT and REGISTRATION
        cursor.execute("""
            SELECT TABLE_NAME
            FROM USER_TAB_COLUMNS
            WHERE COLUMN_NAME = 'EVENT_ID'
              AND TABLE_NAME NOT IN ('EVENT', 'REGISTRATION', 'ATTENDANCE')
              AND TABLE_NAME NOT LIKE 'BIN$%'
              AND TABLE_NAME IN (SELECT TABLE_NAME FROM USER_TABLES)
        """)
        child_tables = [row[0] for row in cursor.fetchall()]

        # Audit/log tables last: deleting expenses may fire a trigger
        # that writes a new audit row
        child_tables.sort(key=lambda name: (name.endswith("_AUDIT"), name))

        for table_name in child_tables:
            cursor.execute(
                f'DELETE FROM "{table_name}" WHERE EVENT_ID = :event_id',
                {"event_id": event_id}
            )

        # 3. Registrations
        cursor.execute(
            "DELETE FROM REGISTRATION WHERE EVENT_ID = :event_id",
            {"event_id": event_id}
        )

        # 4. The event itself
        cursor.execute(
            "DELETE FROM EVENT WHERE EVENT_ID = :event_id",
            {"event_id": event_id}
        )

        connection.commit()
        return redirect(url_for("manage_events"))

    except ValueError:
        return "Invalid event ID.", 400

    except oracledb.Error:
        if connection:
            connection.rollback()
        app.logger.exception("Delete event database error")
        return "Unable to delete event. Check the Flask terminal.", 500

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# --------------------------------------------------
# STUDENT REGISTRATIONS
# --------------------------------------------------
@app.route("/registrations", methods=["GET", "POST"])
def manage_registrations():
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        if request.method == "POST":
            student_id = int(request.form["student_id"])
            event_id = int(request.form["event_id"])

            # Block registration for completed (past) events
            cursor.execute("""
                SELECT EVENT_DATE,
                       CASE WHEN EVENT_DATE < TRUNC(SYSDATE)
                            THEN 1 ELSE 0 END
                FROM EVENT
                WHERE EVENT_ID = :event_id
            """, {"event_id": event_id})
            event_row = cursor.fetchone()

            if event_row is None:
                return "Event not found.", 400

            if event_row[1] == 1:
                return "This event is already completed. Registration is closed.", 400

            # Block duplicate active registration
            cursor.execute("""
                SELECT COUNT(*)
                FROM REGISTRATION
                WHERE STUDENT_ID = :student_id
                  AND EVENT_ID = :event_id
                  AND TRIM(STATUS) = 'Registered'
            """, {"student_id": student_id, "event_id": event_id})

            if cursor.fetchone()[0] > 0:
                return "This student is already registered for this event.", 400

            cursor.execute("""
                SELECT NVL(MAX(REGISTRATION_ID), 2000) + 1
                FROM REGISTRATION
                WHERE REGISTRATION_ID > 0
            """)
            registration_id = cursor.fetchone()[0]

            cursor.execute("""
                INSERT INTO REGISTRATION (
                    REGISTRATION_ID, STUDENT_ID, EVENT_ID,
                    REGISTRATION_DATE, STATUS
                )
                VALUES (
                    :registration_id, :student_id, :event_id,
                    SYSDATE, 'Registered'
                )
            """, {
                "registration_id": registration_id,
                "student_id": student_id,
                "event_id": event_id
            })

            connection.commit()
            return redirect(url_for("manage_registrations"))

        cursor.execute("""
            SELECT STUDENT_ID
            FROM STUDENT
            ORDER BY STUDENT_ID
        """)
        students = cursor.fetchall()

        cursor.execute("""
            SELECT EVENT_ID, EVENT_NAME
            FROM EVENT
            WHERE EVENT_DATE >= TRUNC(SYSDATE)
            ORDER BY EVENT_DATE
        """)
        events = cursor.fetchall()

        cursor.execute("""
            SELECT R.REGISTRATION_ID,
                   R.STUDENT_ID,
                   E.EVENT_NAME,
                   R.REGISTRATION_DATE,
                   R.STATUS
            FROM REGISTRATION R
            JOIN EVENT E ON E.EVENT_ID = R.EVENT_ID
            ORDER BY R.REGISTRATION_ID DESC
        """)
        registrations = cursor.fetchall()

        return render_template(
            "registrations.html",
            students=students,
            events=events,
            registrations=registrations
        )

    except ValueError:
        if connection:
            connection.rollback()
        return "Enter valid numeric IDs.", 400

    except oracledb.IntegrityError:
        if connection:
            connection.rollback()
        app.logger.exception("Registration integrity error")
        return "Registration failed. Check student and event IDs.", 400

    except oracledb.Error:
        if connection:
            connection.rollback()
        app.logger.exception("Registration database error")
        return "Unable to load registrations. Check the Flask terminal.", 500

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# --------------------------------------------------
# CANCEL REGISTRATION
# --------------------------------------------------
@app.route("/registrations/cancel", methods=["POST"])
def cancel_registration():
    connection = None
    cursor = None

    try:
        registration_id = int(request.form["registration_id"])

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            UPDATE REGISTRATION
            SET STATUS = 'Cancelled'
            WHERE REGISTRATION_ID = :registration_id
              AND TRIM(STATUS) = 'Registered'
        """, {"registration_id": registration_id})

        if cursor.rowcount == 0:
            connection.rollback()
            return "Registration not found or already cancelled.", 400

        connection.commit()
        return redirect(url_for("manage_registrations"))

    except ValueError:
        if connection:
            connection.rollback()
        return "Invalid registration ID.", 400

    except oracledb.Error:
        if connection:
            connection.rollback()
        app.logger.exception("Cancellation database error")
        return "Unable to cancel registration. Check the Flask terminal.", 500

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# --------------------------------------------------
# ATTENDANCE
# --------------------------------------------------
@app.route("/attendance", methods=["GET", "POST"])
def manage_attendance():
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        if request.method == "POST":
            registration_id = int(request.form["registration_id"])
            attendance_status = request.form["attendance_status"]

            if attendance_status not in ("Present", "Absent"):
                return "Invalid attendance status.", 400

            # Confirm the registration is active
            cursor.execute("""
                SELECT REGISTRATION_ID
                FROM REGISTRATION
                WHERE REGISTRATION_ID = :registration_id
                  AND TRIM(STATUS) = 'Registered'
            """, {"registration_id": registration_id})

            if cursor.fetchone() is None:
                return "Registration not found or is cancelled.", 400

            # Check for an existing attendance record
            cursor.execute("""
                SELECT ATTENDANCE_ID
                FROM ATTENDANCE
                WHERE REGISTRATION_ID = :registration_id
            """, {"registration_id": registration_id})

            existing = cursor.fetchone()

            if existing:
                cursor.execute("""
                    UPDATE ATTENDANCE
                    SET ATTENDANCE_STATUS = :attendance_status
                    WHERE REGISTRATION_ID = :registration_id
                """, {
                    "attendance_status": attendance_status,
                    "registration_id": registration_id
                })
            else:
                cursor.execute("""
                    INSERT INTO ATTENDANCE (
                        ATTENDANCE_ID,
                        REGISTRATION_ID,
                        ATTENDANCE_STATUS
                    )
                    VALUES (
                        (SELECT NVL(MAX(ATTENDANCE_ID), 0) + 1
                         FROM ATTENDANCE),
                        :registration_id,
                        :attendance_status
                    )
                """, {
                    "registration_id": registration_id,
                    "attendance_status": attendance_status
                })

            connection.commit()
            return redirect(url_for("manage_attendance"))

        # Only registrations whose status is Registered
        cursor.execute("""
            SELECT
                R.REGISTRATION_ID,
                R.STUDENT_ID,
                E.EVENT_NAME,
                R.STATUS,
                A.ATTENDANCE_STATUS,
                CASE WHEN E.EVENT_DATE > TRUNC(SYSDATE)
                     THEN 'Upcoming' ELSE 'Started' END AS EVENT_STATE,
                E.EVENT_ID
            FROM REGISTRATION R
            JOIN EVENT E
                ON E.EVENT_ID = R.EVENT_ID
            LEFT JOIN ATTENDANCE A
                ON A.REGISTRATION_ID = R.REGISTRATION_ID
            WHERE TRIM(R.STATUS) = 'Registered'
            ORDER BY R.REGISTRATION_ID DESC
        """)

        attendance_records = cursor.fetchall()

        return render_template(
            "attendance.html",
            attendance_records=attendance_records
        )

    except ValueError:
        if connection:
            connection.rollback()
        return "Enter a valid registration ID.", 400

    except oracledb.Error:
        if connection:
            connection.rollback()
        app.logger.exception("Attendance database error")
        return "Unable to load attendance. Check the Flask terminal.", 500

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# --------------------------------------------------
# ATTENDANCE REPORT
# --------------------------------------------------
@app.route("/attendance-report")
def attendance_report():
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                E.EVENT_ID,
                E.EVENT_NAME,
                COUNT(R.REGISTRATION_ID) AS TOTAL_REGISTERED,
                NVL(SUM(CASE WHEN A.ATTENDANCE_STATUS = 'Present'
                             THEN 1 ELSE 0 END), 0) AS TOTAL_PRESENT,
                NVL(SUM(CASE WHEN A.ATTENDANCE_STATUS = 'Absent'
                             THEN 1 ELSE 0 END), 0) AS TOTAL_ABSENT,
                COUNT(R.REGISTRATION_ID) - COUNT(A.ATTENDANCE_ID)
                    AS TOTAL_NOT_MARKED,
                CASE
                    WHEN COUNT(A.ATTENDANCE_ID) = 0 THEN NULL
                    ELSE ROUND(
                        100 * SUM(CASE WHEN A.ATTENDANCE_STATUS = 'Present'
                                       THEN 1 ELSE 0 END)
                        / COUNT(R.REGISTRATION_ID), 2)
                END AS ATTENDANCE_PERCENTAGE
            FROM EVENT E
            LEFT JOIN REGISTRATION R
                ON E.EVENT_ID = R.EVENT_ID
                AND TRIM(R.STATUS) = 'Registered'
            LEFT JOIN ATTENDANCE A
                ON R.REGISTRATION_ID = A.REGISTRATION_ID
            GROUP BY E.EVENT_ID, E.EVENT_NAME
            ORDER BY E.EVENT_ID
        """)
        report_records = cursor.fetchall()

        cursor.execute("""
            SELECT
                COUNT(*),
                NVL(SUM(CASE
                    WHEN A.ATTENDANCE_STATUS = 'Present' THEN 1
                    ELSE 0
                END), 0),
                NVL(SUM(CASE
                    WHEN A.ATTENDANCE_STATUS = 'Absent' THEN 1
                    ELSE 0
                END), 0)
            FROM ATTENDANCE A
            JOIN REGISTRATION R
                ON R.REGISTRATION_ID = A.REGISTRATION_ID
            WHERE TRIM(R.STATUS) = 'Registered'
        """)
        attendance_totals = cursor.fetchone()

        cursor.execute("SELECT COUNT(*) FROM EVENT")
        total_events = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM REGISTRATION
            WHERE TRIM(STATUS) = 'Registered'
        """)
        total_registered = cursor.fetchone()[0]

        total_present = attendance_totals[1]
        total_absent = attendance_totals[2]
        total_not_marked = total_registered - total_present - total_absent

        return render_template(
            "attendance_report.html",
            report_records=report_records,
            total_events=total_events,
            total_registered=total_registered,
            total_present=total_present,
            total_absent=total_absent,
            total_not_marked=total_not_marked
        )

    except oracledb.Error:
        app.logger.exception("Attendance report database error")
        return "Unable to load attendance report. Check the Flask terminal.", 500

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


if __name__ == "__main__":
    app.run(debug=True)
