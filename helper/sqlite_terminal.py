import sqlite3

# Connect to existing or new queries.db
conn = sqlite3.connect('queries.db')
cursor = conn.cursor()

print("📄 Connected to queries.db")
print("Type your SQL commands below.")
print("Type 'exit' to quit.\n")

while True:
    try:
        command = input("SQL> ").strip()
        if command.lower() == "exit":
            print("👋 Exiting...")
            break
        if command == "":
            continue

        cursor.execute(command)

        # Fetch and print results if SELECT query
        if command.lower().startswith("select"):
            results = cursor.fetchall()
            if results:
                for row in results:
                    print(f"➡️ {row}")
            else:
                print("✅ Query executed. No results to display.")
        else:
            conn.commit()
            print("✅ Query executed successfully.")

    except Exception as e:
        print(f"❌ Error: {e}")

# Close DB connection
conn.close()

