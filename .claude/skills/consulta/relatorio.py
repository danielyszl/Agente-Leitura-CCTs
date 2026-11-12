"""
Monta o relatório da consulta (saida/consulta.html) a partir das respostas em saida/resultado.json.

    python .claude/skills/consulta/relatorio.py
    python .claude/skills/consulta/relatorio.py saida/resultado.json saida/outro.html

Não usa IA: só organiza o que o agente já leu. O formato do JSON está em modelo.json (mesma pasta).
Documento (registro no MTE), vigência, arquivos e lojas vêm do índice do ferramentas.py,
por isso o relatório nunca mostra o código interno (id) das CCTs.
Visual: tema claro com a identidade do Robô Mediador (verde, cantos retos, rótulos em maiúsculas).
Cada informação pedida ganha uma cor, usada nos cartões do topo, na tabela e no gráfico dela.
"""
import json
import math
import re
import sys
import unicodedata
from datetime import date
from html import escape
from pathlib import Path

PROJETO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJETO))
sys.dont_write_bytecode = True  # não cria a pasta __pycache__ no projeto
import ferramentas as f  # noqa: E402  (índice, textos e registro no MTE)

ROTULO = {"sim": "Encontrado", "parcial": "Parcial", "nao": "Não consta"}
SIGNIFICADO = {"sim": "a CCT traz a informação completa.",
               "parcial": "a CCT traz só uma parte (falta um valor, um percentual ou um dos anos).",
               "nao": "a CCT não trata do assunto."}
NIVEL = {"alto": ("Alto", "resolva antes de usar o dado"),
         "medio": ("Médio", "confira no PDF antes de usar"),
         "baixo": ("Baixo", "só para saber; não muda o resultado")}
UF = {"RS": "Rio Grande do Sul", "SC": "Santa Catarina", "PR": "Paraná", "MS": "Mato Grosso do Sul",
      "SP": "São Paulo", "MT": "Mato Grosso", "GO": "Goiás", "MG": "Minas Gerais", "RJ": "Rio de Janeiro"}
# Cores validadas para daltonismo sobre fundo branco (script validate_palette da skill de gráficos).
# A ordem importa: cores parecidas nunca ficam lado a lado.
COR = {"sim": "#2E9B45", "parcial": "#E0A100", "nao": "#7D8A80", "outra": "#7D8A80",
       "infos": ["#2a78d6", "#e87ba4", "#6250d6", "#eb6834", "#1baf7a"],  # 1 por informação pedida
       "fatias": ["#2a78d6", "#eb6834", "#6250d6", "#1baf7a"]}
COR_INFO = {}  # nome da informação -> cor (preenchido em montar)
# Números do resumo: (cor do número, fundo do cartão)
KPI_COR = [("#1c5cab", "#EAF2FC"), ("#4a3aa7", "#EFEDFB"), ("#B8461C", "#FDEEE7"), ("#1C6D27", "#E9F6EC")]
SIGLAS = {"MTE", "TST", "CLT", "REPIS", "DSR", "ME", "EPP", "PN", "CCT", "SINDECSAP", "INPC", "SC", "RS",
          "PR", "MS"}


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


def quebrar(nome: str, largura: int = 11, linhas: int = 2) -> list[str]:
    """Quebra um nome em até 2 linhas curtas (rótulos das colunas)."""
    saida, atual = [], ""
    for p in nome.split():
        if atual and len(atual) + 1 + len(p) > largura:
            saida.append(atual)
            atual = p
        else:
            atual = f"{atual} {p}".strip()
    saida.append(atual)
    if len(saida) > linhas:
        saida = saida[:linhas]
        saida[-1] = saida[-1][: largura - 1] + "…"
    return saida


def icone(st: str) -> str:
    """Quadrado cheio, meio cheio ou vazio: a forma diz o status mesmo sem cor."""
    c = COR[st]
    borda = f'<rect x="1.5" y="1.5" width="9" height="9" fill="none" stroke="{c}" stroke-width="1.5"/>'
    corpo = {"sim": f'<rect x="1" y="1" width="10" height="10" fill="{c}"/>',
             "parcial": borda + f'<rect x="1" y="1" width="5.5" height="10" fill="{c}"/>',
             "nao": borda}[st]
    return f'<svg class="ic" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">{corpo}</svg>'


def tip(titulo: str, valor: str, nota: str = "") -> str:
    """Atributos do balão que aparece ao passar o mouse (ou focar com o teclado)."""
    extra = f' data-tip-n="{esc(nota)}"' if nota else ""
    return f'tabindex="0" data-tip-t="{esc(titulo)}" data-tip-v="{esc(valor)}"{extra}'


