# ADR 0003 — Publicação controlada

- Status: aceito
- Data: 2026-08-11

## Contexto

O projeto possui fluxos que enviam configurações diretamente para `main` e um
agente experimental que cria proposta por branch. Publicação direta reduz a
capacidade de revisar dados, testes e mudanças aprendidas automaticamente.

## Decisão

Toda alteração de código, configuração de fonte ou snapshot público será feita
em branch e submetida por pull request. O produto nunca fará merge automático.
Publicação exige confirmação explícita do administrador.

Dados administrativos, quarentena, checkpoints, logs privados e segredos não
podem fazer parte da proposta pública.

## Consequências

- O fluxo atual de push direto será descontinuado na Fase 1.
- Cada lote precisa de manifesto, métricas de qualidade e checksum quando houver
  snapshot.
- Falha nos testes ou baixa qualidade bloqueia a proposta.
