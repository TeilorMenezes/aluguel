# Dados públicos versionados

Esta pasta recebe snapshots produzidos pelo Agente de Expansão Imobiliária:

- `imoveis.db`: somente a tabela pública de imóveis e metadados do snapshot;
- `manifest.json`: versão do esquema, checksum, qualidade e contagens;
- `selectors_override.yaml`: correções manuais aprovadas para o scraper.

O banco e o manifesto são criados pelo aplicativo local e enviados somente por
pull request. Dados administrativos, quarentena, histórico e erros não entram
nesta pasta.