# ------------------------------------------------------------------ dados

def carregar(caminho: Path):
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    indice = f._carregar_indice()
    hoje = date.fromisoformat(dados.get("data") or date.today().isoformat())
    arquivos_por_id = {}
    for a in indice["arquivos"].values():
        if a["id"]:
            arquivos_por_id.setdefault(a["id"], []).append(a["arquivo"])
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
        c.update({
            "_arquivos": arquivos,
            "_lojas": sorted({a.split("_")[0] for a in arquivos}),
            "_registro": registro,
            "_uf": registro[:2] if registro else "?",
            "_tipo": tipo,
            "_doc": f"{curto} · registro {registro}" if registro else curto,
            "_ini": m["vigencia_inicio"],
            "_fim": m["vigencia_fim"],
            "_atraso": (hoje - date.fromisoformat(m["vigencia_fim"])).days if m["vigencia_fim"] else None,
            "_data_base": m.get("data_base") or "",
            "_ancora": ancora,
            "_complementar": bool(c.get("complementar")),
        })
        c["_busca"] = slug(" ".join([c["nome"], registro, c["_uf"], " ".join(arquivos), " ".join(c["_lojas"])]))
    dados["ccts"].sort(key=lambda c: (c["_fim"], c["nome"]))
    return dados, indice, hoje


def vencimento(c) -> str:
    if c["_atraso"] is None:
        return "sem vigência no texto"
    if c["_atraso"] > 0:
        return f"venceu {br(c['_fim'])} · {c['_atraso']} dias"
    return f"vale até {br(c['_fim'])}"


# ------------------------------------------------------------------ gráficos

def grafico_cobertura(infos, principais) -> str:
    """Barras empilhadas: em quantas CCTs cada informação foi encontrada."""
    largura, rot, linha, alt = 470, 120, 38, 20
    total = len(principais)
    partes = []
    for i, inf in enumerate(infos):
        y = 6 + i * linha
        partes.append(f'<text x="0" y="{y + alt / 2}" class="g-rot" dominant-baseline="middle">{esc(inf)}</text>')
        cont = {k: sum(1 for c in principais if c["infos"][inf]["st"] == k) for k in ROTULO}
        ativos = [k for k in ROTULO if cont[k]]
        x = rot
        for j, k in enumerate(ativos):
            w = (largura - rot) * cont[k] / total
            w_desenho = w - (2 if j < len(ativos) - 1 else 0)  # 2px de respiro entre os pedaços
            partes.append(f'<rect x="{x:.1f}" y="{y}" width="{w_desenho:.1f}" height="{alt}" fill="{COR[k]}" '
                          f'{tip(inf, f"{ROTULO[k]}: {cont[k]} de {total} CCTs")}/>')
            if w_desenho >= 22:
                partes.append(f'<text x="{x + w_desenho / 2:.1f}" y="{y + alt / 2}" class="g-in" fill="#0F1A12" '
                              f'text-anchor="middle" dominant-baseline="central">{cont[k]}</text>')
            x += w
    altura = 6 + len(infos) * linha
    legenda = "".join(f'<span>{icone(k)}{ROTULO[k]}</span>' for k in ROTULO)
    return (f'<div class="graf" style="--c:{COR["sim"]}"><h3>O que foi encontrado</h3>'
            f'<p class="sub">nº de CCTs principais, de {total}</p>'
            f'<div class="leg">{legenda}</div><div class="svg-wrap"><svg viewBox="0 0 {largura} {altura}" '
            f'style="min-width:380px" role="img" aria-label="Quantas CCTs trazem cada informação">'
            f'{"".join(partes)}</svg></div></div>')


