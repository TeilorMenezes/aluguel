# Arquitetura do Agente de Expansão Imobiliária

## Objetivo e isolamento

O aplicativo roda somente em `127.0.0.1`, usa o banco
`agente_expansao/data/agente_expansao.db` e não lê nem grava o banco público de
imóveis. O Streamlit público continua tendo `app.py` como entrada; este painel
tem entrada própria em `agente_expansao/app.py`.

## Fluxo

1. **Mapeamento:** a API de Localidades do IBGE fornece estados, regiões
   geográficas imediatas e municípios.
2. **Descoberta determinística:** consultas públicas localizam domínios
   candidatos, removem portais e redes sociais e procuram uma página de aluguel.
3. **Inspeção JavaScript:** Playwright abre Chromium, espera a renderização e
   entrega o DOM final ao detector de cards.
4. **Validação:** regras medem título, preço, imagem, link, links únicos e sinais
   de que a página é realmente de aluguel.
   A escolha de cards usa seletores estáveis e penaliza wrappers genéricos; links
   de favorito, comparação e paginação perdem prioridade. Imagens podem vir de
   `img`, `picture`, atributos lazy, `srcset` ou `background-image`.
5. **Revisão:** baixa confiança ou validação incompleta vai para quarentena.
   Confiança alta vai para revisão, nunca para publicação automática.
6. **Aprendizado:** correções manuais ficam no banco local, associadas à
   plataforma detectada. Em inspeções futuras da mesma plataforma, os seletores
   aprendidos são aplicados ao DOM renderizado e só vencem a heurística quando a
   validação mede qualidade igual ou superior. O contrato `AmbiguityResolver` e
   o fallback de seletores permitem usar um modelo local ou API somente na faixa
   ambígua. O modelo escolhe candidatos pré-gerados em um pacote higienizado e
   sua resposta nunca vence sem revalidação determinística.
7. **Publicação:** candidatos aprovados geram uma branch `codex/...` e um pull
   request. A branch `main` nunca é escrita diretamente pelo agente.

## Snapshot público

O banco bruto do agente nunca é publicado. `snapshot_publico.py` produz um
SQLite mínimo, com esquema versionado e manifesto JSON contendo checksum,
qualidade e contagem por imobiliária. Há dois modos:

- substituição completa de todo o catálogo;
- atualização parcial, mesclando fontes escolhidas com o snapshot público atual.

O site público copia o snapshot validado para seu banco efêmero somente quando
este ainda não existe. Em seguida, o agendador e a busca natural continuam
funcionando normalmente.

Correções visuais ficam inicialmente em
`agente_expansao/data/selectors_override.yaml`. Ao publicar um snapshot, uma
cópia revisada vai para `public_data/selectors_override.yaml`, que é mesclada
pelo scraper sem apagar o `sites_config.yaml`.

No próprio fluxo de ensino, os cinco seletores obrigatórios e a navegação
aprendida são editáveis antes do salvamento. Um aprendizado persistido é
recarregado ao selecionar a mesma fonte, e qualquer alteração invalida o teste
anterior. Edições persistidas usam gravação atômica e histórico append-only, com
rollback se o registro do histórico falhar. A cópia do override na proposta é
imutável: se o override local divergir, a publicação é bloqueada até gerar
nova prévia.

## Componentes

- `storage.py`: SQLite, histórico, erros, correções e publicações.
- `integrations.py`: adaptador para IBGE, descoberta e detector já existentes.
- `engine.py`: estados do fluxo e política de confiança.
- `publication.py`: prévia YAML e publicação manual em pull request.
- `app.py`: interface administrativa amigável.

## Limites de recursos

O inspetor manual abre um Chromium por vez. A coleta em massa usa um controlador
adaptativo baseado em `psutil`: calcula trabalhadores por CPU lógica e RAM
disponível, reserva ao menos 2 GB para o Windows e reduz o lote sob pressão.
Fontes HTTP/API usam orçamento próprio, maior que fontes Playwright.

A paginação local começa por controles estruturais fortes, testa textos de
continuação, observa URLs de rede do mesmo domínio e recorre à rolagem. O
critério de progresso é sempre a quantidade de URLs de anúncios inéditas. Duas
ações sem crescimento encerram botões; três encerram rolagem. Há também limites
absolutos de ações para evitar loops infinitos.

APIs só são promovidas quando o mesmo padrão GET paginado aparece em pelo menos
duas páginas observadas. A estratégia conserva um fallback de navegador. Uma
resposta que não aumentar o conjunto de URLs é rejeitada, registrada no histórico
local e não pode apagar o catálogo anterior.

Filtros automáticos são limitados a valores realmente publicados em `<select>`
ou links do próprio domínio. O agente não inventa combinações. Card e filtro são
reunidos por URL, com no máximo 60 opções por controle.

O banco de trabalho é também o checkpoint. Cada imobiliária concluída confirma
seus dados e status no SQLite; uma retomada ignora somente status `concluido` e
repete itens interrompidos ou com erro. O banco oficial local só é substituído
quando o processo termina com sucesso.
