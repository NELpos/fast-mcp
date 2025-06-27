import os
import psycopg
from dotenv import load_dotenv

def main():
    """Connects to the PostgreSQL database and sets up a sample table."""
    load_dotenv()

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL environment variable not set.")
        print("Please create a .env file with the DATABASE_URL.")
        return

    try:
        # Connect to the database
        with psycopg.connect(db_url) as conn:
            print("Successfully connected to the database.")
            with conn.cursor() as cur:
                # Create the employees table if it doesn't exist
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS employees (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(100),
                        position VARCHAR(100),
                        email VARCHAR(100) UNIQUE
                    );
                """)
                print("Table 'employees' created or already exists.")

                # Insert some dummy data (optional, prevents duplicates on re-run)
                employees_data = [
                    ('Alice', 'Software Engineer', 'alice@example.com'),
                    ('Bob', 'Project Manager', 'bob@example.com'),
                    ('Charlie', 'Data Scientist', 'charlie@example.com')
                ]

                # Check for existing emails before inserting
                for name, position, email in employees_data:
                    cur.execute("SELECT id FROM employees WHERE email = %s", (email,))
                    if cur.fetchone() is None:
                        cur.execute(
                            "INSERT INTO employees (name, position, email) VALUES (%s, %s, %s)",
                            (name, position, email)
                        )
                        print(f"Inserted {name}.")
                    else:
                        print(f"Employee {name} with email {email} already exists.")

                conn.commit()
                print("\nDummy data setup complete.")

    except psycopg.Error as e:
        print(f"Database error: {e}")

if __name__ == "__main__":
    main()
