import sqlite3

conn = sqlite3.connect(r'c:\Users\denny\Development\SwissUnihockeyStats\data\swissunihockey.db')
c = conn.cursor()

print("TEAMS TABLE SCHEMA:")
schema = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='teams'").fetchone()
print(schema[0] if schema else 'No teams table')

print("\n\nCLUBS TABLE SCHEMA:")
schema = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='clubs'").fetchone()
print(schema[0] if schema else 'No clubs table')

conn.close()
