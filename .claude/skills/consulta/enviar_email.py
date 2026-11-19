"""
Envia o relatório da consulta (saida/consulta.html) por e-mail, com o mesmo envio dos robôs Mediador e ComuniQ.

    python .claude/skills/consulta/enviar_email.py              envia
    python .claude/skills/consulta/enviar_email.py --previa     só grava saida/email_previa.html, sem enviar
    python .claude/skills/consulta/enviar_email.py --sem-novas  consulta diária sem CCT nova: aviso curto, sem anexo
                                                                (confirma que o agente rodou)

Não usa IA. O corpo é curto e aponta para o anexo: o relatório completo é o consulta.html.
Visual de e-mail dos agentes (diferente do dos robôs, que têm faixa verde cheia e "Olá / Att"):
fundo branco com barra verde-clara no topo, quadrado verde e título em maiúsculas, cartão do anexo
e rodapé "gerado automaticamente".
A configuração fica fora do projeto (não vai para o git), como nos robôs:
C:\\Users\\<usuário>\\.AgenteLeituraCCTs\\config.ini, seção [Email] com EmailRemetente,
SenhaApp (senha de app do Gmail) e EmailDestinatario (vários separados por ; ou ,).
Os erros ficam anotados em Logs Permanentes\\log_email.txt, na mesma pasta.
"""
import configparser
import smtplib
import sys
from datetime import date, datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

sys.dont_write_bytecode = True  # não cria a pasta __pycache__ na skill
import relatorio as r  # noqa: E402  (mesma pasta: lê o resultado.json do mesmo jeito que o relatório)

PASTA_CONFIG = Path.home() / ".AgenteLeituraCCTs"
CONFIG = PASTA_CONFIG / "config.ini"
LOG = PASTA_CONFIG / "Logs Permanentes" / "log_email.txt"
RESULTADO = r.PROJETO / "saida" / "resultado.json"
RELATORIO = r.PROJETO / "saida" / "consulta.html"
TIMEOUT_SMTP = 180
# cores do relatório: verde-escuro do texto, verde-claro da marca, cinza dos rótulos
VERDE, VERDE_VIVO, CINZA, FUNDO = "#1C5A24", "#5AD46D", "#6B7F70", "#F4F6F3"
# O Outlook usa o motor do Word: só respeita largura, fundo e espaço em tabelas, ignora CSS separado
# e não herda a fonte da tabela de fora. Por isso tabelas, estilo em cada tag e a fonte repetida.
# Os rótulos já vão escritos em maiúsculas porque o Outlook nem sempre aplica text-transform.
FONTE = "font-family: Arial, sans-serif;"
ROTULO = f"{FONTE} font-size: 11px; font-weight: bold; letter-spacing: 1.5px; color: {CINZA};"


# ------------------------------------------------------------------ configuração

def carregar_config():
    """Devolve (remetente, senha, destinatários). Na primeira vez, cria o config.ini vazio para preencher."""
    if not CONFIG.exists():
        PASTA_CONFIG.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text("[Email]\nEmailRemetente = \nSenhaApp = \nEmailDestinatario = \n", encoding="utf-8")
        raise ValueError(f"Criei {CONFIG}. Preencha EmailRemetente, SenhaApp e EmailDestinatario e rode de novo.")
    config = configparser.ConfigParser()
    config.read(CONFIG, encoding="utf-8")
    email = config["Email"] if "Email" in config else {}
    remetente = email.get("EmailRemetente", "").strip()
    senha = email.get("SenhaApp", "").strip()
    destinatarios = [e.strip() for e in email.get("EmailDestinatario", "").replace(",", ";").split(";") if e.strip()]
    if not (remetente and senha and destinatarios):
        raise ValueError(f"Configuração incompleta em {CONFIG}: preencha EmailRemetente, SenhaApp e EmailDestinatario.")
    return remetente, senha, destinatarios


# ------------------------------------------------------------------ corpo

def plural(n: int, singular: str, plural_: str) -> str:
    return f"{n} {singular if n == 1 else plural_}"


