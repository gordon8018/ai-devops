#!/usr/bin/env python3
"""
Message Bus - Agent 间消息传递系统

实现发布/订阅模式，支持 Agent 间异步消息传递。

Usage:
    from orchestrator.bin.message_bus import MessageBus
    
    bus = MessageBus()
    bus.subscribe("agent-1", "alert", callback)
    bus.publish("alert", {"type": "timeout", "task_id": "xxx"})
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from queue import Queue
from typing import Any, Callable, Optional
import threading


@dataclass
class Message:
    """消息结构"""
    message_id: str
    from_agent: str
    to_agent: str
    content: Any
    timestamp: int
    topic: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "content": self.content,
            "timestamp": self.timestamp,
            "topic": self.topic,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(
            message_id=data["message_id"],
            from_agent=data["from_agent"],
            to_agent=data["to_agent"],
            content=data.get("content"),
            timestamp=data["timestamp"],
            topic=data.get("topic"),
        )


class MessageBus:
    """
    消息总线 - 发布/订阅模式
    
    Features:
    - 发布/订阅模式
    - 点对点消息传递
    - 消息队列管理
    - 持久化支持（通过 db.py）
    """
    
    def __init__(self, persist: bool = True):
        """
        初始化消息总线
        
        Args:
            persist: 是否持久化到数据库
        """
        self.persist = persist
        # 订阅者: topic -> list of callbacks
        self._subscribers: dict[str, list[Callable[[Message], None]]] = defaultdict(list)
        # Agent 消息队列: agent_id -> Queue
        self._agent_queues: dict[str, Queue] = defaultdict(Queue)
        # 使用 RLock 替代 Lock，支持同一线程重入
        self._lock = threading.RLock()
        
        # 延迟导入 db，避免循环依赖
        if self.persist:
            from db import save_message, get_pending_messages, mark_message_delivered
    
    def publish(
        self,
        topic: str,
        content: Any,
        from_agent: str = "system",
        to_agent: str = "*",
    ) -> str:
        """
        发布消息到指定主题
        
        Args:
            topic: 消息主题
            content: 消息内容
            from_agent: 发送方 Agent ID
            to_agent: 接收方 Agent ID（"*" 表示广播）
        
        Returns:
            message_id
        """
        message_id = self._generate_message_id()
        message = Message(
            message_id=message_id,
            from_agent=from_agent,
            to_agent=to_agent,
            content=content,
            timestamp=int(time.time() * 1000),
            topic=topic,
        )
        
        # 持久化
        if self.persist:
            from db import save_message
            save_message(message.to_dict())
        
        # 分发给订阅者 - 使用临时副本避免锁内回调（防止死锁）
        with self._lock:
            callbacks = list(self._subscribers.get(topic, []))
            # 如果是点对点消息，加入目标 Agent 队列
            if to_agent != "*":
                self._agent_queues[to_agent].put(message)
        
        # 在锁外执行回调，避免死锁风险
        for callback in callbacks:
            try:
                callback(message)
            except Exception as e:
                print(f"[MessageBus] Callback error for {topic}: {e}")
        
        return message_id
    
    def subscribe(
        self,
        agent_id: str,
        topic: str,
        callback: Callable[[Message], None]
    ) -> None:
        """
        订阅主题
        
        Args:
            agent_id: 订阅者 Agent ID
            topic: 订阅主题
            callback: 消息回调函数
        """
        with self._lock:
            self._subscribers[topic].append(callback)
    
    def unsubscribe(
        self,
        agent_id: str,
        topic: str,
        callback: Optional[Callable[[Message], None]] = None
    ) -> None:
        """
        取消订阅
        
        Args:
            agent_id: 订阅者 Agent ID
            topic: 订阅主题
            callback: 指定回调（None 则移除该 agent 的所有订阅）
        """
        with self._lock:
            if callback:
                try:
                    self._subscribers[topic].remove(callback)
                except ValueError:
                    pass
            else:
                # 移除该 agent 的所有订阅（需要 callback 关联 agent_id）
                pass
    
    def send_message(
        self,
        from_agent: str,
        to_agent: str,
        content: Any,
        topic: Optional[str] = None
    ) -> str:
        """
        点对点发送消息
        
        Args:
            from_agent: 发送方 Agent ID
            to_agent: 接收方 Agent ID
            content: 消息内容
            topic: 可选主题
        
        Returns:
            message_id
        """
        message_id = self._generate_message_id()
        message = Message(
            message_id=message_id,
            from_agent=from_agent,
            to_agent=to_agent,
            content=content,
            timestamp=int(time.time() * 1000),
            topic=topic,
        )
        
        # 持久化
        if self.persist:
            from db import save_message
            save_message(message.to_dict())
        
        # 加入目标 Agent 队列
        with self._lock:
            self._agent_queues[to_agent].put(message)
        
        return message_id
    
    def receive_messages(
        self,
        agent_id: str,
        limit: int = 10
    ) -> list[Message]:
        """
        接收消息（非阻塞）
        
        Args:
            agent_id: Agent ID
            limit: 最多接收数量
        
        Returns:
            消息列表
        """
        messages = []
        seen_ids = set()
        
        # 如果开启了持久化，从数据库加载未投递消息
        if self.persist:
            from db import get_pending_messages
            pending = get_pending_messages(agent_id, limit=limit)
            for msg_dict in pending:
                msg = Message.from_dict(msg_dict)
                if msg.message_id not in seen_ids:
                    messages.append(msg)
                    seen_ids.add(msg.message_id)
        
        # 从内存队列获取
        queue = self._agent_queues.get(agent_id)
        if queue:
            while len(messages) < limit:
                try:
                    msg = queue.get_nowait()
                    if msg.message_id not in seen_ids:
                        messages.append(msg)
                        seen_ids.add(msg.message_id)
                except:
                    break
        
        # 标记为已投递
        if self.persist and messages:
            from db import mark_message_delivered
            for msg in messages:
                mark_message_delivered(msg.message_id)
        
        return messages
    
    def get_queue_size(self, agent_id: str) -> int:
        """获取 Agent 消息队列大小"""
        queue = self._agent_queues.get(agent_id)
        return queue.qsize() if queue else 0
    
    def clear_queue(self, agent_id: str) -> None:
        """清空 Agent 消息队列"""
        with self._lock:
            queue = self._agent_queues.get(agent_id)
            if queue:
                while not queue.empty():
                    try:
                        queue.get_nowait()
                    except:
                        break
    
    def _generate_message_id(self) -> str:
        """生成消息 ID"""
        import uuid
        return f"msg-{int(time.time())}-{uuid.uuid4().hex[:8]}"


# 全局单例与线程锁
_global_bus: Optional[MessageBus] = None
_bus_lock = threading.RLock()  # 使用 RLock 替代 Lock


def get_message_bus() -> MessageBus:
    """获取全局消息总线实例
    
    使用 double-checked locking 模式确保线程安全。
    """
    global _global_bus
    if _global_bus is None:
        with _bus_lock:
            # Double-check after acquiring lock
            if _global_bus is None:
                _global_bus = MessageBus(persist=True)
    return _global_bus


if __name__ == "__main__":
    # 测试代码
    bus = MessageBus(persist=False)
    
    received = []
    
    def on_alert(msg: Message):
        print(f"[ALERT] {msg.from_agent} -> {msg.to_agent}: {msg.content}")
        received.append(msg)
    
    # 订阅
    bus.subscribe("agent-1", "alert", on_alert)
    
    # 发布
    msg_id = bus.publish("alert", {"type": "test"}, from_agent="system")
    print(f"Published: {msg_id}")
    
    # 点对点
    msg_id2 = bus.send_message("system", "agent-2", {"task": "hello"})
    msgs = bus.receive_messages("agent-2")
    print(f"Agent-2 received: {len(msgs)} messages")
    
    print(f"Total alerts received: {len(received)}")
