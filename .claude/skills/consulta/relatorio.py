"""
Monta o relatório da consulta (saida/consulta.html) a partir das respostas em saida/resultado.json.

    python .claude/skills/consulta/relatorio.py
    python .claude/skills/consulta/relatorio.py saida/resultado.json saida/outro.html

Não usa IA: só organiza o que o agente já leu. O formato do JSON está em modelo.json (mesma pasta).
Documento (registro no MTE), vigência, sindicatos, arquivos e lojas vêm do ferramentas.py,
por isso o relatório nunca mostra o código interno (id) das CCTs.
Ordem (pedido do setor de Cargos e Salários): resultado por CCT primeiro, em fichas com todos os pisos;
pontos de atenção e explicações no fim. Sem gráficos: a ficha já mostra os números (pedido de 19/11/2026).
Visual: tema claro com a identidade do Robô Mediador (verde, cantos retos, rótulos em maiúsculas).
"""
import json
import re
import sys
import unicodedata
from datetime import date
from html import escape
from pathlib import Path

PROJETO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJETO))
sys.dont_write_bytecode = True  # não cria a pasta __pycache__ no projeto
import ferramentas as f  # noqa: E402  (índice, textos, registro no MTE e sindicatos)

ROTULO = {"sim": "Encontrado", "parcial": "Parcial", "nao": "Não consta"}
SIGNIFICADO = {"sim": "a CCT traz a informação completa.",
               "parcial": "a CCT traz só uma parte (falta um valor, um percentual ou um dos anos).",
               "nao": "a CCT não trata do assunto."}
NIVEL = {"alto": ("Alto", "resolva antes de usar o dado"),
         "medio": ("Médio", "confira no PDF antes de usar"),
         "baixo": ("Baixo", "só para saber; não muda o resultado")}
# Cores validadas para daltonismo sobre fundo branco (script validate_palette da skill de gráficos).
# A ordem importa: cores parecidas nunca ficam lado a lado.
COR = {"sim": "#2E9B45", "parcial": "#E0A100", "nao": "#7D8A80", "outra": "#7D8A80",
       "infos": ["#2a78d6", "#e87ba4", "#6250d6", "#eb6834", "#1baf7a"]}  # uma por informação, na ordem
COR_INFO = {}  # nome da informação -> cor (preenchido em montar)
# Números do resumo: (cor do número, fundo do cartão)
KPI_COR = [("#1c5cab", "#EAF2FC"), ("#4a3aa7", "#EFEDFB"), ("#B8461C", "#FDEEE7"), ("#1C6D27", "#E9F6EC")]
SITUACAO = {"vigente": "Vigente", "vencida": "Vencida", "futura": "Futura", "sem_vigencia": "Sem vigência"}
SIGLAS = {"MTE", "TST", "CLT", "REPIS", "DSR", "ME", "EPP", "PN", "CCT", "SINDECSAP", "INPC", "SC", "RS",
          "PR", "MS", "ATS"}


# ------------------------------------------------------------------ textos

def esc(t) -> str:
    return escape(str(t), quote=True)


def br(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else "?"


def numero(v: float, unidade: str) -> str:
    if unidade == "R$":
        return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",") + unidade


def frase(t: str) -> str:
    """'CLÁUSULA TERCEIRA - PISO SALARIAL' -> 'Cláusula terceira – Piso salarial' (siglas ficam)."""
    palavras = []
    for p in t.split(" "):
        letras = "".join(c for c in p if c.isalpha())
        if letras and letras.isupper() and letras not in SIGLAS:
            p = p.lower()
        palavras.append(p)
    t = " ".join(palavras).replace(" - ", " – ")
    return "; ".join(" – ".join(s[:1].upper() + s[1:] for s in parte.split(" – "))
                     for parte in t.split("; "))


