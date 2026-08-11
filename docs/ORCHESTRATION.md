# Orquestração dos agentes

## Objetivo

Este chat ou tarefa principal atua como orquestrador do Mapa do Aluguel. Os
agentes em `.codex/agents/` são especialistas sob demanda: ficam disponíveis,
mas só começam a trabalhar quando recebem uma delegação concreta.

Os agentes não substituem os chats antigos. O histórico anterior permanece como
referência; requisitos duráveis devem estar nos arquivos oficiais do projeto.

## Catálogo

| Agente | Usar para | Modo esperado |
|---|---|---|
| `plataforma_dados` | domínio, banco, migrações, API e histórico | análise e implementação |
| `coleta_fontes` | descoberta, scraping, normalização e quarentena | análise e implementação controlada |
| `frontend_ux_seo` | interface pública, acessibilidade e SEO técnico | análise e implementação |
| `qualidade_release` | testes, CI, regressão e parecer de release | revisão independente e testes |
| `seguranca_compliance` | segurança, privacidade e política de fontes | somente leitura |
| `devops_confiabilidade` | workers, ambientes, observabilidade e backup | análise e implementação controlada |
| `analytics_mercado` | métricas, amostras e indicadores | análise e implementação controlada |
| `growth_conteudo` | posicionamento, conteúdo e aquisição | rascunhos; publicação exige aprovação |

O limite local é de três subagentes simultâneos, além do orquestrador. Paralelismo
é indicado principalmente para leitura, auditoria e testes independentes. Escrita
paralela só é permitida quando os arquivos e contratos não se sobrepõem.

## Contrato obrigatório de delegação

Toda delegação deve informar:

1. objetivo e resultado esperado;
2. contexto e decisões já aceitas;
3. arquivos permitidos e arquivos proibidos;
4. dependências e proprietário dos contratos compartilhados;
5. critérios de aceitação;
6. validações obrigatórias;
7. ações externas proibidas ou autorizadas;
8. formato do handoff e momento de retorno.

Exemplo:

```text
Use o agente qualidade_release para revisar a alteração atual.

Objetivo: verificar regressões na inclusão de imóveis com preço sob consulta.
Permitido: leitura do repositório e criação de testes em tests/.
Proibido: alterar app.py, db.py, sites_config.yaml, publicar ou fazer push.
Aceite: reproduzir o comportamento, executar a suíte e classificar os riscos.
Retorno: achados por severidade, testes, arquivos e parecer de release.
```

## Prompt reutilizável do orquestrador

```text
Você é o orquestrador principal do projeto Mapa do Aluguel.

Leia AGENTS.md e os documentos oficiais em docs/ antes de decisões estruturais.
Mantenha a visão global de produto, arquitetura, roadmap, riscos e alterações em
andamento. Use os agentes personalizados de .codex/agents/ apenas para tarefas
independentes e claramente delimitadas.

Antes de delegar, verifique branch, git status, worktrees, arquivos sob posse de
cada frente e dependências entre tarefas. Para cada agente, forneça objetivo,
contexto, arquivos permitidos e proibidos, critérios de aceitação, validações e
formato do handoff. Não permita escrita paralela nos mesmos arquivos ou contratos.

Espere os especialistas necessários, confronte resultados divergentes, valide as
evidências e entregue ao usuário uma conclusão única. O especialista aconselha;
o orquestrador responde pelo resultado integrado.

Não publique, faça merge, push, deploy, exclua dados, crie custos, altere DNS ou
execute ação externa irreversível sem autorização explícita do usuário. Preserve
trabalho existente e informe riscos, limites e pendências com clareza.
```

## Fluxo de execução

1. O orquestrador classifica a tarefa e consulta o roadmap.
2. Define um único proprietário para cada arquivo ou contrato compartilhado.
3. Delega apenas partes independentes e mantém decisões no chat principal.
4. Especialistas devolvem handoffs, não apenas logs ou opiniões soltas.
5. O orquestrador revisa diferenças, testes e riscos.
6. Somente o resultado consolidado é apresentado como decisão do projeto.

Nenhum agente possui autorização permanente para publicar ou agir em sistemas
externos. Essas ações continuam dependendo do pedido explícito do usuário.
