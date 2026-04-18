# Target Platform Interfaces Roadmap

## Назначение

Зафиксировать минимальный roadmap интерфейсов, которые должны появиться по мере реализации платформы.

## Интерфейсы уровня `core runtime`

Должны появиться интерфейсы:

- provider adapter interface;
- tool contract interface;
- session loop interface;
- permission and approval interface;
- usage and cost telemetry interface.

## Интерфейсы уровня `workflow layer`

Должны появиться интерфейсы:

- workflow definition;
- stage transition model;
- execution batch contract;
- artifact lifecycle contract;
- compatibility adapter contract для `ai-multi-agents`.

## Интерфейсы уровня `project layer`

Должны появиться интерфейсы:

- project workflow registration;
- project agent registration;
- project config contract;
- canonical context shortlist contract.

## Интерфейсы внешней интеграции

Должны появиться:

- local monitor data feed;
- runtime snapshot feed;
- project orchestrator integration surface;
- future hybrid-mode runtime switch.

## Практический вывод для `Этапа 1`

На первом этапе эти интерфейсы не нужно реализовывать полностью.  
Нужно зафиксировать саму карту интерфейсов, чтобы следующие этапы не спорили о placement и boundaries.
