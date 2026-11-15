"""Tratamento para análise: decodificação de categorias, idade em anos, datas, CID-10 e municípios.

Regra geral: as variáveis ORIGINAIS (maiúsculas) são mantidas intactas; as variáveis DERIVADAS
são criadas em minúsculas, para que toda transformação seja rastreável e auditável.
"""

import json
import os
import time

import numpy as np
import pandas as pd
import requests

from .catalogo import REGIOES, UF_POR_CODIGO

# ---------------------------------------------------------------- dicionários de códigos
SEXO_SIM = {"1": "Masculino", "2": "Feminino", "M": "Masculino", "F": "Feminino"}
SEXO_SIH = {"1": "Masculino", "2": "Feminino", "3": "Feminino"}
SEXO_SINAN = {"M": "Masculino", "F": "Feminino"}
RACA_SIM = {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena"}
RACA_SIH = {"01": "Branca", "02": "Preta", "03": "Parda", "04": "Amarela", "05": "Indígena",
            "1": "Branca", "2": "Preta", "3": "Parda", "4": "Amarela", "5": "Indígena"}
ESTCIV = {"1": "Solteiro", "2": "Casado", "3": "Viúvo", "4": "Separado judicialmente/divorciado", "5": "União estável"}
ESC_ANOS = {"1": "Nenhuma", "2": "1 a 3 anos", "3": "4 a 7 anos", "4": "8 a 11 anos", "5": "12 anos ou mais"}
LOCOCOR = {"1": "Hospital", "2": "Outros estabelecimentos de saúde", "3": "Domicílio", "4": "Via pública",
           "5": "Outros", "6": "Aldeia indígena"}
CIRCOBITO = {"1": "Acidente", "2": "Suicídio", "3": "Homicídio", "4": "Outros"}
PARTO = {"1": "Vaginal", "2": "Cesáreo"}
GRAVIDEZ = {"1": "Única", "2": "Dupla", "3": "Tripla ou mais"}
GESTACAO = {"1": "Menos de 22 semanas", "2": "22 a 27 semanas", "3": "28 a 31 semanas",
            "4": "32 a 36 semanas", "5": "37 a 41 semanas", "6": "42 semanas ou mais"}
CONSULTAS = {"1": "Nenhuma", "2": "1 a 3", "3": "4 a 6", "4": "7 ou mais"}
CAR_INT = {"01": "Eletivo", "02": "Urgência", "03": "Acidente no local de trabalho", "04": "Acidente no trajeto",
           "05": "Outros acidentes de trânsito", "06": "Outras lesões/envenenamentos"}
SINAN_EVOLUCAO = {"1": "Cura", "2": "Óbito pelo agravo", "3": "Óbito por outras causas", "4": "Óbito em investigação"}
# SIM – variáveis perinatais/maternas (categorias do TabNet)
TIPOBITO = {"1": "Fetal", "2": "Não fetal"}
OBITOPARTO = {"1": "Antes do parto", "2": "Durante o parto", "3": "Depois do parto"}
SIM_NAO = {"1": "Sim", "2": "Não", "S": "Sim", "N": "Não"}
OBITOPUERP = {"1": "Sim, até 42 dias após o parto", "2": "Sim, de 43 dias a 1 ano", "3": "Não"}
TPMORTEOCO = {"1": "Na gravidez", "2": "No parto", "3": "No abortamento", "4": "Até 42 dias após o término da gestação",
              "5": "De 43 dias a 1 ano após o término da gestação", "8": "Não ocorreu nestes períodos"}
FAIXAS_PESO = [(0, 500, "Menos de 500 g"), (500, 1000, "500 a 999 g"), (1000, 1500, "1.000 a 1.499 g"),
               (1500, 2500, "1.500 a 2.499 g"), (2500, 3000, "2.500 a 2.999 g"), (3000, 4000, "3.000 a 3.999 g"),
               (4000, 99999, "4.000 g e mais")]
FAIXAS_IDADE_MAE = ([0, 15, 20, 25, 30, 35, 40, 45, 100],
                    ["10 a 14 anos", "15 a 19 anos", "20 a 24 anos", "25 a 29 anos", "30 a 34 anos",
                     "35 a 39 anos", "40 a 44 anos", "45 anos ou mais"])

FAIXAS = [(0, 1, "<1"), (1, 5, "1-4"), (5, 10, "5-9"), (10, 15, "10-14"), (15, 20, "15-19"),
          (20, 30, "20-29"), (30, 40, "30-39"), (40, 50, "40-49"), (50, 60, "50-59"),
          (60, 70, "60-69"), (70, 80, "70-79"), (80, 200, "80+")]

CAPITULOS_CID10 = [
    ("A00", "B99", "I", "Algumas doenças infecciosas e parasitárias"),
    ("C00", "D48", "II", "Neoplasias"),
    ("D50", "D89", "III", "Doenças do sangue e órgãos hematopoéticos e transtornos imunitários"),
    ("E00", "E90", "IV", "Doenças endócrinas, nutricionais e metabólicas"),
    ("F00", "F99", "V", "Transtornos mentais e comportamentais"),
    ("G00", "G99", "VI", "Doenças do sistema nervoso"),
    ("H00", "H59", "VII", "Doenças do olho e anexos"),
    ("H60", "H95", "VIII", "Doenças do ouvido e da apófise mastoide"),
    ("I00", "I99", "IX", "Doenças do aparelho circulatório"),
    ("J00", "J99", "X", "Doenças do aparelho respiratório"),
    ("K00", "K93", "XI", "Doenças do aparelho digestivo"),
    ("L00", "L99", "XII", "Doenças da pele e do tecido subcutâneo"),
    ("M00", "M99", "XIII", "Doenças do sistema osteomuscular e do tecido conjuntivo"),
    ("N00", "N99", "XIV", "Doenças do aparelho geniturinário"),
    ("O00", "O99", "XV", "Gravidez, parto e puerpério"),
    ("P00", "P96", "XVI", "Algumas afecções originadas no período perinatal"),
    ("Q00", "Q99", "XVII", "Malformações congênitas, deformidades e anomalias cromossômicas"),
    ("R00", "R99", "XVIII", "Sintomas, sinais e achados anormais não classificados em outra parte"),
    ("S00", "T98", "XIX", "Lesões, envenenamentos e outras consequências de causas externas"),
    ("V01", "Y98", "XX", "Causas externas de morbidade e mortalidade"),
    ("Z00", "Z99", "XXI", "Fatores que influenciam o estado de saúde e o contato com os serviços de saúde"),
    ("U00", "U99", "XXII", "Códigos para propósitos especiais"),
]


# ---------------------------------------------------------------- utilitários
def _decod(s, mapa, ignorado="Ignorado"):
    s = s.astype("string").str.strip()
    out = s.map(mapa)
    out = out.where(s.isna() | out.notna(), ignorado)
    return out.astype("string")


def _data(s, formato):
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    return pd.to_datetime(s.astype("string"), format=formato, errors="coerce")


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def faixa_etaria(idade):
    bins = [f[0] for f in FAIXAS] + [FAIXAS[-1][1]]
    rot = [f[2] for f in FAIXAS]
    idade = pd.to_numeric(idade, errors="coerce").astype(float)
    return pd.cut(idade, bins=bins, labels=rot, right=False).astype("string")


def cid_capitulo(cid):
    c = cid.astype("string").str.upper().str.replace(r"[^A-Z0-9]", "", regex=True).str[:3]
    cap = pd.Series(pd.NA, index=cid.index, dtype="string")
    desc = pd.Series(pd.NA, index=cid.index, dtype="string")
    for ini, fim, num, nome in CAPITULOS_CID10:
        m = (c >= ini) & (c <= fim)
        cap = cap.mask(m.fillna(False), num)
        desc = desc.mask(m.fillna(False), nome)
    return cap, desc


def _np(x):
    """Série (possivelmente com NA) → ndarray float, com NaN no lugar de NA (np.select exige ndarray puro)."""
    return pd.to_numeric(x, errors="coerce").astype(float).to_numpy()


def idade_codificada_sim(s):
    """IDADE do SIM (3 dígitos): 1º dígito = unidade (0 min, 1 h, 2 dias, 3 meses, 4 anos, 5 = 100+ anos)."""
    s = s.astype("string").str.strip()
    s = s.where(s.str.len() > 0).str.zfill(3)  # vazio = sem informação (não "0 minutos")
    un = _np(s.str[0])
    v = _np(s.str[1:])
    anos = np.select(
        [un == 0, un == 1, un == 2, un == 3, un == 4, un == 5],
        [v / 525960, v / 8766, v / 365.25, v / 12, v, 100 + v], default=np.nan)
    return pd.Series(anos, index=s.index, dtype="Float64").round(3)


def idade_codificada_sinan(s):
    """NU_IDADE_N do SINAN (4 dígitos): 1º = unidade (1 h, 2 dias, 3 meses, 4 anos)."""
    x = _np(s)
    un = x // 1000
    v = x % 1000
    anos = np.select([un == 1, un == 2, un == 3, un == 4], [v / 8766, v / 365.25, v / 12, v], default=np.nan)
    return pd.Series(anos, index=s.index, dtype="Float64").round(3)


def idade_sih(idade, cod):
    v = _np(idade)
    c = _np(cod.astype("string").str.strip())
    anos = np.select([c == 2, c == 3, c == 4, c == 5], [v / 365.25, v / 12, v, 100 + v], default=np.nan)
    return pd.Series(anos, index=idade.index, dtype="Float64").round(3)


# ---------------------------------------------------------------- municípios (IBGE)
class Municipios:
    URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"

    def __init__(self, pasta_cache, log=print):
        self.arq = os.path.join(pasta_cache, "municipios_ibge.json")
        self.log = log
        self._mapa = None

    def mapa(self):
        if self._mapa is not None:
            return self._mapa
        dados = None
        if os.path.exists(self.arq) and (time.time() - os.path.getmtime(self.arq)) < 90 * 86400:
            with open(self.arq, encoding="utf-8") as fh:
                dados = json.load(fh)
        else:
            try:
                r = requests.get(self.URL, timeout=60)
                r.raise_for_status()
                dados = {}
                for m in r.json():
                    cod7 = str(m["id"])
                    micro = m.get("microrregiao") or {}
                    meso = micro.get("mesorregiao") or {}
                    uf = (meso.get("UF") or {}) if meso else ((m.get("regiao-imediata") or {}).get("regiao-intermediaria") or {}).get("UF") or {}
                    dados[cod7[:6]] = {"cod7": cod7, "nome": m["nome"], "uf": uf.get("sigla")}
                with open(self.arq, "w", encoding="utf-8") as fh:
                    json.dump(dados, fh, ensure_ascii=False)
            except Exception as e:
                self.log(f"  ! não foi possível obter nomes de municípios do IBGE ({e}); seguindo sem eles.")
                dados = {}
        self._mapa = dados
        return dados

    def adicionar(self, df, coluna, prefixo):
        if coluna not in df.columns:
            return
        cod = df[coluna].astype("string").str.strip().str[:6]
        mp = self.mapa()
        df[f"{prefixo}_cod_ibge6"] = cod
        if mp:
            df[f"{prefixo}_cod_ibge7"] = cod.map(lambda c: mp.get(c, {}).get("cod7") if isinstance(c, str) else None).astype("string")
            df[f"{prefixo}_nome"] = cod.map(lambda c: mp.get(c, {}).get("nome") if isinstance(c, str) else None).astype("string")
        uf_cod = cod.str[:2]
        df[f"{prefixo}_uf"] = uf_cod.map(UF_POR_CODIGO).astype("string")
        df[f"{prefixo}_regiao"] = cod.str[:1].map(REGIOES).astype("string")


# ---------------------------------------------------------------- tratamento por sistema
def tratar(df, sistema, municipios, procedimentos_nomes=None):
    if df.empty:
        return df
    f = {"SIM": _sim, "SIM-NAC": _sim, "SINASC": _sinasc, "SIH": _sih, "SINAN": _sinan,
         "CNES": _cnes, "SIA": _sia}.get(sistema)
    if f:
        f(df, municipios)
    col = COLUNA_PROC.get(sistema)
    if col and col in df:
        df["procedimento"] = df[col].astype("string").str.strip()
        if procedimentos_nomes:
            from .referencias import fmt_proc
            df["procedimento_nome"] = df["procedimento"].map(
                lambda c: f"{fmt_proc(c)} {procedimentos_nomes.get(c, '')}".strip() if isinstance(c, str) else None
            ).astype("string")
    variaveis_extras(df)
    return df


# ---------------------------------------------------------------- variáveis extras (filtros do TabNet)
APGAR_CAT = [(0, 3, "0 a 2"), (3, 6, "3 a 5"), (6, 8, "6 a 7"), (8, 11, "8 a 10")]
ROBSON = {str(i): f"Grupo {i}" for i in range(1, 11)} | {"11": "Não classificado"}
KOTELCHUCK = {"1": "Não fez pré-natal", "2": "Inadequado", "3": "Intermediário", "4": "Adequado",
              "5": "Mais que adequado", "6": "Não classificado"}
SINAN_CLASSI_FIN = {"1": "Confirmado", "2": "Descartado", "8": "Inconclusivo"}
SINAN_CLASSI_FIN_ARBO = {"5": "Descartado", "8": "Inconclusivo", "10": "Dengue", "11": "Dengue com sinais de alarme",
                         "12": "Dengue grave", "13": "Chikungunya"}
SINAN_CRITERIO = {"1": "Laboratorial", "2": "Clínico-epidemiológico", "3": "Em investigação"}
SIM_NAO_IGN = {"1": "Sim", "2": "Não"}
SINAN_AUTOCTONE = {"1": "Sim", "2": "Não", "3": "Indeterminado"}
TB_FORMA = {"1": "Pulmonar", "2": "Extrapulmonar", "3": "Pulmonar + extrapulmonar"}
TB_ENTRADA = {"1": "Caso novo", "2": "Recidiva", "3": "Reingresso após abandono", "4": "Não sabe",
              "5": "Transferência", "6": "Pós-óbito"}
TB_ENCERRA = {"1": "Cura", "2": "Abandono", "3": "Óbito por tuberculose", "4": "Óbito por outras causas",
              "5": "Transferência", "6": "Mudança de diagnóstico", "7": "TB drogarresistente",
              "8": "Mudança de esquema", "9": "Falência", "10": "Abandono primário"}
TB_HIV = {"1": "Positivo", "2": "Negativo", "3": "Em andamento", "4": "Não realizado"}
HANS_CLASSOP = {"1": "Paucibacilar", "2": "Multibacilar"}
HANS_FORMA = {"1": "Indeterminada", "2": "Tuberculoide", "3": "Dimorfa", "4": "Virchowiana", "5": "Não classificada"}
TB, HANS = ("A15", "A16", "A17", "A18", "A19"), ("A30",)
EXTRAS_DECOD = [  # (coluna original, coluna derivada, mapa, prefixos CID do agravo SINAN ou None = qualquer)
    ("TPROBSON", "grupo_robson", ROBSON, None), ("KOTELCHUCK", "adequacao_prenatal", KOTELCHUCK, None),
    ("CRITERIO", "criterio_confirmacao", SINAN_CRITERIO, None), ("HOSPITALIZ", "hospitalizacao", SIM_NAO_IGN, None),
    ("TPAUTOCTO", "caso_autoctone", SINAN_AUTOCTONE, None), ("FORMA", "forma_clinica_tb", TB_FORMA, TB),
    ("TRATAMENTO", "tipo_entrada_tb", TB_ENTRADA, TB), ("SITUA_ENCE", "encerramento_tb", TB_ENCERRA, TB),
    ("HIV", "hiv_tb", TB_HIV, TB), ("CLASSOPERA", "classificacao_operacional", HANS_CLASSOP, HANS),
    ("FORMACLINI", "forma_clinica_hans", HANS_FORMA, HANS),
]


def _agravo_eh(df, prefixos):
    if prefixos is None:
        return True
    if "ID_AGRAVO" not in df:
        return False
    a = df["ID_AGRAVO"].dropna().astype("string").str.upper()
    return bool(len(a)) and a.str.startswith(prefixos).mean() > 0.9


def variaveis_extras(df):
    """Decodifica variáveis usadas como filtros no TabNet (SINASC e SINAN) quando a coluna original existe e a
    derivada ainda não. Também é chamada pela interface, para bases processadas antes desta versão."""
    for orig, nova, mapa, agravo in EXTRAS_DECOD:
        if orig in df and nova not in df and _agravo_eh(df, agravo):
            s = df[orig].astype("string").str.strip().str.lstrip("0").replace("", pd.NA)
            df[nova] = _decod(s, mapa)
    if "CLASSI_FIN" in df and "classificacao_final" not in df:
        arbo = "ID_AGRAVO" in df and df["ID_AGRAVO"].astype("string").str.upper().str.startswith(("A90", "A92")).any()
        df["classificacao_final"] = _decod(df["CLASSI_FIN"].astype("string").str.strip().str.lstrip("0"),
                                           SINAN_CLASSI_FIN_ARBO if arbo else SINAN_CLASSI_FIN)
    for orig, nova in (("APGAR1", "apgar1_cat"), ("APGAR5", "apgar5_cat")):
        if orig in df and nova not in df:
            v = _num(df[orig]).astype("Float64").mask(lambda x: x > 10)
            cat = pd.Series(pd.NA, index=df.index, dtype="string")
            for ini, fim, rot in APGAR_CAT:
                cat[(v >= ini) & (v < fim)] = rot
            df[nova] = cat.fillna("Ignorado")
    return df


def _sim(df, mun):
    if "DTOBITO" in df:
        df["data_obito"] = _data(df["DTOBITO"], "%d%m%Y")
        df["ano_obito"] = df["data_obito"].dt.year.astype("Int64")
        df["mes_obito"] = df["data_obito"].dt.month.astype("Int64")
    if "DTNASC" in df:
        df["data_nascimento"] = _data(df["DTNASC"], "%d%m%Y")
    if "IDADE" in df:
        df["idade_anos"] = idade_codificada_sim(df["IDADE"])
        df["faixa_etaria"] = faixa_etaria(df["idade_anos"])
        df["obito_infantil"] = (df["idade_anos"] < 1).astype("boolean")
    if "SEXO" in df:
        df["sexo"] = _decod(df["SEXO"], SEXO_SIM)
    if "RACACOR" in df:
        df["raca_cor"] = _decod(df["RACACOR"], RACA_SIM)
    if "ESTCIV" in df:
        df["estado_civil"] = _decod(df["ESTCIV"], ESTCIV)
    if "ESC" in df:
        df["escolaridade"] = _decod(df["ESC"], ESC_ANOS)
    if "LOCOCOR" in df:
        df["local_ocorrencia"] = _decod(df["LOCOCOR"], LOCOCOR)
    if "CIRCOBITO" in df:
        df["circunstancia_obito"] = _decod(df["CIRCOBITO"], CIRCOBITO)
    if "CAUSABAS" in df:
        df["causa_basica"] = df["CAUSABAS"].astype("string").str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
        df["causa_basica_cat3"] = df["causa_basica"].str[:3]
        df["cid10_capitulo"], df["cid10_capitulo_nome"] = cid_capitulo(df["causa_basica"])
    _sim_perinatal(df)
    mun.adicionar(df, "CODMUNRES", "mun_residencia")
    mun.adicionar(df, "CODMUNOCOR", "mun_ocorrencia")


def _peso_cat(peso):
    p = pd.to_numeric(peso, errors="coerce").astype(float)
    return pd.cut(p, [f[0] for f in FAIXAS_PESO] + [FAIXAS_PESO[-1][1]], labels=[f[2] for f in FAIXAS_PESO],
                  right=False).astype("string")


def _idade_mae(df, col):
    df["idade_mae"] = _num(df[col]).astype("Float64").mask(lambda x: (x < 8) | (x > 65))
    b, r = FAIXAS_IDADE_MAE
    df["faixa_etaria_mae"] = pd.cut(df["idade_mae"].astype(float), b, labels=r, right=False).astype("string")


def _sim_perinatal(df):
    """Variáveis da DO para óbitos fetais, infantis e maternos (mesmas seleções do TabNet)."""
    fetal = pd.Series(False, index=df.index)
    if "TIPOBITO" in df:
        df["tipo_obito"] = _decod(df["TIPOBITO"], TIPOBITO)
        fetal = (df["tipo_obito"] == "Fetal").fillna(False)
        # óbito fetal não tem idade nem características do falecido: evita "idade 0" e afins
        for c in ("idade_anos", "faixa_etaria", "obito_infantil", "estado_civil", "escolaridade", "raca_cor"):
            if c in df and fetal.any():
                df[c] = df[c].mask(fetal)
    if "IDADE" in df:
        # faixa etária do óbito infantil (neonatal precoce/tardio, pós-neonatal)
        s = df["IDADE"].astype("string").str.strip()
        s = s.where(s.str.len() > 0).str.zfill(3)
        un, v = _np(s.str[0]), _np(s.str[1:])
        dias = np.select([un <= 1, un == 2, un == 3], [0, v, v * 30.44], default=np.nan)
        cat = np.select([dias < 7, dias < 28, dias < 365], ["0 a 6 dias", "7 a 27 dias", "28 a 364 dias"],
                        default="")
        cat = pd.Series(cat, index=df.index).replace("", pd.NA)
        df["faixa_etaria_infantil"] = cat.where(~fetal & pd.Series(np.isfinite(dias), index=df.index)).astype("string")
        df["componente_infantil"] = df["faixa_etaria_infantil"].map(
            {"0 a 6 dias": "Neonatal precoce", "7 a 27 dias": "Neonatal tardio", "28 a 364 dias": "Pós-neonatal"}
        ).astype("string")
    if "IDADEMAE" in df:
        _idade_mae(df, "IDADEMAE")
    if "ESCMAE" in df:
        df["escolaridade_mae"] = _decod(df["ESCMAE"], ESC_ANOS)
    if "GESTACAO" in df:
        df["gestacao_semanas_cat"] = _decod(df["GESTACAO"], GESTACAO)
    if "SEMAGESTAC" in df:
        df["semanas_gestacao"] = _num(df["SEMAGESTAC"]).astype("Float64").mask(lambda x: (x < 10) | (x > 45))
    if "GRAVIDEZ" in df:
        df["tipo_gravidez"] = _decod(df["GRAVIDEZ"], GRAVIDEZ)
    if "PARTO" in df:
        df["tipo_parto"] = _decod(df["PARTO"], PARTO)
    if "PESO" in df:
        df["peso_g"] = _num(df["PESO"]).astype("Float64").mask(lambda x: (x < 100) | (x > 7000))
        df["peso_nascer_cat"] = _peso_cat(df["peso_g"])
        df["baixo_peso"] = (df["peso_g"] < 2500).astype("boolean")
    if "OBITOPARTO" in df:
        df["obito_relacao_parto"] = _decod(df["OBITOPARTO"], OBITOPARTO)
    if "TPPOS" in df:
        df["obito_investigado"] = _decod(df["TPPOS"], SIM_NAO)
    for c, n in (("QTDFILVIVO", "filhos_vivos"), ("QTDFILMORT", "filhos_mortos")):
        if c in df:
            df[n] = _num(df[c]).astype("Float64").mask(lambda x: x > 30)
    if "OBITOGRAV" in df:
        df["obito_na_gravidez"] = _decod(df["OBITOGRAV"], SIM_NAO)
    if "OBITOPUERP" in df:
        df["obito_no_puerperio"] = _decod(df["OBITOPUERP"], OBITOPUERP)
    if "TPMORTEOCO" in df:
        df["momento_obito_materno"] = _decod(df["TPMORTEOCO"], TPMORTEOCO)
    # remove colunas totalmente vazias (ex.: variáveis maternas em óbitos de adultos)
    for c in ("idade_mae", "faixa_etaria_mae", "escolaridade_mae", "gestacao_semanas_cat", "semanas_gestacao",
              "tipo_gravidez", "tipo_parto", "peso_g", "peso_nascer_cat", "baixo_peso", "obito_relacao_parto",
              "faixa_etaria_infantil", "componente_infantil", "filhos_vivos", "filhos_mortos",
              "obito_na_gravidez", "obito_no_puerperio", "momento_obito_materno"):
        if c in df and (df[c].isna() | df[c].isin(["Ignorado"])).all():
            del df[c]


def _sinasc(df, mun):
    if "DTNASC" in df:
        df["data_nascimento"] = _data(df["DTNASC"], "%d%m%Y")
        df["ano_nascimento"] = df["data_nascimento"].dt.year.astype("Int64")
        df["mes_nascimento"] = df["data_nascimento"].dt.month.astype("Int64")
    if "SEXO" in df:
        df["sexo"] = _decod(df["SEXO"], SEXO_SIM)
    if "RACACOR" in df:
        df["raca_cor"] = _decod(df["RACACOR"], RACA_SIM)
    if "RACACORMAE" in df:
        df["raca_cor_mae"] = _decod(df["RACACORMAE"], RACA_SIM)
    if "IDADEMAE" in df:
        _idade_mae(df, "IDADEMAE")
    if "ESCMAE" in df:
        df["escolaridade_mae"] = _decod(df["ESCMAE"], ESC_ANOS)
    if "ESTCIVMAE" in df:
        df["estado_civil_mae"] = _decod(df["ESTCIVMAE"], ESTCIV)
    if "PARTO" in df:
        df["tipo_parto"] = _decod(df["PARTO"], PARTO)
    if "GRAVIDEZ" in df:
        df["tipo_gravidez"] = _decod(df["GRAVIDEZ"], GRAVIDEZ)
    if "GESTACAO" in df:
        df["gestacao_semanas_cat"] = _decod(df["GESTACAO"], GESTACAO)
    if "CONSULTAS" in df:
        df["consultas_prenatal"] = _decod(df["CONSULTAS"], CONSULTAS)
    if "SEMAGESTAC" in df:
        df["semanas_gestacao"] = _num(df["SEMAGESTAC"]).astype("Float64").mask(lambda x: (x < 20) | (x > 45))
        df["prematuro"] = (df["semanas_gestacao"] < 37).astype("boolean")
    if "PESO" in df:
        df["peso_g"] = _num(df["PESO"]).astype("Float64").mask(lambda x: (x < 200) | (x > 7000))
        df["peso_nascer_cat"] = _peso_cat(df["peso_g"])
        df["baixo_peso"] = (df["peso_g"] < 2500).astype("boolean")
    for c, n in (("APGAR1", "apgar1"), ("APGAR5", "apgar5")):
        if c in df:
            df[n] = _num(df[c]).astype("Float64").mask(lambda x: x > 10)
    if "IDANOMAL" in df:
        df["anomalia_congenita"] = df["IDANOMAL"].astype("string").map({"1": True, "2": False}).astype("boolean")
    mun.adicionar(df, "CODMUNRES", "mun_residencia")
    mun.adicionar(df, "CODMUNNASC", "mun_nascimento")


def _sih(df, mun):
    for c, n in (("DT_INTER", "data_internacao"), ("DT_SAIDA", "data_saida"), ("NASC", "data_nascimento")):
        if c in df:
            df[n] = _data(df[c], "%Y%m%d")
    if "data_internacao" in df:
        df["ano_internacao"] = df["data_internacao"].dt.year.astype("Int64")
        df["mes_internacao"] = df["data_internacao"].dt.month.astype("Int64")
    if "ANO_CMPT" in df and "MES_CMPT" in df:
        df["competencia"] = (df["ANO_CMPT"].astype("string") + "-" + df["MES_CMPT"].astype("string").str.zfill(2))
        # "Ano/mês de processamento" = competência da AIH (é o que o TabNet chama de "Ano processamento")
        df["ano_processamento"] = _num(df["ANO_CMPT"]).astype("Int64")
        df["mes_processamento"] = _num(df["MES_CMPT"]).astype("Int64")
    if "IDADE" in df and "COD_IDADE" in df:
        df["idade_anos"] = idade_sih(df["IDADE"], df["COD_IDADE"])
        df["faixa_etaria"] = faixa_etaria(df["idade_anos"])
    if "SEXO" in df:
        df["sexo"] = _decod(df["SEXO"], SEXO_SIH)
    if "RACA_COR" in df:
        df["raca_cor"] = _decod(df["RACA_COR"], RACA_SIH)
    if "CAR_INT" in df:
        df["carater_internacao"] = _decod(df["CAR_INT"], CAR_INT)
    if "MORTE" in df:
        df["obito_hospitalar"] = (_num(df["MORTE"]) == 1).astype("boolean")
    if "DIAS_PERM" in df:
        df["permanencia_dias"] = _num(df["DIAS_PERM"]).astype("Float64")
    if "VAL_TOT" in df:
        df["valor_total_rs"] = _num(df["VAL_TOT"]).astype("Float64")
    if "DIAG_PRINC" in df:
        df["diag_principal"] = df["DIAG_PRINC"].astype("string").str.upper().str.strip()
        df["diag_principal_cat3"] = df["diag_principal"].str[:3]
        df["cid10_capitulo"], df["cid10_capitulo_nome"] = cid_capitulo(df["diag_principal"])
    mun.adicionar(df, "MUNIC_RES", "mun_residencia")
    mun.adicionar(df, "MUNIC_MOV", "mun_internacao")


def _sinan(df, mun):
    for c, n in (("DT_NOTIFIC", "data_notificacao"), ("DT_SIN_PRI", "data_primeiros_sintomas"),
                 ("DT_OBITO", "data_obito")):
        if c in df:
            df[n] = _data(df[c], "%Y%m%d")
    if "data_notificacao" in df:
        df["ano_notificacao"] = df["data_notificacao"].dt.year.astype("Int64")
    diagnostico(df)
    if "SEM_NOT" in df:
        df["semana_epi_notificacao"] = df["SEM_NOT"]
    if "NU_IDADE_N" in df:
        df["idade_anos"] = idade_codificada_sinan(df["NU_IDADE_N"])
        df["faixa_etaria"] = faixa_etaria(df["idade_anos"])
    if "CS_SEXO" in df:
        df["sexo"] = _decod(df["CS_SEXO"], SEXO_SINAN)
    if "CS_RACA" in df:
        df["raca_cor"] = _decod(df["CS_RACA"], RACA_SIM)
    if "EVOLUCAO" in df:
        df["evolucao"] = _decod(df["EVOLUCAO"], SINAN_EVOLUCAO)
    mun.adicionar(df, "ID_MN_RESI", "mun_residencia")
    mun.adicionar(df, "ID_MUNICIP", "mun_notificacao")


def diagnostico(df):
    """SINAN: data/ano/mês de diagnóstico a partir de DT_DIAG. O TabNet e os painéis do MS contam os casos pelo ANO
    DE DIAGNÓSTICO (não pelo de notificação, nem pelo arquivo SIxxBRaa, que é por ano de notificação). Conferido:
    sífilis em gestante RJ, 2009–2025, idêntico ao TabNet. Também usada pela interface em bases antigas."""
    if "DT_DIAG" not in df or "ano_diagnostico" in df:
        return df
    df["data_diagnostico"] = _data(df["DT_DIAG"], "%Y%m%d")
    df["ano_diagnostico"] = df["data_diagnostico"].dt.year.astype("Int64")
    df["mes_diagnostico"] = df["data_diagnostico"].dt.month.astype("Int64")
    return df


def _cnes(df, mun):
    mun.adicionar(df, "CODUFMUN", "mun_estabelecimento")


def _sia(df, mun):
    if "PA_CMP" in df:
        df["competencia"] = df["PA_CMP"].astype("string").str[:4] + "-" + df["PA_CMP"].astype("string").str[4:6]
        df["ano_processamento"] = _num(df["PA_CMP"].astype("string").str[:4]).astype("Int64")
        df["mes_processamento"] = _num(df["PA_CMP"].astype("string").str[4:6]).astype("Int64")
    if "PA_SEXO" in df:
        df["sexo"] = _decod(df["PA_SEXO"], SEXO_SINAN)
    if "PA_IDADE" in df:
        df["idade_anos"] = _num(df["PA_IDADE"]).astype("Float64").mask(lambda x: x > 130)
        df["faixa_etaria"] = faixa_etaria(df["idade_anos"])
    if "PA_RACACOR" in df:
        df["raca_cor"] = _decod(df["PA_RACACOR"], RACA_SIH)
    if "PA_VALAPR" in df:
        df["valor_aprovado_rs"] = _num(df["PA_VALAPR"]).astype("Float64")
    mun.adicionar(df, "PA_MUNPCN", "mun_residencia")
    mun.adicionar(df, "PA_UFMUN", "mun_atendimento")


# ---------------------------------------------------------------- universo de cada variável (SIM)
# Na DO, vários blocos só são preenchidos para parte dos óbitos; nos demais o campo fica vazio porque NÃO SE APLICA
# (não é falta de informação). Descrever essas variáveis na base toda daria "Sem informação" em ~99% (ex.: tipo de
# parto em óbitos de adultos) e esconderia a distribuição real.
VARS_PERINATAIS = {"tipo_parto", "faixa_etaria_mae", "escolaridade_mae", "gestacao_semanas_cat", "tipo_gravidez",
                   "peso_nascer_cat", "obito_relacao_parto", "idade_mae", "peso_g", "semanas_gestacao", "baixo_peso",
                   "filhos_vivos", "filhos_mortos"}
VARS_INFANTIS = {"componente_infantil", "faixa_etaria_infantil"}
VARS_MATERNAS = {"obito_na_gravidez", "obito_no_puerperio", "momento_obito_materno"}


def universo(df, var, sistema):
    """(máscara, descrição) dos registros a que `var` se aplica, ou None quando vale para todos os registros
    (ou quando a base não permite saber). Só o SIM tem variáveis restritas a parte dos óbitos."""
    if sistema not in ("SIM", "SIM-NAC"):
        return None
    idade = pd.to_numeric(df["idade_anos"], errors="coerce") if "idade_anos" in df else None
    fetal = (df["tipo_obito"] == "Fetal").fillna(False) if "tipo_obito" in df else None
    if var in VARS_PERINATAIS:
        if idade is None and fetal is None:
            return None
        m = pd.Series(False, index=df.index)
        if idade is not None:
            m |= (idade < 1).fillna(False)
        if fetal is not None:
            m |= fetal
        return m, "óbitos fetais e de menores de 1 ano"
    if var in VARS_INFANTIS and idade is not None:
        m = (idade < 1).fillna(False)
        return (m & ~fetal if fetal is not None else m), "óbitos de menores de 1 ano"
    if var in VARS_MATERNAS and idade is not None and "sexo" in df:
        m = (df["sexo"] == "Feminino").fillna(False) & idade.between(10, 49.999).fillna(False)
        return m, "óbitos de mulheres de 10 a 49 anos"
    if var == "circunstancia_obito" and "causa_basica" in df:
        m = df["causa_basica"].astype("string").str[:1].isin(list("VWXY")).fillna(False)
        return m, "óbitos por causas externas (V01–Y98)"
    return None


# ---------------------------------------------------------------- filtros
def expandir_cids(itens):
    """Aceita prefixos (I21, C50) e faixas de categorias (X60-X84, A00-B99) → lista de prefixos de 3 caracteres."""
    out = []
    for item in itens or []:
        for p in str(item).replace(";", ",").replace(" ", ",").split(","):
            p = p.strip().upper().replace(".", "")
            if not p:
                continue
            if "-" in p:
                a, b = (x.strip()[:3] for x in p.split("-", 1))
                if len(a) == 3 and len(b) == 3 and a[0].isalpha() and b[0].isalpha():
                    for letra in range(ord(a[0]), ord(b[0]) + 1):
                        ini = int(a[1:]) if chr(letra) == a[0] else 0
                        fim = int(b[1:]) if chr(letra) == b[0] else 99
                        out += [f"{chr(letra)}{n:02d}" for n in range(ini, fim + 1)]
                    continue
            out.append(p)
    return list(dict.fromkeys(out))



COLUNA_CID = {"SIM": "CAUSABAS", "SIM-NAC": "CAUSABAS", "SIH": "DIAG_PRINC", "SINAN": "ID_AGRAVO",
              "SIA": "PA_CIDPRI"}
COLUNA_PROC = {"SIH": "PROC_REA", "SIA": "PA_PROC_ID"}
COLUNA_MUN_RES = {"SIM": "CODMUNRES", "SIM-NAC": "CODMUNRES", "SINASC": "CODMUNRES", "SIH": "MUNIC_RES",
                  "SINAN": "ID_MN_RESI", "SIA": "PA_MUNPCN", "CNES": "CODUFMUN"}


def filtros_previos(sistema, cids=None, ufs_residencia=None, municipios=None, procedimentos=None):
    """Filtros por prefixo aplicados durante a leitura do DBF (antes de decodificar as demais colunas)."""
    from .catalogo import UFS
    f = []
    if cids and COLUNA_CID.get(sistema):
        f.append((COLUNA_CID[sistema], tuple(c.upper().replace(".", "") for c in cids)))
    if procedimentos and COLUNA_PROC.get(sistema):
        f.append((COLUNA_PROC[sistema], tuple(procedimentos)))
    col = COLUNA_MUN_RES.get(sistema)
    if col and municipios:
        f.append((col, tuple(str(x)[:6] for x in municipios)))
    elif col and ufs_residencia:
        f.append((col, tuple(UFS[u] for u in ufs_residencia)))
    return f


def filtrar(df, sistema, cids=None, ufs_residencia=None, municipios=None, procedimentos=None):
    if df.empty:
        return df
    m = pd.Series(True, index=df.index)
    if procedimentos:
        col = COLUNA_PROC.get(sistema)
        if col and col in df:
            v = df[col].astype("string").str.strip()
            m &= v.str.startswith(tuple(procedimentos)).fillna(False)
    if cids:
        col = COLUNA_CID.get(sistema)
        if col and col in df:
            v = df[col].astype("string").str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
            m &= v.str.startswith(tuple(c.upper().replace(".", "") for c in cids)).fillna(False)
    col = COLUNA_MUN_RES.get(sistema)
    if col and col in df:
        cod = df[col].astype("string").str.strip()
        if ufs_residencia:
            from .catalogo import UFS
            m &= cod.str[:2].isin([UFS[u] for u in ufs_residencia]).fillna(False)
        if municipios:
            m &= cod.str[:6].isin([str(x)[:6] for x in municipios]).fillna(False)
    return df[m].reset_index(drop=True)
