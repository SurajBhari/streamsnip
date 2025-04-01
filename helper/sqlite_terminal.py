import sqlite3

# Connect to existing or new queries.db
conn = sqlite3.connect('queries.db')
cursor = conn.cursor()

print("📄 Connected to queries.db")
print("Type your SQL commands below.")
print("Type 'exit' to quit.\n")

def is_subscribed(channel_id):
    cur = conn.cursor()
    cur.execute("SELECT * FROM MEMBERSHIP WHERE channel_id=?", (channel_id,))
    membership_detail = cur.fetchone()
    if not membership_detail:
        # if the channel is not in db that means its new. give 28 days of free trial that means 199 rs
        with conn:
            end_time = int(time.time()) + 29 * 24 * 60 * 60  # we give 29 to include current day too
            start_time = int(time.time())
            cur.execute("INSERT INTO MEMBERSHIP VALUES (?, ?, ?, ?)", (channel_id, "FREE", start_time, end_time))
            cur.execute(
                "INSERT INTO TRANSACTIONS VALUES (?, ?, ?, ?, ?, ?)",
                (
                    channel_id,
                    0,
                    int(time.time()),
                    "FREE TRIAL",
                    "FREE",
                    "Free Trial for 28 days",
                ),
            )
            conn.commit()
        return is_subscribed(channel_id)
    membership_detail = Membership(membership_detail)
    if membership_detail.active:
        return membership_detail.type
    return ""  # no membership

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
