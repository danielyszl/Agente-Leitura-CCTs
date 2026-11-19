---
name: consulta
description: Responde uma pergunta sobre as CCTs (ex.: "das CCTs vencidas, traga piso salarial e reajuste") ou faz a consulta diária do setor de Cargos e Salários (`/consulta diária`, só CCTs ainda não analisadas). Filtra os arquivos com a ferramenta e chama o subagente leitor-ccts só para as CCTs que interessam. Gera saida/consulta.html.
argument-hint: "<o que você procura nas CCTs> | diária"
---

Pedido do usuário: $ARGUMENTS

Se o pedido estiver vazio, pergunte ao usuário o que ele procura e pare.
Se o pedido for "diária" (ou "diaria"), siga também a seção **Consulta diária**, que muda alguns passos.

1. Rode `python ferramentas.py extrair` para incluir arquivos novos (os que não mudaram não são lidos de novo).

2. Separe o pedido em três partes:
   - **Filtros sem IA:** vencida/atrasada, vigente ou futura vira `--situacao`; loja, cidade ou código do sindicato (SINDxxxx) vira `--nome`.
   - **Condição** (opcional): algo que a CCT precisa ter para entrar no resultado (ex.: "que tenham auxílio creche"). Vira `--termo`, com 2 a 4 variações (ex.: `--termo "auxilio creche" --termo "creche"`). Acentos, maiúsculas e hífens não importam.
   - **Informações a trazer:** a lista do que extrair de cada CCT (ex.: piso salarial; reajuste). Se o pedido não tiver lista, a informação é a própria pergunta.

3. Rode `python ferramentas.py buscar` com os filtros e a condição (sem condição, ele só lista as CCTs que passam nos filtros).
   - Nenhuma CCT: tente termos mais amplos antes de concluir que não existe.
   - Mais de 30 CCTs: refine antes de seguir.

4. Se a saída do `buscar` já responde o pedido (ex.: "quais CCTs estão vencidas"), vá direto ao passo 6, sem subagente.

5. Para cada CCT, chame o subagente `leitor-ccts` passando o id, a lista de informações (com o que cada uma cobre) e, se houver, as páginas onde os termos apareceram. Mande até 8 chamadas na mesma mensagem, para rodarem em paralelo, e espere o lote terminar antes do próximo.

6. Grave as respostas em `saida/resultado.json`, no formato de `modelo.json` (nesta pasta), e rode `python .claude/skills/consulta/relatorio.py`. Ele monta `saida/consulta.html` (substitui a consulta anterior) com o visual do Robô Mediador. Se o script apontar um erro no JSON, corrija e rode de novo. Depois responda no chat com: o pedido, quantas CCTs e arquivos foram analisados e um resumo do que foi encontrado.

7. Só se o pedido mandar enviar por e-mail (ex.: tarefa agendada), rode `python .claude/skills/consulta/enviar_email.py` depois do relatório. Ele manda um resumo no corpo e o `consulta.html` em anexo. Se aparecer "E-mail NÃO enviado", diga o motivo no chat.

## Consulta diária
Consulta fixa do setor de Cargos e Salários, para rodar todo dia numa tarefa agendada, sem ninguém acompanhando. Não faça perguntas.
- **Filtro:** no passo 3, rode `python ferramentas.py buscar --novas`. Ele lista só as CCTs que ainda não saíram num relatório diário, as mais recentes primeiro, até o `LimiteDiario` do `config.ini` (fora do projeto). Analise todas as listadas, principais e complementares, sem refinar.
- **Nenhuma CCT na fila:** rode `python .claude/skills/consulta/enviar_email.py --sem-novas` (aviso curto de que o agente rodou) e pare.
- **Informações:** as 9 da lista abaixo, nesta ordem, com o `nome` e o `foco` de `modelo.json`.
- **resultado.json:** `"diaria": true`, `pedido` "Consulta diária: CCTs novas", `grupo` "novas" e `filtro` "Nova: convenção coletiva que ainda não tinha sido analisada pelo agente. Até N por dia, as mais recentes primeiro." (N é o limite que o `buscar` mostrou).
- **No fim:** envie o e-mail (passo 7). Se ele saiu, rode `python ferramentas.py marcar`: as CCTs do relatório ficam anotadas como analisadas e não voltam no dia seguinte. Se o e-mail não saiu, não marque: elas entram de novo amanhã.

