from db import get_db_connection


def main():
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT CURRENT_USER(), DATABASE()")
            account, database = cursor.fetchone()

            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]

            print("Database connection successful!")
            print("MySQL account:", account)
            print("Database:", database)
            print("Saved users:", total_users)


if __name__ == "__main__":
    main()