def grafico_estados(ccts) -> str:
    """Rosca: lojas por estado (a sigla vem do registro no MTE)."""
    por_uf = {}
    for c in ccts:
        por_uf.setdefault(c["_uf"], set()).update(c["_lojas"])
    itens = sorted(((uf, len(l)) for uf, l in por_uf.items()), key=lambda t: (-t[1], t[0]))
    total = len({l for c in ccts for l in c["_lojas"]})
    soma = sum(n for _, n in itens)
    r, espessura, cx = 64, 20, 90
    volta = 2 * math.pi * r
    partes, legenda, inicio = [], [], 0.0
    for i, (uf, n) in enumerate(itens):
        cor = COR["fatias"][i] if i < len(COR["fatias"]) else COR["outra"]
        comp = volta * n / soma
        pct = round(100 * n / soma)
        nome_uf = UF.get(uf, uf)
        partes.append(f'<circle cx="{cx}" cy="{cx}" r="{r}" fill="none" stroke="{cor}" stroke-width="{espessura}" '
                      f'stroke-dasharray="{max(comp - 2, 0.5):.2f} {volta:.2f}" stroke-dashoffset="{-inicio:.2f}" '
                      f'transform="rotate(-90 {cx} {cx})" {tip(nome_uf, f"{n} lojas · {pct}%")}/>')
        legenda.append(f'<li><span class="sw" style="background:{cor}"></span><b>{esc(uf)}</b> '
                       f'<span class="m">{esc(nome_uf)}</span><span class="n">{n} lojas · {pct}%</span></li>')
        inicio += comp
    centro = (f'<text x="{cx}" y="{cx - 4}" text-anchor="middle" class="g-centro">{total}</text>'
              f'<text x="{cx}" y="{cx + 16}" text-anchor="middle" class="g-rot">lojas</text>')
    return (f'<div class="graf" style="--c:{COR["fatias"][0]}"><h3>Lojas por estado</h3>'
            f'<p class="sub">lojas que usam alguma destas CCTs</p>'
            f'<div class="pizza"><svg viewBox="0 0 180 180" width="180" height="180" role="img" '
            f'aria-label="Lojas por estado">{"".join(partes)}{centro}</svg><ul class="leg-lista">'
            f'{"".join(legenda)}</ul></div></div>')


def grafico_valores(g, principais) -> str:
    """Barras (horizontais) ou colunas com um número por CCT, do maior para o menor."""
    inf, unidade = g["info"], g.get("unidade", "")
    itens = [(c, c["infos"][inf]) for c in principais
             if isinstance(c["infos"].get(inf, {}).get("valor"), (int, float))]
    if not itens:
        return ""
    itens.sort(key=lambda t: (-t[1]["valor"], t[0]["nome"]))
    vmax = max(r["valor"] for _, r in itens)
    tem_nota = any(r.get("nota") for _, r in itens)
    cor = COR_INFO.get(inf, COR["outra"])  # a mesma cor da informação no resto da página
    partes = []

    def marca(x, y, w, h, c, r):
        valor = numero(r["valor"], unidade)
        dica = tip(c["nome"], valor, r.get("nota", ""))
        if r.get("nota"):  # valor com ressalva: só o contorno
            return (f'<rect x="{x + 1:.1f}" y="{y + 1:.1f}" width="{max(w - 2, 0):.1f}" '
                    f'height="{max(h - 2, 0):.1f}" fill="#fff" stroke="{cor}" stroke-width="2" {dica}/>')
        return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{cor}" {dica}/>'

    if g.get("forma") == "colunas":
        largura, topo, plot, faixa = 1000, 22, 190, 40
        passo = (largura - 10) / len(itens)
        w = min(24, passo * .5)
        for i, (c, r) in enumerate(itens):
            h = plot * r["valor"] / vmax
            x = 5 + i * passo + (passo - w) / 2
            y = topo + plot - h
            partes.append(marca(x, y, w, h, c, r))
            partes.append(f'<text x="{x + w / 2:.1f}" y="{y - 6:.1f}" text-anchor="middle" class="g-val">'
                          f'{esc(numero(r["valor"], unidade))}</text>')
            for k, linha in enumerate(quebrar(c.get("curto") or c["nome"])):
                partes.append(f'<text x="{x + w / 2:.1f}" y="{topo + plot + 16 + k * 14}" text-anchor="middle" '
                              f'class="g-rot">{esc(linha)}</text>')
        partes.append(f'<line x1="0" x2="{largura}" y1="{topo + plot}" y2="{topo + plot}" class="g-base"/>')
        caixa, minimo = (largura, topo + plot + faixa), 860
    else:
        largura, rot, linha, h = 1000, 200, 28, 14
        valor_w = 110
        for i, (c, r) in enumerate(itens):
            y = 4 + i * linha
            w = (largura - rot - valor_w) * r["valor"] / vmax
            partes.append(f'<text x="0" y="{y + h / 2}" class="g-rot" dominant-baseline="central">'
                          f'{esc(c.get("curto") or c["nome"])}</text>')
            partes.append(marca(rot, y, w, h, c, r))
            partes.append(f'<text x="{rot + w + 8:.1f}" y="{y + h / 2}" class="g-val" dominant-baseline="central">'
                          f'{esc(numero(r["valor"], unidade))}</text>')
        partes.append(f'<line x1="{rot}" x2="{rot}" y1="0" y2="{len(itens) * linha}" class="g-base"/>')
        caixa, minimo = (largura, len(itens) * linha + 4), 760
    nota = (f'<p class="nota-graf"><span class="sw vazio" style="border-color:{cor}"></span>Contorno: valor com '
            f'ressalva. Passe o mouse para ver o motivo.</p>') if tem_nota else ""
    return (f'<div class="graf largo" style="--c:{cor}"><h3>{esc(g["titulo"])}</h3>'
            f'<p class="sub">{esc(g.get("subtitulo", ""))}</p>'
            f'<div class="svg-wrap"><svg viewBox="0 0 {caixa[0]} {caixa[1]}" style="min-width:{minimo}px" '
            f'role="img" aria-label="{esc(g["titulo"])}">{"".join(partes)}</svg></div>{nota}</div>')


