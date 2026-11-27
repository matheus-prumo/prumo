#!/usr/bin/env python3
"""Baixa o Informe Mensal dos FIIs da CVM e gera cvm-fii.json para o Prumo ler."""
import csv, io, json, os, re, sys, time, urllib.request, zipfile, datetime

URL = "https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip"
LOCAL = os.environ.get("CVM_LOCAL")  # para testes: pasta com os zips


def baixar(ano):
    if LOCAL:
        p = os.path.join(LOCAL, f"inf_mensal_fii_{ano}.zip")
        return open(p, "rb").read() if os.path.exists(p) else None
    try:
        req = urllib.request.Request(URL.format(ano=ano), headers={"User-Agent": "prumo-cvm/1.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def ler_csv(z, padrao):
    nome = next((n for n in z.namelist() if re.search(padrao, n, re.I)), None)
    if not nome:
        return [], []
    txt = z.read(nome).decode("cp1252", errors="replace")
    linhas = list(csv.reader(io.StringIO(txt), delimiter=";"))
    return (linhas[0], linhas[1:]) if linhas else ([], [])


def col(cab, padrao):
    return next((i for i, c in enumerate(cab) if re.search(padrao, c, re.I)), -1)


def num(v):
    v = (v or "").strip()
    if not v:
        return None
    if re.search(r",\d+$", v) and not re.search(r"\.\d+,", v):
        v = v.replace(".", "").replace(",", ".")
    try:
        return float(v.replace(",", "."))
    except ValueError:
        return None


def ler_ano(ano):
    dados = baixar(ano)
    if not dados:
        return []
    z = zipfile.ZipFile(io.BytesIO(dados))
    gc, gl = ler_csv(z, r"geral")
    cc, cl = ler_csv(z, r"complemento")
    g = {k: col(gc, p) for k, p in [("cnpj", r"^cnpj"), ("data", r"data_refer"), ("isin", r"isin"), ("nome", r"^nome_fundo"), ("seg", r"segmento")]}
    c = {k: col(cc, p) for k, p in [("cnpj", r"^cnpj"), ("data", r"data_refer"), ("vpa", r"valor_patrimonial_cota"), ("pl", r"^patrimonio_liquido"), ("dy", r"dividend_yield"), ("cot", r"total_numero_cotistas"), ("tx", r"taxa_administracao")]}
    if min(g["cnpj"], g["isin"], c["cnpj"], c["vpa"]) < 0:
        raise SystemExit(f"colunas mudaram em {ano}: {gc} / {cc}")
    info = {}
    for l in gl:
        if len(l) <= max(g.values()):
            continue
        isin = l[g["isin"]].upper()
        if not re.match(r"^BR[A-Z]{4}", isin):
            continue
        d = l[g["data"]] if g["data"] >= 0 else ""
        k = l[g["cnpj"]]
        if k not in info or d >= info[k]["d"]:
            info[k] = {"d": d, "raiz": isin[2:6], "nome": l[g["nome"]] if g["nome"] >= 0 else "", "seg": l[g["seg"]] if g["seg"] >= 0 else ""}
    meses = []
    for l in cl:
        if len(l) <= max(c.values()):
            continue
        i = info.get(l[c["cnpj"]])
        if not i:
            continue
        pega = lambda k: num(l[c[k]]) if c[k] >= 0 else None
        meses.append({**i, "d": (l[c["data"]] or "")[:7], "vpa": pega("vpa"), "pl": pega("pl"), "dy": pega("dy"), "cot": pega("cot"), "tx": pega("tx")})
    return meses


def main():
    ano = datetime.date.today().year
    meses = ler_ano(ano) + ler_ano(ano - 1)
    if not meses:
        raise SystemExit("a CVM não devolveu dados")
    por = {}
    for m in meses:
        if m["d"]:
            por.setdefault(m["raiz"], {})[m["d"]] = m
    F = {}
    for raiz, ms in por.items():
        ordem = sorted(ms)
        ult = ms[ordem[-1]]
        rend = []
        for d in ordem[-12:]:
            m = ms[d]
            if m["dy"] is not None and m["vpa"]:
                f = m["dy"] if abs(m["dy"]) < 0.5 else m["dy"] / 100
                if f >= 0:
                    rend.append(f * m["vpa"])
        F[raiz] = {"ref": ult["d"], "nome": ult["nome"], "seg": ult["seg"], "vpa": ult["vpa"], "pl": ult["pl"], "cot": ult["cot"], "tx": ult["tx"],
                   "rend12": round(sum(rend) * 12 / len(rend), 2) if len(rend) >= 6 else None, "meses": len(rend)}
    out = {"em": int(time.time() * 1000), "fonte": "CVM - Informe Mensal FII (dados abertos)", "F": F}
    with open(sys.argv[1] if len(sys.argv) > 1 else "cvm-fii.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"ok: {len(F)} fundos")


if __name__ == "__main__":
    main()
