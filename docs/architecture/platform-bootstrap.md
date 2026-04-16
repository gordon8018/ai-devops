# Platform Bootstrap

This bootstrap slice introduces the first platform-native architecture surface:

- `packages/shared/domain` for first-class entities such as `WorkItem`, `ContextPack`, and `AgentRun`
- `packages/context/packer` for structured context assembly
- `packages/kernel/events` and `packages/kernel/storage` for the control-plane backbone
- `apps/console_api` for the initial WorkItem-facing application service
- `orchestrator/api/work_items.py` as the compatibility HTTP surface while the dedicated console API grows

The existing `orchestrator/bin` flow remains available. Legacy task inputs are translated into `WorkItem + ContextPack` before plan generation so that scoped tasks preserve their executable contract.
