#!/usr/bin/env python3
"""Robô de dados do Prumo.
Junta, num arquivo só (dados.json), os números que o Prumo usa:
  - ações e FIIs da bolsa (Fundamentus)
  - títulos do Tesouro Direto (Tesouro Transparente, governo)
  - ETFs do exterior (Yahoo Finanças)
E, uma vez por semana, fundos.json com a cota dos fundos de investimento (CVM, Informe Diário).
Usa só a biblioteca padrão do Python. Cada parte que falhar não derruba as outras.
"""
import csv, datetime, gzip, html, io, json, os, re, sys, time, unicodedata, urllib.request, zipfile

LOCAL = os.environ.get("ROBO_LOCAL")  # pasta com respostas salvas, para testes
UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36"
HOJE = datetime.date.fromisoformat(os.environ["ROBO_HOJE"]) if os.environ.get("ROBO_HOJE") else datetime.date.today()

ETFS_US = ["VOO", "VTI", "VT", "VXUS", "VWO", "IJR", "QQQM", "SCHD", "VIG", "DGRO", "VYM", "VNQ", "BND", "TIP", "SGOV"]
TESOURO_URLS = [
    "https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv",
]
TESOURO_CKAN = "https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show?id=df56aa42-484a-4a59-8184-7676580c81e3"


def nome_local(url):
    return re.sub(r"[^A-Za-z0-9]+", "_", url)[-150:]


def baixar(url, timeout=90):
    if LOCAL:
        p = os.path.join(LOCAL, nome_local(url))
        if not os.path.exists(p):
            raise urllib.error.HTTPError(url, 404, "nao achei (teste)", None, None)
        return open(p, "rb").read()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        dados = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            dados = gzip.decompress(dados)
        return dados


def sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower()


def num(v):
    v = html.unescape((v or "").strip()).replace("%", "").replace("\xa0", "").strip()
    if v in ("", "-", "--"):
        return None
    if "," in v:
        v = v.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", v):  # 12.300.000 (milhar com ponto)
        v = v.replace(".", "")
    try:
        return float(v)
    except ValueError:
        return None


