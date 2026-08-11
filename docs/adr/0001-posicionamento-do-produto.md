# ADR 0001 — Posicionamento do produto

- Status: aceito
- Data: 2026-08-11

## Contexto

O projeto reúne anúncios de terceiros e já discutiu, em momentos distintos,
agregação, intermediação, venda e indicadores profissionais. Misturar esses
modelos agora aumenta risco jurídico, técnico e de comunicação.

## Decisão

O Mapa do Aluguel será inicialmente um agregador de imóveis para locação. Ele
organiza dados, identifica a fonte e redireciona o usuário ao anúncio original.
Não recebe valores, não representa as partes e não promete disponibilidade.

Venda, intermediação e produtos profissionais permanecem fora do núcleo atual e
exigem decisão própria antes de implementação.

## Consequências

- A interface deve destacar fonte e última verificação.
- Conteúdo e automações não podem sugerir atuação como corretora.
- O escopo técnico prioriza qualidade do catálogo e expansão de fontes.
- Mudança futura de modelo exige revisão jurídica e novo ADR.
