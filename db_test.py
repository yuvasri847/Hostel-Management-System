
import oracledb

oracledb.init_oracle_client(
    lib_dir=r"C:\Users\Admin\Downloads\instantclient_23_26"
)

connection = None
cursor = None

try:
    connection = oracledb.connect(
        user="YUVA",
        password="sky",
        dsn="localhost:1521/xe"
    )

    cursor = connection.cursor()

    print("\nHOSTEL EVENT MANAGEMENT SYSTEM")
    print("-" * 40)

    tables = [
        "HOSTEL",
        "STUDENT",
        "ORGANIZER",
        "EVENT",
        "REGISTRATION",
        "VOLUNTEER",
        "ATTENDANCE",
        "EXPENSE",
        "FEEDBACK"
    ]

    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"{table:<15} : {count} records")

    print("\nDatabase verification completed!")

except oracledb.Error as error:
    print("Error:", error)

finally:
    if cursor is not None:
        cursor.close()
    if connection is not None:
        connection.close()
