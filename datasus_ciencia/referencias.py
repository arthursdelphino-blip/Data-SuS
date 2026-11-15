"""Dados de referência com cache local: população (IBGE), descrições da CID-10 (DATASUS) e malhas municipais (IBGE)."""

import ftplib
import json
import os
import re
import tempfile
import time

import numpy as np
import pandas as pd  # noqa: F401
import requests
from dbfread import DBF

from .catalogo import FTP_HOST, UFS

API_AGREGADOS = "https://servicodados.ibge.gov.br/api/v3/agregados"
API_MALHAS = "https://servicodados.ibge.gov.br/api/v3/malhas/estados"


def _ler_json(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def _gravar_json(p, obj):
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)


# ------------------------------------------------------------------ população (TabNet / POPSVS)
DIR_POPSVS = "/dissemin/publicos/IBGE/POPSVS"
FONTE_POP_SVS = ("Ministério da Saúde/SVSA – Estudo de Estimativas Populacionais por Município, Idade e Sexo "
                 "(TabNet/DATASUS)")
REGIAO_POR_DIGITO = {"1": "Norte", "2": "Nordeste", "3": "Sudeste", "4": "Sul", "5": "Centro-Oeste"}
FAIXAS_ETARIAS_APP = [(0, 1, "<1"), (1, 5, "1-4"), (5, 10, "5-9"), (10, 15, "10-14"), (15, 20, "15-19"),
                      (20, 30, "20-29"), (30, 40, "30-39"), (40, 50, "40-49"), (50, 60, "50-59"),
                      (60, 70, "60-69"), (70, 80, "70-79"), (80, 999, "80+")]


def _popsvs_ano(pasta_cache, ano, log=print):
    """Arquivo POPSBRaa.zip do FTP do DATASUS (a mesma base de 'População residente' do TabNet) → DataFrame
    cod6, sexo, idade (0–80, 80 = 80 anos ou mais), pop. Cache em parquet por ano."""
    import zipfile
    from .ftp import ClienteFTP
    from .leitura import ler_dbf_rapido
    pasta = os.path.join(pasta_cache, "popsvs")
    os.makedirs(pasta, exist_ok=True)
    pq = os.path.join(pasta, f"popsvs_{ano}.parquet")
    if os.path.exists(pq):
        return pd.read_parquet(pq)
    cli = ClienteFTP(pasta_cache, log=log)
    try:
        alvo = f"POPSBR{ano % 100:02d}.ZIP"
        nome = next((n for n in cli.listar(DIR_POPSVS) if n.upper() == alvo), None)
        if not nome:
            return None
        zp = os.path.join(pasta, nome)
        cli.baixar(DIR_POPSVS, nome, zp)
    finally:
        cli.fechar()
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(zp) as z:
        dbfs = [n for n in z.namelist() if n.lower().endswith(".dbf")]
        z.extract(dbfs[0], tmp)
        d = ler_dbf_rapido(os.path.join(tmp, dbfs[0]))
    out = pd.DataFrame({
        "cod6": d["COD_MUN"].astype("string").str[:6],
        "sexo": d["SEXO"].astype("string").map({"1": "Masculino", "2": "Feminino"}),
        "idade": pd.to_numeric(d["IDADE"], errors="coerce").astype("Int64"),
        "pop": pd.to_numeric(d["POP"], errors="coerce").astype("Float64"),
    }).dropna()
    out = out.groupby(["cod6", "sexo", "idade"], as_index=False)["pop"].sum()
    out.to_parquet(pq, index=False)
    os.remove(zp)
    return out


def populacao_svs(pasta_cache, ufs, anos, log=print):
    """População por município (cod6), ano, sexo e idade simples (0–80+) – base do TabNet.

    Verificação de consistência: se o total de uma UF em um ano cair >20% em relação ao ano anterior
    disponível (arquivo incompleto), aquele ano é descartado para a UF, com aviso."""
    cods = {UFS[u] for u in ufs if u in UFS}
    partes = []
    for ano in sorted(set(int(a) for a in anos)):
        d = _popsvs_ano(pasta_cache, ano, log=log)
        if d is None:
            continue
        if cods:
            d = d[d["cod6"].str[:2].isin(cods)]
        partes.append(d.assign(ano=ano))
    if not partes:
        return pd.DataFrame(columns=["cod6", "ano", "sexo", "idade", "pop", "uf"])
    pop = pd.concat(partes, ignore_index=True)
    from .catalogo import UF_POR_CODIGO
    pop["uf"] = pop["cod6"].str[:2].map(UF_POR_CODIGO)
    tot = pop.groupby(["uf", "ano"])["pop"].sum().reset_index().sort_values(["uf", "ano"])
    tot["anterior"] = tot.groupby("uf")["pop"].shift()
    ruins = tot[tot["anterior"].notna() & (tot["pop"] < 0.8 * tot["anterior"])]
    for _, r in ruins.iterrows():
        log(f"  ! população TabNet de {r['uf']} em {int(r['ano'])} parece incompleta; ano ignorado para essa UF.")
        pop = pop[~((pop["uf"] == r["uf"]) & (pop["ano"] == r["ano"]))]
    return pop.reset_index(drop=True)