# ------------------------------------------------------------------ seções

def secao_topo(dados, indice, hoje, principais, ccts) -> str:
    infos = dados["infos"]
    lojas = {l for c in ccts for l in c["_lojas"]}
    n_arquivos = sum(len(c["_arquivos"]) for c in ccts)
    grupo = dados.get("grupo", "analisadas")
    foco = "".join(f'<li style="--c:{COR_INFO[i["nome"]]}"><b>{esc(i["nome"])}</b><span>{esc(i.get("foco", ""))}'
                   f'</span></li>' for i in infos)
    legenda = "".join(f'<li><span class="chip {k}">{icone(k)}{ROTULO[k]}</span>{SIGNIFICADO[k]}</li>' for k in ROTULO)
    comp = len(ccts) - len(principais)
    explica = (f"Várias lojas usam a mesma CCT: os {len(indice['arquivos'])} arquivos têm {len(indice['ccts'])} "
               f"textos diferentes. Das {len(ccts)} CCTs {grupo}, {len(principais)} são principais")
    explica += (f" e {comp} tratam só de outro assunto (horários, feriados, banco de horas)." if comp else ".")
    kpis = [(len(indice["arquivos"]), "arquivos na pasta"), (len(indice["ccts"]), "CCTs diferentes"),
            (len(ccts), f"CCTs {grupo}"), (len(lojas), f"lojas ({n_arquivos} arquivos)")]
    caixas = "".join(f'<div class="kpi" style="--c:{c};--t:{t}"><div class="n">{n}</div><div class="l">{esc(l)}</div>'
                     f'</div>' for (n, l), (c, t) in zip(kpis, KPI_COR))
    return f"""
<header class="topo">
  <div class="linha-topo"><div class="marca"></div><h1>Consulta de CCTs</h1><div class="data">{hoje:%d/%m/%Y}</div></div>
  <p class="rotulo">Pedido</p>
  <p class="pedido">{esc(dados["pedido"])}</p>
  <p class="detalhe">{esc(dados.get("filtro", ""))} Fonte: CCTs baixadas do Mediador.</p>
</header>
<section class="sec foco">
  <p class="rotulo">Foco desta consulta</p>
  <p>O agente procurou <b>só estas {len(infos)} informações</b> em cada CCT:</p>
  <ul class="foco-lista">{foco}</ul>
  <p class="aviso">As CCTs têm muitas outras cláusulas (jornada, benefícios, contribuições…) que ficaram fora
  desta consulta. Para outro assunto, faça uma nova consulta.</p>
  <p class="rotulo" style="margin-top:20px">Como ler os resultados</p>
  <ul class="legenda">{legenda}</ul>
</section>
<section class="sec">
  <p class="rotulo">Resumo</p>
  <div class="kpis">{caixas}</div>
  <p class="detalhe">{esc(explica)}</p>
</section>"""


def secao_graficos(dados, principais, ccts) -> str:
    infos = [i["nome"] for i in dados["infos"]]
    blocos = [grafico_cobertura(infos, principais), grafico_estados(ccts)]
    blocos += [grafico_valores(g, principais) for g in dados.get("graficos", [])]
    return f"""
<section class="sec">
  <p class="rotulo">Panorama</p>
  <div class="graficos">{"".join(b for b in blocos if b)}</div>
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
            pontos = "".join(f"<li>{esc(p)}</li>" for p in a.get("pontos", []))
            itens.append(f'<article class="alerta n-{nivel}" id="{a["_ancora"]}"><h3>{esc(a["titulo"])}</h3>'
                         f'<ul>{pontos}</ul>{f"<p class=onde>{rotulo}: {onde}</p>" if onde else ""}</article>')
        grupos.append(f'<div class="nivel"><p class="titulo-nivel"><span class="chip-nivel n-{nivel}">{nome}</span>'
                      f'{acao} <span class="qtd">({len(meus)})</span></p><div class="alertas">{"".join(itens)}'
                      f'</div></div>')
    return f"""