def slug(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def icone(st: str) -> str:
    """Quadrado cheio, meio cheio ou vazio: a forma diz o status mesmo sem cor."""
    c = COR[st]
    borda = f'<rect x="1.5" y="1.5" width="9" height="9" fill="none" stroke="{c}" stroke-width="1.5"/>'
    corpo = {"sim": f'<rect x="1" y="1" width="10" height="10" fill="{c}"/>',
             "parcial": borda + f'<rect x="1" y="1" width="5.5" height="10" fill="{c}"/>',
             "nao": borda}[st]
    return f'<svg class="ic" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">{corpo}</svg>'


def link_pdf(c, pag=None, texto=None) -> str:
    """Link que abre o PDF da CCT (todos os arquivos têm o mesmo texto) já na página indicada."""
    if not c["_pdfs"]:
        return esc(texto or "")
    nome, uri = c["_pdfs"][0]
    primeira = re.search(r"\d+", str(pag or ""))
    alvo = f"{uri}#page={primeira.group(0)}" if primeira else uri
    rotulo = texto or nome
    return (f'<a href="{esc(alvo)}" target="_blank" rel="noopener" title="Abrir o PDF {esc(nome)}'
            f'{f" na página {primeira.group(0)}" if primeira else ""}">{esc(rotulo)} ↗</a>')


# ------------------------------------------------------------------ dados

def carregar(caminho: Path):
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    indice = f._carregar_indice()
    hoje = date.fromisoformat(dados.get("data") or date.today().isoformat())
    arquivos_por_id, pdfs_por_id = {}, {}
    for caminho, a in indice["arquivos"].items():
        if a["id"]:
            arquivos_por_id.setdefault(a["id"], []).append(a["arquivo"])
            # link para abrir o PDF (só funciona para quem tem acesso à mesma pasta)
            pdfs_por_id.setdefault(a["id"], []).append((a["arquivo"], Path(caminho).as_uri()))
    ancoras = set()
    for c in dados["ccts"]:
        m = indice["ccts"][c["id"]]
        arquivos = sorted(arquivos_por_id.get(c["id"], []))
        registro = f._registro(c["id"])
        tipo = frase(m["tipo"])
        anos = re.search(r"\d{4}/\d{4}", tipo)
        curto = f"CCT {anos.group(0)}" if anos and "convenção" in tipo.lower() else tipo
        ancora = "cct-" + slug(c["nome"])
        while ancora in ancoras:
            ancora += "-2"
        ancoras.add(ancora)
        ini, fim = m["vigencia_inicio"], m["vigencia_fim"]
        situacao = ("sem_vigencia" if not fim else "futura" if ini and hoje.isoformat() < ini
                    else "vigente" if hoje.isoformat() <= fim else "vencida")
        c.update({
            "_arquivos": arquivos,
            "_pdfs": sorted(pdfs_por_id.get(c["id"], [])),
            "_lojas": sorted({a.split("_")[0] for a in arquivos}),
            "_registro": registro,
            "_uf": registro[:2] if registro else "?",
            "_tipo": tipo,
            "_doc": f"{curto} · registro {registro}" if registro else curto,
            "_ini": ini,
            "_fim": fim,
            "_situacao": situacao,
            "_atraso": (hoje - date.fromisoformat(fim)).days if fim else None,
            "_data_base": m.get("data_base") or "",
            "_sindicatos": f._sindicatos(c["id"]),
            "_ancora": ancora,
            "_complementar": bool(c.get("complementar")),
        })
        c["_busca"] = slug(" ".join([c["nome"], registro, c["_uf"], " ".join(arquivos), " ".join(c["_lojas"])]
                                    + [n for lado in c["_sindicatos"].values() for n, _ in lado]))
    if dados.get("diaria"):  # consulta diária: as mais recentes primeiro, como na fila
        dados["ccts"].sort(key=lambda c: (c["_ini"], c["nome"]), reverse=True)
        analisadas = set(f._carregar_analisadas())
        de_hoje = {c["id"] for c in dados["ccts"]}
        dados["_fila"] = len(set(indice["ccts"]) - analisadas - de_hoje)
        dados["_total_analisadas"] = len(analisadas | de_hoje)
    else:
        dados["ccts"].sort(key=lambda c: (c["_fim"], c["nome"]))
    return dados, indice, hoje


def vencimento(c) -> str:
    if c["_situacao"] == "sem_vigencia":
        return "sem vigência no texto"
    if c["_situacao"] == "futura":
        return f"começa {br(c['_ini'])}"
    if c["_atraso"] > 0:
        return f"venceu {br(c['_fim'])} · {c['_atraso']} dias"
    return f"vigente até {br(c['_fim'])}"


# ------------------------------------------------------------------ fichas (resultado por CCT)

def sindicatos(c) -> str:
    """Laboral e patronal com CNPJ, como estão no cabeçalho da CCT (o Mediador às vezes corta o nome)."""
    s = c["_sindicatos"]

    def lista(partes):
        return "".join(f'<span class="sind">{esc(n)}<span class="cnpj">CNPJ {esc(cnpj)}</span></span>'
                       for n, cnpj in partes)
    if "laboral" in s:
        return (f'<div><dt>Sindicato laboral</dt><dd>{lista(s["laboral"])}</dd></div>'
                f'<div><dt>Sindicato patronal</dt><dd>{lista(s["patronal"])}</dd></div>')
    if s.get("partes"):
        return f'<div class="dois"><dt>Sindicatos</dt><dd>{lista(s["partes"])}</dd></div>'
    return '<div class="dois"><dt>Sindicatos</dt><dd>não identificados no cabeçalho · veja o PDF</dd></div>'


def bloco_pisos(c, inf, r) -> str:
    """Tabela com todos os pisos da CCT, função por função."""
    cab = f'<p class="f-rot">{icone(r["st"])}{esc(inf)}</p>'
    if r["st"] == "nao" or not r.get("pisos"):
        texto = r.get("curta") or ROTULO[r["st"]]
        return f'<div class="f-pisos">{cab}<p class="f-vazio">{esc(texto)}</p></div>'
    linhas = []
    for p in r["pisos"]:
        nota = f'<span class="nota">⚠ {esc(p["nota"])}</span>' if p.get("nota") else ""
        linhas.append(f'<tr><td>{esc(p["funcao"])}{nota}</td><td class="num">{esc(p["valor"])}</td>'
                      f'<td>{esc(p.get("desde") or "—")}</td></tr>')
    linhas = "".join(linhas)
    return (f'<div class="f-pisos">{cab}<table class="pisos"><thead><tr><th>Função</th><th>Valor</th>'
            f'<th>Desde</th></tr></thead><tbody>{linhas}</tbody></table></div>')


def bloco_info(inf, r) -> str:
    """Uma informação na grade da ficha. Com 'periodo' (ATS), o percentual aparece em destaque."""
    if r["st"] != "nao" and isinstance(r.get("valor"), (int, float)) and r.get("periodo"):
        valor = (f'<p class="grande">{esc(numero(r["valor"], "%"))}<small>por {esc(r["periodo"])}</small></p>'
                 + (f'<p class="f-val">{esc(r["curta"])}</p>' if r.get("curta") else ""))
    else:
        texto = r.get("curta") or ROTULO[r["st"]]
        if r["st"] == "nao" and r.get("curta"):
            texto = f'Não consta · {r["curta"]}'
        valor = f'<p class="f-val">{esc(texto)}</p>'
    return f'<div class="f-info {r["st"]}"><p class="f-rot">{icone(r["st"])}{esc(inf)}</p>{valor}</div>'


def detalhe_fontes(c, infos) -> str:
    """O que fica dentro de "Ver detalhes e fontes": arquivos e, para cada informação, itens, cláusula e trecho."""
    arquivos = "".join(f'<li><a href="{esc(uri)}" target="_blank" rel="noopener" title="Abrir este PDF">{esc(nome)}'
                       f' ↗</a></li>' for nome, uri in c["_pdfs"])
    corpo = [f'<details class="arquivos"><summary><b>Arquivos com este texto</b> ({len(c["_arquivos"])})</summary>'
             f'<ul>{arquivos}</ul></details>']
    for inf in infos:
        r = c["infos"][inf]
        pontos = "".join(f"<li>{esc(p)}</li>" for p in r.get("pontos", []))
        fonte = (f'<p class="fonte">Fonte: {esc(frase(r["clausula"]))} · '
                 f'{link_pdf(c, r.get("pag"), "pág. " + str(r.get("pag", "?")))}</p>' if r.get("clausula") else "")
        trecho = (f'<details class="trecho"><summary>Ver trecho da CCT</summary><blockquote>“{esc(r["trecho"])}”'
                  f'</blockquote></details>' if r.get("trecho") else "")
        corpo.append(f'<div class="info" style="--c:{COR_INFO[inf]}"><div class="rot">{esc(inf)}<span class="st">'
                     f'{icone(r["st"])}{ROTULO[r["st"]]}</span></div><div><ul>{pontos}</ul>{fonte}{trecho}</div></div>')
    if c.get("obs"):
        corpo.append('<div class="obs"><b>Outras observações</b><ul>'
                     + "".join(f"<li>{esc(o)}</li>" for o in c["obs"]) + "</ul></div>")
    return "".join(corpo)


def ficha(c, infos, meus) -> str:
    com_pisos = next((i for i in infos if "pisos" in c["infos"][i]), None)
    blocos = "".join(bloco_info(i, c["infos"][i]) for i in infos if i != com_pisos)
    pisos = bloco_pisos(c, com_pisos, c["infos"][com_pisos]) if com_pisos else ""
    alertas = ""
    if meus:
        itens = "".join(f'<li><span class="nv n-{a["nivel"]}"></span><a href="#{a["_ancora"]}" '
                        f'data-de="{c["_ancora"]}" data-nome="{esc(c["nome"])}">{esc(a["titulo"])}</a></li>'
                        for a in meus)
        alertas = f'<div class="f-alertas"><p class="f-rot">Pontos de atenção</p><ul>{itens}</ul></div>'
    situacoes = ",".join(c["infos"][i]["st"] for i in infos)  # usado pelos filtros
    lojas = ", ".join(c["_lojas"])
    return f"""<article class="ficha s-{c["_situacao"]}" id="{c["_ancora"]}" data-busca="{c["_busca"]}" data-st="{situacoes}">
<header class="f-cab"><div><h3>{esc(c["nome"])}</h3><p class="doc">{esc(c["_doc"])}</p></div>
<span class="sit">{esc(vencimento(c))}</span></header>
<dl class="f-dados">{sindicatos(c)}
<div><dt>Vigência</dt><dd>{br(c["_ini"])} a {br(c["_fim"])}<br>data-base {esc(c["_data_base"] or "—")}</dd></div>
<div><dt>Lojas ({len(c["_lojas"])})</dt><dd>{esc(lojas)}</dd></div></dl>
<div class="f-corpo">{pisos}<div class="f-grade">{blocos}</div>{alertas}</div>
<details class="f-det"><summary>Ver detalhes e fontes</summary><div class="f-det-corpo">{detalhe_fontes(c, infos)}</div></details>
</article>"""


# ------------------------------------------------------------------ seções

def secao_topo(dados, hoje) -> str:
    return f"""
<header class="topo">
  <div class="linha-topo"><div class="marca"></div><h1>Consulta de CCTs</h1><div class="data">{hoje:%d/%m/%Y}</div></div>
  <p class="rotulo">Pedido</p>
  <p class="pedido">{esc(dados["pedido"])}</p>
  <p class="detalhe">{esc(dados["filtro"]) + "<br>" if dados.get("filtro") else ""}Fonte: convenções coletivas obtidas no sistema Mediador.</p>
</header>"""


def secao_resultado(dados, indice, principais, ccts, alertas_por_cct) -> str:
    infos = [i["nome"] for i in dados["infos"]]
    lojas = {l for c in ccts for l in c["_lojas"]}
    grupo = dados.get("grupo", "analisadas")
    if dados.get("diaria"):
        kpis = [(len(ccts), "CCTs analisadas hoje"), (len(lojas), "lojas"),
                (dados["_fila"], "CCTs na fila"), (dados["_total_analisadas"], "analisadas no total")]
    else:
        n_arquivos = sum(len(c["_arquivos"]) for c in ccts)
        kpis = [(len(ccts), f"CCTs {grupo}"), (len(lojas), f"lojas ({n_arquivos} arquivos)"),
                (len(indice["ccts"]), "CCTs diferentes na pasta"), (len(indice["arquivos"]), "arquivos na pasta")]
    caixas = "".join(f'<div class="kpi" style="--c:{c};--t:{t}"><div class="n">{n}</div><div class="l">{esc(l)}</div>'
                     f'</div>' for (n, l), (c, t) in zip(kpis, KPI_COR))
    fichas = "".join(ficha(c, infos, alertas_por_cct.get(c["id"], [])) for c in principais)
    op_info = "".join(f'<option value="{n}">{esc(i)}</option>' for n, i in enumerate(infos))
    op_st = "".join(f'<option value="{k}">{ROTULO[k]}</option>' for k in ROTULO)
    return f"""
<section class="sec" id="resultado">
  <div class="cab-sec"><p class="rotulo">Resultado por CCT</p>
  <div><button class="btn" id="abrir">Abrir detalhes</button> <button class="btn" id="fechar">Fechar detalhes</button></div></div>
  <div class="kpis">{caixas}</div>
  <div class="filtros">
    <input id="busca" class="busca" type="search" aria-label="Filtrar"
      placeholder="Filtrar por cidade, loja (ex.: 044), sindicato ou registro">
    <label class="campo"><span>Situação</span><select id="f-st"><option value="">Todas</option>{op_st}</select></label>
    <label class="campo"><span>Em qual informação</span><select id="f-info" disabled>
      <option value="">Qualquer uma</option>{op_info}</select></label>
    <button class="btn" id="limpar" type="button">Limpar</button>
  </div>
  <p class="contagem" id="contagem"></p>
  <div class="fichas">{fichas}</div>
</section>"""


def secao_complementares(dados, comps, por_id) -> str:
    if not comps:
        return ""
    itens = []
    for c in comps:
        k = c["complementar"]
        pedidas = []
        for inf, r in c.get("infos", {}).items():
            if r.get("st") != "nao":
                texto = "; ".join(r.get("pontos", []))
                pedidas.append(f"{esc(inf)}: {esc(texto[:1].lower() + texto[1:])}")
        linha_pedidas = ("<p class=pedidas><b>Das informações pedidas:</b> " + "; ".join(pedidas) + "</p>"
                         if pedidas else "<p class=pedidas>Não trata de nenhuma das informações pedidas.</p>")
        if k.get("principal") in por_id:
            p = por_id[k["principal"]]
            principal = f'CCT principal destas lojas: <a href="#{p["_ancora"]}">{esc(p["nome"])}</a>.'
        else:
            principal = esc(k.get("principal_txt", ""))
        itens.append(f"""<article id="{c["_ancora"]}" data-busca="{c["_busca"]}">
  <h3>{esc(c["nome"])} <span>— {esc(k.get("assunto", ""))}</span></h3>
  <p class="doc">{esc(c["_doc"])} · {esc(vencimento(c))} · lojas {esc(", ".join(c["_lojas"]))} ·
  {link_pdf(c, None, "abrir PDF")}</p>
  <ul>{"".join(f"<li>{esc(p)}</li>" for p in k.get("pontos", []))}</ul>{linha_pedidas}
  <p class="pedidas">{principal}</p></article>""")
    return f"""
<section class="sec">
  <p class="rotulo">CCTs complementares</p>
  <p class="detalhe">Acordos curtos sobre outro assunto, que valem junto com a CCT principal das mesmas lojas.</p>
  <div class="comps">{"".join(itens)}</div>
</section>"""


def secao_alertas(dados, por_id) -> str:
    if not dados.get("alertas"):
        return ""
    grupos = []
    for nivel, (nome, acao) in NIVEL.items():  # do mais grave para o mais leve
        meus = [a for a in dados["alertas"] if a["nivel"] == nivel]
        if not meus:
            continue
        itens = []
        for a in meus:
            ids = a.get("ccts", [])
            onde = ", ".join(f'<a href="#{por_id[i]["_ancora"]}">{esc(por_id[i]["nome"])}</a>' for i in ids)
            rotulo = "CCTs" if len(ids) > 1 else "CCT"
            pontos = []
            for p in a.get("pontos", []):
                # marca a quais CCTs o item se refere (pelo nome da cidade), para destacá-lo ao vir da ficha
                citadas = [por_id[i]["_ancora"] for i in ids if slug(por_id[i]["nome"].split(" (")[0]) in slug(p)]
                attr = f' data-ccts="{" ".join(citadas)}"' if citadas else ""
                pontos.append(f"<li{attr}>{esc(p)}</li>")
            pontos = "".join(pontos)
            itens.append(f'<article class="alerta n-{nivel}" id="{a["_ancora"]}"><h3>{esc(a["titulo"])}</h3>'
                         f'<ul>{pontos}</ul>{f"<p class=onde>{rotulo}: {onde}</p>" if onde else ""}</article>')
        grupos.append(f'<div class="nivel"><p class="titulo-nivel"><span class="chip-nivel n-{nivel}">{nome}</span>'
                      f'{acao} <span class="qtd">({len(meus)})</span></p><div class="alertas">{"".join(itens)}'
                      f'</div></div>')
    return f"""
<section class="sec">
  <p class="rotulo">Pontos de atenção</p>
  {"".join(grupos)}
</section>"""


def secao_sobre(dados, indice, principais, ccts) -> str:
    """Fim da página: o que foi procurado, como ler os resultados e como o relatório foi feito."""
    infos = dados["infos"]
    grupo = dados.get("grupo", "analisadas")
    foco = "".join(f'<li style="--c:{COR_INFO[i["nome"]]}"><b>{esc(i["nome"])}</b><span>{esc(i.get("foco", ""))}'
                   f'</span></li>' for i in infos)
    legenda = "".join(f'<li><span class="chip {k}">{icone(k)}{ROTULO[k]}</span>{SIGNIFICADO[k]}</li>' for k in ROTULO)
    comp = len(ccts) - len(principais)
    explica = (f"Várias lojas usam a mesma CCT: os {len(indice['arquivos'])} arquivos da pasta têm "
               f"{len(indice['ccts'])} textos diferentes. Das {len(ccts)} CCTs {grupo}, "
               + ("1 é principal" if len(principais) == 1 else f"{len(principais)} são principais"))
    if comp:
        explica += (" e " + ("1 trata" if comp == 1 else f"{comp} tratam")
                    + " só de outro assunto (horários, feriados, banco de horas).")
    else:
        explica += "."
    passos = [
        ("Sem IA", "Separar", f"Um programa abre os {len(indice['arquivos'])} PDFs da pasta, junta os que têm o "
         f"mesmo texto e separa as CCTs {grupo}."),
        ("Com IA", "Ler", "Para cada CCT, a IA olha a lista de cláusulas e lê só as que falam das informações "
         "pedidas. Ela anota o valor, a cláusula e a página."),
        ("Com IA", "Revisar", "As respostas são juntadas e comparadas. O que falta ou parece errado vira "
         "ponto de atenção."),
        ("Sem IA", "Montar", "Um programa monta esta página e copia do cabeçalho de cada CCT o registro, a "
         "vigência e os sindicatos. Nenhum valor é calculado ou completado por ele."),
    ]
    caixas = "".join(f'<div class="passo {"com-ia" if t == "Com IA" else ""}"><span class="ia">{t}</span>'
                     f'<h3>{i}. {esc(n)}</h3><p>{esc(d)}</p></div>' for i, (t, n, d) in enumerate(passos, 1))
    return f"""
<section class="sec foco">
  <p class="rotulo">Foco desta consulta</p>
  <p>O agente concentrou a análise de cada CCT <b>nestas informações</b>:</p>
  <ul class="foco-lista">{foco}</ul>
  <p class="rotulo" style="margin-top:20px">Como ler os resultados</p>
  <ul class="legenda">{legenda}</ul>
  <p class="detalhe">{esc(explica)}</p>
</section>
<section class="sec">
  <p class="rotulo">Como este relatório foi feito</p>
  <div class="passos">{caixas}</div>
</section>"""


# ------------------------------------------------------------------ página

CSS = """
:root{
  /* tema claro com a identidade do Robô Mediador: verde, cantos retos, rótulos em maiúsculas */
  --fundo:#F3F6F1; --card:#FFFFFF; --card-2:#F7FAF6; --borda:#DCE4D9; --borda-2:#C5D1C1;
  --texto:#0F1A12; --texto-2:#4E6153; --texto-3:#6B7B6E;
  --verde:#1C6D27; --verde-vivo:#5AD46D; --verde-faixa:#1C5A24;
  /* status (validados para daltonismo) e fundos suaves */
  --st-sim:#2E9B45; --st-parcial:#E0A100; --st-nao:#7D8A80;
  --t-sim:#E9F6EC; --t-parcial:#FFF4D4; --t-nao:#F1F3F1;
  /* níveis dos pontos de atenção */
  --n-alto:#C0392B; --n-medio:#E0A100; --n-baixo:#4F7396;
  --t-alto:#FCECEA; --t-medio:#FFF6DC; --t-baixo:#ECF2F8;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--fundo);color:var(--texto);font:14px/1.55 "Segoe UI",system-ui,-apple-system,Roboto,sans-serif;-webkit-print-color-adjust:exact;print-color-adjust:exact}
a{color:var(--verde);text-decoration:none;border-bottom:1px solid #A9D3B1}
a:hover{border-bottom-color:var(--verde)}
h3{font-size:14px;margin:0}
ul{margin:0;padding-left:18px}
.pagina{max-width:1120px;margin:0 auto;padding:24px 30px 40px}
/* faixa do topo, no verde do robô */
.topo{background:var(--verde-faixa);color:#fff;padding:20px 26px 24px;border-bottom:4px solid var(--verde-vivo)}
.linha-topo{display:flex;align-items:center;gap:16px;padding-bottom:16px;margin-bottom:18px;border-bottom:1px solid rgba(255,255,255,.18)}
.marca{width:18px;height:18px;background:var(--verde-vivo);flex:none}
.topo h1{margin:0;flex:1;font-size:26px;font-weight:700;text-transform:uppercase;letter-spacing:.01em}
.topo .data{font-size:11px;font-weight:700;letter-spacing:.06em;color:#D6F0DA;border:1px solid rgba(255,255,255,.3);padding:9px 14px}
.topo .rotulo{color:#A9DDB2}
.topo .pedido{margin:0 0 6px;font-size:22px;font-weight:700;line-height:1.3}
.topo .detalhe{color:#CFE8D3;margin:0}
.sec{padding:24px 0;border-bottom:1px solid var(--borda)}
.rotulo{margin:0 0 10px;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--texto-2)}
.detalhe{margin:8px 0 0;font-size:13px;color:var(--texto-2)}
.foco p{margin:0 0 10px}
.foco-lista{list-style:none;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}
.foco-lista li{background:var(--card);border:1px solid var(--borda);border-top:4px solid var(--c);padding:12px 14px}
.foco-lista b{display:flex;align-items:center;gap:8px;margin-bottom:4px}
.foco-lista b::before{content:"";width:10px;height:10px;background:var(--c);flex:none}
.foco-lista span{font-size:12.5px;color:var(--texto-2)}
.legenda{list-style:none;padding:0;display:flex;flex-wrap:wrap;gap:10px 26px;font-size:13px;color:var(--texto-2)}
.legenda li{display:flex;align-items:center;gap:8px}
.chip{display:inline-flex;align-items:center;font-weight:700;color:var(--texto);padding:3px 10px;font-size:12.5px}
.chip.sim{background:var(--t-sim)} .chip.parcial{background:var(--t-parcial)} .chip.nao{background:var(--t-nao)}
.ic{flex:none;vertical-align:-1px;margin-right:6px}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.kpi{padding:14px 16px;border-left:4px solid var(--c);background:var(--t)}
.kpi .n{font-size:28px;font-weight:700;color:var(--c);line-height:1.15}
.kpi .l{font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--texto-2)}
/* pontos de atenção */
.nv{display:inline-block;width:9px;height:9px;margin-right:7px;vertical-align:0}
.nv.n-alto{background:var(--n-alto)} .nv.n-medio{background:var(--n-medio)} .nv.n-baixo{background:var(--n-baixo)}
.nivel+.nivel{margin-top:18px}
.titulo-nivel{margin:0 0 8px;font-size:13px;color:var(--texto-2);display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.chip-nivel{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;padding:3px 10px;color:#fff}
.chip-nivel.n-alto{background:var(--n-alto)} .chip-nivel.n-medio{background:var(--n-medio);color:#231a00} .chip-nivel.n-baixo{background:var(--n-baixo)}
.titulo-nivel .qtd{color:var(--texto-3)}
.alertas{display:grid;gap:6px}
.alerta{background:var(--t-baixo);border-left:4px solid var(--n-baixo);padding:10px 16px;scroll-margin-top:12px}
.alerta.n-alto{background:var(--t-alto);border-left-color:var(--n-alto)}
.alerta.n-medio{background:var(--t-medio);border-left-color:var(--n-medio)}
.alerta h3{margin-bottom:3px}
.alerta ul{font-size:13px;color:#33463A}
.alerta .onde{margin:6px 0 0;font-size:12.5px;color:var(--texto-2)}
/* destaque ao chegar pela ficha de uma CCT */
.alerta.destaque{box-shadow:0 0 0 3px var(--verde-vivo);animation:pulso 1.4s ease-out 1}
@keyframes pulso{0%{box-shadow:0 0 0 12px rgba(90,212,109,0)}35%{box-shadow:0 0 0 7px rgba(90,212,109,.55)}100%{box-shadow:0 0 0 3px var(--verde-vivo)}}
.alerta li.marcado{background:rgba(90,212,109,.3);color:var(--texto);font-weight:600;padding:0 6px;margin-left:-6px}
.alerta a.marcado{background:rgba(90,212,109,.3);font-weight:700;padding:0 3px}
.alerta .voltar{display:inline-block;margin-top:8px;font-size:12px;font-weight:700}
@media (prefers-reduced-motion:reduce){.alerta.destaque{animation:none}}
/* filtros */
.busca{width:100%;margin:12px 0;padding:12px 14px;font:inherit;font-size:13px;color:var(--texto);background:var(--card);border:1px solid var(--borda-2);border-radius:0}
.busca:focus{outline:none;border-color:var(--verde)}
.busca::placeholder{color:var(--texto-3)}
.filtros{display:flex;flex-wrap:wrap;align-items:flex-end;gap:10px;margin:16px 0 8px}
.filtros .busca{flex:1 1 280px;margin:0}
.campo{display:flex;flex-direction:column;gap:3px}
.campo span{font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--texto-2)}
.campo select{font:inherit;font-size:13px;padding:11px 10px;min-width:170px;color:var(--texto);background:var(--card);border:1px solid var(--borda-2);border-radius:0;cursor:pointer}
.campo select:focus{outline:none;border-color:var(--verde)}
.campo select:disabled{color:var(--texto-3);background:var(--fundo);cursor:not-allowed}
.campo:has(select:disabled) span{color:var(--texto-3)}
.filtros .btn{padding:12px 14px}
.contagem{margin:0 0 10px;font-size:12.5px;color:var(--texto-2)}
/* fichas: uma por CCT, com tudo à vista */
.fichas{display:grid;gap:16px}
.ficha{background:var(--card);border:1px solid var(--borda);border-top:4px solid var(--verde-vivo);scroll-margin-top:12px;min-width:0}
.ficha.s-vencida{border-top-color:var(--n-alto)}
.ficha.s-futura{border-top-color:var(--n-baixo)}
.f-cab{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-start;gap:8px 16px;padding:14px 18px 12px}
.f-cab h3{font-size:19px;line-height:1.25}
.f-cab .doc{margin:2px 0 0;font-size:12.5px;color:var(--texto-2)}
.sit{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;padding:6px 10px;background:var(--t-sim);color:var(--verde);white-space:nowrap}
.s-vencida .sit{background:var(--t-alto);color:var(--n-alto)}
.s-futura .sit{background:var(--t-baixo);color:var(--n-baixo)}
.s-sem_vigencia .sit{background:var(--t-nao);color:var(--texto-2)}
.f-dados{display:grid;grid-template-columns:3fr 3fr 2fr 2fr;gap:2px;margin:0 18px}
.f-dados div{background:var(--fundo);padding:8px 12px;min-width:0}
.f-dados .dois{grid-column:span 2}
.f-dados dt,.f-rot{font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--texto-2)}
.f-dados dd{margin:2px 0 0;font-size:12.5px;overflow-wrap:anywhere}
.sind{display:block}
.sind+.sind{margin-top:4px}
.cnpj{display:block;font-size:11.5px;color:var(--texto-3)}
.f-corpo{padding:14px 18px 16px}
.f-rot{display:flex;align-items:center;margin:0 0 6px}
.pisos{width:100%;border-collapse:collapse;font-size:13.5px}
.pisos th{text-align:left;font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--texto-2);padding:6px 12px;border-bottom:2px solid var(--borda-2);background:#EEF3EC}
.pisos td{padding:7px 12px;border-bottom:1px solid var(--borda);vertical-align:top}
.pisos td.num{font-weight:700;white-space:nowrap;font-variant-numeric:tabular-nums}
.pisos td:last-child{white-space:nowrap;color:var(--texto-2)}
.pisos .nota{display:block;font-size:12px;color:#7A5B00}
.f-vazio{margin:0;color:var(--texto-3)}
.f-grade{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:8px;margin-top:14px}
.f-grade:first-child{margin-top:0}
.f-info{padding:10px 12px;background:var(--t-sim);border-left:4px solid var(--st-sim);min-width:0}
.f-info.parcial{background:var(--t-parcial);border-left-color:var(--st-parcial)}
.f-info.nao{background:var(--t-nao);border-left-color:var(--st-nao)}
.f-val{margin:0;font-size:13.5px}
.f-info.nao .f-val{color:var(--texto-3)}
.grande{margin:0 0 2px;font-size:30px;font-weight:700;line-height:1.1}
.grande small{font-size:13px;font-weight:600;color:var(--texto-2);margin-left:6px}
.f-alertas{margin-top:14px;font-size:13px}
.f-alertas ul{list-style:none;padding:0}
.f-det{border-top:1px solid var(--borda);padding:0 18px}
.f-det>summary{cursor:pointer;padding:11px 0;font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--verde)}
.f-det-corpo{padding-bottom:14px}
/* detalhes e fontes */
.cab-sec{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px;margin-bottom:12px}
.cab-sec .rotulo{margin:0}
.btn{font:inherit;font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--verde);background:var(--card);border:1px solid var(--borda-2);padding:9px 14px;cursor:pointer}
.btn:hover{background:var(--t-sim)}
.arquivos{font-size:12px;color:var(--texto-3);margin:0 0 4px}
.arquivos summary{cursor:pointer;color:var(--texto-2)}
.arquivos summary b{font-weight:600}
.arquivos ul{list-style:none;padding:4px 0 0 18px;word-break:break-word}
.arquivos li{padding:1px 0}
.info{display:grid;grid-template-columns:170px 1fr;gap:6px 16px;padding:12px 0;border-top:1px solid var(--borda)}
.info:first-of-type{margin-top:10px}
.info .rot{font-weight:700;border-left:4px solid var(--c);padding-left:10px}
.info .st{display:block;font-weight:400;font-size:12.5px;color:var(--texto-2);margin-top:2px}
.info ul{font-size:13.5px}
.fonte{margin:6px 0 0;font-size:12px;color:var(--texto-2)}
.trecho summary{cursor:pointer;font-size:12px;color:var(--verde);margin-top:2px}
.trecho blockquote{margin:6px 0 0;padding:6px 12px;border-left:3px solid var(--c,var(--borda-2));background:var(--fundo);font-size:12.5px;color:var(--texto-2)}
.obs{margin-top:8px;padding-top:10px;border-top:1px solid var(--borda);font-size:13px;color:var(--texto-2)}
.obs b{color:var(--texto)}
/* complementares e como foi feito */
.comps{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:12px}
.comps article{background:var(--card);border:1px solid var(--borda);border-top:4px solid var(--n-baixo);padding:14px 16px;font-size:13px;scroll-margin-top:12px}
.comps h3 span{font-weight:400;color:var(--texto-2)}
.comps .doc{margin:2px 0 8px;font-size:12px;color:var(--texto-2)}
.comps ul{color:var(--texto-2)}
.pedidas{margin:8px 0 0;color:var(--texto-2)}
.passos{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.passo{background:var(--card);border:1px solid var(--borda);border-top:4px solid var(--n-baixo);padding:14px 16px}
.passo.com-ia{border-top-color:var(--verde-vivo)}
.passo h3{margin:8px 0 4px}
.passo p{margin:0;font-size:13px;color:var(--texto-2)}
.ia{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;padding:3px 8px;color:#fff;background:var(--n-baixo)}
.com-ia .ia{background:var(--verde-faixa)}
footer{padding-top:18px;font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--texto-3)}
.oculto{display:none!important}
@media (max-width:860px){
  .comps{grid-template-columns:minmax(0,1fr)}
  .passos,.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
  .f-dados{grid-template-columns:1fr 1fr}
}
@media (max-width:560px){
  .pagina{padding:16px 16px 32px}
  .topo{padding:16px}
  .topo h1{font-size:19px}
  .topo .pedido{font-size:18px}
  .info{grid-template-columns:1fr}
  .passos,.f-dados{grid-template-columns:minmax(0,1fr)}
  .f-dados .dois{grid-column:auto}
  .f-cab,.f-corpo,.f-det{padding-left:12px;padding-right:12px}
  .f-dados{margin:0 12px}
  .pisos th,.pisos td{padding:6px 8px}
}
@media print{
  body{background:#fff}
  .busca,.btn,.filtros{display:none}
  .ficha,.alerta{break-inside:avoid}
}
"""

JS = """
const norm = s => s.normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase();
// filtros das fichas: texto (cidade, loja, sindicato, registro) + informação + situação
const busca = document.getElementById('busca');
const fInfo = document.getElementById('f-info');
const fSt = document.getElementById('f-st');
const contagem = document.getElementById('contagem');
function filtrar() {
  const q = norm(busca.value.trim()).replace(/[^a-z0-9]+/g, '-');
  // a informação só filtra junto com uma situação (toda CCT tem todas as informações)
  fInfo.disabled = !fSt.value;
  if (!fSt.value) fInfo.value = '';
  const inf = fInfo.value, st = fSt.value;
  let vistas = 0, total = 0;
  document.querySelectorAll('.ficha').forEach(el => {
    const sts = el.dataset.st.split(',');
    const ok = (!q || el.dataset.busca.includes(q)) &&
               (!st || (inf === '' ? sts.includes(st) : sts[+inf] === st));
    el.classList.toggle('oculto', !ok);
    total++; if (ok) vistas++;
  });
  document.querySelectorAll('.comps [data-busca]').forEach(el =>
    el.classList.toggle('oculto', q !== '' && !el.dataset.busca.includes(q)));
  const filtro = st ? ' · ' + fSt.options[fSt.selectedIndex].text + ' em ' +
                 (inf === '' ? 'alguma informação' : fInfo.options[fInfo.selectedIndex].text) : '';
  contagem.textContent = (vistas === total && !q && !st) ? 'Mostrando as ' + total + ' CCTs'
                        : 'Mostrando ' + vistas + ' de ' + total + ' CCTs' + filtro;
}
busca.addEventListener('input', filtrar);
fInfo.addEventListener('change', filtrar);
fSt.addEventListener('change', filtrar);
function limparFiltros() { busca.value = ''; fInfo.value = ''; fSt.value = ''; filtrar(); }
document.getElementById('limpar').onclick = limparFiltros;
filtrar();
function ir(id) {
  const el = document.getElementById(id);
  if (!el) return;
  if (el.classList.contains('oculto')) limparFiltros();  // a ficha estava escondida por um filtro
  el.scrollIntoView({behavior: 'smooth', block: 'start'});
}
// ponto de atenção clicado na ficha de uma CCT: vai até ele e destaca o que é daquela CCT
function limparDestaque() {
  document.querySelectorAll('.destaque, .marcado').forEach(el => el.classList.remove('destaque', 'marcado'));
  document.querySelectorAll('.alerta .voltar').forEach(el => el.remove());
}
function destacarAlerta(alerta, cct, nome) {
  limparDestaque();
  alerta.classList.add('destaque');
  alerta.querySelectorAll('li[data-ccts]').forEach(li => {
    if (li.dataset.ccts.split(' ').includes(cct)) li.classList.add('marcado');
  });
  const link = alerta.querySelector('.onde a[href="#' + cct + '"]');
  if (link) link.classList.add('marcado');
  const voltar = document.createElement('a');
  voltar.href = '#' + cct; voltar.className = 'voltar'; voltar.textContent = '↩ Voltar para ' + nome;
  alerta.appendChild(voltar);
  alerta.scrollIntoView({behavior: 'smooth', block: 'center'});
}
document.addEventListener('click', e => {
  limparDestaque();  // o destaque é passageiro: qualquer clique na página tira
  const a = e.target.closest('a[href^="#"]');
  if (!a) return;
  e.preventDefault();
  const alvo = document.getElementById(a.getAttribute('href').slice(1));
  if (a.dataset.de && alvo) { destacarAlerta(alvo, a.dataset.de, a.dataset.nome); return; }
  ir(a.getAttribute('href').slice(1));
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') limparDestaque(); });
document.getElementById('abrir').onclick = () => document.querySelectorAll('.f-det').forEach(d => d.open = true);
document.getElementById('fechar').onclick = () => document.querySelectorAll('.f-det').forEach(d => d.open = false);
"""


def montar(dados, indice, hoje) -> str:
    COR_INFO.clear()
    for n, inf in enumerate(dados["infos"]):  # sem repetir cor: da 6ª informação em diante, cinza
        COR_INFO[inf["nome"]] = COR["infos"][n] if n < len(COR["infos"]) else COR["outra"]
    ccts = dados["ccts"]
    por_id = {c["id"]: c for c in ccts}
    principais = [c for c in ccts if not c["_complementar"]]
    comps = [c for c in ccts if c["_complementar"]]
    alertas_por_cct = {}
    for i, a in enumerate(dados.get("alertas", []), 1):
        a["_ancora"] = f"alerta-{i}"
        for cid in a.get("ccts", []):
            alertas_por_cct.setdefault(cid, []).append(a)
    for lista in alertas_por_cct.values():
        lista.sort(key=lambda a: list(NIVEL).index(a["nivel"]))
    corpo = (secao_topo(dados, hoje)
             + secao_resultado(dados, indice, principais, ccts, alertas_por_cct)
             + secao_complementares(dados, comps, por_id)
             + secao_alertas(dados, por_id)
             + secao_sobre(dados, indice, principais, ccts))
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Consulta de CCTs</title><style>{CSS}</style></head>
<body><div class="pagina">{corpo}
<footer>Gerado automaticamente pelo agente de consulta de CCTs · {hoje:%d/%m/%Y}</footer>
</div><script>{JS}</script></body></html>
"""


def conferir(dados, indice):
    """Para cedo, com mensagem clara, se o JSON tiver algo que o relatório não sabe mostrar."""
    erros = []
    nomes = [i["nome"] for i in dados.get("infos", [])]
    for c in dados.get("ccts", []):
        if c.get("id") not in indice["ccts"]:
            erros.append(f"CCT '{c.get('nome')}': id '{c.get('id')}' não está no índice")
            continue
        if c.get("complementar"):
            continue
        for inf in nomes:
            r = c.get("infos", {}).get(inf)
            if not r or r.get("st") not in ROTULO:
                erros.append(f"CCT '{c['nome']}': falta '{inf}' ou o status não é sim/parcial/nao")
                continue
            for p in r.get("pisos", []):
                if not p.get("funcao") or not p.get("valor"):
                    erros.append(f"CCT '{c['nome']}', {inf}: todo piso precisa de 'funcao' e 'valor'")
                    break
    for a in dados.get("alertas", []):
        if a.get("nivel") not in NIVEL:
            erros.append(f"Ponto de atenção '{a.get('titulo')}': nível deve ser alto, medio ou baixo")
        for cid in a.get("ccts", []):
            if cid not in {c.get("id") for c in dados.get("ccts", [])}:
                erros.append(f"Ponto de atenção '{a.get('titulo')}': id '{cid}' não está entre as CCTs do JSON")
    if erros:
        sys.exit("Corrija o resultado.json:\n- " + "\n- ".join(erros))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    caminho = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJETO / "saida" / "resultado.json"
    bruto = json.loads(caminho.read_text(encoding="utf-8"))
    conferir(bruto, f._carregar_indice())
    dados, indice, hoje = carregar(caminho)
    destino = Path(sys.argv[2]) if len(sys.argv) > 2 else PROJETO / "saida" / "consulta.html"
    destino.write_text(montar(dados, indice, hoje), encoding="utf-8")
    principais = sum(1 for c in dados["ccts"] if not c["_complementar"])
    print(f"Relatório salvo em {destino} ({principais} CCTs principais, "
          f"{len(dados['ccts']) - principais} complementares, {len(dados.get('alertas', []))} pontos de atenção)")


if __name__ == "__main__":
    main()
