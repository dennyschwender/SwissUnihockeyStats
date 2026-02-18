import sqlite3

conn = sqlite3.connect(r'c:\Users\denny\Development\SwissUnihockeyStats\data\swissunihockey.db')
c = conn.cursor()

print('Clubs by season:')
for row in c.execute('SELECT season_id, COUNT(*) FROM clubs GROUP BY season_id ORDER BY season_id DESC LIMIT 10'):
    print(f'  Season {row[0]}: {row[1]} clubs')

print('\nTeams by season:')
for row in c.execute('SELECT season_id, COUNT(*) FROM teams GROUP BY season_id ORDER BY season_id DESC LIMIT 10'):
    print(f'  Season {row[0]}: {row[1]} teams')

print('\nPlayers:')
for row in c.execute('SELECT COUNT(*) FROM players'):
    print(f'  Total players: {row[0]}')

print('\nTeam-Players by season:')
for row in c.execute('SELECT t.season_id, COUNT(*) FROM team_players tp JOIN teams t ON tp.team_id = t.id GROUP BY t.season_id ORDER BY t.season_id DESC LIMIT 10'):
    print(f'  Season {row[0]}: {row[1]} team-players')

conn.close()
