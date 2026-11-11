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

6. Escreva `saida/consulta.html` (substitui a consulta anterior) e responda no chat com: o pedido, quantas CCTs e arquivos foram analisados e um resumo do que foi encontrado.

## Como montar o HTML
Use como modelo o arquivo `modelo.html` desta pasta (`.claude/skills/consulta/modelo.html`): mesmo CSS, mesma estrutura e o mesmo jeito de mostrar a fonte. Troque só os dados.
- **Cabeçalho:** "Consulta de CCTs", o pedido, a data e os números (arquivos na pasta, CCTs analisadas, arquivos/lojas cobertos).
- **Resumo por informação:** um cartão por informação com quantas CCTs têm, não têm ou têm em parte.
- **Tabela:** uma linha por CCT e uma coluna por informação. Cada célula traz a resposta curta e, ao passar o mouse ou abrir, a cláusula e o trecho. "Não encontrado" e "parcial" ficam visíveis com cor própria.
- **Detalhe por CCT:** lojas (arquivos), vigência, e para cada informação a resposta completa, a cláusula e o trecho.
- **Alertas:** CCTs que tratam só de outro assunto, arquivos sem texto e dúvidas da leitura.
- **Rodapé:** "Gerado automaticamente pelo agente de consulta de CCTs".
- Arquivo único, CSS dentro de `<style>`, sem bibliotecas externas.
