# Package 1 Acceptance

## Scope

- Event actor fields on `Event` and `AuditEvent`
- Kernel `InMemoryEventBus` to legacy `EventManager` bridge
- `WorkItemService` standard domain event publication
- Structured `work_item.status_changed` payload with `oldStatus/newStatus`

## Commands

```bash
pytest tests/test_event_manager.py tests/test_kernel_event_bus.py tests/test_work_item_service.py tests/test_runtime_state.py tests/test_release_worker.py tests/test_incident_worker.py tests/test_console_work_items_service.py -v
python3 scripts/package_1_acceptance.py
```

## Expected

- Event JSON contains `actorId` / `actorType`
- `EventManager` history contains:
  - `work_item.created`
  - `context_pack.created`
  - `plan.requested`
  - `work_item.status_changed`
- Bridged work item events carry:
  - `source = "kernel.work_items"`
  - `actorId = "system:kernel"`
  - `actorType = "system"`
- `work_item.status_changed` payload contains:
  - `workItemId`
  - `oldStatus`
  - `newStatus`
  - `qualityRunId`

## Breaking Change Notice

- `work_item.status_changed` event payload no longer exposes the legacy top-level `status` field.
- Consumers must read `oldStatus` / `newStatus` instead.
- This package only guarantees backward compatibility for the coarse `EventType` envelope, not for the old status payload shape.

## Manual Notes

- Run the script with `python3`; this environment does not expose a `python` alias.
- The acceptance script self-injects the repository root into `sys.path`, so it can be run directly from the repo root without extra `PYTHONPATH` setup.
