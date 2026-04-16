from __future__ import annotations

from packages.kernel.events.bus import EventEnvelope, InMemoryEventBus


def test_in_memory_event_bus_publishes_to_subscribers_and_keeps_history() -> None:
    bus = InMemoryEventBus()
    received: list[EventEnvelope] = []

    unsubscribe = bus.subscribe(received.append)
    bus.publish("work_item.created", {"workItemId": "wi_001"})
    bus.publish("context_pack.created", {"packId": "ctx_001"})

    assert [event.event_type for event in received] == [
        "work_item.created",
        "context_pack.created",
    ]
    assert [event.event_type for event in bus.history()] == [
        "work_item.created",
        "context_pack.created",
    ]

    unsubscribe()
    bus.publish("agent_run.prepared", {"runId": "run_001"})
    assert [event.event_type for event in received] == [
        "work_item.created",
        "context_pack.created",
    ]


def test_in_memory_event_bus_keeps_actor_and_source_metadata() -> None:
    bus = InMemoryEventBus()

    envelope = bus.publish(
        "work_item.created",
        {"workItemId": "wi_001"},
        source="kernel",
        actor_id="system:kernel",
        actor_type="system",
    )

    assert envelope.source == "kernel"
    assert envelope.actor_id == "system:kernel"
    assert envelope.actor_type == "system"
