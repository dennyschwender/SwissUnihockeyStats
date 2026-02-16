"""Test caching performance - demonstrates speed improvement."""

import sys
import time
from pathlib import Path

# Add parent directory to path
current_dir = Path(__file__).parent
parent_dir = current_dir.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from api import SwissUnihockeyClient


def test_caching():
    """Compare performance with and without caching."""
    
    print("=" * 80)
    print("CACHING PERFORMANCE TEST")
    print("=" * 80)
    print()
    
    # Test WITHOUT caching
    print("1️⃣  TEST WITHOUT CACHING")
    print("-" * 80)
    client_no_cache = SwissUnihockeyClient(use_cache=False)
    
    start = time.time()
    print("  • Fetching clubs (1st time)...", end=" ")
    client_no_cache.get_clubs()
    time1 = time.time() - start
    print(f"✓ {time1:.3f}s")
    
    start = time.time()
    print("  • Fetching clubs (2nd time)...", end=" ")
    client_no_cache.get_clubs()
    time2 = time.time() - start
    print(f"✓ {time2:.3f}s")
    
    start = time.time()
    print("  • Fetching clubs (3rd time)...", end=" ")
    client_no_cache.get_clubs()
    time3 = time.time() - start
    print(f"✓ {time3:.3f}s")
    
    total_no_cache = time1 + time2 + time3
    print(f"\n  Total time: {total_no_cache:.3f}s")
    print()
    
    # Test WITH caching
    print("2️⃣  TEST WITH CACHING")
    print("-" * 80)
    client_with_cache = SwissUnihockeyClient(use_cache=True)
    
    # Clear cache first
    client_with_cache.cache.clear()
    
    start = time.time()
    print("  • Fetching clubs (1st time - cache miss)...", end=" ")
    client_with_cache.get_clubs()
    time1_cached = time.time() - start
    print(f"✓ {time1_cached:.3f}s (API call)")
    
    start = time.time()
    print("  • Fetching clubs (2nd time - cache hit)...", end=" ")
    client_with_cache.get_clubs()
    time2_cached = time.time() - start
    print(f"✓ {time2_cached:.3f}s (from cache ⚡)")
    
    start = time.time()
    print("  • Fetching clubs (3rd time - cache hit)...", end=" ")
    client_with_cache.get_clubs()
    time3_cached = time.time() - start
    print(f"✓ {time3_cached:.3f}s (from cache ⚡)")
    
    total_with_cache = time1_cached + time2_cached + time3_cached
    print(f"\n  Total time: {total_with_cache:.3f}s")
    print()
    
    # Results
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    improvement = ((total_no_cache - total_with_cache) / total_no_cache) * 100
    speedup = total_no_cache / total_with_cache
    
    print(f"  Without caching: {total_no_cache:.3f}s")
    print(f"  With caching:    {total_with_cache:.3f}s")
    print()
    print(f"  ⚡ Improvement:   {improvement:.1f}% faster")
    print(f"  ⚡ Speedup:       {speedup:.1f}x faster")
    print()
    
    # Cache stats
    stats = client_with_cache.cache.get_stats()
    print("  Cache Statistics:")
    print(f"    • Entries:    {stats['total_entries']}")
    print(f"    • Files:      {stats['total_files']}")
    print(f"    • Size:       {stats['total_size_mb']} MB")
    print(f"    • Categories: {list(stats['categories'].keys())}")
    print()
    
    print("=" * 80)


def test_multiple_endpoints():
    """Test caching with multiple endpoints."""
    
    print("\n" + "=" * 80)
    print("MULTIPLE ENDPOINTS TEST")
    print("=" * 80)
    print()
    
    client = SwissUnihockeyClient(use_cache=True)
    client.cache.clear()
    
    endpoints = [
        ("Clubs", lambda: client.get_clubs()),
        ("Leagues", lambda: client.get_leagues()),
        ("Seasons", lambda: client.get_seasons()),
    ]
    
    # First pass - all cache misses
    print("First pass (cache misses):")
    start_total = time.time()
    for name, func in endpoints:
        start = time.time()
        func()
        elapsed = time.time() - start
        print(f"  • {name:15} {elapsed:.3f}s")
    first_pass = time.time() - start_total
    print(f"Total: {first_pass:.3f}s\n")
    
    # Second pass - all cache hits
    print("Second pass (cache hits):")
    start_total = time.time()
    for name, func in endpoints:
        start = time.time()
        func()
        elapsed = time.time() - start
        print(f"  • {name:15} {elapsed:.3f}s ⚡")
    second_pass = time.time() - start_total
    print(f"Total: {second_pass:.3f}s\n")
    
    speedup = first_pass / second_pass
    print(f"⚡ Speedup: {speedup:.1f}x faster")
    print()


def test_force_refresh():
    """Test force_refresh parameter."""
    
    print("=" * 80)
    print("FORCE REFRESH TEST")
    print("=" * 80)
    print()
    
    client = SwissUnihockeyClient(use_cache=True)
    
    print("1. Normal fetch (uses cache if available):")
    start = time.time()
    client.get_clubs()
    print(f"   Time: {time.time() - start:.3f}s\n")
    
    print("2. Force refresh (bypasses cache, fetches fresh):")
    start = time.time()
    client.get_clubs(force_refresh=True)
    print(f"   Time: {time.time() - start:.3f}s\n")
    
    print("3. Normal fetch again (uses fresh cache):")
    start = time.time()
    client.get_clubs()
    print(f"   Time: {time.time() - start:.3f}s ⚡\n")


if __name__ == "__main__":
    try:
        test_caching()
        test_multiple_endpoints()
        test_force_refresh()
        
        print("=" * 80)
        print("✓ All tests completed successfully!")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
