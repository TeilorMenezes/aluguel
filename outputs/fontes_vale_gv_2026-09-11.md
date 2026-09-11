# Expansão de fontes — Vale do Aço e Governador Valadares

Data da validação: 2026-09-11 (America/Sao_Paulo)

## Escopo e método

A planilha `C:\Users\teilo\Downloads\imobiliarias_vale_do_aco_governador_valadares.xlsx` foi lida integralmente e somente para análise. O arquivo original não foi alterado. Nomes e domínios foram normalizados para evitar promover duplicatas, portais ou páginas sociais como fonte oficial.

Cada candidata prioritária foi revalidada no site oficial. A avaliação considerou disponibilidade pública de locações, `robots.txt`, links de termos/privacidade quando expostos, estrutura de descoberta, paginação, separação entre aluguel e venda e cobertura de título, preço de aluguel, tipo, bairro, cidade, URL e foto. Não houve tentativa de contornar login, CAPTCHA, `403`, falha de DNS ou outra restrição.

## Inventário da planilha

| Grupo inicial | Linhas | Decisão |
|---|---:|---|
| Já configuradas ou parcialmente configuradas | 25 | Preservadas; nenhuma fonte considerada correta foi reconfigurada |
| Candidatas novas prioritárias | 32 | 16 ativadas, 2 configuradas inativas e 14 mantidas fora da coleta |
| Candidatas secundárias | 22 | Mantidas para lote futuro; prioridade menor ou rota de locação ainda insuficiente |
| Revisão, indisponibilidade ou bloqueio | 13 | Não ativadas |
| Portal, página social ou ausência de catálogo próprio verificável | 11 | Não ativadas |
| **Total** | **103** | — |

Já existentes: Oliveira, CIRSA, Certa, JF, Realize, Correta, Allex, Diferencial, Portal Imóveis Ipatinga, Moradia, Ferreira, Catedral, M.E., Minas Caixa, Portal Timóteo, Arthuso, Helena, Imóveis Godinho, MG Corretor, Nilton, Pontual, Mercantil, DOMMUS, Delas e Epifânio.

Candidatas secundárias preservadas para outro lote: MyBroker Ipatinga, Lage, JS Imóveis, Paulanayra, Urbe, Márcio Imóveis, Casa Linhares, Perim, Localiza, Leoni, Pimenta, Muratori, Pereira, Open Lote, Actual, Carvalho Negócios, Mafalda, Sobreira, Liderança, Morada, Laura e Realiza.

## Fontes novas ativadas

A contagem abaixo é da execução final em banco SQLite temporário e exclusivo. “Duração” é a medição do smoke funcional individual; a coleta final foi processada em pequenos lotes, por isso seu tempo de parede não é a soma desta coluna.

