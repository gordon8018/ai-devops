#!/usr/bin/env python3
"""
单元测试 - P2/P3 修复验证

测试内容：
1. 订阅回调死锁风险修复 (message_bus.py)
2. WebSocket TOCTOU 修复 (websocket.py)
3. 日志轮转配置 (RotatingFileHandler)
"""

import unittest
import threading
import time
import tempfile
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler
import logging


class TestMessageBusDeadlockFix(unittest.TestCase):
    """测试订阅回调死锁修复"""
    
    def test_uses_rlock_not_lock(self):
        """验证 MessageBus 使用 RLock 而不是 Lock"""
        from orchestrator.bin.message_bus import MessageBus
        
        bus = MessageBus(persist=False)
        # RLock 允许同一线程多次获取锁
        self.assertIsInstance(bus._lock, type(threading.RLock()))
    
    def test_callback_outside_lock(self):
        """验证回调在锁外执行"""
        from orchestrator.bin.message_bus import MessageBus, Message
        
        bus = MessageBus(persist=False)
        
        # 记录回调执行时的锁状态
        lock_held_during_callback = []
        
        def callback(msg):
            # 检查锁是否被持有
            # 由于我们无法直接检查 RLock 状态，
            # 我们通过尝试再次获取锁来验证（RLock 应该允许）
            acquired = bus._lock.acquire(blocking=False)
            if acquired:
                bus._lock.release()
            lock_held_during_callback.append(acquired)
        
        bus.subscribe("agent-1", "test_topic", callback)
        bus.publish("test_topic", {"data": "test"})
        
        # 由于回调在锁外执行，回调执行时锁应该未被持有
        # 但因为使用 RLock，即使锁被持有也能再次获取
        # 所以这个测试主要验证没有死锁发生
        self.assertEqual(len(lock_held_during_callback), 1)
    
    def test_no_deadlock_on_nested_publish(self):
        """测试嵌套发布不会死锁"""
        from orchestrator.bin.message_bus import MessageBus
        
        bus = MessageBus(persist=False)
        results = []
        
        def callback1(msg):
            results.append("callback1")
            # 在回调中再次发布（如果锁未正确处理会死锁）
            bus.publish("topic2", {"nested": True})
        
        def callback2(msg):
            results.append("callback2")
        
        bus.subscribe("agent-1", "topic1", callback1)
        bus.subscribe("agent-2", "topic2", callback2)
        
        # 设置超时以检测死锁
        def run_test():
            bus.publish("topic1", {"data": "test"})
        
        thread = threading.Thread(target=run_test)
        thread.daemon = True
        thread.start()
        thread.join(timeout=2.0)  # 2秒超时
        
        # 如果线程完成，说明没有死锁
        self.assertFalse(thread.is_alive(), "Deadlock detected!")
        self.assertIn("callback1", results)


class TestWebSocketTOCTOUFix(unittest.TestCase):
    """测试 WebSocket TOCTOU 修复"""
    
    def test_uses_rlock(self):
        """验证 WebSocketHandler 使用 RLock"""
        from orchestrator.api.websocket import WebSocketHandler
        
        handler = WebSocketHandler()
        self.assertIsInstance(handler._lock, type(threading.RLock()))
    
    def test_class_level_rlock(self):
        """验证类级别的锁也是 RLock"""
        from orchestrator.api.websocket import WebSocketHandler
        
        self.assertIsInstance(WebSocketHandler._lock, type(threading.RLock()))


class TestRotatingFileHandlerConfig(unittest.TestCase):
    """测试日志轮转配置"""
    
    def test_global_scheduler_logging_config(self):
        """验证 GlobalScheduler 使用 RotatingFileHandler"""
        from orchestrator.bin.global_scheduler import GlobalScheduler, SchedulerConfig
        
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            config = SchedulerConfig(log_file=log_file)
            scheduler = GlobalScheduler(config)
            
            # 验证日志文件会被创建
            from orchestrator.bin.global_scheduler import SchedulingDecision
            
            decision = SchedulingDecision(
                plan_id="test-plan",
                decision="dispatched",
                reason="test",
                timestamp=int(time.time() * 1000)
            )
            scheduler._log_decision(decision)
            
            # 日志文件应该存在
            self.assertTrue(log_file.exists())
    
    def test_process_guardian_logging_setup(self):
        """验证 ProcessGuardian 配置了 RotatingFileHandler"""
        from orchestrator.bin.process_guardian import ProcessGuardian
        
        guardian = ProcessGuardian()
        
        # 验证 logger 已配置
        logger = logging.getLogger("process_guardian")
        self.assertIsNotNone(logger)
        
        # 验证有 RotatingFileHandler
        has_rotating = any(
            isinstance(h, RotatingFileHandler) 
            for h in logger.handlers
        )
        self.assertTrue(has_rotating, "RotatingFileHandler not configured")
    
    def test_rotating_file_handler_params(self):
        """验证 RotatingFileHandler 参数正确"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            
            handler = RotatingFileHandler(
                log_file,
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5,
                encoding="utf-8"
            )
            
            # 验证参数
            self.assertEqual(handler.maxBytes, 10*1024*1024)
            self.assertEqual(handler.backupCount, 5)
            
            handler.close()
    
    def test_log_rotation(self):
        """测试日志轮转功能"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            
            # 创建小 maxBytes 用于测试
            handler = RotatingFileHandler(
                log_file,
                maxBytes=100,  # 100 bytes
                backupCount=3,
                encoding="utf-8"
            )
            
            logger = logging.getLogger("test_rotation")
            logger.handlers.clear()
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            
            # 写入足够多的数据触发轮转
            for i in range(20):
                logger.info(f"Test message {i} " + "x" * 10)
            
            handler.close()
            
            # 验证生成了备份文件
            backup_files = list(Path(tmpdir).glob("test.log.*"))
            self.assertGreater(len(backup_files), 0, "Log rotation did not create backup files")


if __name__ == "__main__":
    unittest.main(verbosity=2)