<section class="sec">
  <p class="rotulo">Pontos de atenção</p>
  <p class="detalhe" style="margin:0 0 14px">Do mais importante para o menos importante.</p>
  {"".join(grupos)}
</section>"""


def secao_tabela(dados, principais) -> str:
    infos = [i["nome"] for i in dados["infos"]]
    linhas = []
    for c in principais:
        celulas = []
        for inf in infos:
            r = c["infos"][inf]
            fonte = f'Fonte: {frase(r["clausula"])} · pág. {r.get("pag", "?")}' if r.get("clausula") else ""
            if r["st"] == "nao":
                texto = "Não consta" + (f' · {r["curta"]}' if r.get("curta") else "")
            else:
                texto = r.get("curta") or ROTULO[r["st"]]
            celulas.append(f'<td class="c-{r["st"]}" title="{esc(fonte)}"><span class="cel {r["st"]}">{icone(r["st"])}'
                           f'<span>{esc(texto)}</span></span></td>')
        linhas.append(f'<tr data-alvo="{c["_ancora"]}" data-busca="{c["_busca"]}" tabindex="0"><td class="cct">'
                      f'<b>{esc(c["nome"])}</b><span class="doc">{esc(c["_doc"])}</span>'
                      f'<span class="venc">{esc(vencimento(c))}</span></td>{"".join(celulas)}</tr>')
    cab = "".join(f'<th style="--c:{COR_INFO[i]}">{esc(i)}</th>' for i in infos)
    return f"""
<section class="sec">
  <p class="rotulo">Resultado por CCT</p>
  <p class="detalhe">Clique numa linha para ver o detalhe. Passe o mouse numa célula para ver a cláusula.</p>
  <input id="busca" class="busca" type="search" aria-label="Filtrar"
    placeholder="Filtrar por cidade, loja (ex.: 044), sindicato (ex.: SIND0040) ou registro">
  <div class="tabela"><table><thead><tr><th>CCT</th>{cab}</tr></thead><tbody>{"".join(linhas)}</tbody></table></div>
</section>"""


def secao_detalhes(dados, principais, alertas_por_cct) -> str:
    infos = [i["nome"] for i in dados["infos"]]
    blocos = []
    for c in principais:
        meus = alertas_por_cct.get(c["id"], [])
        marca = ""
        if meus:
            pior = min(meus, key=lambda a: list(NIVEL).index(a["nivel"]))["nivel"]
            marca = (f'<span class="marca-alerta"><span class="nv n-{pior}"></span>{len(meus)} ponto'
                     f'{"s" if len(meus) > 1 else ""} de atenção</span>')
        linhas_alerta = "".join(f'<li><span class="nv n-{a["nivel"]}"></span><a href="#{a["_ancora"]}">'
                                f'{esc(a["titulo"])}</a></li>' for a in meus)
        arquivos = " · ".join(esc(a) for a in c["_arquivos"])
        corpo = [f"""<dl class="dados">
  <div><dt>Documento lido</dt><dd>{esc(c["_tipo"])}<br>registro no MTE {esc(c["_registro"] or "?")}</dd></div>
  <div><dt>Vigência</dt><dd>{br(c["_ini"])} a {br(c["_fim"])}</dd></div>
  <div><dt>Data-base</dt><dd>{esc(c["_data_base"] or "—")}</dd></div>
  <div><dt>Lojas ({len(c["_lojas"])})</dt><dd>{esc(", ".join(c["_lojas"]))}</dd></div>
