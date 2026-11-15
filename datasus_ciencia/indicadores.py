"""Indicadores prontos de mortalidade e letalidade (definições do MS/RIPSA), a partir das bases processadas.

Cada indicador junta um numerador (óbitos do SIM) e um denominador (nascidos vivos do SINASC, internações do SIH
ou população do TabNet), alinhados por ano e local de residência, com IC95% exato de Poisson.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import estatistica as E
from .referencias import FAIXAS_5_80, PADRAO_OMS_80, faixa5_80
from .tratamento import expandir_cids

DIAS = 365.25
CID_MATERNA = "O00-O95,O98-O99,A34,F53,M830"  # morte materna (MS); O96–O97 (tardias/sequelas) excluídas
GRUPOS_DCNT = {"Doenças cardiovasculares": "I00-I99", "Neoplasias malignas": "C00-C97",
               "Diabetes mellitus": "E10-E14", "Doenças respiratórias crônicas": "J30-J98"}

# chave → definição. num/den: sistemas aceitos; mult: multiplicador; unidade: texto da unidade
INDICADORES = {
    "tmi": {"nome": "Taxa de mortalidade infantil", "num": ("SIM", "SIM-NAC"), "den": "SINASC", "mult": 1000,
            "unidade": "por 1.000 nascidos vivos", "faixa_dias": (0, 365),
            "def": "Óbitos de menores de 1 ano ÷ nascidos vivos × 1.000."},
    "neo": {"nome": "Taxa de mortalidade neonatal", "num": ("SIM", "SIM-NAC"), "den": "SINASC", "mult": 1000,
            "unidade": "por 1.000 nascidos vivos", "faixa_dias": (0, 28),
            "def": "Óbitos de 0 a 27 dias ÷ nascidos vivos × 1.000."},
    "neo_precoce": {"nome": "Taxa de mortalidade neonatal precoce", "num": ("SIM", "SIM-NAC"), "den": "SINASC",
                    "mult": 1000, "unidade": "por 1.000 nascidos vivos", "faixa_dias": (0, 7),
                    "def": "Óbitos de 0 a 6 dias ÷ nascidos vivos × 1.000."},
    "neo_tardia": {"nome": "Taxa de mortalidade neonatal tardia", "num": ("SIM", "SIM-NAC"), "den": "SINASC",
                   "mult": 1000, "unidade": "por 1.000 nascidos vivos", "faixa_dias": (7, 28),
                   "def": "Óbitos de 7 a 27 dias ÷ nascidos vivos × 1.000."},
    "pos_neo": {"nome": "Taxa de mortalidade pós-neonatal", "num": ("SIM", "SIM-NAC"), "den": "SINASC",
                "mult": 1000, "unidade": "por 1.000 nascidos vivos", "faixa_dias": (28, 365),
                "def": "Óbitos de 28 a 364 dias ÷ nascidos vivos × 1.000."},
    "fetal": {"nome": "Taxa de mortalidade fetal", "num": ("SIM", "SIM-NAC"), "den": "SINASC", "mult": 1000,
              "unidade": "por 1.000 nascimentos (vivos + óbitos fetais)",
              "def": "Óbitos fetais (≥22 semanas ou ≥500 g, quando informados) ÷ (nascidos vivos + óbitos fetais com o "
                     "mesmo critério) × 1.000."},
    "perinatal": {"nome": "Taxa de mortalidade perinatal", "num": ("SIM", "SIM-NAC"), "den": "SINASC", "mult": 1000,
                  "unidade": "por 1.000 nascimentos (vivos + óbitos fetais)",
                  "def": "(Óbitos fetais ≥22 semanas + óbitos de 0 a 6 dias) ÷ (nascidos vivos + óbitos fetais "
                         "≥22 semanas) × 1.000."},
    "rmm": {"nome": "Razão de mortalidade materna", "num": ("SIM", "SIM-NAC"), "den": "SINASC", "mult": 100_000,
            "unidade": "por 100 mil nascidos vivos",
            "def": "Óbitos maternos (CID-10 O00–O95, O98–O99, A34, F53, M83.0) ÷ nascidos vivos × 100 mil. "
                   "Não inclui o fator de correção do MS para sub-registro."},
    "letal_sim_sih": {"nome": "Letalidade (óbitos do SIM ÷ internações do SIH)", "num": ("SIM",), "den": "SIH",
                      "mult": 100, "unidade": "%",
                      "def": "Óbitos pela causa (SIM, dentro e fora do hospital) ÷ internações pela mesma causa "
                             "(SIH/SUS) × 100. Indicador aproximado: as bases não são ligadas por pessoa."},
    "dcnt": {"nome": "Mortalidade prematura por DCNT (30–69 anos)", "num": ("SIM",), "den": "POP", "mult": 100_000,
             "unidade": "por 100 mil hab. de 30 a 69 anos",
             "def": "Óbitos de 30 a 69 anos por doenças cardiovasculares (I00–I99), neoplasias malignas (C00–C97), "
                    "diabetes (E10–E14) e doenças respiratórias crônicas (J30–J98) ÷ população de 30 a 69 anos × "
                    "100 mil (meta 3.4 dos ODS)."},
    "tx_incid": {"nome": "Taxa de incidência / detecção (SINAN)", "num": ("SINAN",), "den": "POP", "mult": 100_000,
                 "unidade": "por 100 mil hab.", "por_pop": True,
                 "def": "Casos notificados (residentes) ÷ população residente × 100 mil. Na tuberculose, o MS usa "
                        "só casos novos; na hanseníase, chama-se taxa de detecção."},
    "tx_mort": {"nome": "Taxa de mortalidade (SIM)", "num": ("SIM", "SIM-NAC"), "den": "POP", "mult": 100_000,
                "unidade": "por 100 mil hab.", "por_pop": True,
                "def": "Óbitos (não fetais) de residentes ÷ população residente × 100 mil; geral ou por causa."},
    "tx_intern": {"nome": "Taxa de internação (SIH)", "num": ("SIH",), "den": "POP", "mult": 10_000,
                  "unidade": "por 10 mil hab.", "por_pop": True,
                  "def": "Internações (AIH aprovadas) de residentes ÷ população residente × 10 mil; geral ou por "
                         "causa (diagnóstico principal)."},
    "razao_sexo": {"nome": "Razão de mortalidade por sexo (M/F)", "num": ("SIM",), "den": "POP", "mult": 100_000,
                   "unidade": "razão", "def": "Taxa de mortalidade masculina ÷ taxa feminina (cada uma por 100 mil "
                                              "hab. do mesmo sexo)."},
}

# tipos do SIM-NAC que servem de numerador (DOFET = óbitos fetais, DOINF = infantis, DOMAT = maternos,
# DOEXT = causas externas). O SIM por UF (DO) não tem óbitos fetais: a taxa fetal só sai do DOFET.
_INFANTIS = {"SIM": None, "SIM-NAC": {"DOINF"}}
NUM_TIPOS = {"tmi": _INFANTIS, "neo": _INFANTIS, "neo_precoce": _INFANTIS, "neo_tardia": _INFANTIS,
             "pos_neo": _INFANTIS, "fetal": {"SIM-NAC": {"DOFET"}},
             "perinatal": {"SIM": None, "SIM-NAC": {"DOINF", "DOFET"}},
             "rmm": {"SIM": None, "SIM-NAC": {"DOMAT"}},
             "tx_mort": {"SIM": None, "SIM-NAC": {"DOINF", "DOMAT", "DOEXT"}}}


def serve_numerador(ch, sistema, tipo=None):
    """A base (sistema, tipo) pode ser numerador do indicador `ch`? Ex.: óbitos fetais (DOFET) não entram na
    mortalidade infantil (dariam numerador 0)."""
    if sistema not in INDICADORES[ch]["num"]:
        return False
    regra = NUM_TIPOS.get(ch)
    if regra is None:
        return True
    if sistema not in regra:
        return False
    tipos = regra[sistema]
    return tipos is None or (tipo or "").upper() in tipos

COL_ANO = {"SIM": "ano_obito", "SIM-NAC": "ano_obito", "SINASC": "ano_nascimento", "SIH": "ano_processamento",
           "SINAN": "ano_notificacao"}
COL_CID = {"SIM": "causa_basica", "SIM-NAC": "causa_basica", "SIH": "diag_principal"}
NIVEIS = {"Total": [], "UF de residência": ["mun_residencia_uf"],
          "Município de residência": ["mun_residencia_cod_ibge6", "mun_residencia_nome", "mun_residencia_uf"]}


# ------------------------------------------------------------------ seleção do numerador
def _cid(df, sistema, spec):
    col = COL_CID.get(sistema)
    if col not in df:
        col = "CAUSABAS" if "CAUSABAS" in df else "DIAG_PRINC"
    v = df[col].astype("string").str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
    prefs = tuple(expandir_cids(spec.replace("M830", "M83").split(",")))
    m = v.str.startswith(prefs).fillna(False)
    if "M830" in spec:  # só M83.0 (osteomalácia puerperal), não todo o M83
        m &= ~(v.str.startswith("M83") & ~v.str.startswith("M830")).fillna(False)
    return m


def _fetal(df):
    if "tipo_obito" in df:
        return (df["tipo_obito"] == "Fetal").fillna(False)
    return pd.Series(False, index=df.index)


def _fetal_viavel(df):
    """Óbito fetal com ≥22 semanas ou ≥500 g; sem as duas informações, entra (critério do TabNet)."""
    vazio = pd.Series(np.nan, index=df.index)
    sem = pd.to_numeric(df["semanas_gestacao"], errors="coerce") if "semanas_gestacao" in df else vazio
    peso = pd.to_numeric(df["peso_g"], errors="coerce") if "peso_g" in df else vazio
    conhecido = sem.notna() | peso.notna()
    viavel = (sem >= 22) | (peso >= 500)
    return _fetal(df) & (viavel | ~conhecido).fillna(True)


def idade_dias(df):
    """Idade em dias completos. `idade_anos` é guardada com 3 casas (ex.: 7 dias = 0,019 ano = 6,94 dias), então
    arredonda para o dia inteiro mais próximo – sem isso, óbitos com 7 dias caem na faixa de 0 a 6 dias."""
    if "idade_anos" not in df:
        return None
    return np.round(pd.to_numeric(df["idade_anos"], errors="coerce").astype(float) * DIAS)


def selecionar_numerador(chave, df, sistema, cid_spec=None, so_novos=False, sem_descartados=False):
    """Máscara booleana dos registros que entram no numerador do indicador."""
    ind = INDICADORES[chave]
    dias = idade_dias(df)
    nao_fetal = ~_fetal(df)
    if chave == "tx_incid":
        m = pd.Series(True, index=df.index)
        if so_novos and "tipo_entrada_tb" in df:
            m &= (df["tipo_entrada_tb"] == "Caso novo").fillna(False)
        if sem_descartados and "classificacao_final" in df:
            m &= ~(df["classificacao_final"] == "Descartado").fillna(False)
        return m
    if chave == "tx_mort":
        return nao_fetal & (_cid(df, sistema, cid_spec) if cid_spec else True)
    if chave == "tx_intern":
        return _cid(df, sistema, cid_spec) if cid_spec else pd.Series(True, index=df.index)
    if "faixa_dias" in ind:
        a, b = ind["faixa_dias"]
        if dias is None:
            return pd.Series(False, index=df.index)
        return nao_fetal & (dias >= a) & (dias < b)
    if chave == "fetal":
        return _fetal_viavel(df)
    if chave == "perinatal":
        precoce = nao_fetal & (dias < 7) if dias is not None else pd.Series(False, index=df.index)
        return _fetal_viavel(df) | precoce.fillna(False)
    if chave == "rmm":
        fem = (df["sexo"] == "Feminino").fillna(False) if "sexo" in df else True
        return nao_fetal & _cid(df, sistema, CID_MATERNA) & fem
    if chave == "letal_sim_sih":
        return _cid(df, sistema, cid_spec) if cid_spec else pd.Series(True, index=df.index)
    if chave == "dcnt":
        idade = pd.to_numeric(df.get("idade_anos"), errors="coerce")
        return nao_fetal & idade.between(30, 69.999) & _cid(df, sistema, ",".join(GRUPOS_DCNT.values()))
    return nao_fetal


def grupo_dcnt(df, sistema):
    out = pd.Series(pd.NA, index=df.index, dtype="string")
    for nome, spec in GRUPOS_DCNT.items():
        out[_cid(df, sistema, spec) & out.isna()] = nome
    return out


# ------------------------------------------------------------------ contagens e taxas
def contar(df, ano_col, nivel, mascara=None):
    chaves = [ano_col] + NIVEIS[nivel]
    d = df if mascara is None else df[mascara]
    if not len(d):
        return pd.DataFrame(columns=["ano"] + NIVEIS[nivel] + ["n"])
    c = d.groupby(chaves, dropna=False, observed=True).size().reset_index(name="n")
    return c.rename(columns={ano_col: "ano"})


def combinar(num, den, nivel, mult, anos=None):
    """num/den (ano, nível, n) → taxa com IC95% de Poisson (numerador). Anos fora de `anos` são descartados."""
    chaves = ["ano"] + NIVEIS[nivel]
    em_comum = [c for c in chaves if c in den.columns and c in num.columns]
    num = num.groupby(em_comum, as_index=False, dropna=False)["n"].sum() if len(num) else \
        pd.DataFrame(columns=em_comum + ["n"])
    if nivel == "Município de residência" and "mun_residencia_nome" not in den:
        den = den.groupby(em_comum, as_index=False)["n"].sum()
        chaves = em_comum
    t = den.rename(columns={"n": "denominador"}).merge(num.rename(columns={"n": "numerador"}), on=em_comum,
                                                        how="left")
    t["numerador"] = t["numerador"].fillna(0).astype(int)
    if anos is not None:
        t = t[t["ano"].isin(anos)]
    t = t[t["denominador"] > 0].copy()
    tx = E.taxas(t["numerador"].to_numpy(), t["denominador"].to_numpy(), mult)
    t[["taxa", "ic95_inf", "ic95_sup"]] = tx.round(3).to_numpy()
    t["ano"] = t["ano"].astype(int)
    return t.sort_values(chaves).reset_index(drop=True)


def total_periodo(t, mult):
    k, n = t["numerador"].sum(), t["denominador"].sum()
    tx = E.taxas([k], [n], mult).iloc[0]
    return {"numerador": int(k), "denominador": float(n), "taxa": tx["taxa"], "ic95_inf": tx["ic95_inf"],
            "ic95_sup": tx["ic95_sup"]}


def tendencia(t):
    """Prais-Winsten sobre a série anual total (sem desagregação)."""
    s = t.groupby("ano")[["numerador", "denominador"]].sum().reset_index()
    s = s[s["numerador"] > 0]
    if len(s) < 4:
        return None
    return E.prais_winsten(s["ano"], s["numerador"] / s["denominador"])


# ------------------------------------------------------------------ indicadores com população
def populacao_por(pop, nivel, idade_min=None, idade_max=None, sexo=None):
    """pop (populacao_svs: cod6, ano, sexo, idade, pop, uf) → (ano, nível, n)."""
    p = pop
    if idade_min is not None:
        p = p[p["idade"].astype(int) >= idade_min]
    if idade_max is not None:
        p = p[p["idade"].astype(int) <= idade_max]
    if sexo:
        p = p[p["sexo"] == sexo]
    p = p.rename(columns={"cod6": "mun_residencia_cod_ibge6", "uf": "mun_residencia_uf"})
    cols = [c for c in NIVEIS[nivel] if c in p] if nivel != "Município de residência" else \
        ["mun_residencia_cod_ibge6"]
    g = p.groupby(["ano"] + cols, as_index=False)["pop"].sum().rename(columns={"pop": "n"})
    return g


def padronizada_dcnt(obitos_df, pop, ano_col, anos):
    """Taxa de DCNT 30–69 padronizada por idade (OMS, faixas quinquenais 30–69) por ano."""
    return padronizada(obitos_df, pop, ano_col, anos, 30, 69)


def padronizada(obitos_df, pop, ano_col, anos, idade_min=0, idade_max=80, mult=100_000):
    """Taxa padronizada por idade (método direto, população-padrão mundial da OMS, faixas quinquenais com 80+)
    por ano, restrita às faixas de idade_min a idade_max. `pop` já deve estar filtrada nas mesmas idades/sexo."""
    i0, i1 = int(idade_min) // 5, min(int(idade_max) // 5, 16)
    faixas = FAIXAS_5_80[i0:i1 + 1]
    pesos = PADRAO_OMS_80[i0:i1 + 1]
    ob = obitos_df.assign(_f=faixa5_80(obitos_df["idade_anos"]))
    pp = pop.assign(_f=faixa5_80(pop["idade"]))
    linhas = []
    for ano in anos:
        d = ob[ob[ano_col] == ano].groupby("_f").size().reindex(faixas, fill_value=0)
        n = pp[pp["ano"] == ano].groupby("_f")["pop"].sum().reindex(faixas, fill_value=0)
        if n.sum() > 0:
            r = E.padronizacao_direta(d.to_numpy(), n.to_numpy(), pesos, mult)
            linhas.append({"ano": int(ano), "taxa_padronizada": round(r["taxa"], 3),
                           "ic95_inf_pad": round(r["ic95_inf"], 3), "ic95_sup_pad": round(r["ic95_sup"], 3)})
    return pd.DataFrame(linhas)


def razao_por_sexo(obitos_df, pop, ano_col, anos, padronizar=False):
    """Por ano: taxas M e F por 100 mil, razão M/F com IC95% e p."""
    linhas = []
    ob = obitos_df.assign(_f=faixa5_80(obitos_df["idade_anos"])) if padronizar else obitos_df
    pp = pop.assign(_f=faixa5_80(pop["idade"])) if padronizar else pop
    for ano in anos:
        o, p = ob[ob[ano_col] == ano], pp[pp["ano"] == ano]
        kM, kF = int((o["sexo"] == "Masculino").sum()), int((o["sexo"] == "Feminino").sum())
        nM, nF = p.loc[p["sexo"] == "Masculino", "pop"].sum(), p.loc[p["sexo"] == "Feminino", "pop"].sum()
        if not (nM and nF):
            continue
        if padronizar:
            def pad(sx, pop_sx):
                d = o[o["sexo"] == sx].groupby("_f").size().reindex(FAIXAS_5_80, fill_value=0)
                n = pop_sx.groupby("_f")["pop"].sum().reindex(FAIXAS_5_80, fill_value=0)
                return E.padronizacao_direta(d.to_numpy(), n.to_numpy(), PADRAO_OMS_80)
            rF, rM = pad("Feminino", p[p["sexo"] == "Feminino"]), pad("Masculino", p[p["sexo"] == "Masculino"])
            rz = E.razao_padronizada(rF, rM)
            tM, tF, razao, ic, pv = rM["taxa"], rF["taxa"], rz["razao"], rz["ic"], rz["p"]
        else:
            c = E.comparar_taxas(kF, nF, kM, nM)
            tM, tF, razao, ic, pv = c["tB"] * 1e5, c["tA"] * 1e5, c["razao"], c["razao_ic"], c["p"]
        linhas.append({"ano": int(ano), "óbitos M": kM, "óbitos F": kF, "taxa M": round(tM, 2),
                       "taxa F": round(tF, 2), "razão M/F": round(razao, 3), "ic95_inf": round(ic[0], 3),
                       "ic95_sup": round(ic[1], 3), "p": E.fmt_p(pv)})
    return pd.DataFrame(linhas)


def anos_em_comum(*series):
    conj = None
    for s in series:
        a = set(int(x) for x in pd.Series(s).dropna().unique())
        conj = a if conj is None else conj & a
    return sorted(conj or [])