def rotular_populacao(pop):
    """Acrescenta região, faixa etária do app e faixa quinquenal (80+) a um DataFrame de populacao_svs."""
    p = pop.copy()
    p["regiao"] = p["cod6"].str[:1].map(REGIAO_POR_DIGITO)
    idade = p["idade"].astype(int)
    p["faixa_etaria"] = pd.cut(idade, [f[0] for f in FAIXAS_ETARIAS_APP] + [999],
                               labels=[f[2] for f in FAIXAS_ETARIAS_APP], right=False).astype(str)
    p["faixa5"] = faixa5_80(idade)
    return p


def populacao_municipal(pasta_cache, ufs, compatibilizar=True, anos=None, log=print):
    """População residente por município (código IBGE 6 díg.) e ano.

    Fonte principal: base de população do TabNet (MS/SVSA – estimativas por município, idade e sexo, compatíveis
    com o Censo 2022), lida do FTP do DATASUS. Se indisponível, usa IBGE (SIDRA 6579 + Censo 2022) compatibilizado
    às Projeções 2024.
    """
    try:
        anos = list(anos) if anos is not None else list(range(2000, time.localtime().tm_year + 1))
        p = populacao_svs(pasta_cache, ufs, anos, log=log)
        if len(p):
            out = p.groupby(["cod6", "ano"], as_index=False)["pop"].sum().rename(columns={"pop": "populacao"})
            out["populacao"] = out["populacao"].astype(float)
            out["fonte_pop"] = FONTE_POP_SVS
            return out
    except Exception as e:
        log(f"  ! população do TabNet indisponível ({e}); usando IBGE.")
    return _populacao_municipal_ibge(pasta_cache, ufs, compatibilizar)


def _populacao_municipal_ibge(pasta_cache, ufs, compatibilizar=True):
    """População residente por município (código IBGE 6 díg.) e ano – via IBGE (alternativa).

    Fontes: IBGE – Estimativas da população (SIDRA tabela 6579) e Censo 2022 (tabela 4709); anos sem
    estimativa (ex.: 2007, 2010, 2023) são interpolados. Com `compatibilizar=True`, os municípios de cada UF são
    reescalados para somar o total da UF nas Projeções da População – Revisão 2024 (compatível com o Censo 2022),
    eliminando a descontinuidade entre as estimativas pré-censo e a contagem do Censo 2022.
    """
    pop = _populacao_municipal_bruta(pasta_cache, ufs)
    if not compatibilizar or pop.empty:
        return pop
    try:
        proj = projecao_2024(pasta_cache)
        tot = proj[(proj["sexo"] == "Ambos")].groupby(["sigla", "ano"])["pop"].sum()
    except Exception:
        return pop
    from .catalogo import UF_POR_CODIGO
    pop["uf"] = pop["cod6"].str[:2].map(UF_POR_CODIGO)
    soma = pop.groupby(["uf", "ano"])["populacao"].transform("sum")
    alvo = pd.Series(list(zip(pop["uf"], pop["ano"]))).map(tot).to_numpy()
    fator = np.where(np.isfinite(alvo) & (soma.to_numpy() > 0), alvo / soma.to_numpy(), 1.0)
    pop["populacao"] = (pop["populacao"] * fator).round()
    pop["fonte_pop"] = np.where(np.isfinite(alvo), "IBGE (compatibilizado à Projeção 2024)", pop["fonte_pop"])
    return pop.drop(columns="uf")