</dl><p class="arquivos"><b>Arquivos com este texto:</b> {arquivos}</p>"""]
        if meus:
            corpo.append(f'<div class="seus-alertas"><b>Pontos de atenção</b><ul>{linhas_alerta}</ul></div>')
        for inf in infos:
            r = c["infos"][inf]
            pontos = "".join(f"<li>{esc(p)}</li>" for p in r.get("pontos", []))
            fonte = (f'<p class="fonte">Fonte: {esc(frase(r["clausula"]))} · pág. {esc(r.get("pag", "?"))}</p>'
                     if r.get("clausula") else "")
            trecho = (f'<details class="trecho"><summary>Ver trecho da CCT</summary><blockquote>“{esc(r["trecho"])}”'
                      f'</blockquote></details>' if r.get("trecho") else "")
            corpo.append(f'<div class="info" style="--c:{COR_INFO[inf]}"><div class="rot">{esc(inf)}<span class="st">'
                         f'{icone(r["st"])}'
                         f'{ROTULO[r["st"]]}</span></div><div><ul>{pontos}</ul>{fonte}{trecho}</div></div>')
        if c.get("obs"):
            corpo.append('<div class="obs"><b>Outras observações</b><ul>'
                         + "".join(f"<li>{esc(o)}</li>" for o in c["obs"]) + "</ul></div>")
        blocos.append(f'<details class="cct" id="{c["_ancora"]}" data-busca="{c["_busca"]}"><summary>'
                      f'<span class="nome">{esc(c["nome"])}</span><span class="sub">{esc(vencimento(c))}</span>'
                      f'{marca}</summary><div class="corpo">{"".join(corpo)}</div></details>')
    return f"""
<section class="sec">
  <div class="cab-sec"><p class="rotulo">Detalhe de cada CCT</p>
  <div><button class="btn" id="abrir">Abrir todas</button> <button class="btn" id="fechar">Fechar todas</button></div></div>
  {"".join(blocos)}
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
  <p class="doc">{esc(c["_doc"])} · {esc(vencimento(c))} · lojas {esc(", ".join(c["_lojas"]))}</p>
  <ul>{"".join(f"<li>{esc(p)}</li>" for p in k.get("pontos", []))}</ul>{linha_pedidas}
  <p class="pedidas">{principal}</p></article>""")
    return f"""
<section class="sec">
  <p class="rotulo">CCTs complementares</p>
  <p class="detalhe">Acordos curtos sobre outro assunto, que valem junto com a CCT principal das mesmas lojas.</p>
  <div class="comps">{"".join(itens)}</div>
</section>"""


def secao_como(dados, indice) -> str:
    grupo = dados.get("grupo", "analisadas")
    passos = [
        ("Sem IA", "Separar", f"Um programa abre os {len(indice['arquivos'])} PDFs da pasta, junta os que têm o "
         f"mesmo texto e separa as CCTs {grupo} pela data de vigência."),
        ("Com IA", "Ler", "Para cada CCT, a IA olha a lista de cláusulas e lê só as que falam das informações "
         "pedidas. Ela anota o valor, a cláusula e a página."),
        ("Com IA", "Revisar", "As respostas são juntadas e comparadas. O que falta ou parece errado vira "
         "ponto de atenção."),
        ("Sem IA", "Montar", "Um programa monta esta página. Nenhum valor é calculado ou completado por ele."),
    ]
    caixas = "".join(f'<div class="passo {"com-ia" if t == "Com IA" else ""}"><span class="ia">{t}</span>'
                     f'<h3>{i}. {esc(n)}</h3><p>{esc(d)}</p></div>' for i, (t, n, d) in enumerate(passos, 1))
    return f"""
