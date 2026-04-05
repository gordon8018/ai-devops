#!/usr/bin/env python3
"""Tests for ResourceMonitor module"""
import pytest
import time
import os
from unittest.mock import Mock, patch, mock_open
from dataclasses import asdict

from orchestrator.bin.resource_monitor import (
    ResourceMonitor,
    CPUStats,
    MemoryStats,
    DiskStats,
    NetworkStats,
    get_resource_monitor,
)


class TestCPUStats:
    def test_cpu_stats_creation(self):
        stats = CPUStats(percent=45.5, user=20.0, system=15.0, idle=64.5, cores=8, load_avg=[1.5, 1.2, 1.0])
        assert stats.percent == 45.5
        assert stats.cores == 8

    def test_cpu_stats_asdict(self):
        stats = CPUStats(percent=30.0, user=10.0, system=10.0, idle=80.0, cores=4, load_avg=[0.5, 0.4, 0.3])
        result = asdict(stats)
        assert result["percent"] == 30.0


class TestMemoryStats:
    def test_memory_stats_creation(self):
        stats = MemoryStats(total=16 * 1024**3, available=8 * 1024**3, used=8 * 1024**3, percent=50.0, swap_total=8 * 1024**3, swap_used=2 * 1024**3, swap_percent=25.0)
        assert stats.total == 16 * 1024**3
        assert stats.percent == 50.0

    def test_memory_stats_zero_values(self):
        stats = MemoryStats(total=0, available=0, used=0, percent=0.0, swap_total=0, swap_used=0, swap_percent=0.0)
        assert stats.total == 0


class TestDiskStats:
    def test_disk_stats_creation(self):
        stats = DiskStats(total=500 * 1024**3, used=250 * 1024**3, free=250 * 1024**3, percent=50.0, filesystem="/dev/sda1")
        assert stats.total == 500 * 1024**3
        assert stats.filesystem == "/dev/sda1"

    def test_disk_stats_custom_path(self):
        stats = DiskStats(total=100 * 1024**3, used=50 * 1024**3, free=50 * 1024**3, percent=50.0, filesystem="/home")
        assert stats.filesystem == "/home"


class TestNetworkStats:
    def test_network_stats_creation(self):
        stats = NetworkStats(bytes_sent=1024**3, bytes_recv=2 * 1024**3, packets_sent=1000000, packets_recv=2000000, bytes_sent_per_sec=1024 * 100, bytes_recv_per_sec=1024 * 200)
        assert stats.bytes_sent == 1024**3

    def test_network_stats_zero_values(self):
        stats = NetworkStats(bytes_sent=0, bytes_recv=0, packets_sent=0, packets_recv=0, bytes_sent_per_sec=0.0, bytes_recv_per_sec=0.0)
        assert stats.bytes_sent == 0

class TestResourceMonitor:
    def test_resource_monitor_initialization(self):
        monitor = ResourceMonitor()
        assert monitor._last_net_stats is None
        assert monitor._cpu_count >= 1

    def test_get_memory_stats_returns_memory_stats(self):
        monitor = ResourceMonitor()
        stats = monitor.get_memory_stats()
        assert isinstance(stats, MemoryStats)

    def test_get_disk_stats_returns_disk_stats(self):
        monitor = ResourceMonitor()
        stats = monitor.get_disk_stats("/")
        assert isinstance(stats, DiskStats)
        assert stats.filesystem == "/"

    def test_get_disk_stats_custom_path(self):
        monitor = ResourceMonitor()
        stats = monitor.get_disk_stats("/tmp")
        assert stats.filesystem == "/tmp"

    def test_get_network_stats_returns_network_stats(self):
        monitor = ResourceMonitor()
        stats = monitor.get_network_stats()
        assert isinstance(stats, NetworkStats)

    def test_get_network_stats_calculates_rate(self):
        monitor = ResourceMonitor()
        stats1 = monitor.get_network_stats()
        time.sleep(0.1)
        stats2 = monitor.get_network_stats()
        assert stats2.bytes_sent_per_sec >= 0

    def test_get_all_stats_returns_dict(self):
        monitor = ResourceMonitor()
        result = monitor.get_all_stats()
        assert isinstance(result, dict)
        assert "cpu" in result
        assert "memory" in result
        assert "disk" in result
        assert "network" in result
        assert "timestamp" in result

    def test_get_all_stats_structure(self):
        monitor = ResourceMonitor()
        result = monitor.get_all_stats()
        assert "percent" in result["cpu"]
        assert "total" in result["memory"]
        assert "total" in result["disk"]

    def test_get_summary_returns_dict(self):
        monitor = ResourceMonitor()
        result = monitor.get_summary()
        assert isinstance(result, dict)
        assert "cpu" in result
        assert "memory" in result

    def test_get_summary_converts_to_readable_units(self):
        monitor = ResourceMonitor()
        result = monitor.get_summary()
        assert "usedGB" in result["memory"]
        assert "bytesSentMB" in result["network"]

    def test_multiple_instances_independent(self):
        monitor1 = ResourceMonitor()
        monitor2 = ResourceMonitor()
        stats1 = monitor1.get_cpu_stats()
        stats2 = monitor2.get_cpu_stats()
        assert isinstance(stats1, CPUStats)
        assert isinstance(stats2, CPUStats)


class TestGetResourceMonitor:
    def test_get_resource_monitor_returns_instance(self):
        import orchestrator.bin.resource_monitor as rm
        rm._monitor_instance = None
        monitor = get_resource_monitor()
        assert isinstance(monitor, ResourceMonitor)

    def test_get_resource_monitor_singleton(self):
        import orchestrator.bin.resource_monitor as rm
        rm._monitor_instance = None
        monitor1 = get_resource_monitor()
        monitor2 = get_resource_monitor()
        assert monitor1 is monitor2


class TestResourceMonitorEdgeCases:
    def test_get_disk_stats_invalid_path(self):
        monitor = ResourceMonitor()
        stats = monitor.get_disk_stats("/nonexistent/path")
        assert isinstance(stats, DiskStats)

    def test_get_cpu_stats_handles_error(self):
        monitor = ResourceMonitor()
        with patch('builtins.open', side_effect=PermissionError("Access denied")):
            stats = monitor.get_cpu_stats()
        assert isinstance(stats, CPUStats)
        assert stats.percent == 0.0

    def test_get_memory_stats_handles_error(self):
        monitor = ResourceMonitor()
        with patch('builtins.open', side_effect=PermissionError("Access denied")):
            stats = monitor.get_memory_stats()
        assert isinstance(stats, MemoryStats)
        assert stats.total == 0

    def test_network_stats_negative_rate_protection(self):
        monitor = ResourceMonitor()
        monitor.get_network_stats()
        monitor._last_net_stats = (10**18, 10**18)
        stats = monitor.get_network_stats()
        assert stats.bytes_sent_per_sec >= 0
