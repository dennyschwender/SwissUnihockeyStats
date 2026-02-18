import sqlite3

conn = sqlite3.connect(r'c:\Users\denny\Development\SwissUnihockeyStats\data\swissunihockey.db')
c = conn.cursor()

print("Teams per club:")
for row in c.execute('SELECT t.club_id, c.name, COUNT(*) FROM teams t JOIN clubs c ON t.club_id=c.id AND t.season_id=c.season_id WHERE t.season_id=2025 GROUP BY t.club_id, c.name'):
    print(f'  Club {row[0]} ({row[1]}): {row[2]} teams')

print(f'\nTotal teams in season 2025: {c.execute("SELECT COUNT(*) FROM teams WHERE season_id=2025").fetchone()[0]}')

conn.close()
