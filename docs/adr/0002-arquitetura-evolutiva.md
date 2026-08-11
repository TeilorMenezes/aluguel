# ADR 0002 — Arquitetura evolutiva

- Status: aceito
- Data: 2026-08-11

## Contexto

O MVP concentra site, administração, agendamento, coleta e SQLite no mesmo
projeto Streamlit. Há valor funcional que deve ser preservado, mas o acoplamento
impede operação confiável e evolução de SEO, histórico e escala.

## Decisão

Adotar migração incremental para monólito modular com processos separados para
site público, administração, API e workers. PostgreSQL é o destino do banco
operacional; o snapshot SQLite permanece como ponte, não arquitetura final.

Não haverá reescrita total. Cada limite será extraído com compatibilidade,
testes, migração reversível e gate documentado.

## Consequências

- O Streamlit pode continuar temporariamente como administração.
- O worker e o agendamento sairão do processo público antes da migração visual.
- O histórico será introduzido antes dos indicadores.
- Novas features não justificam furar a ordem do roadmap.
