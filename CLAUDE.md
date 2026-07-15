# Memória do projeto: imoveis_scraper

## Objetivo

Construir um agregador em Python de imóveis para aluguel de imobiliárias de Ipatinga, MG. A aplicação coleta anúncios de sites distintos, normaliza os dados, armazena-os e os exibe em uma interface única com busca e filtros.

O projeto é usado em Windows e Linux/Ubuntu. Considere que o Git via terminal ainda é um fluxo novo para o mantenedor; explique comandos de forma objetiva e segura quando forem necessários.

## Estado conhecido

- O scraper já foi funcional e publicado no Streamlit Community Cloud.
- Sete fontes já foram configuradas: Oliveira Imóveis, Cirsa Imóveis, Certa Imóveis, JF Corretor, Imobiliária Realize, Correta Imóveis MG e Allex Imóveis.
- Há trabalho em andamento para criar um detector automático de seletores CSS, tanto como CLI quanto como parte de um painel administrativo em Streamlit.
- Também houve um pipeline para baixar e filtrar dados públicos de CNPJ e descobrir imobiliárias locais por CNAE.

## Arquitetura e ferramentas

- Scraping: Playwright com Chromium.
- Configuração por site: `sites_config.yaml`. Todo o comportamento específico por imobiliária deve permanecer configurável, incluindo paginação, seletores, regex e ações iniciais.
- Armazenamento: SQLite, via `db.py`.
- Geocodificação: Nominatim/OpenStreetMap, via `geocode.py`.
- Agendamento: APScheduler, via `scheduler_runner.py`; execução a cada seis horas e diariamente às 09:10.
- Normalização de tipos: `tipos.py` (por exemplo, kitnet/studio/quitinete para formas canônicas).
- Interface: Streamlit em `app.py`, com grade de cards, filtros laterais e mapa Folium.
- Deploy: Streamlit Community Cloud; dependências do sistema em `packages.txt`.
- Dados CNPJ: espelho casadosdados.com.br. Arquivos usam nomes como `Cnaes.zip`, `Municipios.zip` e `Empresas0.zip`–`Empresas9.zip`. CNAEs relevantes: 6810201, 6810202, 6821801, 6821802 e 6822600.

## Próximas prioridades

1. Finalizar e integrar o pacote `detector/` ao projeto principal.
2. Criar o painel administrativo Streamlit para revisar e salvar configurações detectadas.
3. Conciliar o esquema assumido pelo detector para `sites_config.yaml` com o esquema real. O ponto central de ajuste é `_formatar_bloco_site()` em `yaml_manager.py`.
4. Usar o conjunto de CNPJs, se necessário, para encontrar novas imobiliárias.

## Padrões das fontes já analisadas

- Oliveira e Cirsa: Universal Software; conteúdo renderizado por JavaScript e paginação por botão.
- JF Corretor: Code49; campos diretos `tipo` e `address`.
- Realize: WordPress; paginação por URL em `/page/{pagina}/`.
- Allex: ImóvelOffice; endereço dedicado no formato `Bairro - Cidade`.
- Correta Imóveis: cards `.work`, com seletores `nth-of-type`.
- Certa Imóveis: usar diretamente `/imoveis/aluguel`; o formulário AJAX da página inicial não foi confiável.

## Lições e cuidados

- Se um seletor encontrar versões oculta e visível de um elemento, percorra todas as correspondências e clique somente na visível.
- Na detecção de card raiz, a maior repetição pode apontar para nós folha, como `span.preco`. Exija pelo menos três descendentes para reduzir falsos positivos.
- O bairro é o campo de menor confiança: não há padrão textual robusto; priorize palavras-chave nos nomes de classes CSS.
- O detector deve usar heurísticas genéricas — agrupamento por assinatura tag+classe, repetição, presença de preço e quantidade de descendentes — e não depender de uma plataforma específica.
- Sempre informe `encoding='utf-8'` ao ler arquivos.
- No Windows, o OneDrive pode manter arquivos abertos. Para exclusões, feche os arquivos explicitamente e use tentativas sequenciais com espera progressiva.
- Em Streamlit Cloud, nomes de pacotes Linux podem variar (por exemplo, `libgdk-pixbuf-2.0-0` e sufixos `t64` no Debian trixie).
- O fluxo para adicionar sites é: obter HTML de depuração, analisar seletores, cadastrar a configuração em `sites_config.yaml` e validar a extração.