def _populacao_municipal_bruta(pasta_cache, ufs):
    partes = []
    for uf in ufs:
        if uf not in UFS:
            continue
        arq = os.path.join(pasta_cache, f"pop_{uf}.json")
        if os.path.exists(arq):
            dados = _ler_json(arq)
        else:
            dados = {}
            loc = f"N6[N3[{UFS[uf]}]]"
            per = requests.get(f"{API_AGREGADOS}/6579/periodos", timeout=60).json()
            anos = "|".join(p["id"] for p in per)
            for url in (f"{API_AGREGADOS}/6579/periodos/{anos}/variaveis/9324?localidades={loc}",
                        f"{API_AGREGADOS}/4709/periodos/2022/variaveis/93?localidades={loc}"):
                r = requests.get(url, timeout=120)
                r.raise_for_status()
                for s in r.json()[0]["resultados"][0]["series"]:
                    cod6 = s["localidade"]["id"][:6]
                    for ano, v in s["serie"].items():
                        if v and v.strip("-. "):
                            dados.setdefault(cod6, {})[ano] = int(v)
            _gravar_json(arq, dados)
        for cod6, serie in dados.items():
            for ano, v in serie.items():
                partes.append((cod6, int(ano), v))
    if not partes:
        return pd.DataFrame(columns=["cod6", "ano", "populacao", "fonte_pop"])
    pop = pd.DataFrame(partes, columns=["cod6", "ano", "populacao"])
    # interpolação para anos faltantes
    anos = range(pop["ano"].min(), pop["ano"].max() + 1)
    grade = pd.MultiIndex.from_product([pop["cod6"].unique(), anos], names=["cod6", "ano"])
    pop = pop.set_index(["cod6", "ano"]).reindex(grade)
    pop["fonte_pop"] = np.where(pop["populacao"].notna(), "IBGE", "interpolado")
    pop["populacao"] = pop.groupby(level=0)["populacao"].transform(
        lambda s: s.interpolate(limit_area="inside").ffill().bfill()).round()
    return pop.reset_index()


FAIXAS_5 = ["0 a 4", "5 a 9", "10 a 14", "15 a 19", "20 a 24", "25 a 29", "30 a 34", "35 a 39", "40 a 44",
            "45 a 49", "50 a 54", "55 a 59", "60 a 64", "65 a 69", "70 a 74", "75 a 79", "80 a 84", "85 a 89", "90+"]
# População-padrão mundial da OMS (Ahmad et al., 2001), por 100 mil, agregando 90+
PADRAO_OMS = [8860, 8690, 8600, 8470, 8220, 7930, 7610, 7150, 6590, 6040, 5370, 4550, 3720, 2960, 2210, 1520,
              910, 440, 195]


# Versão com 80+ como último grupo (compatível com a população do TabNet, que agrega 80 anos ou mais)
FAIXAS_5_80 = FAIXAS_5[:16] + ["80+"]
PADRAO_OMS_80 = PADRAO_OMS[:16] + [sum(PADRAO_OMS[16:])]


def faixa5_80(idade):
    i = pd.to_numeric(pd.Series(idade), errors="coerce").astype(float)
    pos = np.floor(i / 5).clip(upper=16)
    return pos.map(lambda p: FAIXAS_5_80[int(p)] if pd.notna(p) else None).to_numpy()


def faixa5(idade):
    """Idade em anos → faixa quinquenal compatível com FAIXAS_5."""
    i = pd.to_numeric(idade, errors="coerce").astype(float)
    pos = np.floor(i / 5).clip(upper=18)
    return pos.map(lambda p: FAIXAS_5[int(p)] if pd.notna(p) else None)


URL_PROJ_2024 = ("https://ftp.ibge.gov.br/Projecao_da_Populacao/Projecao_da_Populacao_2024/"
                 "projecoes_2024_tab2_grupo_quinquenal.xlsx")


