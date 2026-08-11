# Roadmap técnico

O roadmap usa gates de qualidade, não datas artificiais. Uma fase só avança
quando seus critérios de saída forem demonstrados.

## Fase 0 — Consolidação

Objetivo: preservar o que já existe e estabelecer uma única direção.

- [x] Auditar chats, repositório e worktree experimental.
- [x] Preservar o Agente de Expansão em branch local revisável.
- [x] Alinhar a branch com a `main` atual.
- [x] Criar regras operacionais em `AGENTS.md`.
- [x] Registrar visão, arquitetura, responsabilidades e decisões.
- [x] Adicionar CI mínimo para compilação e testes.
- [ ] Revisar o diff funcional do agente antes de merge.
- [ ] Criar pull request somente após autorização do usuário.
- [ ] Definir quais partes experimentais entram na primeira integração.

Gate de saída: branch revisada, testes verdes, nenhum dado administrativo
versionado e plano de integração aprovado.

## Fase 1 — Modularização segura

Objetivo: reduzir acoplamento sem interromper o MVP.

- Extrair configuração, autenticação administrativa e inicialização de `app.py`.
- Definir contratos de domínio para fonte, anúncio, coleta e revisão.
- Introduzir migrações idempotentes para o banco atual.
- Unificar publicação somente por branch e pull request.
- Configurar fuso `America/Sao_Paulo` e impedir jobs duplicados.
- Criar testes de integração do snapshot e da inicialização pública.

Gate de saída: site atual operante, módulos com responsabilidades explícitas e
rollback documentado.

## Fase 2 — Histórico e operação separada

Objetivo: tornar a coleta auditável e independente do site.

- Criar observações históricas de preço e disponibilidade.
- Separar worker e agendador do processo Streamlit.
- Adicionar fila, identificador de execução, métricas e alertas.
- Criar painel de saúde das fontes e política por domínio.
- Implementar backup e teste de restauração.

Gate de saída: reiniciar ou suspender o site não interrompe a coleta; nenhuma
coleta vazia apaga dados válidos.

## Fase 3 — Plataforma de produção

Objetivo: preparar domínio próprio, SEO e expansão regional.

- Migrar dados operacionais para PostgreSQL com plano de retorno.
- Expor API estável para catálogo.
- Criar site público indexável por região, bairro, tipo e imóvel.
- Implementar autenticação administrativa com usuários, funções e auditoria.
- Criar ambientes de homologação e produção.

Gate de saída: domínio próprio, publicação reproduzível, monitoramento e
recuperação validados.

## Fase 4 — Produto avançado

Objetivo: ampliar valor somente sobre dados confiáveis.

- Favoritos, alertas, comparação e reporte de inconsistência.
- Deduplicação entre fontes.
- Integrações por feed com parceiros.
- Indicadores para corretores com critérios estatísticos mínimos.
- Experimentação de modelo comercial e expansão nacional.

Gate de saída: métricas de qualidade e uso justificam cada nova capacidade.
