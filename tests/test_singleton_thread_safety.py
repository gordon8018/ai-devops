"""
并发测试：验证单例模式的线程安全性

测试 alert_router, global_scheduler, message_bus 中的单例在多线程环境下是否安全。
"""
import threading
import time
import pytest
import sys
import os

# 添加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'orchestrator', 'bin'))


class TestAlertRouterThreadSafety:
    """测试 AlertRouter 单例的线程安全性"""
    
    def test_concurrent_get_router_returns_same_instance(self):
        """并发调用 get_router() 应该返回同一个实例"""
        from alert_router import get_router, set_router
        import orchestrator.bin.alert_router as module
        
        # 重置单例
        set_router(None)
        module._router_instance = None
        
        instances = []
        errors = []
        
        def get_instance():
            try:
                instance = get_router()
                instances.append(id(instance))
            except Exception as e:
                errors.append(str(e))
        
        # 创建多个线程同时获取实例
        threads = [threading.Thread(target=get_instance) for _ in range(50)]
        
        # 同时启动所有线程
        for t in threads:
            t.start()
        
        # 等待所有线程完成
        for t in threads:
            t.join()
        
        # 验证
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(instances) == 50, f"Expected 50 instances, got {len(instances)}"
        
        # 所有实例的 id 应该相同
        unique_ids = set(instances)
        assert len(unique_ids) == 1, f"Expected 1 unique instance, got {len(unique_ids)}: {unique_ids}"


class TestGlobalSchedulerThreadSafety:
    """测试 GlobalScheduler 单例的线程安全性"""
    
    def test_concurrent_get_global_scheduler_returns_same_instance(self):
        """并发调用 get_global_scheduler() 应该返回同一个实例"""
        from global_scheduler import get_global_scheduler, reset_global_scheduler
        
        # 重置单例
        reset_global_scheduler()
        
        instances = []
        errors = []
        
        def get_instance():
            try:
                instance = get_global_scheduler()
                instances.append(id(instance))
            except Exception as e:
                errors.append(str(e))
        
        # 创建多个线程同时获取实例
        threads = [threading.Thread(target=get_instance) for _ in range(50)]
        
        # 同时启动所有线程
        for t in threads:
            t.start()
        
        # 等待所有线程完成
        for t in threads:
            t.join()
        
        # 验证
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(instances) == 50, f"Expected 50 instances, got {len(instances)}"
        
        # 所有实例的 id 应该相同
        unique_ids = set(instances)
        assert len(unique_ids) == 1, f"Expected 1 unique instance, got {len(unique_ids)}: {unique_ids}"


class TestMessageBusThreadSafety:
    """测试 MessageBus 单例的线程安全性"""
    
    def test_concurrent_get_message_bus_returns_same_instance(self):
        """并发调用 get_message_bus() 应该返回同一个实例"""
        from message_bus import get_message_bus
        import orchestrator.bin.message_bus as module
        
        # 重置单例
        module._global_bus = None
        
        instances = []
        errors = []
        
        def get_instance():
            try:
                instance = get_message_bus()
                instances.append(id(instance))
            except Exception as e:
                errors.append(str(e))
        
        # 创建多个线程同时获取实例
        threads = [threading.Thread(target=get_instance) for _ in range(50)]
        
        # 同时启动所有线程
        for t in threads:
            t.start()
        
        # 等待所有线程完成
        for t in threads:
            t.join()
        
        # 验证
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(instances) == 50, f"Expected 50 instances, got {len(instances)}"
        
        # 所有实例的 id 应该相同
        unique_ids = set(instances)
        assert len(unique_ids) == 1, f"Expected 1 unique instance, got {len(unique_ids)}: {unique_ids}"


class TestSingletonStressTest:
    """压力测试：验证高并发下的单例安全性"""
    
    def test_high_concurrency_router(self):
        """高并发压力测试 - AlertRouter"""
        from alert_router import get_router, set_router
        import orchestrator.bin.alert_router as module
        
        # 重置单例
        set_router(None)
        module._router_instance = None
        
        instances = []
        errors = []
        
        def get_instance():
            try:
                for _ in range(10):  # 每个线程调用10次
                    instance = get_router()
                    instances.append(id(instance))
                    time.sleep(0.0001)  # 极短延迟
            except Exception as e:
                errors.append(str(e))
        
        # 创建 100 个线程
        threads = [threading.Thread(target=get_instance) for _ in range(100)]
        
        # 同时启动所有线程
        for t in threads:
            t.start()
        
        # 等待所有线程完成
        for t in threads:
            t.join()
        
        # 验证
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(instances) == 1000, f"Expected 1000 calls, got {len(instances)}"
        
        # 所有实例的 id 应该相同
        unique_ids = set(instances)
        assert len(unique_ids) == 1, f"Expected 1 unique instance, got {len(unique_ids)}"
    
    def test_high_concurrency_scheduler(self):
        """高并发压力测试 - GlobalScheduler"""
        from global_scheduler import get_global_scheduler, reset_global_scheduler
        
        # 重置单例
        reset_global_scheduler()
        
        instances = []
        errors = []
        
        def get_instance():
            try:
                for _ in range(10):  # 每个线程调用10次
                    instance = get_global_scheduler()
                    instances.append(id(instance))
                    time.sleep(0.0001)  # 极短延迟
            except Exception as e:
                errors.append(str(e))
        
        # 创建 100 个线程
        threads = [threading.Thread(target=get_instance) for _ in range(100)]
        
        # 同时启动所有线程
        for t in threads:
            t.start()
        
        # 等待所有线程完成
        for t in threads:
            t.join()
        
        # 验证
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(instances) == 1000, f"Expected 1000 calls, got {len(instances)}"
        
        # 所有实例的 id 应该相同
        unique_ids = set(instances)
        assert len(unique_ids) == 1, f"Expected 1 unique instance, got {len(unique_ids)}"
    
    def test_high_concurrency_message_bus(self):
        """高并发压力测试 - MessageBus"""
        from message_bus import get_message_bus
        import orchestrator.bin.message_bus as module
        
        # 重置单例
        module._global_bus = None
        
        instances = []
        errors = []
        
        def get_instance():
            try:
                for _ in range(10):  # 每个线程调用10次
                    instance = get_message_bus()
                    instances.append(id(instance))
                    time.sleep(0.0001)  # 极短延迟
            except Exception as e:
                errors.append(str(e))
        
        # 创建 100 个线程
        threads = [threading.Thread(target=get_instance) for _ in range(100)]
        
        # 同时启动所有线程
        for t in threads:
            t.start()
        
        # 等待所有线程完成
        for t in threads:
            t.join()
        
        # 验证
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(instances) == 1000, f"Expected 1000 calls, got {len(instances)}"
        
        # 所有实例的 id 应该相同
        unique_ids = set(instances)
        assert len(unique_ids) == 1, f"Expected 1 unique instance, got {len(unique_ids)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