def projecao_2024(pasta_cache):
    """IBGE – Projeções da População, Revisão 2024 (compatível com o Censo 2022): população por UF/região/Brasil,
    sexo e faixa quinquenal, 2000–2070. Colunas: sigla, ano, sexo (Ambos/Masculino/Feminino), faixa, pop."""
    arq = os.path.join(pasta_cache, "projecao_2024.parquet")
    if os.path.exists(arq):
        return pd.read_parquet(arq)
    pasta = os.path.join(pasta_cache, "ibge_projecao_2024")
    os.makedirs(pasta, exist_ok=True)
    xlsx = os.path.join(pasta, "projecoes_2024_tab2_grupo_quinquenal.xlsx")
    if not os.path.exists(xlsx):
        r = requests.get(URL_PROJ_2024, timeout=300)
        r.raise_for_status()
        with open(xlsx, "wb") as fh:
            fh.write(r.content)
    d = pd.read_excel(xlsx, header=5)
    d = d[d["SIGLA"].notna() & d["GRUPO ETÁRIO"].notna()]
    anos = [c for c in d.columns if isinstance(c, (int, float)) and not isinstance(c, bool)]
    longo = d.melt(id_vars=["GRUPO ETÁRIO", "SEXO", "SIGLA"], value_vars=anos, var_name="ano", value_name="pop")

    def faixa(g):
        g = str(g).strip()
        if g.startswith("90"):
            return "90+"
        a, b = g.split("-")
        return f"{int(a)} a {int(b)}"
    longo["faixa"] = longo["GRUPO ETÁRIO"].map(faixa)
    longo["sexo"] = longo["SEXO"].map({"Ambos": "Ambos", "Homens": "Masculino", "Mulheres": "Feminino"})
    longo = longo.rename(columns={"SIGLA": "sigla"})[["sigla", "ano", "sexo", "faixa", "pop"]]
    longo["ano"] = longo["ano"].astype(int)
    longo["pop"] = pd.to_numeric(longo["pop"], errors="coerce")
    longo.to_parquet(arq, index=False)
    return longo


def populacao_uf_idade_sexo(pasta_cache, uf):
    """População da UF por ano, sexo (Masculino/Feminino) e faixa quinquenal – IBGE, Projeções 2024.
    Colunas: ano, sexo, faixa, pop."""
    p = projecao_2024(pasta_cache)
    return p[(p["sigla"] == uf) & (p["sexo"] != "Ambos")][["ano", "sexo", "faixa", "pop"]].reset_index(drop=True)


def populacao_uf_idade_sexo_rev2018(pasta_cache, uf):
    """(Legado) Projeção revisão 2018 via SIDRA 7358 – não compatível com o Censo 2022."""
    arq = os.path.join(pasta_cache, f"pop_idade_sexo_{uf}.json")
    if os.path.exists(arq):
        return pd.DataFrame(_ler_json(arq))
    meta = requests.get(f"{API_AGREGADOS}/7358/metadados", timeout=60).json()
    cats = {c["id"]: c for c in meta["classificacoes"]}
    idades = {x["id"]: x["nome"] for x in cats[287]["categorias"]}
    anos = {x["id"]: x["nome"] for x in cats[1933]["categorias"]}
    alvo = {}
    for i, nome in idades.items():
        m = re.match(r"^(\d+) a (\d+) anos$", nome)
        if m and int(m.group(2)) - int(m.group(1)) == 4 and int(m.group(1)) < 90:
            alvo[i] = f"{m.group(1)} a {m.group(2)}"
        elif re.match(r"^90 anos ou mais$", nome):
            alvo[i] = "90+"
    url = (f"{API_AGREGADOS}/7358/periodos/2018/variaveis/606?localidades=N3[{UFS[uf]}]"
           f"&classificacao=2[4,5]|287[{','.join(map(str, alvo))}]|1933[all]")
    r = requests.get(url, timeout=180)
    r.raise_for_status()
    linhas = []
    for res in r.json()[0]["resultados"]:
        cl = {str(c["id"]): list(c["categoria"].items())[0] for c in res["classificacoes"]}
        sexo = "Masculino" if str(cl["2"][0]) == "4" else "Feminino"
        faixa = alvo.get(int(cl["287"][0]))
        ano = int(cl["1933"][1])
        for s in res["series"]:
            v = list(s["serie"].values())[0]
            if faixa and v and v.strip("-. "):
                linhas.append({"ano": ano, "sexo": sexo, "faixa": faixa, "pop": int(v)})
    _gravar_json(arq, linhas)
    return pd.DataFrame(linhas)


# ------------------------------------------------------------------ CID-10
def cid10_descricoes(pasta_cache):
    """Dicionário código CID-10 (3 ou 4 caracteres, sem ponto) → descrição (tabela oficial do DATASUS/SIM)."""
    arq = os.path.join(pasta_cache, "cid10.json")
    if os.path.exists(arq):
        return _ler_json(arq)
    desc = {}
    try:
        ftp = ftplib.FTP(FTP_HOST, timeout=60)
        ftp.login()
        ftp.cwd("/dissemin/publicos/SIM/CID10/TABELAS")
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "CID10.DBF")
            with open(p, "wb") as fh:
                ftp.retrbinary("RETR CID10.DBF", fh.write)
            ftp.quit()
            for r in DBF(p, encoding="latin-1"):
                cod = (r["CID10"] or "").strip().upper()
                txt = re.sub(r"^[A-Z]\d{2}(\.\d)?\s+", "", (r["DESCR"] or "").strip())
                if cod:
                    desc[cod] = txt
        _gravar_json(arq, desc)
    except Exception:
        pass
    return desc


