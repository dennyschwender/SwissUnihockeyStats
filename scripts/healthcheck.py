#!/usr/bin/env python3
"""
Docker health check script for SwissUnihockey container
Tests API client initialization and basic functionality
"""

import sys
from pathlib import Path

try:
    # Import API client
    from api import SwissUnihockeyClient
    
    # Create client instance
    client = SwissUnihockeyClient()
    
    # Test basic API call (use cache if available)
    clubs = client.get_clubs()
    
    # Verify response
    if not clubs or 'entries' not in clubs:
        print("❌ Health check failed: Invalid API response")
        sys.exit(1)
    
    # Success
    print(f"✅ Health check passed: {len(clubs['entries'])} clubs accessible")
    sys.exit(0)
    
except ImportError as e:
    print(f"❌ Health check failed: Import error - {e}")
    sys.exit(1)
    
except Exception as e:
    print(f"❌ Health check failed: {e}")
    sys.exit(1)
