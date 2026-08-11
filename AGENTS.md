# AGENTS.md — Mapa do Aluguel

## Missão

Evoluir o Mapa do Aluguel como agregador confiável de imóveis para locação,
começando pelo Vale do Aço e permitindo expansão gradual para outras regiões.
O produto organiza ofertas públicas e direciona o usuário à fonte original; não
presuma intermediação imobiliária.

## Fontes oficiais do projeto

Leia antes de decisões estruturais:

- `docs/PRODUCT.md`: visão, escopo e regras de negócio.
- `docs/ARCHITECTURE.md`: estado atual, arquitetura-alvo e invariantes.
- `docs/ROADMAP.md`: ordem de implementação e gates.
- `docs/WORKSTREAMS.md`: responsabilidades e limites entre especialistas.
- `docs/adr/`: decisões arquiteturais aceitas.

Se código e documentação divergirem, registre a divergência e corrija a fonte
afetada dentro do escopo da tarefa. Não invente comportamento ausente.

## Regras de trabalho

- Preserve alterações locais e trabalho de outros chats ou worktrees.
- Antes de editar, verifique `git status`, branch, worktrees e testes relevantes.
- Prefira mudanças pequenas, reversíveis e acompanhadas de testes.
- Não permita que trabalhos paralelos editem os mesmos arquivos.
- O orquestrador mantém a visão global e sintetiza o resultado; especialistas
  recebem tarefas delimitadas com arquivos permitidos e critérios de aceitação.
- Não crie novos agentes, serviços, dependências ou abstrações sem necessidade
  concreta para o objetivo atual.

## Limites de aprovação

Análises e diagnósticos autorizam somente leitura e validações não destrutivas.
Pedidos de construção ou correção autorizam mudanças locais e testes dentro do
escopo. Exija confirmação explícita antes de:

- publicar, fazer merge ou enviar mudanças para produção;
- excluir dados ou executar migração irreversível;
- alterar DNS, comprar serviços ou criar custo recorrente;
- enviar mensagens, posts ou dados para sistemas externos;
- ampliar materialmente o escopo solicitado.

## Dados, coleta e compliance

- Prefira API ou feed permitido, depois HTTP estruturado e só então Playwright.
- Nunca contorne login, CAPTCHA, bloqueio técnico ou controle de acesso.
- Respeite `robots.txt`, termos aplicáveis, limites e política registrada da fonte.
- Toda configuração aprendida deve ser validada; baixa confiança vai à quarentena.
- Preserve fonte, URL original, horário da coleta e evidência de qualidade.
- Não apague histórico de imóveis; registre mudança de estado ou inatividade.
- Não versione segredos, bancos administrativos, checkpoints, logs privados ou
  dados pessoais desnecessários.
- Horários operacionais usam `America/Sao_Paulo`.

## Arquitetura e publicação

- O site público não deve executar crawlers no próprio processo em produção.
- Painel administrativo, workers, API e site público possuem ciclos de vida
  separados, ainda que a migração seja incremental.
- IA é fallback para ambiguidades; regras determinísticas cuidam do fluxo comum.
- Toda publicação deve ocorrer por branch e pull request. Nunca faça push direto
  para `main` por automação do produto.

## Validação mínima

Após mudanças Python, execute:

```powershell
py -3.11 -m compileall -q .
py -3.11 -m unittest discover -s tests -v
```

Quando a tarefa tocar interface ou coleta real, acrescente validação funcional
proporcional ao risco. Não declare sucesso apenas com teste sintético.

## Definição de concluído

Uma tarefa termina quando o escopo foi atendido, testes relevantes passaram,
alterações do usuário foram preservadas, riscos foram relatados e a documentação
afetada foi atualizada. Publicação continua pendente até autorização explícita.
