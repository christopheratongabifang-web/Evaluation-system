import sqlite3

def main():
    try:
        conn = sqlite3.connect('library.db')
        cur = conn.cursor()
        cur.execute("SELECT id, username, email, password_hash FROM user LIMIT 20")
        rows = cur.fetchall()
        if not rows:
            print('NO_USERS')
        else:
            for r in rows:
                print(r)
        conn.close()
    except Exception as e:
        print('ERROR', e)

if __name__ == '__main__':
    main()
