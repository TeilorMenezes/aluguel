# Arquitetura do Mapa do Aluguel

## Estado atual

O repositório contém um MVP funcional e um agente administrativo experimental.

| Componente | Implementação atual |
|---|---|
| Site público | Streamlit em `app.py` |
| Coleta | Playwright/HTTP em `scraper.py`, executado pelo agente local |
| Descoberta | `descobrir_sites.py` e dados públicos de CNPJ |
| Banco | SQLite em `db.py` |
| Agendamento | legado disponível no código, não iniciado pelo site público |
| Configuração | `sites_config.yaml` e overrides aprovados |
| Administração avançada | `agente_expansao/` local e separado |
| Snapshot público | `snapshot_publico.py` e `public_data/` |

Nesta branch, o site público opera em modo somente leitura sobre o snapshot versionado. O
agente local mantém coleta, revisão e publicação em ciclo separado. O código
legado de agendamento ainda existe para remoção incremental, mas não é importado
nem iniciado pelo processo público.

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
- O processo público nunca inicia Playwright, scheduler ou coleta manual.
- Publicação exige lote validado e aprovação explícita.
- Snapshot público contém apenas o contrato mínimo documentado.
- Um checksum novo substitui atomicamente o banco efêmero anterior; o mesmo
  snapshot não é reaplicado em cada rerun.
- Banco administrativo e banco público são separados.
- Cidades exibidas no catálogo são municípios oficiais da referência pública
  versionada do IBGE; grafias equivalentes são consolidadas antes de virar filtro.
- Bairros são evidência da fonte: só aparecem quando associados a uma cidade
  oficial e passam por limpeza, deduplicação tipográfica e validação de conteúdo.
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
- O módulo legado de agendamento ainda existe, embora não seja carregado pelo
  Streamlit público, e ainda não declara fuso.
- Dependências usam limites mínimos, não um lock reproduzível.
- Cobertura de testes é focada no backend e não mede UX ou coleta real contínua.
- O snapshot SQLite é uma ponte operacional, não o banco final de produção.