# ------------------------------------------------------------------ SIGTAP (procedimentos SUS)
FTP_SIGTAP = ("ftp2.datasus.gov.br", "/pub/sistemas/tup/downloads")


def _ler_tabela_sigtap(z, nome):
    layout = z.read(f"{nome}_layout.txt").decode("latin-1").splitlines()[1:]
    cols = []
    for ln in layout:
        p = ln.split(",")
        if len(p) >= 4:
            cols.append((p[0], int(p[2]) - 1, int(p[3])))
    out = []
    for ln in z.read(f"{nome}.txt").decode("latin-1").splitlines():
        out.append({c: ln[i:f].strip() for c, i, f in cols})
    return out


def sigtap(pasta_cache):
    """Tabela de procedimentos do SUS (SIGTAP): {'procedimentos': {cod10: nome}, 'grupos': {cod2: nome},
    'subgrupos': {cod4: nome}, 'formas': {cod6: nome}}. Une a versão mais recente com a mais antiga
    disponível, para cobrir códigos já extintos."""
    arq = os.path.join(pasta_cache, "sigtap.json")
    if os.path.exists(arq) and (time.time() - os.path.getmtime(arq)) < 60 * 86400:
        return _ler_json(arq)
    import io
    import zipfile
    host, pasta = FTP_SIGTAP
    ftp = ftplib.FTP(host, timeout=120)
    ftp.login()
    ftp.cwd(pasta)
    versoes = sorted(n for n in ftp.nlst() if n.lower().startswith("tabelaunificada") and n.lower().endswith(".zip"))
    res = {"procedimentos": {}, "grupos": {}, "subgrupos": {}, "formas": {}, "versoes": []}
    for v in [versoes[0], versoes[-1]]:  # antiga primeiro; a recente sobrescreve nomes
        buf = io.BytesIO()
        ftp.retrbinary(f"RETR {v}", buf.write)
        z = zipfile.ZipFile(buf)
        for r in _ler_tabela_sigtap(z, "tb_procedimento"):
            res["procedimentos"][r["CO_PROCEDIMENTO"]] = r["NO_PROCEDIMENTO"].capitalize()
        for r in _ler_tabela_sigtap(z, "tb_grupo"):
            res["grupos"][r["CO_GRUPO"]] = r["NO_GRUPO"].capitalize()
        for r in _ler_tabela_sigtap(z, "tb_sub_grupo"):
            res["subgrupos"][r["CO_GRUPO"] + r["CO_SUB_GRUPO"]] = r["NO_SUB_GRUPO"].capitalize()
        for r in _ler_tabela_sigtap(z, "tb_forma_organizacao"):
            res["formas"][r["CO_GRUPO"] + r["CO_SUB_GRUPO"] + r["CO_FORMA_ORGANIZACAO"]] = r["NO_FORMA_ORGANIZACAO"].capitalize()
        res["versoes"].append(v)
    ftp.quit()
    _gravar_json(arq, res)
    return res


def fmt_proc(cod):
    c = str(cod)
    return f"{c[:2]}.{c[2:4]}.{c[4:6]}.{c[6:9]}-{c[9:]}" if len(c) == 10 else c


def procedimentos_opcoes(pasta_cache):
    """{rótulo: prefixo} para menu suspenso: grupos, subgrupos, formas de organização e procedimentos."""
    t = sigtap(pasta_cache)
    ops = {}
    for k, v in sorted(t["grupos"].items()):
        ops[f"Grupo {k}: {v}"] = k
    for k, v in sorted(t["subgrupos"].items()):
        ops[f"Subgrupo {k[:2]}.{k[2:]}: {v}"] = k
    for k, v in sorted(t["formas"].items()):
        ops[f"Forma {k[:2]}.{k[2:4]}.{k[4:]}: {v}"] = k
    for k, v in sorted(t["procedimentos"].items()):
        ops[f"{fmt_proc(k)} – {v}"] = k
    return ops


