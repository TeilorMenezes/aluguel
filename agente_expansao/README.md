# Agente de Expansão Imobiliária

Painel administrativo local, separado do site público, para descobrir e validar
novas fontes de imóveis para aluguel.

## Instalação no Windows

Abra o PowerShell na pasta do projeto e execute:

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Iniciar

Dê dois cliques em `INICIAR_AGENTE.bat`, que fica na pasta principal do
projeto. Também é possível abrir o PowerShell na pasta principal e rodar:

```powershell
powershell -ExecutionPolicy Bypass -File .\iniciar_agente.ps1
```

O navegador abre em `http://127.0.0.1:8502`. Mantenha o terminal aberto enquanto
usa o aplicativo e pressione `Ctrl+C` para encerrar.

## Uso recomendado

1. Em **Mapear**, escolha estado, região ou cidade e inicie a descoberta. Sites
   que já estejam no `sites_config.yaml`, no banco original ou no snapshot
   público são desconsiderados.
2. Em **Revisar**, inspecione cada candidato com JavaScript.
3. Quando a detecção falhar, abra **Ensinar manualmente**. Navegue até a
   listagem e clique em card, link, título, preço e imagem.
4. Em **Raspar e visualizar**, escolha todas as imobiliárias ou somente algumas
   e execute a coleta robusta local.
5. Confira erros, quantidades, qualidade e a amostra visual dos anúncios.
6. Prepare uma **substituição completa** ou uma **atualização parcial**. Também
   é possível raspar todas e publicar somente as fontes escolhidas.
7. Em **Publicar**, confirme a criação do pull request do banco público.

Publicar exige [GitHub CLI](https://cli.github.com/) autenticado com `gh auth
login`. A ação cria somente uma proposta para revisão; não faz merge e não
altera produção diretamente.

## Bancos separados

- `agente_expansao.db`: candidatos, correções, histórico e erros; nunca é enviado.
- `coleta_local.db`: resultado robusto da raspagem no computador.
- `proposta_publica/imoveis.db`: snapshot mínimo e validado mostrado na prévia.
- `public_data/imoveis.db`: snapshot que o site passa a usar depois do merge.

O snapshot público contém somente dados já públicos dos anúncios. O Streamlit
público não executa raspagem: ele lê exclusivamente o snapshot aprovado. Quando
o checksum do manifesto muda após um merge, o banco efêmero anterior é
substituído atomicamente.

## Capacidade e paginação automáticas

Na coleta local, o agente mede CPU e RAM antes de cada lote. Fontes com navegador
recebem até o limite calculado para o computador naquele momento; APIs podem usar
mais tarefas simultâneas. Se CPU passar de 88–95% ou a memória livre ficar abaixo
de 2–3 GB, a concorrência diminui automaticamente.

Sites configurados sem paginação são examinados em busca de botão “carregar
mais”, próxima página, parâmetros `page`/`pagina`, rolagem infinita e filtros de
cidade, bairro, tipo ou preço. O agente mede URLs novas após cada ação, acumula
cards mesmo em listas virtualizadas e salva a estratégia aprovada em
`data/selectors_override.yaml`.

Quando duas ou mais páginas de uma API GET estável são observadas, o agente
aprende o modelo da URL e tenta reutilizá-lo na próxima coleta. JSON estruturado
e fragmentos HTML são aceitos. Se a API não produzir anúncios novos, a coleta
volta automaticamente ao botão ou navegador que funcionava antes.

Uma coleta interrompida mantém `coleta_local.working.db`. Na execução seguinte,
o painel oferece retomar as imobiliárias pendentes ou descartar esse progresso.
O histórico de estratégias aprendidas, reutilizadas e rejeitadas fica somente em
`data/strategy_history.jsonl`.

Na aba **Ensinar manualmente**, além dos cinco campos do card, o administrador
escolhe visualmente entre descoberta automática, botão “carregar mais”, rolagem,
próxima página, filtros ou página única. Nenhum DevTools é necessário.

## Testes

```powershell
python -m unittest discover -s tests -v
```

Consulte `ARQUITETURA.md` para decisões de segurança e pontos de extensão de IA.
