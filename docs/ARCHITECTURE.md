# Arquitetura do Mapa do Aluguel

## Estado atual

O repositório contém um MVP funcional e um agente administrativo experimental.

| Componente | Implementação atual |
|---|---|
| Site público | Streamlit em `app.py` |
| Coleta | Playwright/HTTP em `scraper.py` |
| Descoberta | `descobrir_sites.py` e dados públicos de CNPJ |
| Banco | SQLite em `db.py` |
| Agendamento | APScheduler no processo do Streamlit |
| Configuração | `sites_config.yaml` e overrides aprovados |
| Administração avançada | `agente_expansao/` local e separado |
| Snapshot público | `snapshot_publico.py` e `public_data/` |

Essa base é apropriada para validação local, mas site, agendador, coleta e banco
ainda compartilham ciclo de vida. O arquivo público principal também concentra
interface, autenticação e operação.

## Arquitetura-alvo

A migração será incremental para um monólito modular com processos separados:

```text
site público indexável
          |
          v
        API
          |
          v
 PostgreSQL + cache
          ^
          |
 fila de trabalhos <--- painel administrativo
          ^
          |
 workers de descoberta e coleta
```

Limites planejados:

- `public-web`: experiência pública, SEO e leitura de catálogo.
- `admin`: revisão de fontes, quarentena, lotes e auditoria.
- `api`: contratos de consulta e administração autorizada.
- `collector`: descoberta, extração, normalização e qualidade.
- `domain`: regras de imóveis, fontes, revisões e publicação.
- `persistence`: banco, migrações, repositórios e snapshots.
- `operations`: fila, agendamento, métricas, alertas e backups.

Esses limites não exigem reescrita imediata. O código atual será extraído por
fluxo, mantendo compatibilidade até a substituição completa.

## Modelo de dados conceitual

- `sources`: identidade, domínio, política, status e risco da fonte.
- `source_strategies`: seletores, APIs, paginação, filtros, versão e confiança.
- `crawl_runs`: início, fim, resultado, volume, erro e evidência.
- `properties`: identidade canônica de um imóvel.
- `listings`: anúncio de um imóvel em uma fonte específica.
- `listing_observations`: preço, disponibilidade e campos observados em cada data.
- `review_queue`: quarentena, motivo, decisão e responsável.
- `publication_batches`: conteúdo proposto, validação, aprovação e destino.
- `audit_events`: ações administrativas relevantes.

O histórico é append-only para observações. Uma coleta não apaga observações
anteriores. Listings podem ficar inativos, mas continuam consultáveis para
auditoria e indicadores.

## Invariantes técnicos

- O worker nunca escreve diretamente na interface pública.
- Publicação exige lote validado e aprovação explícita.
- Snapshot público contém apenas o contrato mínimo documentado.
- Banco administrativo e banco público são separados.
- Estratégia aprendida conserva fallback e histórico de validação.
- Uma resposta vazia não promove estratégia nem remove catálogo anterior.
- Toda execução recebe identificador e timestamps em `America/Sao_Paulo` ou UTC
  com conversão explícita na apresentação.
- Segredos entram por ambiente ou gerenciador apropriado, nunca pelo Git.

## Migração incremental

1. Consolidar e versionar o agente experimental.
2. Isolar contratos de domínio e persistência do Streamlit.
3. Adicionar histórico de observações sem remover o banco atual.
4. Separar worker e agendador do processo público.
5. Introduzir PostgreSQL e migrações com execução paralela controlada.
6. Expor API de leitura estável.
7. Migrar a experiência pública para frontend indexável.
8. Manter o Streamlit como administração temporária até sua substituição.

## Restrições atuais conhecidas

- A autenticação administrativa usa uma senha compartilhada.
- O agendamento ainda está acoplado ao Streamlit e não declara fuso.
- Dependências usam limites mínimos, não um lock reproduzível.
- Cobertura de testes é focada no backend e não mede UX ou coleta real contínua.
- O snapshot SQLite é uma ponte operacional, não o banco final de produção.
