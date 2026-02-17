"""Quick script to test teams API and cache reload"""
import requests
import json

# Get current cache status
print("=== Current Cache Status ===")
resp = requests.get("http://localhost:8000/cache/status")
status = resp.json()
print(f"Teams count: {status['teams_count']}")
print(f"Status: {status['status']}")
print()

# Try to clear cache (restart server to reload)
print("=== Solution ===")
print("Server needs to be fully restarted to reload Python modules.")
print("The code changes are correct in the file, but Python cached the old version.")
print()
print("Run: Stop-Process -Name python -Force")
print("Then restart the server")
