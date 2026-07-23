# Scraper de Imóveis para Alugar

Aplicação Python que varre sites de imobiliárias configurados por você,
guarda os imóveis para aluguel em um banco SQLite, e mostra tudo numa
página Streamlit com filtros de preço/bairro e um mapa interativo.

## 1. Instalação

```bash
pip install -r requirements.txt
playwright install chromium
```

## 2. ⚠️ Passo obrigatório: descobrir os seletores CSS dos sites

Os sites que você indicou (`oliveiraimoveis.net` e `cirsa.com.br`) carregam
a lista de imóveis via JavaScript, então preciso saber exatamente qual
elemento HTML representa cada "card" de imóvel, o preço, o bairro, etc.
Isso varia de site para site e só dá pra descobrir olhando a página já
carregada no navegador.

Rode, para cada site:

```bash
python inspect_selectors.py oliveira
python inspect_selectors.py cirsa
```

Isso abre um Chrome de verdade, espera o JS carregar os imóveis, e salva
em `data/debug_<site>.html` e `data/debug_<site>.png`. Com o navegador
aberto (ou o HTML salvo), clique com o botão direito em um card de imóvel
→ **Inspecionar** → identifique:

| O que procurar | Onde preencher no `sites_config.yaml` |
|---|---|
| Elemento que envolve o card inteiro do imóvel | `seletores.card` |
| O link `<a href="...">` do imóvel | `seletores.link` |
| O texto do preço (ex: "R$ 1.200") | `seletores.preco` |
| O texto do bairro (se existir separado) | `seletores.bairro` |
| A `<img>` de destaque do card | `seletores.thumbnail` |
| Um elemento estável que só aparece quando os imóveis já carregaram | `espera_seletor` |

Seletores CSS costumam ser assim: `.card-imovel`, `div.property-card a.link`,
`.preco-card span`. Depois de identificar, edite `sites_config.yaml` e
troque os valores `PREENCHER_...`.

> Assim que você tiver esses seletores, me mande o HTML salvo em
> `data/debug_oliveira.html` / `data/debug_cirsa.html` (ou só os trechos
> dos cards) que eu preencho o `sites_config.yaml` certinho pra você.

## 3. Rodar a aplicação

```bash
streamlit run app.py
```

Isso abre a showpage no navegador. Ao iniciar, a aplicação já agenda:
- uma varredura a cada **6 horas**
- uma varredura fixa todo dia às **9:10**
- e você pode clicar em **"🔄 Atualizar agora"** na barra lateral a qualquer momento

### Fluxo recomendado no computador local

1. Abra `http://localhost:8501` e entre na Administração.
2. Execute **Atualizar agora** para usar o processamento do computador.
3. Descubra novas imobiliárias e revise as rejeitadas na **Quarentena**.
4. Aprove somente os sites que extraírem card, link e preço corretamente.
5. Na aba **Publicar no site**, clique em **Publicar configurações no GitHub**.

O botão cria um commit apenas com `sites_config.yaml` e
`detector_patterns.yaml`; banco de dados, quarentena e senhas nunca são
incluídos. Depois do deploy, o site publicado coleta automaticamente as
integrações que ainda não possuem imóveis.

## 4. Estrutura do projeto

```
imoveis_scraper/
├── app.py                 # Interface Streamlit (showpage, filtros, mapa)
├── scraper.py              # Motor de varredura (Playwright)
├── scheduler_runner.py     # Agendamento (6h + horário fixo + manual)
├── geocode.py               # bairro -> latitude/longitude (Nominatim)
├── db.py                    # Banco SQLite
├── inspect_selectors.py     # Ferramenta para descobrir seletores CSS
├── sites_config.yaml        # Configuração dos sites e seletores
├── requirements.txt
└── data/
    ├── imoveis.db            # Banco gerado automaticamente
    └── debug_*.html/png      # Gerado pelo inspect_selectors.py
```

## 5. Adicionando um novo site no futuro

Basta adicionar um novo bloco em `sites_config.yaml` dentro de `sites:`,
seguindo o mesmo formato, e preencher os seletores usando o mesmo processo
do passo 2. Não é necessário mexer no código.

## 6. Descobrir imobiliárias do Vale do Aço

Primeiro gere uma única base de CNPJ para os quatro municípios centrais:

```bash
python baixar_imobiliarias_cnpj.py --municipio IPATINGA --municipio TIMOTEO --municipio "CORONEL FABRICIANO" --municipio "SANTANA DO PARAISO"
```

Em seguida, informe o CSV gerado ao descobridor:

```bash
python descobrir_sites.py data/imobiliarias_cnpj.csv
```

Ele consulta resultados públicos para cada empresa ativa, descarta redes sociais e portais de anúncios e salva os domínios mais prováveis em `data/sites_candidatos_vale_aco.csv`. Revise a lista e cadastre cada URL pela aba **Administração** do app.

## 7. Observações importantes

- **Respeite os Termos de Uso** dos sites das imobiliárias e o arquivo
  `robots.txt` de cada um antes de rodar varreduras automatizadas com
  frequência. Um intervalo de 6h é razoável, mas ajuste conforme
  necessário.
- O geocoding usa o **Nominatim** (gratuito), que tem limite de ~1
  requisição por segundo — por isso os resultados ficam em cache no banco
  e a primeira varredura pode demorar um pouco mais.
- Se um imóvel não tiver bairro identificável nem no card nem no
  título/URL, ele fica no banco sem coordenadas e não aparece no mapa
  (mas continua aparecendo na lista).