def montar_corpo(pedido: str, hoje, titulo_cartao: str, destaque: str, texto: str, resumo: str) -> str:
    """Corpo curto no visual dos agentes. O cartão traz o anexo (ou o aviso de que não há CCT nova)."""
    # width="600" é a largura que o Outlook respeita; max-width deixa o celular encolher
    return f"""
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width: 600px; max-width: 100%; border: 1px solid #DDE3DE;">
  <tr>
    <td bgcolor="{VERDE_VIVO}" height="6" style="background-color: {VERDE_VIVO}; height: 6px; font-size: 0; line-height: 0;">&nbsp;</td>
  </tr>
  <tr>
    <td style="padding: 22px 28px 18px 28px; border-bottom: 1px solid #E3E9E4; {FONTE}">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td width="14" valign="middle">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
              <td width="14" height="14" bgcolor="{VERDE_VIVO}" style="width: 14px; height: 14px; background-color: {VERDE_VIVO}; font-size: 0; line-height: 0;">&nbsp;</td>
            </tr></table>
          </td>
          <td valign="middle" style="padding-left: 12px; {FONTE} font-size: 20px; font-weight: bold; letter-spacing: 1px; color: {VERDE};">CONSULTA DE CCTS</td>
          <td valign="middle" align="right" style="{FONTE} font-size: 12px; font-weight: bold; color: {VERDE};">{hoje:%d/%m/%Y}</td>
        </tr>
      </table>
      <div style="padding-top: 8px; {ROTULO}">AGENTE DE IA · ANÁLISE DAS CONVENÇÕES COLETIVAS</div>
    </td>
  </tr>
  <tr>
    <td style="padding: 22px 28px 24px 28px; {FONTE}">
      <p style="margin: 0 0 6px 0; {ROTULO}">PEDIDO</p>
      <p style="margin: 0 0 18px 0; {FONTE} font-size: 16px; font-weight: bold; color: #1A1A1A;">{r.esc(pedido)}</p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td bgcolor="#EEF7F0" style="background-color: #EEF7F0; border: 1px solid #CFE6D5; border-left: 5px solid {VERDE}; padding: 16px 18px; {FONTE}">
            <div style="{ROTULO} color: {VERDE};">{titulo_cartao}</div>
            <div style="padding-top: 6px; {FONTE} font-size: 16px; font-weight: bold; color: #1A1A1A;">{destaque}</div>
            <div style="padding-top: 6px; {FONTE} font-size: 14px; color: #333333;">{texto}</div>
          </td>
        </tr>
      </table>
      <p style="margin: 16px 0 0 0; {FONTE} font-size: 13px; color: #555555;">{resumo}</p>
    </td>
  </tr>
  <tr>
    <td bgcolor="{FUNDO}" style="background-color: {FUNDO}; padding: 12px 28px; border-top: 1px solid #E3E9E4; {ROTULO} font-size: 10px;">GERADO AUTOMATICAMENTE PELO AGENTE DE CONSULTA DE CCTS</td>
  </tr>
</table>
"""


# ------------------------------------------------------------------ envio

def enviar(previa: bool, sem_novas: bool):
    if sem_novas:
        hoje = date.today()
        total = len(r.f._carregar_analisadas())
        nome_anexo = ""
        assunto = f"Consulta de CCTs - {hoje:%d/%m/%Y} - nenhuma CCT nova"
        corpo = montar_corpo("Consulta diária: CCTs novas", hoje, "NENHUMA CCT NOVA HOJE",
                             "Não há CCT nova para analisar.",
                             "O agente rodou normalmente e olha a pasta de novo no próximo dia.",
                             plural(total, "CCT já analisada no total", "CCTs já analisadas no total"))
    else:
        if not RELATORIO.exists() or RELATORIO.stat().st_mtime < RESULTADO.stat().st_mtime:
            raise ValueError("O consulta.html não existe ou é mais antigo que o resultado.json: "
                             "rode o relatorio.py antes.")
        dados, _indice, hoje = r.carregar(RESULTADO)
        nome_anexo = f"consulta_ccts_{hoje:%d-%m-%Y}.html"
        assunto = f"Relatório Consulta de CCTs - {hoje:%d/%m/%Y}"
        resumo = plural(len(dados["ccts"]), "CCT analisada", "CCTs analisadas")
        if dados.get("diaria"):
            resumo += f" · {plural(dados['_fila'], 'CCT ficou', 'CCTs ficaram')} na fila para os próximos dias"
        corpo = montar_corpo(dados["pedido"], hoje, "RELATÓRIO EM ANEXO", nome_anexo,
                             "Abra o anexo para ver o relatório completo no navegador, com a ficha de cada CCT.",
                             resumo)
    if previa:
        destino = r.PROJETO / "saida" / "email_previa.html"
        destino.write_text(corpo, encoding="utf-8")
        print(f"Prévia do e-mail salva em {destino} (nada foi enviado)")
        return
    remetente, senha, destinatarios = carregar_config()
    msg = MIMEMultipart()  # corpo + anexo
    msg["From"] = remetente
    msg["To"] = ", ".join(destinatarios)
    msg["Subject"] = assunto
    msg.attach(MIMEText(corpo, "html", "utf-8"))
    if nome_anexo:
        anexo = MIMEBase("text", "html")
        anexo.set_payload(RELATORIO.read_bytes())
        encoders.encode_base64(anexo)
        anexo.add_header("Content-Disposition", f'attachment; filename="{nome_anexo}"')
        msg.attach(anexo)
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=TIMEOUT_SMTP) as servidor:
        servidor.starttls()
        servidor.login(remetente, senha)
        servidor.sendmail(remetente, destinatarios, msg.as_string())
    print(f"E-mail enviado para {len(destinatarios)} destinatário(s)"
          f"{', com o relatório em anexo' if nome_anexo else ', avisando que não há CCT nova'}.")


def registrar_erro(mensagem: str):
    """Anota no log permanente, para saber depois por que um envio agendado falhou."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as log:
        log.write(f"Erro na data: {datetime.now():%d-%m-%Y_%H-%M}\nENVIO DE EMAIL\n\n{mensagem}\n\n{'-' * 49}\n\n")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        enviar(previa="--previa" in sys.argv, sem_novas="--sem-novas" in sys.argv)
        return
    except smtplib.SMTPAuthenticationError:
        erro = f"O Gmail recusou o login. Confira EmailRemetente e SenhaApp em {CONFIG}."
    except Exception as e:
        erro = str(e)
    registrar_erro(erro)
    sys.exit(f"E-mail NÃO enviado: {erro}\n(anotado em {LOG})")


if __name__ == "__main__":
    main()