GRUPOS_CID = [
    ("Doenças isquêmicas do coração", "I20-I25"), ("Infarto agudo do miocárdio", "I21-I22"),
    ("Doenças cerebrovasculares (AVC)", "I60-I69"), ("Doenças hipertensivas", "I10-I15"),
    ("Insuficiência cardíaca", "I50"), ("Neoplasias malignas", "C00-C97"), ("Câncer de mama", "C50"),
    ("Câncer de colo do útero", "C53"), ("Câncer de próstata", "C61"), ("Câncer de pulmão/brônquios", "C33-C34"),
    ("Câncer colorretal", "C18-C21"), ("Diabetes mellitus", "E10-E14"), ("DPOC", "J40-J44"),
    ("Pneumonia", "J12-J18"), ("Influenza e pneumonia", "J09-J18"), ("COVID-19", "U07,B342"),
    ("Tuberculose", "A15-A19"), ("HIV/aids", "B20-B24"), ("Doenças diarreicas", "A00-A09"),
    ("Dengue", "A90-A91"), ("Doença de Chagas", "B57"), ("Cirrose e doenças do fígado", "K70-K77"),
    ("Doença renal crônica", "N18"), ("Transtornos por uso de álcool", "F10"),
    ("Demências e Alzheimer", "F00-F03,G30"), ("Acidentes de transporte", "V01-V99"),
    ("Quedas", "W00-W19"), ("Afogamento", "W65-W74"), ("Lesões autoprovocadas (suicídio)", "X60-X84"),
    ("Agressões (homicídio)", "X85-Y09"), ("Intervenção legal e guerra", "Y35-Y36"),
    ("Eventos de intenção indeterminada", "Y10-Y34"), ("Causas externas (todas)", "V01-Y98"),
    ("Causas mal definidas", "R00-R99"), ("Afecções perinatais", "P00-P96"),
    ("Malformações congênitas", "Q00-Q99"), ("Gravidez, parto e puerpério", "O00-O99"),
]


def cid10_opcoes(pasta_cache):
    """Opções para menu suspenso: {rótulo: prefixos}. Grupos de pesquisa, capítulos e categorias (3 caracteres)."""
    from .tratamento import CAPITULOS_CID10
    ops = {}
    for nome, cods in GRUPOS_CID:
        ops[f"Grupo: {nome} ({cods.replace(',', ', ')})"] = cods
    for ini, fim, num, nome in CAPITULOS_CID10:
        ops[f"Capítulo {num}: {nome} ({ini}-{fim})"] = f"{ini}-{fim}"
    desc = cid10_descricoes(pasta_cache)
    for cod in sorted(c for c in desc if len(c) == 3):
        ops[f"{cod} – {desc[cod]}"] = cod
    return ops


# ------------------------------------------------------------------ malhas
def _area(anel):
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(anel, anel[1:] + anel[:1])) / 2


def _rebobinar(geo):
    """Vega/d3 esperam anel externo no sentido horário (o GeoJSON RFC 7946 do IBGE usa anti-horário)."""
    def poligono(aneis):
        out = []
        for i, anel in enumerate(aneis):
            externo = i == 0
            horario = _area(anel) < 0
            out.append(anel if horario == externo else anel[::-1])
        return out
    for f in geo.get("features", []):
        g = f.get("geometry") or {}
        if g.get("type") == "Polygon":
            g["coordinates"] = poligono(g["coordinates"])
        elif g.get("type") == "MultiPolygon":
            g["coordinates"] = [poligono(p) for p in g["coordinates"]]
    return geo


def _malha(arq, url):
    if os.path.exists(arq):
        return _rebobinar(_ler_json(arq))
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    g = r.json()
    _gravar_json(arq, g)
    return _rebobinar(g)


def malha_municipios(pasta_cache, uf):
    """GeoJSON dos municípios da UF (propriedade `codarea` = código IBGE 7 díg.)."""
    return _malha(os.path.join(pasta_cache, f"malha_{uf}.json"),
                  f"{API_MALHAS}/{UFS[uf]}?formato=application/vnd.geo%2Bjson&intrarregiao=municipio&qualidade=minima")


def malha_ufs(pasta_cache):
    return _malha(os.path.join(pasta_cache, "malha_BR_ufs.json"),
                  "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?formato=application/vnd.geo%2Bjson"
                  "&intrarregiao=UF&qualidade=minima")
