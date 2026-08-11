# Frentes de trabalho e especialistas

## Modelo de coordenação

O orquestrador mantém a responsabilidade pelo resultado final. Especialistas
atuam como capacidades delimitadas. Eles não ampliam escopo, publicam ou tomam
decisões irreversíveis sem autorização.

Cada delegação deve conter objetivo, contexto, arquivos permitidos, arquivos
proibidos, critérios de aceitação, validação e formato do relatório.

## Frentes principais

| Frente | Responsabilidade | Não possui |
|---|---|---|
| Plataforma e Dados | domínio, banco, migrações, API e histórico | scraping e UX |
| Coleta e Fontes | descoberta, estratégias, qualidade e quarentena | publicação final |
| Frontend, UX e SEO | experiência pública, acessibilidade e indexação | regras de coleta |
| Qualidade e Release | testes, CI, regressão e parecer de release | novas regras de negócio |
| Segurança e Compliance | autenticação, segredos, risco e política de fontes | parecer jurídico definitivo |
| DevOps e Confiabilidade | ambientes, workers, filas, backup e observabilidade | produto e conteúdo |
| Analytics | indicadores, amostras e contratos analíticos | alteração de dados brutos |
| Growth e Conteúdo | SEO editorial, marca e aquisição | publicação sem aprovação |

## Concorrência

Trabalhos podem ocorrer em paralelo somente quando:

- editam conjuntos de arquivos diferentes;
- não dependem da decisão ainda pendente do outro;
- possuem contratos de entrada e saída definidos;
- a ordem de integração é conhecida.

Mudanças no esquema de dados, contratos compartilhados, `app.py`, `scraper.py`,
`sites_config.yaml` e workflows de publicação exigem um único proprietário por
vez. Revisão pode ser paralela; escrita, não.

## Handoff obrigatório

O especialista encerra com:

1. resultado e decisão tomada;
2. arquivos alterados;
3. testes e evidências;
4. riscos e limitações;
5. dependências para outra frente;
6. recomendação de integrar, revisar ou bloquear.

O orquestrador verifica o handoff, resolve divergências e somente então apresenta
uma conclusão ao usuário.
