"""
Ferramenta do agente de CCTs.

Lê os PDFs uma vez, guarda o texto (marcando cada página) e deixa o agente
procurar e ler só o que interessa, sem abrir os 600 arquivos.

Comandos (rodar na pasta do projeto):

    python ferramentas.py extrair
        Lê os PDFs da pasta do config.json e guarda o texto em saida/textos/.
        Arquivos que não mudaram desde a última vez não são lidos de novo.

    python ferramentas.py buscar --termo "auxilio creche" --termo "creche" --situacao vencida
        Lista as CCTs que citam algum dos termos, com as páginas e um trecho.
        Acentos, maiúsculas e hífens não importam. Outros filtros:
          --todos              exige todos os termos na mesma CCT
          --nome "SANTA ROSA"  só arquivos com esse pedaço no nome (loja, cidade, SINDxxxx)
          --situacao           vigente | vencida | futura | sem_vigencia
        Sem --termo, só lista as CCTs que passam nos filtros.

    python ferramentas.py ler <id> --paginas 1-3
        Mostra o texto da CCT (ou só das páginas pedidas). <id> é o código entre
        colchetes que o buscar mostra; também aceita parte do nome do arquivo.

    python ferramentas.py ler <id> --sumario
        Lista as cláusulas da CCT (título e página), para escolher o que ler.

    python ferramentas.py ler <id> --clausula "piso" --clausula "salario normativo"
        Mostra só as cláusulas cujo título tem algum desses termos.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from functools import lru_cache

import pypdfium2 as pdfium  # ~30x mais rápido que o pdfplumber para extrair texto

AQUI = os.path.dirname(os.path.abspath(__file__))
PASTA_TEXTOS = os.path.join(AQUI, "saida", "textos")
INDICE = os.path.join(AQUI, "saida", "indice.json")

MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
         "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
# Frase padrão do Mediador: "...vigência no período de 01º de maio de 2026 a 30 de abril
# de 2027 e a data-base da categoria em 01º de maio."
RE_VIGENCIA = re.compile(r"per[íi]odo de (.+?) a (.+?) e a data-base da categoria em (.+?)[.;]", re.I)
RE_PAGINA = re.compile(r"^=== PÁGINA (\d+) ===$", re.M)
# O Mediador numera as cláusulas por extenso: "CLÁUSULA DÉCIMA PRIMEIRA - TÍTULO".
# Só letras no rótulo: "CLÁUSULA 04 - ..." no meio do texto é citação, não cláusula nova.
RE_CLAUSULA = re.compile(r"^[ \t]*(CL[ÁA]USULA[ \t]+[A-ZÀ-Ú \t]{2,60}?)[ \t]+-[ \t]+(.+?)[ \t]*$", re.M)
RE_CONTROLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


# ------------------------------------------------------------------ utilidades

@lru_cache(maxsize=None)
def _letra(ch: str) -> str:
    base = unicodedata.normalize("NFKD", ch)[:1].lower()[:1]
    return base if base.isalnum() else " "


def _simplificar(texto: str) -> str:
    """Tira acentos, maiúsculas e pontuação mantendo o MESMO tamanho do texto.
    Assim a posição achada no texto simplificado serve para recortar o original."""
    return "".join(map(_letra, texto))


def _normal(texto: str) -> str:
    return " ".join(_simplificar(texto).split())


def _para_data(s: str) -> str:
    """'01º de maio de 2026' ou '01/05/2026' -> '2026-05-01' ('' se não reconhecer)."""
    s = _simplificar(s)  # "01º de maio" vira "01o de maio"; "01/05/2026" vira "01 05 2026"
    try:
        m = re.search(r"(\d{1,2})o?\s+de\s+([a-z]+)\s+de\s+(\d{4})", s)
        if m and m.group(2) in MESES:
            return date(int(m.group(3)), MESES[m.group(2)], int(m.group(1))).isoformat()
        m = re.search(r"(\d{1,2})\s+(\d{1,2})\s+(\d{4})", s)
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        pass
    return ""


def _br(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else "?"


def _situacao(cct: dict) -> str:
    inicio, fim = cct.get("vigencia_inicio"), cct.get("vigencia_fim")
    if not fim:
        return "sem_vigencia"
    hoje = date.today().isoformat()
    if inicio and hoje < inicio:
        return "futura"
    return "vigente" if hoje <= fim else "vencida"


def _config() -> dict:
    with open(os.path.join(AQUI, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def _carregar_indice() -> dict:
    if not os.path.exists(INDICE):
        return {"arquivos": {}, "ccts": {}}
    with open(INDICE, encoding="utf-8") as f:
        return json.load(f)


def _caminho_texto(cct_id: str) -> str:
    return os.path.join(PASTA_TEXTOS, f"{cct_id}.txt")


def _ler_paginas(cct_id: str) -> list[str]:
    with open(_caminho_texto(cct_id), encoding="utf-8") as f:
        partes = RE_PAGINA.split(f.read())
    return [t.strip("\n") for t in partes[2::2]]  # split devolve ['', '1', texto1, '2', texto2, ...]


def _clausulas(cct_id: str) -> list[tuple[int, str, str]]:
    """(página, título, texto) de cada cláusula. O texto vai até o começo da próxima."""
    with open(_caminho_texto(cct_id), encoding="utf-8") as f:
        texto = f.read()
    achados = list(RE_CLAUSULA.finditer(texto))
    clausulas = []
    for i, m in enumerate(achados):
        fim = achados[i + 1].start() if i + 1 < len(achados) else len(texto)
        pagina = texto.count("=== PÁGINA ", 0, m.start())  # marcas de página antes da cláusula
        titulo = f"{' '.join(m.group(1).split())} - {m.group(2).strip()}"
        clausulas.append((pagina, titulo, texto[m.start():fim].strip()))
    return clausulas


# -------------------------------------------------------------------- extrair

def _ler_pdf(caminho: str) -> tuple[list[str], str]:
    """Devolve (texto de cada página, mensagem de erro)."""
    try:
        pdf = pdfium.PdfDocument(caminho)
        try:
            paginas = []
            for i in range(len(pdf)):
                pagina = pdf[i]
                textpage = pagina.get_textpage()
                texto = textpage.get_text_range().replace("\r\n", "\n").replace("\r", "\n")
                paginas.append(RE_CONTROLE.sub("", texto))
                textpage.close()
                pagina.close()
            return paginas, ""
        finally:
            pdf.close()
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"


def _dados_cct(paginas: list[str]) -> dict:
    inicio = re.sub(r"\s+", " ", " ".join(paginas)[:20000])  # a vigência fica sempre no começo
    tipo = next((l.strip() for l in paginas[0].splitlines() if l.strip()), "") if paginas else ""
    m = RE_VIGENCIA.search(inicio)
    return {
        "paginas": len(paginas),
        "tipo": tipo[:100],
        "vigencia_inicio": _para_data(m.group(1)) if m else "",
        "vigencia_fim": _para_data(m.group(2)) if m else "",
        "data_base": m.group(3).strip()[:40] if m else "",
    }


def extrair(args) -> int:
    pasta = _config()["pasta_ccts"]
    if not os.path.isdir(pasta):
        print(f"Pasta não encontrada: {pasta} (confira o config.json)")
        return 1

    indice = _carregar_indice()
    atuais, para_ler = {}, []
    for raiz, _, nomes in os.walk(pasta):
        for nome in nomes:
            if not nome.lower().endswith(".pdf"):
                continue
            caminho = os.path.join(raiz, nome)
            st = os.stat(caminho)
            antigo = indice["arquivos"].get(caminho)
            if antigo and (antigo["mtime"], antigo["tamanho"]) == (st.st_mtime, st.st_size):
                atuais[caminho] = antigo  # não mudou: aproveita a leitura anterior
            else:
                para_ler.append((caminho, st))

    # Vários PDFs ao mesmo tempo, um por núcleo do processador
    caminhos = [c for c, _ in para_ler]
    if len(caminhos) > 20:
        with ProcessPoolExecutor(max_workers=min(os.cpu_count() or 4, 16)) as executor:
            lidos = list(executor.map(_ler_pdf, caminhos, chunksize=8))
    else:
        lidos = [_ler_pdf(c) for c in caminhos]

    os.makedirs(PASTA_TEXTOS, exist_ok=True)
    for (caminho, st), (paginas, erro) in zip(para_ler, lidos):
        item = {"arquivo": os.path.basename(caminho), "id": "", "mtime": st.st_mtime,
                "tamanho": st.st_size, "erro": erro}
        texto = "\n".join(paginas)
        if not erro and len(texto.strip()) < 200:
            item["erro"] = "sem texto (provável PDF escaneado)"
        if not item["erro"]:
            # Mesmo texto = mesma CCT: várias lojas usam a mesma e ela é guardada uma vez só
            cct_id = hashlib.sha1(texto.encode("utf-8")).hexdigest()[:10]
            item["id"] = cct_id
            if cct_id not in indice["ccts"] or not os.path.exists(_caminho_texto(cct_id)):
                with open(_caminho_texto(cct_id), "w", encoding="utf-8") as f:
                    for n, t in enumerate(paginas, start=1):
                        f.write(f"=== PÁGINA {n} ===\n{t.strip()}\n")
                indice["ccts"][cct_id] = _dados_cct(paginas)
        atuais[caminho] = item

    # CCTs que nenhum arquivo usa mais (arquivo apagado ou trocado) saem do índice
    usados = {a["id"] for a in atuais.values() if a["id"]}
    for cct_id in list(indice["ccts"]):
        if cct_id not in usados:
            del indice["ccts"][cct_id]
            if os.path.exists(_caminho_texto(cct_id)):
                os.remove(_caminho_texto(cct_id))

    indice["arquivos"] = atuais
    with open(INDICE, "w", encoding="utf-8") as f:
        json.dump(indice, f, ensure_ascii=False, indent=1)

    sem_texto = [a["arquivo"] for a in atuais.values() if a["erro"]]
    print(f"{len(atuais)} arquivos ({len(para_ler)} lidos agora, {len(atuais) - len(para_ler)} sem mudança) "
          f"-> {len(indice['ccts'])} CCTs diferentes")
    if sem_texto:
        print(f"Atenção: {len(sem_texto)} arquivo(s) sem texto, fora da busca: {'; '.join(sem_texto[:10])}")
    return 0


# --------------------------------------------------------------------- buscar

def _trecho(pagina: str, inicio: int, fim: int) -> str:
    recorte = re.sub(r"\s+", " ", pagina[max(0, inicio - 150):fim + 250]).strip()
    return f"...{recorte}..."


def buscar(args) -> int:
    indice = _carregar_indice()
    if not indice["ccts"]:
        print("Nenhum texto extraído. Rode antes: python ferramentas.py extrair")
        return 1

    filtro_nome = _normal(args.nome) if args.nome else ""
    grupos = {}  # id da CCT -> arquivos (lojas) que usam essa CCT
    for item in indice["arquivos"].values():
        if item["id"] and filtro_nome in _normal(item["arquivo"]):
            grupos.setdefault(item["id"], []).append(item["arquivo"])
    if args.situacao:
        grupos = {i: a for i, a in grupos.items() if _situacao(indice["ccts"][i]) == args.situacao}

    # "auxílio-creche" vira o padrão "auxilio\s+creche": acha "AUXÍLIO CRECHE", "auxilio-creche",
    # "Auxílio\ncreche"... Sem \b no final, "creche" também acha "creches".
    padroes = [re.compile(r"\b" + r"\s+".join(map(re.escape, _simplificar(t).split())))
               for t in args.termo if _simplificar(t).strip()]

    achados = []
    for cct_id, arquivos in grupos.items():
        if not padroes:
            achados.append((cct_id, arquivos, [], []))
            continue
        termos_achados, paginas_com_termo, trechos = set(), [], []
        for n, pagina in enumerate(_ler_paginas(cct_id), start=1):
            simples = _simplificar(pagina)
            primeiro = None
            for i, padrao in enumerate(padroes):
                m = padrao.search(simples)
                if m:
                    termos_achados.add(i)
                    primeiro = primeiro or m
            if primeiro:
                paginas_com_termo.append(n)
                if len(trechos) < args.trechos:
                    trechos.append((n, _trecho(pagina, primeiro.start(), primeiro.end())))
        if termos_achados and (not args.todos or len(termos_achados) == len(padroes)):
            achados.append((cct_id, arquivos, paginas_com_termo, trechos))

    achados.sort(key=lambda a: min(a[1]))
    total_arquivos = sum(len(a[1]) for a in achados)
    print(f"{len(achados)} CCT(s) encontrada(s), usadas por {total_arquivos} arquivo(s) "
          f"(de {len(grupos)} CCTs que passaram nos filtros)")
    for cct_id, arquivos, paginas_com_termo, trechos in achados[:args.limite]:
        cct = indice["ccts"][cct_id]
        print(f"\n[{cct_id}] {_situacao(cct).upper()} | vigência {_br(cct['vigencia_inicio'])} a "
              f"{_br(cct['vigencia_fim'])} | {cct['paginas']} págs | {cct['tipo']}")
        print(f"  arquivos ({len(arquivos)}): {'; '.join(sorted(arquivos))}")
        if paginas_com_termo:
            print(f"  termos nas páginas: {', '.join(map(str, paginas_com_termo))}")
        for n, trecho in trechos:
            print(f"  pág. {n}: {trecho}")
    if len(achados) > args.limite:
        print(f"\n... e mais {len(achados) - args.limite} CCT(s). Refine os termos/filtros ou aumente --limite.")

    sem_texto = [a["arquivo"] for a in indice["arquivos"].values() if a["erro"]]
    if sem_texto:
        print(f"\nAtenção: {len(sem_texto)} arquivo(s) sem texto não entram na busca: {'; '.join(sem_texto[:10])}")
    return 0


# ------------------------------------------------------------------------ ler

def _achar_id(indice: dict, procurado: str) -> str:
    if procurado in indice["ccts"]:
        return procurado
    alvo = _normal(procurado)
    ids = {a["id"] for a in indice["arquivos"].values() if a["id"] and alvo in _normal(a["arquivo"])}
    if len(ids) == 1:
        return ids.pop()
    if not ids:
        print(f"Nenhuma CCT com id ou arquivo '{procurado}'. Use o id que o buscar mostra.")
    else:
        print(f"'{procurado}' corresponde a {len(ids)} CCTs diferentes: {', '.join(sorted(ids))}. Use o id.")
    return ""


def _intervalo(texto: str, total: int) -> list[int]:
    """'1-3,7' -> [1, 2, 3, 7], sem passar do total de páginas."""
    paginas = set()
    for parte in texto.split(","):
        inicio, _, fim = parte.strip().partition("-")
        paginas.update(range(int(inicio), int(fim or inicio) + 1))
    return sorted(p for p in paginas if 1 <= p <= total)


def ler(args) -> int:
    indice = _carregar_indice()
    cct_id = _achar_id(indice, args.id)
    if not cct_id:
        return 1
    paginas = _ler_paginas(cct_id)
    try:
        escolhidas = _intervalo(args.paginas, len(paginas)) if args.paginas else range(1, len(paginas) + 1)
    except ValueError:
        print(f"--paginas inválido: '{args.paginas}'. Use, por exemplo, 1-3 ou 6-8,12")
        return 1

    cct = indice["ccts"][cct_id]
    arquivos = sorted(a["arquivo"] for a in indice["arquivos"].values() if a["id"] == cct_id)
    print(f"CCT [{cct_id}] {_situacao(cct).upper()} | vigência {_br(cct['vigencia_inicio'])} a "
          f"{_br(cct['vigencia_fim'])} | data-base {cct['data_base'] or '?'} | {len(paginas)} págs")
    print(f"Arquivos ({len(arquivos)}): {'; '.join(arquivos)}")
    print(f"Texto completo: {os.path.relpath(_caminho_texto(cct_id), AQUI)}\n")

    if args.sumario:
        for pagina, titulo, _ in _clausulas(cct_id):
            print(f"pág. {pagina:>2} | {titulo}")
        return 0

    if args.clausula:
        termos = [_normal(t) for t in args.clausula]
        escolhidas_cl = [c for c in _clausulas(cct_id) if any(t in _normal(c[1]) for t in termos)]
        if not escolhidas_cl:
            print(f"Nenhuma cláusula com {args.clausula} no título. Veja os títulos com --sumario.")
        for pagina, _, texto in escolhidas_cl:
            print(f"--- pág. {pagina} ---\n{texto}\n")
        return 0

    for n in escolhidas:
        print(f"=== PÁGINA {n} ===\n{paginas[n - 1]}\n")
    return 0


# ----------------------------------------------------------------------- main

def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Ferramenta do agente de CCTs")
    comandos = parser.add_subparsers(dest="comando", required=True)

    comandos.add_parser("extrair", help="lê os PDFs e guarda o texto")

    b = comandos.add_parser("buscar", help="procura termos nas CCTs")
    b.add_argument("--termo", action="append", default=[], help="pode repetir; acentos e maiúsculas não importam")
    b.add_argument("--todos", action="store_true", help="exige todos os termos na mesma CCT")
    b.add_argument("--nome", help="pedaço do nome do arquivo (loja, cidade, SINDxxxx)")
    b.add_argument("--situacao", choices=["vigente", "vencida", "futura", "sem_vigencia"])
    b.add_argument("--trechos", type=int, default=3, help="trechos mostrados por CCT (padrão 3)")
    b.add_argument("--limite", type=int, default=30, help="máximo de CCTs mostradas (padrão 30)")

    l = comandos.add_parser("ler", help="mostra o texto de uma CCT")
    l.add_argument("id", help="id da CCT (mostrado pelo buscar) ou parte do nome do arquivo")
    l.add_argument("--paginas", help='ex.: "1-3" ou "6-8,12"')
    l.add_argument("--sumario", action="store_true", help="lista as cláusulas (título e página)")
    l.add_argument("--clausula", action="append", default=[], help="mostra só cláusulas com esse termo no título; pode repetir")

    args = parser.parse_args()
    return {"extrair": extrair, "buscar": buscar, "ler": ler}[args.comando](args)


if __name__ == "__main__":
    sys.exit(main())