def tabela_html(txt):
    """Lê a primeira <table> com cabeçalho: devolve (cabecalhos, linhas)."""
    m = re.search(r"<table[^>]*id=[\"']?resultado[\"']?[^>]*>(.*?)</table>", txt, re.S | re.I) or re.search(r"<table[^>]*>(.*?)</table>", txt, re.S | re.I)
    if not m:
        return [], []
    corpo = m.group(1)
    limpa = lambda s: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()
    cab = [limpa(x) for x in re.findall(r"<th[^>]*>(.*?)</th>", corpo, re.S | re.I)]
    linhas = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", corpo, re.S | re.I):
        tds = [limpa(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
        if tds:
            linhas.append(tds)
    return cab, linhas


def achar(cab, *padroes, padrao_pos=None):
    cs = [sem_acento(c) for c in cab]
    for p in padroes:
        for i, c in enumerate(cs):
            if re.search(p, c):
                return i
    return padrao_pos if padrao_pos is not None else -1


def fundamentus_acoes():
    txt = baixar("https://www.fundamentus.com.br/resultado.php").decode("latin-1")
    cab, L = tabela_html(txt)
    c = {
        "cot": achar(cab, r"^cotacao", padrao_pos=1), "pl": achar(cab, r"^p/l$", padrao_pos=2), "pvp": achar(cab, r"^p/vp$", padrao_pos=3),
        "dy": achar(cab, r"div.?\s*yield", padrao_pos=5), "mliq": achar(cab, r"mrg\.? ?liq", padrao_pos=13), "roe": achar(cab, r"^roe$", padrao_pos=16),
        "liq": achar(cab, r"liq\.? ?2 ?meses", padrao_pos=17), "div": achar(cab, r"div\.? ?brut", padrao_pos=19), "cresc": achar(cab, r"cresc", padrao_pos=20),
    }
    out = {}
    for l in L:
        t = (l[0] if l else "").upper()
        if not re.match(r"^[A-Z]{4}\d{1,2}$", t):
            continue
        v = {k: (num(l[i]) if 0 <= i < len(l) else None) for k, i in c.items()}
        if v["liq"] is not None:
            v["liq"] = round(v["liq"] / 1e6, 2)  # em milhões de reais por dia
        out[t] = {k: x for k, x in v.items() if x is not None}
    if len(out) < 50:
        raise RuntimeError(f"Fundamentus devolveu poucas ações ({len(out)})")
    return out


def fundamentus_fiis():
    txt = baixar("https://www.fundamentus.com.br/fii_resultado.php").decode("latin-1")
    cab, L = tabela_html(txt)
    c = {
        "seg": achar(cab, r"segmento", padrao_pos=1), "cot": achar(cab, r"^cotacao", padrao_pos=2), "ffo": achar(cab, r"ffo", padrao_pos=3),
        "dy": achar(cab, r"dividend", padrao_pos=4), "pvp": achar(cab, r"^p/vp$", padrao_pos=5), "vm": achar(cab, r"valor de mercado", padrao_pos=6),
        "liq": achar(cab, r"^liquidez", padrao_pos=7), "imov": achar(cab, r"qtd|imoveis", padrao_pos=8), "cap": achar(cab, r"cap ?rate", padrao_pos=11),
        "vac": achar(cab, r"vacancia", padrao_pos=12),
    }
    out = {}
    for l in L:
        t = (l[0] if l else "").upper()
        if not re.match(r"^[A-Z]{4}11[A-Z]?$", t):
            continue
        v = {}
        for k, i in c.items():
            if not (0 <= i < len(l)):
                continue
            v[k] = l[i].strip() if k == "seg" else num(l[i])
        if v.get("liq") is not None:
            v["liq"] = round(v["liq"] / 1e6, 2)
        if v.get("vm") is not None:
            v["vm"] = round(v["vm"] / 1e9, 2)
        out[t] = {k: x for k, x in v.items() if x not in (None, "")}
    if len(out) < 30:
        raise RuntimeError(f"Fundamentus devolveu poucos FIIs ({len(out)})")
    return out


def tesouro():
    dados = None
    for u in TESOURO_URLS:
        try:
            dados = baixar(u, timeout=180)
            break
        except Exception:
            dados = None
    if dados is None:  # procura o endereço do arquivo no catálogo do Tesouro Transparente
        j = json.loads(baixar(TESOURO_CKAN))
        for r in j.get("result", {}).get("resources", []):
            if re.search(r"PrecoTaxaTesouroDireto\.csv$", r.get("url", ""), re.I):
                dados = baixar(r["url"], timeout=180)
                break
    if dados is None:
        raise RuntimeError("não achei o arquivo de preços e taxas do Tesouro")
    txt = dados.decode("latin-1")
    L = list(csv.reader(io.StringIO(txt), delimiter=";"))
    cab = [sem_acento(x) for x in L[0]]
    i_tipo, i_venc, i_base = achar(L[0], r"tipo"), achar(L[0], r"vencimento"), achar(L[0], r"data base")
    i_taxa, i_pu = achar(L[0], r"taxa compra"), achar(L[0], r"pu compra")
    i_taxav, i_puv = achar(L[0], r"taxa venda"), achar(L[0], r"pu venda")
    iso = lambda d: "-".join(reversed(d.strip().split("/"))) if "/" in d else d.strip()
    ultima = max(iso(l[i_base]) for l in L[1:] if len(l) > i_base and l[i_base].strip())
    titulos = []
    for l in L[1:]:
        if len(l) <= max(i_tipo, i_venc, i_base, i_taxa) or iso(l[i_base]) != ultima:
            continue
        titulos.append({"tipo": l[i_tipo].strip(), "venc": iso(l[i_venc]), "taxa": num(l[i_taxa]), "pu": num(l[i_pu]) if i_pu >= 0 else None,
                        "taxa_resgate": num(l[i_taxav]) if i_taxav >= 0 else None, "pu_resgate": num(l[i_puv]) if i_puv >= 0 else None})
    titulos.sort(key=lambda x: (x["tipo"], x["venc"]))
    return {"data": ultima, "titulos": titulos}


def yahoo(tickers):
    out = {}
    for t in tickers:
        try:
            j = json.loads(baixar(f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?range=1y&interval=1d&events=div"))
            r = j["chart"]["result"][0]
            p = r["meta"].get("regularMarketPrice")
            divs = (r.get("events") or {}).get("dividends") or {}
            lim = time.time() - 365 * 86400
            soma = sum(d.get("amount", 0) for d in divs.values() if d.get("date", 0) >= lim)
            if p:
                out[t] = {"p": round(p, 2), "div12": round(soma, 4), "dy": round(soma / p * 100, 2) if soma else 0}
        except Exception as e:
            print(f"  yahoo {t}: {e}", file=sys.stderr)
        time.sleep(0.5)
    if not out:
        raise RuntimeError("Yahoo não devolveu nenhum ETF")
    return out


def fnum(v):
    try:
        return float((v or "").strip().replace(",", "."))
    except ValueError:
        return None


def cvm_fundos():
    """Cota mais recente e rentabilidade de 12 meses dos fundos (CVM, Informe Diário)."""
    base = "https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_{ym}.zip"

    def mes(ym):
        z = zipfile.ZipFile(io.BytesIO(baixar(base.format(ym=ym), timeout=300)))
        nome = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        r = csv.reader(io.TextIOWrapper(z.open(nome), encoding="latin-1"), delimiter=";")
        cab = next(r)
        ic = achar(cab, r"^cnpj_fundo"); idt = achar(cab, r"dt_comptc"); iq = achar(cab, r"vl_quota"); ipl = achar(cab, r"vl_patrim"); ict = achar(cab, r"nr_cotst"); isub = achar(cab, r"id_subclasse")
        ult = {}
        for l in r:
            if len(l) <= max(ic, idt, iq) or (isub >= 0 and len(l) > isub and l[isub].strip()):
                continue
            k = re.sub(r"\D", "", l[ic]); d = l[idt]
            if k not in ult or d >= ult[k][0]:
                ult[k] = (d, fnum(l[iq]), fnum(l[ipl]) if ipl >= 0 else None, fnum(l[ict]) if ict >= 0 else None)
        return ult

    def ym_menos(n):
        y, m = HOJE.year, HOJE.month - n
        while m <= 0:
            y, m = y - 1, m + 12
        return f"{y}{m:02d}"

    agora = None
    for n in (0, 1):
        try:
            agora = mes(ym_menos(n)); break
        except Exception:
            continue
    if not agora:
        raise RuntimeError("não achei o informe diário recente")
    antes = None
    for n in (12, 11):
        try:
            antes = mes(ym_menos(n)); break
        except Exception:
            continue
    out = {}
    for k, (d, q, pl, cot) in agora.items():
        if not q or not pl or pl < 50e6 or (cot is not None and cot < 100):
            continue
        r12 = None
        if antes and k in antes and antes[k][1]:
            r12 = round((q / antes[k][1] - 1) * 100, 2)
            if r12 < -90 or r12 > 300:
                r12 = None
        out[k] = [round(q, 8), d, r12, round(pl / 1e6, 1), int(cot) if cot else None]
    return {"em": int(time.time() * 1000), "ref": max(v[1] for v in out.values()) if out else None, "F": out}


def main():
    pasta = sys.argv[1] if len(sys.argv) > 1 else "."
    caminho = os.path.join(pasta, "dados.json")
    try:
        velho = json.load(open(caminho, encoding="utf-8"))
    except Exception:
        velho = {}
    dados = {"em": int(time.time() * 1000), "fontes": {}}
    for chave, func, fonte in [("acoes", fundamentus_acoes, "Fundamentus"), ("fiis", fundamentus_fiis, "Fundamentus"), ("tesouro", tesouro, "Tesouro Transparente"), ("etfus", lambda: yahoo(ETFS_US), "Yahoo Finanças")]:
        try:
            dados[chave] = func()
            dados["fontes"][chave] = {"fonte": fonte, "ok": True, "em": dados["em"]}
            print(f"ok: {chave}")
        except Exception as e:
            print(f"FALHOU {chave}: {e}", file=sys.stderr)
            if chave in velho:  # mantém o último dado bom
                dados[chave] = velho[chave]
            antigo = (velho.get("fontes") or {}).get(chave, {})
            dados["fontes"][chave] = {"fonte": fonte, "ok": False, "erro": str(e)[:200], "em": antigo.get("em")}
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, separators=(",", ":"))
    # fundos de investimento: só às segundas (ou se ainda não existir o arquivo)
    caminho_f = os.path.join(pasta, "fundos.json")
    if os.environ.get("ROBO_FUNDOS") == "1" or HOJE.weekday() == 0 or not os.path.exists(caminho_f):
        try:
            f = cvm_fundos()
            with open(caminho_f, "w", encoding="utf-8") as arq:
                json.dump(f, arq, ensure_ascii=False, separators=(",", ":"))
            print(f"ok: fundos ({len(f['F'])})")
        except Exception as e:
            print(f"FALHOU fundos: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
