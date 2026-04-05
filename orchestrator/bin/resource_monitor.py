#!/usr/bin/env python3
from __future__ import annotations
import json, os, threading, time
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List

@dataclass
class CPUStats:
    percent: float
    user: float
    system: float
    idle: float
    cores: int
    load_avg: List[float]

@dataclass
class MemoryStats:
    total: int
    available: int
    used: int
    percent: float
    swap_total: int
    swap_used: int
    swap_percent: float

@dataclass
class DiskStats:
    total: int
    used: int
    free: int
    percent: float
    filesystem: str

@dataclass
class NetworkStats:
    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int
    bytes_sent_per_sec: float
    bytes_recv_per_sec: float

class ResourceMonitor:
    def __init__(self, cache_interval: float = 5.0):
        self._last_net_stats = None
        self._last_net_time = None
        self._last_cpu_stats = None
        self._last_cpu_time = None
        self._cpu_count = os.cpu_count() or 1
        self._cache_interval = cache_interval
        self._cache_lock = threading.Lock()
        self._cached_all_stats = None
        self._cached_summary = None
        self._cache_timestamp = 0.0
    
    @property
    def cache_interval(self) -> float:
        return self._cache_interval
    
    @cache_interval.setter
    def cache_interval(self, value: float) -> None:
        if value > 0:
            self._cache_interval = value
    
    def _is_cache_valid(self):
        return time.time() - self._cache_timestamp < self._cache_interval

    def get_cpu_stats(self):
        try:
            with open("/proc/stat", "r") as f:
                line = f.readline()
                parts = line.split()
                user = int(parts[1])
                nice = int(parts[2])
                system = int(parts[3])
                idle = int(parts[4])
                iowait = int(parts[5]) if len(parts) > 5 else 0
                irq = int(parts[6]) if len(parts) > 6 else 0
                softirq = int(parts[7]) if len(parts) > 7 else 0
                steal = int(parts[8]) if len(parts) > 8 else 0
                total = user + nice + system + idle + iowait + irq + softirq + steal
                active = user + nice + system + irq + softirq + steal
                if self._last_cpu_stats and self._last_cpu_time:
                    last_total, last_active = self._last_cpu_stats
                    delta_total = total - last_total
                    delta_active = active - last_active
                    percent = (delta_active / delta_total) * 100.0 if delta_total > 0 else 0.0
                else:
                    percent = (active / total * 100.0) if total > 0 else 0.0
                self._last_cpu_stats = (total, active)
                load_avg = [0.0, 0.0, 0.0]
                try:
                    with open("/proc/loadavg", "r") as f:
                        p = f.read().split()
                        load_avg = [float(p[0]), float(p[1]), float(p[2])]
                except: pass
                return CPUStats(percent=round(percent,2), user=round((user/total*100)if total>0 else 0,2), system=round((system/total*100)if total>0 else 0,2), idle=round((idle/total*100)if total>0 else 0,2), cores=self._cpu_count, load_avg=load_avg)
        except:
            return CPUStats(percent=0, user=0, system=0, idle=100, cores=self._cpu_count, load_avg=[0,0,0])

    def get_memory_stats(self):
        try:
            meminfo = {}
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split()
                    meminfo[parts[0].rstrip(":")] = int(parts[1]) * 1024
            total = meminfo.get("MemTotal", 0)
            available = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
            used = total - available
            swap_total = meminfo.get("SwapTotal", 0)
            swap_free = meminfo.get("SwapFree", 0)
            swap_used = swap_total - swap_free
            return MemoryStats(total=total, available=available, used=used, percent=round((used/total*100)if total>0 else 0,2), swap_total=swap_total, swap_used=swap_used, swap_percent=round((swap_used/swap_total*100)if swap_total>0 else 0,2))
        except:
            return MemoryStats(total=0, available=0, used=0, percent=0, swap_total=0, swap_used=0, swap_percent=0)

    def get_disk_stats(self, path="/"):
        try:
            stat = os.statvfs(path)
            total = stat.f_blocks * stat.f_frsize
            free = stat.f_bavail * stat.f_frsize
            return DiskStats(total=total, used=total-free, free=free, percent=round(((total-free)/total*100)if total>0 else 0,2), filesystem=path)
        except:
            return DiskStats(total=0, used=0, free=0, percent=0, filesystem=path)

    def get_network_stats(self):
        try:
            bytes_sent = bytes_recv = packets_sent = packets_recv = 0
            with open("/proc/net/dev", "r") as f:
                next(f); next(f)
                for line in f:
                    parts = line.split()
                    if len(parts) >= 17 and parts[0].rstrip(":") != "lo":
                        bytes_recv += int(parts[1]); packets_recv += int(parts[2])
                        bytes_sent += int(parts[9]); packets_sent += int(parts[10])
            now = time.time()
            if self._last_net_stats and self._last_net_time:
                delta_time = now - self._last_net_time
                delta_sent = bytes_sent - self._last_net_stats[0]
                delta_recv = bytes_recv - self._last_net_stats[1]
                bps = max(0, round(delta_sent/delta_time,2)) if delta_time>0 else 0
                bpr = max(0, round(delta_recv/delta_time,2)) if delta_time>0 else 0
            else:
                bps, bpr = 0.0, 0.0
            self._last_net_stats = (bytes_sent, bytes_recv)
            self._last_net_time = now
            return NetworkStats(bytes_sent=bytes_sent, bytes_recv=bytes_recv, packets_sent=packets_sent, packets_recv=packets_recv, bytes_sent_per_sec=bps, bytes_recv_per_sec=bpr)
        except:
            return NetworkStats(bytes_sent=0, bytes_recv=0, packets_sent=0, packets_recv=0, bytes_sent_per_sec=0, bytes_recv_per_sec=0)

    def get_all_stats_caching(self):
        with self._cache_lock:
            if self._is_cache_valid() and self._cached_all_stats:
                return dict(self._cached_all_stats)
            result = {"cpu": asdict(self.get_cpu_stats()), "memory": asdict(self.get_memory_stats()), "disk": asdict(self.get_disk_stats()), "network": asdict(self.get_network_stats()), "timestamp": int(time.time() * 1000)}
            self._cached_all_stats = dict(result)
            self._cache_timestamp = time.time()
            return result

    def get_summary_caching(self):
        with self._cache_lock:
            if self._is_cache_valid() and self._cached_summary:
                return dict(self._cached_summary)
            cpu = self.get_cpu_stats()
            mem = self.get_memory_stats()
            disk = self.get_disk_stats()
            net = self.get_network_stats()
            result = {"cpu": {"percent": cpu.percent, "cores": cpu.cores, "loadAvg": cpu.load_avg}, "memory": {"percent": mem.percent, "usedGB": round(mem.used/(1024**3),2), "totalGB": round(mem.total/(1024**3),2)}, "disk": {"percent": disk.percent, "usedGB": round(disk.used/(1024**3),2), "totalGB": round(disk.total/(1024**3),2)}, "network": {"bytesSentMB": round(net.bytes_sent/(1024**2),2), "bytesRecvMB": round(net.bytes_recv/(1024**2),2), "sentPerSecKB": round(net.bytes_sent_per_sec/1024,2), "recvPerSecKB": round(net.bytes_recv_per_sec/1024,2)}, "timestamp": int(time.time() * 1000)}
            self._cached_summary = dict(result)
            self._cache_timestamp = time.time()
            return result

    def invalidate_cache(self):
        with self._cache_lock:
            self._cached_all_stats = None
            self._cached_summary = None
            self._cache_timestamp = 0

    def get_all_stats(self):
        return {"cpu": asdict(self.get_cpu_stats()), "memory": asdict(self.get_memory_stats()), "disk": asdict(self.get_disk_stats()), "network": asdict(self.get_network_stats()), "timestamp": int(time.time() * 1000)}

    def get_summary(self):
        cpu = self.get_cpu_stats()
        mem = self.get_memory_stats()
        disk = self.get_disk_stats()
        net = self.get_network_stats()
        return {"cpu": {"percent": cpu.percent, "cores": cpu.cores, "loadAvg": cpu.load_avg}, "memory": {"percent": mem.percent, "usedGB": round(mem.used/(1024**3),2), "totalGB": round(mem.total/(1024**3),2)}, "disk": {"percent": disk.percent, "usedGB": round(disk.used/(1024**3),2), "totalGB": round(disk.total/(1024**3),2)}, "network": {"bytesSentMB": round(net.bytes_sent/(1024**2),2), "bytesRecvMB": round(net.bytes_recv/(1024**2),2), "sentPerSecKB": round(net.bytes_sent_per_sec/1024,2), "recvPerSecKB": round(net.bytes_recv_per_sec/1024,2)}, "timestamp": int(time.time() * 1000)}

_monitor_instance = None

def get_resource_monitor(cache_interval=5.0):
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = ResourceMonitor(cache_interval=cache_interval)
    return _monitor_instance
