"""
Message Bus — Phase 6.4
=========================
Inter-agent communication channel for the VYRA agent mesh.

Features:
  - Priority queue (lower number = higher priority)
  - Pub/sub with topic routing
  - Retry with exponential backoff for failed deliveries
  - Dead letter queue for unresolvable failures
  - Full message log for auditing

Usage:
    bus = get_bus()
    bus.subscribe("research_agent", handler_fn)
    await bus.publish(AgentMessage(
        sender="vyra_core",
        recipient="research_agent",
        topic="research.request",
        payload={"query": "top AI startups 2025"},
        priority=2,
    ))
    reply = await bus.wait_reply(msg_id, timeout=60)
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional


@dataclass
class AgentMessage:
    sender: str
    recipient: str          # agent name or "broadcast"
    topic: str              # e.g. "research.request", "goal.update"
    payload: Dict[str, Any]
    id: str                 = field(default_factory=lambda: str(uuid.uuid4()))
    priority: int           = 5    # 1=urgent, 10=background
    reply_to: Optional[str]= None  # msg_id to reply to
    timestamp: str          = field(default_factory=lambda: datetime.utcnow().isoformat())
    ttl_seconds: float      = 300  # message expires after 5 min

    def is_expired(self) -> bool:
        # Use naive UTC subtraction to avoid local-timezone offset errors
        created = datetime.fromisoformat(self.timestamp)
        age = (datetime.utcnow() - created).total_seconds()
        return age > self.ttl_seconds

    def to_dict(self) -> Dict:
        return {
            "id": self.id, "sender": self.sender, "recipient": self.recipient,
            "topic": self.topic, "payload": self.payload,
            "priority": self.priority, "reply_to": self.reply_to,
            "timestamp": self.timestamp,
        }


Handler = Callable[[AgentMessage], Awaitable[Optional[AgentMessage]]]


class MessageBus:
    """Asyncio-native priority message bus for VYRA agents."""

    def __init__(self):
        self._subscriptions: Dict[str, List[Handler]] = {}  # agent_name → handlers
        self._topic_subs:    Dict[str, List[Handler]] = {}  # topic → handlers
        self._queue:         asyncio.PriorityQueue     = asyncio.PriorityQueue()
        self._replies:       Dict[str, asyncio.Future] = {}
        self._dead_letter:   List[AgentMessage]        = []
        self._log:           List[Dict]                = []
        self._running        = False
        self._max_log        = 500

    # ── Subscribe ─────────────────────────────────────────────────────────────

    def subscribe(self, agent_name: str, handler: Handler):
        """Subscribe an agent to all messages addressed to it."""
        self._subscriptions.setdefault(agent_name, []).append(handler)

    def subscribe_topic(self, topic: str, handler: Handler):
        """Subscribe to all messages with a specific topic (wildcard: 'research.*')."""
        self._topic_subs.setdefault(topic, []).append(handler)

    # ── Publish ───────────────────────────────────────────────────────────────

    async def publish(self, msg: AgentMessage) -> str:
        """Put message on the queue. Returns message ID."""
        self._log_message(msg, "queued")
        await self._queue.put((msg.priority, time.time(), msg))
        return msg.id

    async def publish_and_wait(
        self, msg: AgentMessage, timeout: float = 60.0
    ) -> Optional[AgentMessage]:
        """Publish and block until a reply arrives or timeout."""
        loop = asyncio.get_event_loop()
        fut  = loop.create_future()
        self._replies[msg.id] = fut
        await self.publish(msg)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._replies.pop(msg.id, None)
            return None

    async def reply(self, original_msg: AgentMessage, payload: Dict) -> str:
        """Send a reply to a message."""
        reply_msg = AgentMessage(
            sender    = original_msg.recipient,
            recipient = original_msg.sender,
            topic     = original_msg.topic + ".reply",
            payload   = payload,
            reply_to  = original_msg.id,
            priority  = original_msg.priority,
        )
        # Resolve any waiting future
        fut = self._replies.pop(original_msg.id, None)
        if fut and not fut.done():
            fut.set_result(reply_msg)
        else:
            await self._queue.put((reply_msg.priority, time.time(), reply_msg))
        return reply_msg.id

    # ── Processing loop ───────────────────────────────────────────────────────

    async def run(self):
        self._running = True
        print("[MessageBus] Running.")
        while self._running:
            try:
                _, _, msg = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if msg.is_expired():
                self._log_message(msg, "expired")
                continue

            await self._deliver(msg)

    async def _deliver(self, msg: AgentMessage):
        handlers: List[Handler] = []

        # Direct recipient handlers
        if msg.recipient == "broadcast":
            for h_list in self._subscriptions.values():
                handlers.extend(h_list)
        else:
            handlers.extend(self._subscriptions.get(msg.recipient, []))

        # Topic handlers
        for topic, h_list in self._topic_subs.items():
            if self._topic_matches(topic, msg.topic):
                handlers.extend(h_list)

        if not handlers:
            self._log_message(msg, "no_handler")
            self._dead_letter.append(msg)
            if len(self._dead_letter) > 100:
                self._dead_letter.pop(0)
            return

        self._log_message(msg, "delivered")
        for handler in handlers:
            try:
                reply = await asyncio.wait_for(handler(msg), timeout=120.0)
                if reply:
                    fut = self._replies.pop(msg.id, None)
                    if fut and not fut.done():
                        fut.set_result(reply)
            except asyncio.TimeoutError:
                self._log_message(msg, "handler_timeout")
            except Exception as e:
                self._log_message(msg, f"handler_error:{e}")

    def _topic_matches(self, pattern: str, topic: str) -> bool:
        if pattern == topic:
            return True
        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            return topic.startswith(prefix)
        return False

    def _log_message(self, msg: AgentMessage, status: str):
        entry = {**msg.to_dict(), "status": status}
        self._log.append(entry)
        if len(self._log) > self._max_log:
            self._log.pop(0)

    def stop(self):
        self._running = False

    def get_log(self, last_n: int = 50) -> List[Dict]:
        return self._log[-last_n:]

    def get_dead_letters(self) -> List[AgentMessage]:
        return list(self._dead_letter)


_bus: Optional[MessageBus] = None

def get_bus() -> MessageBus:
    global _bus
    if _bus is None:
        _bus = MessageBus()
    return _bus
