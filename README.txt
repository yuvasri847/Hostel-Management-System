HOSTEL EVENT MANAGEMENT SYSTEM  (Flask + Oracle)

HOW TO RUN
1. Install packages:   pip install -r requirements.txt
2. Check db_test.py   (python db_test.py) - it prints the record count of every table.
3. Start the app:     python app.py
4. Open:              http://127.0.0.1:5000

SETTINGS (top of app.py)
- Instant Client folder : init_oracle_client(lib_dir=...)
- Database user/password/dsn : DB_USER, DB_PASSWORD, DB_DSN
  (can also be set with environment variables of the same names)

FEATURES
- Dashboard : totals, expenses, event list with Upcoming/Completed status
- Events    : add event, delete event (also deletes its linked records)
- Registrations : register students (upcoming events only, no duplicates), cancel
- Attendance : mark Present/Absent for active registrations
- Reports   : Registrations = Present + Absent + Not Marked, attendance rate

RULES
- An event is "Completed" when its date is before today.
- Registration is closed for completed events.
