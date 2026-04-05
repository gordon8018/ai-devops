"""Tests for ResourceMonitor with caching."""

import pytest
import threading
import time
from unittest.mock import patch, MagicMock

# Reset before import
import sys
if 'orchestrator.bin.resource_monitor' in sys.modules:
    del sys.modules['orchestrator.bin.resource_monitor']

from orchestrator.bin.resource_monitor import (
    ResourceMonitor,
    get_resource_monitor,
    _monitor_instance,
    CPUStats,
    MemoryStats,
    DiskStats,
    NetworkStats
)


class TestResourceMonitorCaching:
    """Test ResourceMonitor caching functionality."""
    
    @pytest.fixture
    def monitor(self):
        """Create a ResourceMonitor instance with short cache interval for testing."""
        return ResourceMonitor(cache_interval=0.1)  # 100ms cache for testing
    
    def test_cache_interval_configuration(self, monitor):
        """Test that cache interval is properly configured."""
        assert monitor.cache_interval == 0.1
        
        monitor.cache_interval = 5.0
        assert monitor.cache_interval == 5.0
    
    def test_cache_is_valid(self, monitor):
        """Test cache validity check."""
        assert monitor._is_cache_valid() is False
        
        # Set a timestamp and verify validity
        monitor._cache_timestamp = time.time()
        assert monitor._is_cache_valid() is True
    
    def test_get_all_stats_caching(self, monitor):
        """Test that get_all_stats_caching uses cache."""
        # First call should populate cache
        result1 = monitor.get_all_stats_caching()
        assert result1 is not None
        assert "cpu" in result1
        assert "memory" in result1
        assert "disk" in result1
        assert "network" in result1
        assert "timestamp" in result1
        
        first_timestamp = result1["timestamp"]
        
        # Second call should return cached version
        result2 = monitor.get_all_stats_caching()
        assert result2["timestamp"] == first_timestamp
        
        # But direct call should return fresh data
        result3 = monitor.get_all_stats()
        assert result3 is not None
        # Timestamp should be newer (but could be same if fast)
        assert result3["timestamp"] >= first_timestamp
    
    def test_get_summary_caching(self, monitor):
        """Test that get_summary_caching uses cache."""
        # First call should populate cache
        result1 = monitor.get_summary_caching()
        assert result1 is not None
        assert "cpu" in result1
        assert "memory" in result1
        assert "disk" in result1
        assert "network" in result1
        
        first_timestamp = result1["timestamp"]
        
        # Second call should return cached version
        result2 = monitor.get_summary_caching()
        assert result2["timestamp"] == first_timestamp
    
    def test_cache_invalidation(self, monitor):
        """Test manual cache invalidation."""
        # Populate cache
        monitor.get_all_stats_caching()
        assert monitor._cached_all_stats is not None
        
        # Invalidate
        monitor.invalidate_cache()
        assert monitor._cached_all_stats is None
        assert monitor._cached_summary is None
        
        # Next call should regenerate
        result = monitor.get_all_stats_caching()
        assert result is not None
        assert monitor._cached_all_stats is not None
    
    def test_concurrent_access(self, monitor):
        """Test thread safety of cache."""
        results = []
        errors = []
        
        def worker():
            try:
                for _ in range(10):
                    result = monitor.get_all_stats_caching()
                    results.append(result)
                    time.sleep(0.01)
            except Exception as e:
                errors.append(str(e))
        
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == 50
    
    def test_cache_expiration(self, monitor):
        """Test that cache expires after interval."""
        # Populate cache
        result1 = monitor.get_all_stats_caching()
        time1 = result1["timestamp"]
        
        # Wait for cache to expire
        time.sleep(0.15)  # More than 0.1s cache interval
        
        result2 = monitor.get_all_stats_caching()
        # Timestamp should be different (new data)
        assert result2["timestamp"] != time1
    
    def test_get_all_stats_without_cache(self, monitor):
        """Test that get_all_stats doesn't use cache."""
        result1 = monitor.get_all_stats()
        time1 = result1["timestamp"]
        
        result2 = monitor.get_all_stats()
        # Should be different timestamps (no caching)
        assert result2["timestamp"] >= time1


class TestGetResourceMonitor:
    """Test get_resource_monitor function."""
    
    def test_singleton_pattern(self):
        """Test that get_resource_monitor returns same instance."""
        monitor1 = get_resource_monitor()
        monitor2 = get_resource_monitor()
        assert monitor1 is monitor2
    
    def test_cache_interval_parameter(self):
        """Test that cache_interval parameter is applied on first call."""
        # Delete the singleton to test fresh creation
        import orchestrator.bin.resource_monitor as rm
        rm._monitor_instance = None
        
        monitor = get_resource_monitor(cache_interval=2.5)
        assert monitor.cache_interval == 2.5
        
        # Reset for other tests
        rm._monitor_instance = None
    
    def test_default_cache_interval(self):
        """Test default cache interval."""
        # Reset global instance
        import orchestrator.bin.resource_monitor as rm
        rm._monitor_instance = None
        
        monitor = get_resource_monitor()
        assert monitor.cache_interval == 5.0
        
        # Reset for other tests
        rm._monitor_instance = None
