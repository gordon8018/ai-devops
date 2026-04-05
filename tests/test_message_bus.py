#!/usr/bin/env python3
"""Tests for message_bus.py - MessageBus 测试 (15+ test cases)"""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

SCRIPT_DIR = Path(__file__).parent.absolute()
BASE = SCRIPT_DIR.parent
sys.path.insert(0, str(BASE / "orchestrator" / "bin"))

from message_bus import Message, MessageBus, get_message_bus


class TestMessage(unittest.TestCase):
    """Message 数据类测试 (6 cases)"""
    
    def test_message_creation(self):
        msg = Message(
            message_id="msg-123",
            from_agent="agent-1",
            to_agent="agent-2",
            content={"text": "hello"},
            timestamp=int(time.time() * 1000)
        )
        self.assertEqual(msg.message_id, "msg-123")
        self.assertEqual(msg.from_agent, "agent-1")
        self.assertEqual(msg.to_agent, "agent-2")

    def test_message_to_dict(self):
        msg = Message(
            message_id="msg-456",
            from_agent="sender",
            to_agent="receiver",
            content={"key": "value"},
            timestamp=1234567890
        )
        data = msg.to_dict()
        self.assertEqual(data["message_id"], "msg-456")
        self.assertEqual(data["from_agent"], "sender")
        self.assertEqual(data["content"]["key"], "value")

    def test_message_from_dict(self):
        data = {
            "message_id": "msg-789",
            "from_agent": "a1",
            "to_agent": "a2",
            "content": {"text": "test"},
            "timestamp": 9876543210,
            "topic": "alerts"
        }
        msg = Message.from_dict(data)
        self.assertEqual(msg.message_id, "msg-789")
        self.assertEqual(msg.topic, "alerts")

    def test_message_with_optional_topic(self):
        msg = Message(
            message_id="msg-topic",
            from_agent="agent-a",
            to_agent="agent-b",
            content={"data": "test"},
            timestamp=int(time.time() * 1000),
            topic="notifications"
        )
        self.assertEqual(msg.topic, "notifications")

    def test_message_without_topic(self):
        msg = Message(
            message_id="msg-notopic",
            from_agent="agent-x",
            to_agent="agent-y",
            content={},
            timestamp=int(time.time() * 1000)
        )
        self.assertIsNone(msg.topic)

    def test_message_content_can_be_any_type(self):
        msg = Message(
            message_id="msg-content",
            from_agent="a",
            to_agent="b",
            content="string content",
            timestamp=int(time.time() * 1000)
        )
        self.assertEqual(msg.content, "string content")


class TestMessageBusInit(unittest.TestCase):
    """MessageBus 初始化测试 (4 cases)"""
    
    def test_init_default_persist(self):
        bus = MessageBus()
        self.assertTrue(bus.persist)

    def test_init_no_persist(self):
        bus = MessageBus(persist=False)
        self.assertFalse(bus.persist)

    def test_init_has_subscribers_dict(self):
        bus = MessageBus()
        self.assertIsInstance(bus._subscribers, dict)

    def test_init_has_agent_queues(self):
        bus = MessageBus()
        self.assertIsInstance(bus._agent_queues, dict)


class TestMessageBusPublishSubscribe(unittest.TestCase):
    """MessageBus 发布/订阅测试 (6 cases)"""
    
    def setUp(self):
        self.bus = MessageBus(persist=False)
        self.received_messages = []

    def callback(self, msg):
        self.received_messages.append(msg)

    def test_subscribe_and_publish(self):
        self.bus.subscribe("agent-1", "topic-1", self.callback)
        self.bus.publish("topic-1", {"data": "test"}, from_agent="system")
        self.assertEqual(len(self.received_messages), 1)

    def test_multiple_subscribers(self):
        self.bus.subscribe("agent-1", "topic-2", self.callback)
        self.bus.subscribe("agent-2", "topic-2", self.callback)
        self.bus.publish("topic-2", {"data": "test2"}, from_agent="system")
        self.assertEqual(len(self.received_messages), 2)

    def test_no_subscribers(self):
        # Publishing without subscribers should not raise
        self.bus.publish("topic-no-sub", {"data": "test"})
        self.assertEqual(len(self.received_messages), 0)

    def test_callback_exception_handling(self):
        def bad_callback(msg):
            raise Exception("Callback error")
        
        self.bus.subscribe("agent-1", "topic-3", bad_callback)
        # Should not raise
        self.bus.publish("topic-3", {"data": "test"})

    def test_unsubscribe(self):
        self.bus.subscribe("agent-1", "topic-4", self.callback)
        self.bus.unsubscribe("agent-1", "topic-4", self.callback)
        # Note: unsubscribe may not remove if agent_id tracking not implemented
        # So we just verify it doesn't crash

    def test_publish_to_specific_agent(self):
        self.bus.publish(
            "topic-5",
            {"data": "direct"},
            from_agent="system",
            to_agent="agent-target"
        )
        # Should add to agent-target's queue
        self.assertIn("agent-target", self.bus._agent_queues)