Lista do Cargos (o que cada informação cobre):
1. **Pisos salariais:** todos os pisos, função por função (geral, comissionista, caixa, limpeza, administrativo, estoque, office boy, sem experiência...), com o valor como está no texto e a data de início.
2. **Reajustes:** todos os reajustes previstos, com data e percentual (inclusive escalonados, ex.: "x% em maio e y% em novembro"), base, teto e regra para admitidos depois da data-base.
3. **Retroatividade:** se pisos ou reajustes valem desde uma data anterior à assinatura ou ao registro, desde quando e como pagar as diferenças (prazo, folha). Se a CCT não diz nada, `nao`.
4. **Salário mínimo ou piso regional:** se a CCT liga o piso ou o reajuste ao salário mínimo nacional ou ao piso regional do estado (ex.: "se o piso regional ficar acima, prevalece").
5. **Jovem aprendiz:** salário do aprendiz (valor, percentual do piso ou salário mínimo/hora).
6. **ATS:** adicional por tempo de serviço (anuênio, biênio, triênio, quinquênio): percentual, período e limite.
7. **Feriados e domingos:** se pode trabalhar, como paga (adicional ou valor fixo), folga compensatória, escala e autorizações.
8. **Quebra de caixa:** percentual e base de cálculo.
9. **Horas extras:** percentuais e regras especiais (compensação, banco de horas). Domingos e feriados ficam no item 7.

Os sindicatos (laboral e patronal, com CNPJ) não precisam de leitura: o relatório tira do cabeçalho de cada CCT.

## Como preencher o resultado.json
Copie a estrutura de `modelo.json`. O programa busca sozinho o documento (registro no MTE), a vigência, os sindicatos, os arquivos e as lojas de cada CCT; você escreve só o que a leitura achou.
- `pedido`: o texto do usuário. `data`: dia da consulta (aaaa-mm-dd). `grupo`: como chamar as CCTs do filtro ("atrasadas", "vigentes", "novas"...).
- `filtro`: o critério com estas frases, sem datas (o critério não depende do dia da consulta). Não escreva a fonte: o relatório já mostra.
  - Situação: "Vencida: convenção coletiva cuja data de vigência já terminou." (também para "atrasada"), "Vigente: convenção coletiva cuja vigência já começou e ainda não terminou." ou "Futura: convenção coletiva cuja vigência ainda não começou."
  - Cidade, loja ou sindicato: "Considera apenas CCTs de Alegrete." (com o nome pedido).
- `infos`: uma por informação pedida. Em `foco`, diga em poucas palavras o que o agente procurou.
- `ccts`: uma por CCT lida. O `id` fica só no JSON. `nome` é a cidade.
  - Cada informação tem `st` (`sim`, `parcial` ou `nao`), `curta` (resposta para a ficha, até ~60 caracteres), `pontos` (lista de itens curtos), `clausula`, `pag` e `trecho` (citação curta).
  - Pisos: `pisos` é uma lista com um item por função, cada um com `funcao`, `valor` (como está no texto, ex.: "R$ 1.910,00", mesmo com erro de digitação), `desde` (dd/mm/aaaa) e `nota` (só se houver ressalva, ex.: número diferente do extenso). Se a CCT separar por porte da empresa ou por cidade, um item por linha (ex.: "Vendedor · empresas até 10 empregados").
  - ATS: `valor` (percentual, número) e `periodo` ("anuênio", "triênio", "quinquênio"...) põem o percentual em destaque na ficha. Na `curta`, não repita o período: ponha o limite ou a regra.
  - CCT que trata só de outro assunto (horário, feriados, banco de horas): use `complementar` com `assunto`, `pontos` e `principal` (id da CCT principal das mesmas lojas) ou `principal_txt`. Em `infos`, só o que ela tiver das informações pedidas.
- `alertas`: os pontos de atenção, cada um com `nivel`, `titulo`, `pontos` e `ccts` (lista de ids):
  - `alto`: falta documento ou dado, ou há dúvida que impede usar o resultado (ex.: aditivo fora da pasta, duas CCTs para a mesma loja).
    - Número e extenso com valores diferentes, sem como saber qual vale (ex.: “7% (nove e meio por cento)”, “R$ 130,00 (cento e cinquenta reais)”): sempre `alto`, e a informação fica `parcial`, com os dois valores como estão no texto. Vários casos na mesma CCT viram um alerta só.
    - Escreva o trecho exatamente como aparece, entre aspas, e depois diga que não batem (ex.: “7% (nove e meio por cento)” · número e extenso não batem). Não converta o extenso em número e não escreva em forma de pergunta.
  - `medio`: o dado existe, mas o texto tem erro ou ambiguidade e precisa de conferência no PDF.
  - `baixo`: detalhe para conhecimento, que não muda o resultado (ex.: erro de digitação que o extenso esclarece, como “R$ 2.070,00,00 (dois mil e setenta reais)”: o valor é um só, R$ 2.070,00).
  - O mesmo problema em várias CCTs vira um alerta só, com todas elas em `ccts`.

## Regras de escrita do relatório
- Itens curtos, não parágrafos. Use uma frase inteira só quando ela for necessária para explicar o dado.
- Não repita: o que virou ponto de atenção não volta em `obs` nem em `pontos`, a não ser o mínimo para explicar um "parcial". `obs` é só para o que não cabe em nenhuma informação e muda a leitura do dado.
- Nunca escreva o id (o código entre colchetes) em nenhum texto. Para identificar a CCT, use a cidade e, se precisar, o registro no MTE (o `buscar` mostra).
- Não traga o que não foi pedido (ex.: vale-alimentação numa consulta de piso).
- Valores como no texto: R$ 1.234,56; 10%; dd/mm/aaaa.
