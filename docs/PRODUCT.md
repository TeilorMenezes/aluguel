# Produto — Mapa do Aluguel

## Visão

O Mapa do Aluguel reúne ofertas de locação publicadas por imobiliárias em uma
busca única, clara e rastreável. O usuário compara opções e segue para o anúncio
original para confirmar disponibilidade e negociar com a fonte responsável.

## Problema

Quem procura aluguel precisa abrir muitos sites, lidar com filtros diferentes e
anúncios incompletos ou desatualizados. Imobiliárias regionais também têm pouca
padronização tecnológica, o que torna a agregação manual lenta e frágil.

## Público inicial

- Pessoas procurando imóveis residenciais para alugar.
- Administrador responsável por revisar fontes e qualidade.
- Futuramente, corretores e imobiliárias interessados em indicadores agregados.

## Proposta de valor

- Busca única para diferentes imobiliárias.
- Origem e link original sempre visíveis.
- Filtros consistentes por cidade, bairro, tipo, imobiliária e preço.
- Expansão regional assistida por um agente local com revisão humana.
- Informação de última verificação e canal para reportar inconsistências.

## Escopo atual

- Imóveis para locação de sites oficiais de imobiliárias.
- Landing page, catálogo, mapa, filtros e paginação.
- Descoberta e inspeção de novas fontes.
- Quarentena, ensino visual e publicação controlada de configurações ou snapshots.

## Fora do escopo atual

- Intermediar contratos, receber aluguel ou representar as partes.
- Prometer disponibilidade sem confirmação da fonte.
- Coletar áreas protegidas por login ou contornar bloqueios.
- Operar venda de imóveis como catálogo público principal.
- Produzir indicadores profissionais antes de existir histórico confiável.
- Depender de IA em todas as execuções de coleta.

## Regras de negócio invariantes

1. Cada anúncio publicado conserva fonte e URL original.
2. Configuração nova exige validação e aprovação humana.
3. Baixa confiança nunca entra automaticamente no catálogo.
4. Um erro em uma fonte não pode apagar dados válidos de outras fontes.
5. Uma coleta vazia ou incompleta não pode substituir silenciosamente o catálogo.
6. Saída de estoque é estado histórico, não exclusão definitiva.
7. Dados administrativos não fazem parte do snapshot público.
8. O produto deve comunicar cobertura real, sem sugerir alcance inexistente.

## Capacidades futuras, em ordem de maturidade

### Catálogo confiável

- Páginas próprias e indexáveis por região, bairro, tipo e imóvel.
- Favoritos, comparação, alertas e reporte de anúncio incorreto.
- Deduplicação do mesmo imóvel publicado em múltiplas fontes.

### Expansão operacional

- Fila de fontes, saúde por imobiliária e revalidação automática.
- Integrações por API ou feed com parceiros.
- Publicação por lotes revisáveis e trilha completa de auditoria.

### Inteligência de mercado

- Histórico de preço e disponibilidade.
- Mediana, preço por metro quadrado, estoque e tempo de anúncio.
- Painel profissional somente com amostra e qualidade mínimas documentadas.

## Métricas principais

- Percentual de anúncios com link, título, preço, cidade e imagem válidos.
- Fontes saudáveis nas últimas 24 horas.
- Idade mediana da última verificação dos anúncios.
- Taxa de configurações promovidas da quarentena após revisão.
- Cliques qualificados para a fonte original.
- Tempo e taxa de sucesso da coleta por fonte.

## Decisões ainda pendentes

- Modelo comercial de longo prazo.
- Provedor de hospedagem e banco da versão de produção.
- Política jurídica final de uso de conteúdo, remoção e relacionamento com fontes.
- Critérios exatos para abrir indicadores profissionais ao público.
