#!/usr/bin/env python3
"""Robô de dados do Prumo.
Junta, num arquivo só (dados.json), os números que o Prumo usa:
  - ações e FIIs da bolsa (Fundamentus)
  - títulos do Tesouro Direto (Tesouro Transparente, governo)
  - ETFs do exterior (Yahoo Finanças)
E, uma vez por semana, fundos.json com a cota dos fundos de investimento (CVM, Informe Diário).
Usa só a biblioteca padrão do Python. Cada parte que falhar não derruba as outras.
"""
import csv, datetime, gzip, html, io, json, os, re, subprocess, sys, time, unicodedata, urllib.request, zipfile

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


def baixar(url, timeout=90, tentativas=3, curl=False):
    if LOCAL:
        p = os.path.join(LOCAL, nome_local(url))
        if not os.path.exists(p):
            raise urllib.error.HTTPError(url, 404, "nao achei (teste)", None, None)
        return open(p, "rb").read()
    ultimo = None
    for tentativa in range(tentativas):  # o site caiu? tenta de novo, esperando um pouco mais a cada vez
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "gzip", "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                dados = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    dados = gzip.decompress(dados)
                return dados
        except urllib.error.HTTPError as e:
            ultimo = e
            if e.code not in (429, 500, 502, 503, 504):
                raise
        except Exception as e:  # conexão derrubada, tempo esgotado
            ultimo = e
        if tentativa + 1 < tentativas:
            time.sleep(4 * (tentativa + 1))
    if curl and not isinstance(ultimo, urllib.error.HTTPError):
        # alguns sites do governo barram o Python mas aceitam o curl
        try:
            r = subprocess.run(["curl", "-sSfL", "--compressed", "--retry", "3", "--retry-all-errors", "--max-time", str(timeout),
                                "-A", UA, "-H", "Accept-Language: pt-BR,pt;q=0.9", url], capture_output=True, timeout=timeout * 4 + 30)
            if r.returncode == 0 and r.stdout:
                return r.stdout
            ultimo = RuntimeError("curl: " + (r.stderr.decode("utf-8", "replace").strip()[-60:] or f"código {r.returncode}"))
        except Exception as e:
            ultimo = e
    raise ultimo


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
    motivos = []
    for u in TESOURO_URLS:
        try:
            dados = baixar(u, timeout=240, tentativas=4, curl=True)
            break
        except Exception as e:
            motivos.append("arquivo: " + _motivo(e))
            dados = None
    if dados is None:  # procura o endereço do arquivo no catálogo do Tesouro Transparente
        try:
            j = json.loads(baixar(TESOURO_CKAN, curl=True))
            for r in j.get("result", {}).get("resources", []):
                if re.search(r"PrecoTaxaTesouroDireto\.csv$", r.get("url", ""), re.I):
                    dados = baixar(r["url"], timeout=240, tentativas=2, curl=True)
                    break
        except Exception as e:
            motivos.append("catálogo: " + _motivo(e))
            dados = None
    if dados is None:  # plano B: lista de títulos à venda no site do Tesouro Direto
        try:
            return tesouro_direto()
        except Exception as e:
            motivos.append("Tesouro Direto: " + _motivo(e))
            raise RuntimeError(" · ".join(motivos))
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


def stooq(sym):
    """Último preço pela Stooq (CSV público). Devolve None se não achar."""
    try:
        txt = baixar(f"https://stooq.com/q/l/?s={sym}&f=sd2t2ohlcv&h&e=csv", timeout=20, tentativas=1).decode("utf-8", "replace")
        linhas = [l for l in txt.strip().splitlines() if l]
        if len(linhas) >= 2:
            cab = linhas[0].lower().split(","); val = linhas[1].split(",")
            i = cab.index("close") if "close" in cab else 6
            v = float(val[i])
            return v if v > 0 else None
    except Exception:
        return None
    return None