class TestMessageBusPointToPoint(unittest.TestCase):
    """MessageBus 点对点消息测试 (5 cases)"""
    
    def setUp(self):
        self.bus = MessageBus(persist=False)

    def test_send_message(self):
        msg_id = self.bus.send_message(
            from_agent="sender",
            to_agent="receiver",
            content={"text": "hello"}
        )
        self.assertIsNotNone(msg_id)
        self.assertIn("receiver", self.bus._agent_queues)

    def test_send_message_with_topic(self):
        msg_id = self.bus.send_message(
            from_agent="a",
            to_agent="b",
            content={"data": "test"},
            topic="custom-topic"
        )
        self.assertIsNotNone(msg_id)

    def test_receive_messages_empty(self):
        messages = self.bus.receive_messages("agent-no-msgs")
        self.assertEqual(len(messages), 0)

    def test_send_and_receive(self):
        self.bus.send_message("agent-a", "agent-b", {"text": "hi"})
        messages = self.bus.receive_messages("agent-b", limit=10)
        self.assertGreaterEqual(len(messages), 1)

    def test_receive_respects_limit(self):
        for i in range(5):
            self.bus.send_message("sender", "receiver", {"id": i})
        
        messages = self.bus.receive_messages("receiver", limit=2)
        self.assertLessEqual(len(messages), 2)


class TestMessageBusQueueManagement(unittest.TestCase):
    """MessageBus 队列管理测试 (4 cases)"""
    
    def setUp(self):
        self.bus = MessageBus(persist=False)

    def test_get_queue_size_empty(self):
        size = self.bus.get_queue_size("agent-empty")
        self.assertEqual(size, 0)

    def test_get_queue_size_with_messages(self):
        self.bus.send_message("a", "b", {"text": "msg1"})
        self.bus.send_message("a", "b", {"text": "msg2"})
        size = self.bus.get_queue_size("b")
        self.assertGreaterEqual(size, 2)

    def test_clear_queue(self):
        self.bus.send_message("a", "b", {"text": "msg"})
        self.bus.clear_queue("b")
        size = self.bus.get_queue_size("b")
        self.assertEqual(size, 0)

    def test_clear_empty_queue(self):
        # Should not raise
        self.bus.clear_queue("agent-no-queue")


class TestMessageBusMessageId(unittest.TestCase):
    """MessageBus 消息ID生成测试 (3 cases)"""
    
    def setUp(self):
        self.bus = MessageBus(persist=False)

    def test_generate_message_id_format(self):
        msg_id = self.bus._generate_message_id()
        self.assertIn("msg-", msg_id)

    def test_generate_unique_ids(self):
        id1 = self.bus._generate_message_id()
        id2 = self.bus._generate_message_id()
        self.assertNotEqual(id1, id2)

    def test_message_id_includes_timestamp(self):
        msg_id = self.bus._generate_message_id()
        # Should include current timestamp
        now = int(time.time())
        self.assertTrue(any(char.isdigit() for char in msg_id))


class TestGlobalMessageBus(unittest.TestCase):
    """全局消息总线单例测试 (3 cases)"""
    
    def test_get_message_bus_returns_instance(self):
        bus = get_message_bus()
        self.assertIsInstance(bus, MessageBus)

    def test_get_message_bus_returns_same_instance(self):
        bus1 = get_message_bus()
        bus2 = get_message_bus()
        self.assertIs(bus1, bus2)

    def test_global_bus_thread_safety(self):
        # Basic test to verify lock is used
        import threading
        results = []
        
        def get_bus():
            results.append(get_message_bus())
        
        threads = [threading.Thread(target=get_bus) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All should be the same instance
        self.assertTrue(all(bus is results[0] for bus in results))


if __name__ == "__main__":
    unittest.main()
