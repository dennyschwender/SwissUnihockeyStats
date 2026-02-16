# SwissUnihockey Project - Quick Start Guide

## ✅ What's Working

Your project successfully connects to the SwissUnihockey API and can access:

- **346 Swiss Unihockey clubs** with club IDs
- **50 league/game class combinations** (NLB, 1-5 Liga, Junior/Senior)
- **31 seasons** of historical data (back to 1995/96)
- **League rankings/standings** (TABLE format)
- **Game schedules and results**
- **Team and player information**

## 🚀 Getting Started

### 1. Test the Connection
```powershell
..\.venv\Scripts\python.exe test_api.py
```

### 2. Fetch Sample Data
```powershell
..\.venv\Scripts\python.exe scripts\example_fetch_data.py
```

### 3. Check the Data
Look in `data/raw/` for JSON files with:
- `clubs_*.json` - All 346 clubs
- `leagues_*.json` - All 50 leagues
- `seasons_*.json` - All 31 seasons

## 📊 What You Can Build

### **Phase 1: Data Collection** (NOW)
✅ Fetch clubs, leagues, seasons  
✅ Download league standings  
✅ Get game schedules  
⬜ Store data in database

### **Phase 2: Basic Statistics Website**
- League tables (live standings)
- Team profiles with logos
- Match schedules/results
- Historical season comparisons

### **Phase 3: Advanced Analytics**
- Player statistics dashboard
- Top scorers leaderboard
- Form guides (last 5 games)
- Head-to-head comparisons
- Predictive analytics

### **Phase 4: Real-Time Features**
- Live score updates
- Game event timelines
- Push notifications
- Social media integration

## 💻 Code Examples

### Fetch League Standings
```python
from api import SwissUnihockeyClient

with SwissUnihockeyClient() as client:
    # NLB Men standings for 2025/26
    standings = client.get_rankings(
        league=2,        # 2 = NLB
        game_class=11,   # 11 = Men
        season=2025      # 2025 = 2025/26 season
    )
    
    print(standings)
```

### Fetch Top 10 Clubs by Name
```python
from api import get_clubs

clubs = get_clubs()

# Extract club names and IDs
for club in clubs['entries'][:10]:
    name = club['text']
    club_id = club['set_in_context']['club_id']
    print(f"{name} - ID: {club_id}")
```

### Fetch Games for a League
```python
from api import SwissUnihockeyClient

with SwissUnihockeyClient() as client:
    games = client.get_games(
        league=2,
        game_class=11,
        season=2025
    )
```

## 🗂️ League & Game Class Codes

### League Codes
- `2` = NLB (National League B)
- `3` = 1. Liga
- `4` = 2. Liga
- `5` = 3. Liga
- `6` = 4. Liga
- `7` = 5. Liga
- `12` = Regional
- `13` = Interregional A

### Game Class Codes
- `11` = Herren (Men)
- `21` = Damen (Women)
- `31-36` = Junioren (Juniors)
- `41-44` = Juniorinnen (Junior Women)
- `51` = Senioren (Seniors)

## 📦 Next Development Steps

### 1. Add Data Storage
Install pandas for data processing:
```powershell
..\.venv\Scripts\python.exe -m pip install pandas
```

### 2. Create Analysis Scripts
Add to `analysis/` folder:
- `league_analysis.py` - Analyze league trends
- `player_stats.py` - Player performance metrics
- `team_comparison.py` - Compare teams head-to-head

### 3. Build Web Interface
Choose a framework:
- **Flask** (simple, included in requirements.txt)
- **FastAPI** (modern, async)
- **Streamlit** (quick data dashboards)

### 4. Add Database
For persistent storage:
- SQLite (simple, file-based)
- PostgreSQL (production-ready)
- MongoDB (flexible, document-based)

## 🔍 API Exploration Tips

### Find Available Parameters
Some endpoints accept additional parameters. To discover them:
1. Try the API in your browser: `https://api-v2.swissunihockey.ch/api/clubs`
2. Check the response structure for hints
3. Experiment with different parameter combinations

### Common Parameters
- `club_id` - Filter by club
- `team_id` - Filter by team
- `league` - League number
- `game_class` - Game class (Men/Women/Junior)
- `season` - Season year (YYYY format)
- `group` - Group/division within league
- `from_date` - Start date filter
- `to_date` - End date filter

## 🐛 Troubleshooting

### 404 Errors
Some endpoints (like `/api/topscorers`) may return 404 if:
- Season hasn't started yet
- No data available for that combination
- Required parameters are missing
- Endpoint needs authentication (marked "private" in docs)

**Solution**: Try different season/league combinations

### Timeout Errors
If requests timeout:
- Increase timeout in `config.ini`: `timeout = 60`
- Check your internet connection
- Try again during off-peak hours

## 📚 Resources

- **API Documentation**: https://api-v2.swissunihockey.ch/api/doc/table/overview
- **Swiss Unihockey Website**: https://swissunihockey.ch
- **API Usage Examples**: See `API_USAGE_EXAMPLES.py`
- **Test Script**: `test_api.py`
- **Example Fetcher**: `scripts/example_fetch_data.py`

## 🎯 Project Ideas

### Beginner
1. **Club Directory** - Searchable list of all 346 clubs
2. **League Tables** - Display current standings
3. **Season Selector** - Compare different seasons

### Intermediate
4. **Team Dashboard** - Stats, games, roster
5. **Player Profiles** - Individual statistics
6. **Match Center** - Today's games with live scores

### Advanced
7. **Prediction Model** - ML-based match predictions
8. **Performance Tracker** - Track team form over time
9. **Fantasy League** - Points system based on real stats
10. **Mobile App** - React Native or Flutter app

## 💡 Tips

- **Start small**: Build one feature at a time
- **Cache data**: Don't hammer the API - save responses locally
- **Error handling**: Always wrap API calls in try/except
- **Rate limiting**: Be respectful of API limits
- **Data freshness**: Update data periodically, not on every page load

## ✉️ Need Help?

Check these files:
- `README.md` - Project overview
- `API_USAGE_EXAMPLES.py` - Code snippets
- `config.ini` - Configuration options
- `requirements.txt` - Dependencies

Happy coding! 🏒