def google(sym, bolsas):
    """Último preço pela página do Google Finanças (ex.: VOO:NYSEARCA)."""
    for b in bolsas:
        try:
            txt = baixar(f"https://www.google.com/finance/quote/{sym}:{b}?hl=en", timeout=20, tentativas=1).decode("utf-8", "replace")
            m = re.search(r'data-last-price="([0-9.]+)"', txt)
            if m:
                v = float(m.group(1))
                if v > 0:
                    return v
        except Exception:
            continue
    return None


def tesouro_direto():
    j = json.loads(baixar("https://www.tesourodireto.com.br/json/br/com/b3/tesourodireto/service/api/treasurybondsinfo.json"))
    lista = (j.get("response") or {}).get("TrsrBdTradgList") or []
    titulos = []
    for x in lista:
        b = x.get("TrsrBd") or {}
        nome = b.get("nm") or ""
        tipo = re.sub(r"\s+\d{4}$", "", nome).strip()
        venc = (b.get("mtrtyDt") or "")[:10]
        taxa = b.get("anulInvstmtRate") or b.get("anulRedRate")
        if tipo and venc and taxa:
            titulos.append({"tipo": tipo, "venc": venc, "taxa": float(taxa), "pu": b.get("untrInvstmtVal") or None, "taxa_resgate": b.get("anulRedRate"), "pu_resgate": b.get("untrRedVal")})
    if not titulos:
        raise RuntimeError("Tesouro Direto não devolveu títulos")
    titulos.sort(key=lambda x: (x["tipo"], x["venc"]))
    return {"data": datetime.date.today().isoformat(), "titulos": titulos, "fonte": "tesourodireto.com.br"}


def _num(x):
    try:
        return float(str(x).replace("$", "").replace(",", "").replace("%", "").strip())
    except Exception:
        return None


def _motivo(e):
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    return (str(e) or e.__class__.__name__)[:40]


def cnbc(simbolos):
    """Preços de vários papéis de uma vez pela CNBC. Devolve {símbolo: {p, dy}}."""
    u = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols="
         + "%7C".join(simbolos) + "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json")
    j = json.loads(baixar(u, timeout=30, tentativas=2))
    lista = ((j.get("FormattedQuoteResult") or {}).get("FormattedQuote")) or []
    if isinstance(lista, dict):
        lista = [lista]
    out = {}
    for q in lista:
        p = _num(q.get("last"))
        if q.get("symbol") and p and p > 0:
            dy = _num(q.get("dividendyield") or q.get("yield"))
            out[q["symbol"]] = {"p": p, "dy": dy}
    return out


def nasdaq(t):
    j = json.loads(baixar(f"https://api.nasdaq.com/api/quote/{t}/info?assetclass=etf", timeout=20, tentativas=1))
    p = _num((((j.get("data") or {}).get("primaryData")) or {}).get("lastSalePrice"))
    return p if p and p > 0 else None


def yahoo(tickers):
    """ETFs do exterior. Ordem: Yahoo (traz dividendos) > CNBC > Nasdaq > Stooq > Google."""
    out, motivos, yahoo_ok = {}, {}, True
    for t in tickers:
        if not yahoo_ok:
            break
        j = None
        for host in ("query1", "query2"):
            try:
                j = json.loads(baixar(f"https://{host}.finance.yahoo.com/v8/finance/chart/{t}?range=1y&interval=1d&events=div", timeout=20, tentativas=1))
                break
            except Exception as e:
                motivos["Yahoo"] = _motivo(e)
        if j is None:
            yahoo_ok = False  # bloqueado: não insiste nos outros
            break
        try:
            r = j["chart"]["result"][0]
            p = r["meta"].get("regularMarketPrice")
            divs = (r.get("events") or {}).get("dividends") or {}
            lim = time.time() - 365 * 86400
            soma = sum(d.get("amount", 0) for d in divs.values() if d.get("date", 0) >= lim)
            if p:
                out[t] = {"p": round(p, 2), "div12": round(soma, 4), "dy": round(soma / p * 100, 2) if soma else 0}
        except Exception as e:
            motivos["Yahoo"] = _motivo(e)
        time.sleep(0.5)
    faltam = [t for t in tickers if t not in out]
    if faltam:
        try:
            c = cnbc(faltam)
            for t in faltam:
                if t in c:
                    p, dy = c[t]["p"], c[t]["dy"]
                    out[t] = {"p": round(p, 2), "div12": round(p * dy / 100, 4) if dy else None, "dy": dy, "fonte": "CNBC"}
            if not c:
                motivos["CNBC"] = "sem preços"
        except Exception as e:
            motivos["CNBC"] = _motivo(e)
    for t in [t for t in tickers if t not in out]:
        p, fonte = None, None
        for nome, f in (("Nasdaq", lambda: nasdaq(t)), ("Stooq", lambda: stooq(t.lower() + ".us")), ("Google", lambda: google(t, ("NYSEARCA", "NASDAQ", "BATS", "NYSE")))):
            if motivos.get(nome, "ok") not in ("ok", "sem preço", "HTTP 404"):
                continue  # já falhou com outro ETF: pula
            try:
                p = f()
            except Exception as e:
                motivos[nome] = _motivo(e)
                continue
            if p:
                fonte = nome
                motivos[nome] = "ok"
                break
            motivos[nome] = "sem preço"
        if p:
            out[t] = {"p": round(p, 2), "div12": None, "dy": None, "fonte": fonte}
    if not out:
        raise RuntimeError("nenhuma fonte respondeu (" + " · ".join(f"{k}: {v}" for k, v in motivos.items()) + ")")
    return out


