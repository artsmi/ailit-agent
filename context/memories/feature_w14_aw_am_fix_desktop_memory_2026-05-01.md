# W14 AW↔AM: SoT, SLA RPC, тестовая изоляция (fix/desktop_memory)

**Связь:** см. [`feature_uc2_4_broker_memory_inject_task_2_1_2026-04-30.md`](feature_uc2_4_broker_memory_inject_task_2_1_2026-04-30.md) (UC 2.4 / G4), [`../proto/broker-memory-work-inject.md`](../proto/broker-memory-work-inject.md), [`../proto/runtime-event-contract.md`](../proto/runtime-event-contract.md).

## Факты

1. **SoT** для решений AgentWork по memory-path — `payload.agent_memory_result` (`agent_memory_result.v1`). `memory_slice` — проекция совместимости, не задаёт continuation/cap/timeout-политику.
2. **SLA RPC** AW→AM: одно значение `memory.runtime.agent_memory_rpc_timeout_s` (merged config) на клиенте Work (`_BrokerServiceClient` для `memory.query_context`), на broker (`svc_timeout` для worker `AgentMemory`) и в `agent_memory_ailit_config.agent_memory_rpc_timeout_s` (default 120 с, clamp 5–3600).
3. **Тесты:** autouse `isolate_ailit_test_artifacts` сбрасывает `AILIT_WORK_ROOTS` и `AILIT_KB_NAMESPACE` до выставления `AILIT_WORK_ROOT`, чтобы не протекал `primary_work_root()` между тестами после in-process реестра AgentWork.

**Оглавление:** [`../INDEX.md`](../INDEX.md).