| Fonte | Estratégia e paginação | Encontrados/persistidos | Bairro | Foto real | Duração | Evidência real comparada |
|---|---|---:|---:|---:|---:|---|
| Total Imobiliária | HTTP estruturado, 1 página, link de locação obrigatório | 12/12 | 100% | 100% | 33,62 s | [anúncio](https://www.totalimob.com.br/4380/imoveis/locacao-apartamento-2-quartos-bom-pastor-santana-do-paraiso-mg) |
| Carneiro Imóveis | HTTP estruturado, 1 página, link de locação obrigatório | 1/1 | 100% | 100% | 109,15 s | [anúncio](https://www.carneiroimob.com.br/854/imoveis/locacao-loja-1-quarto-nazare-coronel-fabriciano-mg) |
| Porta Aberta Imóveis | HTTP estruturado, 1 página, link de locação obrigatório | 1/1 | 100% | 100% | 4,37 s | [anúncio](https://www.portaabertaimoveis.com.br/1916/imoveis/locacao-galpao-residencial-bethania-santana-do-paraiso-mg) |
| Jhessica e Marcelo | HTTP estruturado, 1 página, link de locação obrigatório | 1/1 | 100% | 100% | 26,36 s | [anúncio](https://www.jhessicaemarceloimoveis.com.br/904/imoveis/locacao-casa-3-quartos-giovanini-coronel-fabriciano-mg) |
| UNICOM | HTTP estruturado, páginas `?pagina=N`, parada sem novos IDs | 16/16 | 100% | 100% | 14,08 s | [anúncio](https://www.unicom.imb.br/imovel/3539635/sala-comercial-locacao-timoteo-mg-centro) |
| Druwe Imóveis | HTTP estruturado, 1 página | 9/9 | 88,9% | 100% | 14,99 s | [anúncio](https://www.druweimoveis.com.br/imovel/apartamento-para-alugar-em-ipatinga-canaa-com-3-quartos-90m/A676-397) |
| Vasconcelos Imóveis | HTTP estruturado, páginas `?pagina=N`, parada sem novos IDs | 24/24 | 100% | 100% | 10,57 s | [anúncio](https://www.vasconcelosimoveisgv.com/imovel/1874147/comercial-locacao-governador-valadares-mg-ilha-dos-araujos) |
| Solução Imobiliária | HTTP estruturado, 1 página | 18/18 | 83,3% | 94,4% | 17,60 s | [anúncio](https://www.solucaoimobiliaria.com/imovel/apartamento-1-quarto-santos-dumont-governador-valadares-1-vaga-code-983) |
| Segurança Imóveis | HTTP estruturado, 1 página | 12/12 | 100% | 100% | 5,66 s | [anúncio](https://segurancaimoveisgv.com.br/imovel/10305/casa-7-quartos-centro-governador-valadares/) |
| A Lins Imóveis | HTTP estruturado, 1 página | 12/12 | 100% | 91,7% | 9,05 s | [listagem](https://www.linsimoveisgv.com.br/im%C3%B3vel-estado/locacao/) |
| Bom Negócio GV | HTTP estruturado, página numerada, parada sem novos IDs | 8/8 | 100% | 100% | 24,57 s | [anúncio](https://www.bomnegocioimoveisgv.com.br/imovel/locacao/apartamento/governador-valadares-mg/elvamar/apartamento-com-3-dormitorios-disponivel-para-locacao-no-bairro-elvamar/877013) |
| Imóveis Carvalho | HTTP estruturado, WordPress `/page/N/`, parada sem novos IDs | 13/13 | 100% | 100% | 27,03 s | [anúncio](https://imoveiscarvalho.com.br/property/apartamento-vila-mariana/) |
| Geferson Gomes | HTTP estruturado, 1 página | 14/14 | 100% | 100% | 5,31 s | [anúncio](https://gefersongomesimoveis.com.br/aluguel-apartamento-com-02-quartos-centro-mantena-mg-aw0) |
| Guerrinha Imóveis | HTTP estruturado, parâmetro `pagina`, parada sem novos IDs | 23/23 | 100% | 100% | 77,19 s | [anúncio](https://www.guerrinhaimoveis.com.br/imovel/apartamento-para-aluguel-3-quartos-1-suite-2-vagas-cidade-nobre-ipatinga-mg/261) |
| Predileta Imóveis | HTTP estruturado, parâmetro `pagina`, parada sem novos IDs | 35/35 | 100% | 100% | 66,93 s | [anúncio](https://www.imobiliariapredileta.com.br/imovel/apartamento-com-mobilia/724) |
| Betel Imóveis | endpoint JSON público do próprio domínio, paginação de API | 102/102 | 100% | 100% | 8,70 s | [anúncio](https://www.betelimoveis.com/imovel/apartamento-para-alugar-castanheiras-governador-valadares-mg/3991) |

Todos os 301 registros persistidos tinham URL original, título, preço de aluguel e cidade. A cobertura agregada foi: bairro 297/301 (98,7%) e foto real 299/301 (99,3%). Não houve persistência de preço de venda, condomínio, IPTU, taxa ou pacote como aluguel na amostra final. Os dois registros sem foto real ficaram sem imagem; placeholders conhecidos não foram publicados como fotografia.

Os lotes finais levaram 9,37 s (quatro fontes da plataforma C49), 56,90 s (Druwe e Solução no lote em que a paginação das demais foi diagnosticada), 6,54 s (revalidação de UNICOM e Vasconcelos após link estrito), 72,25 s (Segurança, Lins, Bom Negócio e Carvalho) e 119,61 s (Geferson, Guerrinha, Predileta e Betel). Não houve erro residual nas execuções finais.

## Quarentena e descartes prioritários

| Fonte | Decisão | Evidência/razão |
|---|---|---|
| Gláucia Veras | Configurada inativa | 11 cards reais, mas bairro confiável em somente 18%; localização genérica não deve ser promovida |
| Tataia Imóveis | Configurada inativa | 15 cards reais; bairro 0% e cidade 20%; exige detalhe/localização validada |
| Loccus | Fora da configuração | `robots.txt` bloqueia a rota de listagem; não houve contorno |
| Júnio Imóveis | Fora da configuração | Site oficial sem rota pública de locações confirmada |
| João Damasceno | Fora da configuração | Detector não encontrou cards repetíveis e endpoint presumido retornou erro; confiança insuficiente |
| SEJUR | Fora da configuração | Há cards públicos, mas o título correto do imóvel não pôde ser separado com segurança na listagem |
| Americano | Fora da configuração | Estrutura repetível/confiável não confirmada |
| Carlão | Fora da configuração | Estrutura repetível/confiável não confirmada |
| Sérgio Rocha | Fora da configuração | Link, preço e foto não foram extraídos com precisão suficiente |
| Imóvel Bom | Fora da configuração | Qualidade estrutural medida em aproximadamente 16%, abaixo do gate |
| Figueira | Fora da configuração | Cards genéricos e somente dois links únicos em seis resultados aparentes |
| Minervino | Fora da configuração | Preço em 33% e foto em 0% da amostra |
| Carlos Amaral | Fora da configuração | Links detectados, porém preço e foto em 0% dos cards avaliados |
| Docarmo | Fora da configuração | Nenhum padrão seguro de cards; endpoint presumido falhou |
| Singular | Fora da configuração | Links detectados, porém preço e foto em 0% dos cards avaliados |
| J/Dutra | Fora da configuração | Nenhum padrão seguro de cards; endpoint presumido falhou |

No restante da planilha também permaneceram sem ativação as fontes marcadas para revisão, bloqueio ou indisponibilidade, incluindo Rede Lar, Cabral Porto, Contato, Territorium, Orbis, Ipatinga Imóveis, DP, Nivaldo, ImóveisGV, Chaves, Coimbra, Jairo Guedes e Bonfim. Foram respeitados, em particular, DNS indisponível, `403`, conteúdo demonstrativo e catálogo exclusivo de venda. Páginas sem catálogo oficial próprio e agregadores foram mantidos fora da coleta.

## Compliance e rastreabilidade

- O `robots.txt` das 16 fontes promovidas permitia as rotas usadas na data da verificação.
- Quando expostos no site, foram registrados os links públicos de política/termos; exemplos: [Total](https://www.totalimob.com.br/privacy.php), [UNICOM](https://www.unicom.imb.br/politica-de-privacidade), [Vasconcelos](https://www.vasconcelosimoveisgv.com/politica-de-privacidade), [Druwe](https://www.druweimoveis.com.br/imoveis/politica-de-privacidade), [Solução](https://www.solucaoimobiliaria.com/politica-de-privacidade) e [Segurança](https://segurancaimoveisgv.com.br/termos-de-uso/).
- A Betel usa a API JSON pública do próprio domínio. As demais fontes reutilizam o coletor Playwright existente, com seletores determinísticos sobre DOM público; não houve ensino visual, login ou contorno de bloqueio.
- A coleta ocorreu somente no banco temporário `.codex-tmp/fontes_vale_gv_isolado.db`, com geocodificação desabilitada. Nenhum banco principal, ambiente de produção ou snapshot público foi alterado.
- URLs são canônicas da fonte. A paginação encerra por limite e ausência de IDs novos, evitando loops e cards auxiliares de páginas terminais.

## Correções defensivas e regressão

As quatro listagens mistas da plataforma C49 passaram a exigir o seletor de link de locação. Essa regra eliminou da Porta Aberta um anúncio de venda de R$ 899 mil observado durante o diagnóstico. O coletor também passou a rejeitar mais nomes e hosts conhecidos de placeholder e deixou de interpretar o segmento `/buscar` como cidade.

Na reconstrução sobre a base limpa foi reimplementada somente uma dependência observada durante a coleta: navegação com `domcontentloaded` nas páginas estruturadas. Esperar `networkidle` fazia analytics e long-polling de alguns portais consumirem todo o timeout, sem acrescentar evidência sobre os cards.

Foram adicionados testes para presença e finalidade das 16 fontes, origem oficial, paginação determinística, exigência de link de locação em listagens mistas, preferência pela API da Betel, quarentena por baixa cobertura, placeholders, cidade e fallback de link estrito.

Um smoke real posterior na base limpa confirmou: Porta Aberta 1/1, UNICOM 16/16, Imóveis Carvalho 13/13 e Betel 101/101, todos com URL única, preço, cidade e foto. A Betel tinha 102 anúncios na coleta isolada anterior; a diferença de um item é compatível com alteração normal do estoque público, sem mudança de seletor ou contrato da API.

## Limitações e pendências humanas

- Inventário e páginas são um retrato de 2026-09-11; volume e HTML podem mudar.
- Carneiro respondeu lentamente em um smoke individual, embora a coleta final curta tenha concluído. Convém observar latência e taxa de erro antes de ampliar frequência.
- Solução e Druwe têm pequenas lacunas de bairro, e Solução/Lins têm ausência real de foto em poucos cards. O comportamento adotado é preservar `null`, sem inventar dados.
- Lins expõe caracteres acentuados de URL de forma inconsistente; a URL original é preservada, mas merece monitoramento.
- Gláucia e Tataia somente devem ser ativadas após uma estratégia de detalhe que eleve cobertura de localização.
- As fontes secundárias devem ser tratadas em lote posterior, sem diluir o gate de precisão deste lote.

## Recomendação

Integrar as 16 fontes ativas e manter Gláucia/Tataia em quarentena. Não integrar as demais prioritárias sem nova evidência estrutural ou permissão explícita de coleta.
