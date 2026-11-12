---
name: consulta
description: Responde uma pergunta sobre as CCTs (ex.: "das CCTs vencidas, traga piso salarial, reajuste e auxílio creche"). Filtra os arquivos com a ferramenta e chama o subagente leitor-ccts só para as CCTs que interessam. Gera saida/consulta.html.
argument-hint: "<o que você procura nas CCTs>"
---

Pedido do usuário: $ARGUMENTS

Se o pedido estiver vazio, pergunte ao usuário o que ele procura e pare.

1. Rode `python ferramentas.py extrair` para incluir arquivos novos (os que não mudaram não são lidos de novo).

2. Separe o pedido em três partes:
   - **Filtros sem IA:** vencida/atrasada, vigente ou futura vira `--situacao`; loja, cidade ou código do sindicato (SINDxxxx) vira `--nome`.
   - **Condição** (opcional): algo que a CCT precisa ter para entrar no resultado (ex.: "que tenham auxílio creche"). Vira `--termo`, com 2 a 4 variações (ex.: `--termo "auxilio creche" --termo "creche"`). Acentos, maiúsculas e hífens não importam.
   - **Informações a trazer:** a lista do que extrair de cada CCT (ex.: piso salarial; reajuste). Se o pedido não tiver lista, a informação é a própria pergunta.

3. Rode `python ferramentas.py buscar` com os filtros e a condição (sem condição, ele só lista as CCTs que passam nos filtros).
   - Nenhuma CCT: tente termos mais amplos antes de concluir que não existe.
   - Mais de 30 CCTs: refine antes de seguir.

4. Se a saída do `buscar` já responde o pedido (ex.: "quais CCTs estão vencidas"), vá direto ao passo 6, sem subagente.

5. Para cada CCT, chame o subagente `leitor-ccts` passando o id, a lista de informações e, se houver, as páginas onde os termos apareceram. Mande até 8 chamadas na mesma mensagem, para rodarem em paralelo, e espere o lote terminar antes do próximo.

6. Grave as respostas em `saida/resultado.json`, no formato de `modelo.json` (nesta pasta), e rode `python .claude/skills/consulta/relatorio.py`. Ele monta `saida/consulta.html` (substitui a consulta anterior) com o visual do Robô Mediador. Se o script apontar um erro no JSON, corrija e rode de novo. Depois responda no chat com: o pedido, quantas CCTs e arquivos foram analisados e um resumo do que foi encontrado.

## Como preencher o resultado.json
Copie a estrutura de `modelo.json`. O programa busca sozinho o documento (registro no MTE), a vigência, os arquivos e as lojas de cada CCT; você escreve só o que a leitura achou.
- `pedido`: o texto do usuário. `data`: dia da consulta (aaaa-mm-dd). `grupo`: como chamar as CCTs do filtro ("atrasadas", "vigentes"...). `filtro`: uma frase com o critério.
- `infos`: uma por informação pedida. Em `foco`, diga em poucas palavras o que o agente procurou. Isso abre o relatório e deixa claro que a leitura foi focada, não geral.
- `ccts`: uma por CCT lida. O `id` fica só no JSON. `nome` é a cidade; `curto` (opcional) é um nome menor para os gráficos.
  - Cada informação tem `st` (`sim`, `parcial` ou `nao`), `curta` (resposta para a tabela, até ~60 caracteres), `pontos` (lista de itens curtos), `clausula`, `pag` e `trecho` (citação curta).
  - `valor` (número) e `nota` (motivo, se o valor tem ressalva) só quando a informação entra num gráfico.
  - CCT que trata só de outro assunto (horário, feriados, banco de horas): use `complementar` com `assunto`, `pontos` e `principal` (id da CCT principal das mesmas lojas) ou `principal_txt`. Em `infos`, só o que ela tiver das informações pedidas.
- `graficos` (opcional): para informações com um número comparável entre CCTs (piso em R$, reajuste em %). Campos: `info`, `titulo`, `subtitulo`, `unidade` (`R$` ou `%`), `forma` (`barras` ou `colunas`). Os gráficos de "o que foi encontrado" e "lojas por estado" saem sempre.
- `alertas`: os pontos de atenção, cada um com `nivel`, `titulo`, `pontos` e `ccts` (lista de ids):
  - `alto`: falta documento ou dado, ou há dúvida que impede usar o resultado (ex.: aditivo fora da pasta, duas CCTs para a mesma loja).
  - `medio`: o dado existe, mas o texto tem erro ou ambiguidade e precisa de conferência no PDF.
  - `baixo`: detalhe para conhecimento, que não muda o resultado (ex.: erro de digitação que o extenso corrige).
  - O mesmo problema em várias CCTs vira um alerta só, com todas elas em `ccts`.

## Regras de escrita do relatório
- Itens curtos, não parágrafos. Use uma frase inteira só quando ela for necessária para explicar o dado.
- Não repita: o que virou ponto de atenção não volta em `obs` nem em `pontos`, a não ser o mínimo para explicar um "parcial". `obs` é só para o que não cabe em nenhuma informação e muda a leitura do dado.
- Nunca escreva o id (o código entre colchetes) em nenhum texto. Para identificar a CCT, use a cidade e, se precisar, o registro no MTE (o `buscar` mostra).
- Não traga o que não foi pedido (ex.: vale-alimentação numa consulta de piso).
- Valores como no texto: R$ 1.234,56; 10%; dd/mm/aaaa.