<section class="sec">
  <p class="rotulo">Como este relatório foi feito</p>
  <div class="passos">{caixas}</div>
  <p class="detalhe">A IA usa só o texto das CCTs: o que não está lá aparece como “Não consta”, nunca é inventado.
  Para conferir qualquer dado, abra o PDF na página indicada em “Fonte”.</p>
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
.aviso{margin-top:12px!important;font-size:13px;color:#33475A;background:var(--t-baixo);border-left:4px solid var(--n-baixo);padding:9px 12px}
.legenda{list-style:none;padding:0;display:flex;flex-wrap:wrap;gap:10px 26px;font-size:13px;color:var(--texto-2)}
.legenda li{display:flex;align-items:center;gap:8px}
.chip{display:inline-flex;align-items:center;font-weight:700;color:var(--texto);padding:3px 10px;font-size:12.5px}
.chip.sim{background:var(--t-sim)} .chip.parcial{background:var(--t-parcial)} .chip.nao{background:var(--t-nao)}
.ic{flex:none;vertical-align:-1px;margin-right:6px}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.kpi{padding:14px 16px;border-left:4px solid var(--c);background:var(--t)}
.kpi .n{font-size:28px;font-weight:700;color:var(--c);line-height:1.15}
.kpi .l{font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--texto-2)}
/* gráficos */
.graficos{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
.graf{background:var(--card);border:1px solid var(--borda);border-top:4px solid var(--c,var(--verde-vivo));padding:16px 18px;min-width:0}
.graf.largo{grid-column:1/-1}
.graf .sub{margin:2px 0 12px;font-size:12px;color:var(--texto-2)}
.svg-wrap{overflow-x:auto}
.svg-wrap svg{display:block;width:100%;height:auto}
.leg{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:12px;color:var(--texto-2);margin-bottom:10px}
.g-rot{fill:var(--texto-2);font-size:12px}
.g-val{fill:var(--texto);font-size:12px;font-weight:600}
.g-in{font-size:11.5px;font-weight:700}
.g-centro{fill:var(--texto);font-size:30px;font-weight:700}
.g-base{stroke:var(--borda-2);stroke-width:1}
[data-tip-t]{outline:none}
[data-tip-t]:hover,[data-tip-t]:focus{opacity:.75}
.pizza{display:flex;align-items:center;gap:24px;flex-wrap:wrap}
.pizza svg{width:180px;flex:none}
.leg-lista{list-style:none;padding:0;flex:1;min-width:180px;font-size:13px}
.leg-lista li{display:flex;align-items:baseline;gap:8px;padding:5px 0;border-bottom:1px solid var(--borda)}
.leg-lista li:last-child{border-bottom:0}
.leg-lista .m{color:var(--texto-2);flex:1}
.leg-lista .n{white-space:nowrap}
.sw{display:inline-block;width:10px;height:10px;flex:none}
.sw.vazio{border:2px solid var(--texto-3);margin-right:6px;vertical-align:-1px}
.nota-graf{margin:10px 0 0;font-size:12px;color:var(--texto-2)}
.tip{position:fixed;z-index:20;pointer-events:none;background:#fff;border:1px solid var(--borda-2);box-shadow:0 4px 14px rgba(15,26,18,.12);padding:8px 12px;max-width:280px;font-size:12.5px}
.tip .v{font-weight:700;font-size:14px}
.tip .t{color:var(--texto-2)}
.tip .nt{color:var(--texto-2);margin-top:4px;border-top:1px solid var(--borda);padding-top:4px}
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
/* tabela */
.busca{width:100%;margin:12px 0;padding:12px 14px;font:inherit;font-size:13px;color:var(--texto);background:var(--card);border:1px solid var(--borda-2);border-radius:0}
.busca:focus{outline:none;border-color:var(--verde)}
.busca::placeholder{color:var(--texto-3)}
.tabela{overflow-x:auto;border:1px solid var(--borda);background:var(--card)}
table{border-collapse:collapse;width:100%;min-width:980px;font-size:13px}
th,td{text-align:left;vertical-align:top;padding:10px 12px;border-bottom:2px solid var(--card)}
td+td{border-left:2px solid var(--card)}
thead th{position:sticky;top:0;background:#EEF3EC;font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--texto-2);border-bottom:3px solid var(--c,var(--borda-2))}
tbody tr{cursor:pointer;outline:none}
tbody td.cct{background:var(--card);border-bottom:1px solid var(--borda)}
td.c-sim{background:var(--t-sim)} td.c-parcial{background:var(--t-parcial)} td.c-nao{background:var(--t-nao)}
tbody tr:hover td,tbody tr:focus td{box-shadow:inset 0 0 0 999px rgba(15,26,18,.05)}
td.cct{min-width:200px}
td.cct b,td.cct span{display:block}
td.cct .doc{font-size:12px;color:var(--texto-2)}
td.cct .venc{font-size:12px;color:var(--n-alto);font-weight:600}
.cel{display:flex;align-items:flex-start}
.cel .ic{margin-top:4px}
.cel.nao{color:var(--texto-3)}
/* detalhes */
.cab-sec{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px;margin-bottom:12px}
.cab-sec .rotulo{margin:0}
.btn{font:inherit;font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--verde);background:var(--card);border:1px solid var(--borda-2);padding:9px 14px;cursor:pointer}
.btn:hover{background:var(--t-sim)}
details.cct{background:var(--card);border:1px solid var(--borda);border-left:4px solid var(--verde-vivo);margin-bottom:8px;scroll-margin-top:12px}
details.cct>summary{list-style:none;cursor:pointer;padding:13px 16px;display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 14px}
details.cct>summary:hover{background:var(--card-2)}
details.cct>summary::-webkit-details-marker{display:none}
details.cct>summary::before{content:"▸";color:var(--verde)}
details.cct[open]>summary::before{content:"▾"}
summary .nome{font-weight:700;font-size:15px}
summary .sub{font-size:12.5px;color:var(--texto-2)}
.marca-alerta{margin-left:auto;font-size:12px;color:var(--texto-2)}
.corpo{padding:0 16px 16px}
.dados{display:grid;grid-template-columns:2fr 1fr 1fr 2fr;gap:2px;margin:0}
.dados div{background:var(--fundo);padding:8px 12px}
.dados dt{font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--texto-2)}
.dados dd{margin:0;font-size:13px}
.arquivos{font-size:12px;color:var(--texto-3);margin:8px 0 4px;word-break:break-word}
.arquivos b{color:var(--texto-2);font-weight:600}
.seus-alertas{margin:10px 0 2px;font-size:13px}
.seus-alertas ul{list-style:none;padding:0;margin-top:4px}
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
  .graficos,.comps{grid-template-columns:minmax(0,1fr)}
  .passos,.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
  .dados{grid-template-columns:1fr 1fr}
}
@media (max-width:560px){
  .pagina{padding:16px 16px 32px}
  .topo{padding:16px}
  .topo h1{font-size:19px}
  .topo .pedido{font-size:18px}
  .info{grid-template-columns:1fr}
  .passos,.dados{grid-template-columns:minmax(0,1fr)}
}
@media print{
  body{background:#fff}
  .busca,.btn,.tip{display:none}
  details.cct,.alerta,.graf{break-inside:avoid}
}
"""

JS = """
const norm = s => s.normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase();
const busca = document.getElementById('busca');
if (busca) busca.addEventListener('input', () => {
  const q = norm(busca.value.trim()).replace(/[^a-z0-9]+/g, '-');
  document.querySelectorAll('[data-busca]').forEach(el =>
    el.classList.toggle('oculto', q !== '' && !el.dataset.busca.includes(q)));
});
function abrir(id) {
  const el = document.getElementById(id);
  if (!el) return;
  if (el.tagName === 'DETAILS') el.open = true;
  el.scrollIntoView({behavior: 'smooth', block: 'start'});
}
document.querySelectorAll('tr[data-alvo]').forEach(tr => {
  tr.addEventListener('click', () => abrir(tr.dataset.alvo));
  tr.addEventListener('keydown', e => { if (e.key === 'Enter') abrir(tr.dataset.alvo); });
});
document.addEventListener('click', e => {
  const a = e.target.closest('a[href^="#"]');
  if (a) { e.preventDefault(); abrir(a.getAttribute('href').slice(1)); }
});
document.getElementById('abrir').onclick = () => document.querySelectorAll('details.cct').forEach(d => d.open = true);
document.getElementById('fechar').onclick = () => document.querySelectorAll('details.cct').forEach(d => d.open = false);
// balão dos gráficos: texto entra com textContent (nunca como HTML)
const tip = document.createElement('div');
tip.className = 'tip'; tip.hidden = true; document.body.appendChild(tip);
function linha(cls, txt) { const d = document.createElement('div'); d.className = cls; d.textContent = txt; return d; }
function mostrar(el, x, y) {
  tip.replaceChildren(linha('v', el.dataset.tipV), linha('t', el.dataset.tipT));
  if (el.dataset.tipN) tip.appendChild(linha('nt', el.dataset.tipN));
  tip.hidden = false;
  const r = tip.getBoundingClientRect();
  tip.style.left = Math.min(x + 14, innerWidth - r.width - 8) + 'px';
  tip.style.top = Math.max(y - r.height - 12, 8) + 'px';
}
document.querySelectorAll('[data-tip-t]').forEach(el => {
  el.addEventListener('mousemove', e => mostrar(el, e.clientX, e.clientY));
  el.addEventListener('mouseleave', () => tip.hidden = true);
  el.addEventListener('focus', () => { const r = el.getBoundingClientRect(); mostrar(el, r.left + r.width / 2, r.top); });
  el.addEventListener('blur', () => tip.hidden = true);
});
"""


def montar(dados, indice, hoje) -> str:
    COR_INFO.clear()
    for i, inf in enumerate(dados["infos"]):  # sem repetir cor: da 6ª informação em diante, cinza
        COR_INFO[inf["nome"]] = COR["infos"][i] if i < len(COR["infos"]) else COR["outra"]
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
    corpo = (secao_topo(dados, indice, hoje, principais, ccts) + secao_graficos(dados, principais, ccts)
             + secao_alertas(dados, por_id) + secao_tabela(dados, principais)
             + secao_detalhes(dados, principais, alertas_por_cct) + secao_complementares(dados, comps, por_id)
             + secao_como(dados, indice))
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