ESTAVEIS = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "USDS", "PYUSD", "USDD", "BUSD", "GUSD", "USDP", "FRAX", "LUSD", "USD0", "USDX", "EURC", "EURT", "XAUT", "PAXG", "USDB", "RLUSD", "USDF", "USD1", "BFUSD", "SUSDE", "SUSDS"}
EMBRULHADAS = re.compile(r"wrapped|staked|bridged|restaked|liquid staking|lido|binance-peg|coinbase wrapped|\bw(btc|eth)\b", re.I)


def indices():
    out = {}
    try:
        c = cnbc([".BVSP", "BOVA11-BR", "XFIX11-BR", "IVVB11-BR"])
    except Exception:
        c = {}
    for nome, sym in [("IBOV", "%5EBVSP"), ("BOVA11", "BOVA11.SA"), ("XFIX11", "XFIX11.SA"), ("IVVB11", "IVVB11.SA")]:
        cs = {"IBOV": ".BVSP"}.get(nome, nome + "-BR")
        if cs in c:
            out[nome] = round(c[cs]["p"], 2)
            continue
        try:
            p = None
            for host in ("query1", "query2"):
                try:
                    j = json.loads(baixar(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}?range=5d&interval=1d", timeout=20, tentativas=1))
                    p = j["chart"]["result"][0]["meta"].get("regularMarketPrice")
                    break
                except Exception:
                    continue
            if not p:
                p = google({"IBOV": "IBOV", "BOVA11": "BOVA11", "XFIX11": "XFIX11", "IVVB11": "IVVB11"}[nome], ("INDEXBVMF",) if nome == "IBOV" else ("BVMF",))
            if p:
                out[nome] = round(p, 2)
        except Exception as e:
            print(f"  indice {nome}: {e}", file=sys.stderr)
        time.sleep(0.4)
    if not out:
        raise RuntimeError("nenhum índice")
    return out


def _retornos(precos):
    return [precos[i] / precos[i - 1] - 1 for i in range(1, len(precos)) if precos[i - 1] > 0]


def _historico_binance(sym):
    for host in ("https://data-api.binance.vision", "https://api.binance.com"):
        try:
            j = json.loads(baixar(f"{host}/api/v3/klines?symbol={sym}USDT&interval=1d&limit=1000", timeout=30, tentativas=1))
            if isinstance(j, list) and len(j) > 30:
                return [(int(k[0]) // 1000, float(k[4])) for k in j]
        except Exception:
            continue
    return None


def _historico_gecko(cid):
    try:
        j = json.loads(baixar(f"https://api.coingecko.com/api/v3/coins/{cid}/market_chart?vs_currency=usd&days=365&interval=daily", timeout=30, tentativas=1))
        return [(int(t) // 1000, float(p)) for t, p in j.get("prices", []) if p]
    except Exception:
        return None


def cripto():
    L = []
    for pagina in (1, 2):
        j = json.loads(baixar(f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page={pagina}&price_change_percentage=30d,1y"))
        L += j
        time.sleep(3)
    moedas = []
    for c in L:
        s = (c.get("symbol") or "").upper()
        if not s or s in ESTAVEIS or EMBRULHADAS.search((c.get("name") or "") + " " + (c.get("id") or "")):
            continue
        if (c.get("market_cap") or 0) < 50e6 or (c.get("total_volume") or 0) < 2e6:
            continue
        if c.get("current_price") and 0.97 < c["current_price"] < 1.03 and abs(c.get("price_change_percentage_30d_in_currency") or 0) < 2:
            continue  # cara de moeda estável
        moedas.append({"id": c["id"], "s": s, "nome": c.get("name"), "rank": c.get("market_cap_rank"), "mc": c.get("market_cap"), "vol": c.get("total_volume"),
                       "preco": c.get("current_price"), "circ": c.get("circulating_supply"), "total": c.get("total_supply"), "max": c.get("max_supply"),
                       "ath_chg": c.get("ath_change_percentage"), "ch30": c.get("price_change_percentage_30d_in_currency"), "ch1y": c.get("price_change_percentage_1y_in_currency")})
        if len(moedas) >= 150:
            break
    # comportamento em relação ao Bitcoin (1 ano), só para as 80 maiores
    btc = _historico_binance("BTC") or _historico_gecko("bitcoin")
    if not btc:
        raise RuntimeError("sem histórico do Bitcoin")
    bmap = dict((t // 86400, p) for t, p in btc)
    for m in moedas[:80]:
        h = _historico_binance(m["s"]) if m["s"] != "BTC" else btc
        fonte = "binance"
        if not h:
            h = _historico_gecko(m["id"]); fonte = "coingecko"; time.sleep(2.5)
        if not h:
            continue
        m["idade"] = (3.0 if len(h) >= 999 else round((time.time() - h[0][0]) / 86400 / 365, 1)) if fonte == "binance" else None
        dias = [(t // 86400, p) for t, p in h if t // 86400 in bmap][-365:]
        if len(dias) < 120:
            continue
        a = [p for _, p in dias]; b = [bmap[d] for d, _ in dias]
        ra, rb = _retornos(a), _retornos(b)
        n = min(len(ra), len(rb)); ra, rb = ra[-n:], rb[-n:]
        mb = sum(rb) / n; ma = sum(ra) / n
        cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / n; varb = sum((y - mb) ** 2 for y in rb) / n; vara = sum((x - ma) ** 2 for x in ra) / n
        beta = cov / varb if varb else None; corr = cov / (vara ** 0.5 * varb ** 0.5) if vara and varb else None
        sobe = [x / y for x, y in zip(ra, rb) if y > 0.02]; cai = [x / y for x, y in zip(ra, rb) if y < -0.02]
        pico, dd = 0, 0
        for p in a:
            pico = max(pico, p); dd = min(dd, p / pico - 1)
        m.update({"beta": round(beta, 2) if beta is not None else None, "corr": round(corr, 2) if corr is not None else None, "volat": round((vara ** 0.5) * (365 ** 0.5) * 100, 1),
                  "up": round(sorted(sobe)[len(sobe) // 2], 2) if len(sobe) > 10 else None, "down": round(sorted(cai)[len(cai) // 2], 2) if len(cai) > 10 else None, "dd": round(dd * 100, 1)})
        if fonte == "binance":
            time.sleep(0.2)
    return {"em": int(time.time() * 1000), "moedas": moedas}


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
    for chave, func, fonte in [("acoes", fundamentus_acoes, "Fundamentus"), ("fiis", fundamentus_fiis, "Fundamentus"), ("tesouro", tesouro, "Tesouro Transparente"), ("etfus", lambda: yahoo(ETFS_US), "Yahoo / CNBC / Nasdaq"), ("indices", indices, "CNBC / Yahoo"), ("cripto", cripto, "CoinGecko + Binance")]:
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
