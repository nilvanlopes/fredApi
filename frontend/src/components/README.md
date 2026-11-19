# React Bits — Glass Surface e card de assinante

Fonte oficial TypeScript + CSS:
https://reactbits.dev/r/GlassSurface-TS-CSS.json

Holo Card: https://reactbits.dev/r/HoloCard-TS-CSS.json

Documentação: https://reactbits.dev/components/glass-surface

Os arquivos `GlassSurface.tsx` e `GlassSurface.css` foram obtidos do registro
oficial, sem uma reimplementação visual local. A licença MIT + Commons Clause
está preservada em `REACT-BITS-LICENSE.md`.

O menu mobile importa o componente com renderer SVG. O fallback de vidro fosco
continua disponível para os navegadores sem suporte aos filtros SVG de fundo.

Para reduzir o custo na rolagem mobile, o menu usa `refraction={false}` e o
modo fosco do Glass Surface com blur de 8 px.

O Holo Card utiliza o shader oficial com uma extensão local para conteúdo DOM
acessível e altura compacta. O fundo SVG é decorativo; nome, estrelas, partidas
e navegação continuam sendo elementos HTML. O efeito é montado para assinantes
atuais no hover e no card aberto por toque, com animação ociosa desativada e respeito à
preferência por movimento reduzido.

O Holo Card tem limites opcionais de resolução e frequência (`maxDpr` e
`maxFps`), usados com valores 1 e 30 no modal. O ciclo pausa quando o movimento
estabiliza ou o documento fica oculto e retoma com nova interação.


O resumo de assinantes combina o enquadramento do Profile Card e a superfície
metálica com aro e luz do Reflective Card. Fontes oficiais consultadas:

- https://reactbits.dev/r/ProfileCard-TS-CSS.json
- https://reactbits.dev/r/ReflectiveCard-TS-CSS.json

A composição foi adaptada em `Profile.tsx` e `Profile.css` para os dados do Fred:
retrato, nome, estrelas, partidas e ação de abrir o perfil. Não inclui os
renderizadores extras, vídeo, câmera ou sensores dos exemplos. O reflexo CSS
compartilha as coordenadas de luz e o ciclo limitado do Holo Card existente,
sem um segundo loop de animação nem filtros de fundo. A moldura, o reflexo,
o foil e o pattern VIP são exclusivos de `is_subscriber === true`, calculado
pelo servidor a partir da assinatura do mês atual. Os demais jogadores mantêm
o resumo simples.

`public/holo-subscriber.svg` é a textura local do shader. A máscara repetida
`public/vip-pattern.svg` aplica o texto VIP iridescente sobre a foto e o fundo
verde, abaixo das informações e do botão. Essa camada CSS também funciona sem
WebGL e usa as coordenadas de luz existentes, sem outro loop de animação.
Não há badge VIP. As fontes mantêm a licença em `REACT-BITS-LICENSE.md`.
