"""Tabelas de conversão (.CNV) do TabNet, baixadas do FTP do DATASUS e guardadas em cache.

- Territórios por município (código IBGE de 6 dígitos): Região de Saúde (CIR), Macrorregião de Saúde,
  Microrregião IBGE e Região Metropolitana/RIDE  →  `territorios`.
- Listas de causas do TabNet (CID-10): grupos da CID-10, Lista de Mortalidade (geral e infância) e
  causas evitáveis (0–4 e 5–74 anos)  →  `LISTAS`, `classificar`.
"""

from __future__ import annotations

import ftplib
import io
import os
import re
import zipfile

import pandas as pd

FTP_HOST = "ftp.datasus.gov.br"
ARQ_SIH = ("/dissemin/publicos/SIHSUS/200801_/Auxiliar", "TAB_SIH.zip")
ARQ_SIM = ("/dissemin/publicos/SIM/CID10/TAB", "OBITOS_CID10_TAB.zip")
PASTA_TABNET = "tabnet"


def _zip(pasta_cache, origem):
    """ZipFile do arquivo auxiliar do TabNet (baixa uma vez para o cache)."""
    pasta, nome = origem
    destino = os.path.join(pasta_cache, PASTA_TABNET, nome)
    if not os.path.exists(destino):
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        ftp = ftplib.FTP(FTP_HOST, timeout=180)
        ftp.login()
        ftp.cwd(pasta)
        buf = io.BytesIO()
        ftp.retrbinary(f"RETR {nome}", buf.write)
        ftp.quit()
        with open(destino + ".tmp", "wb") as fh:
            fh.write(buf.getvalue())
        os.replace(destino + ".tmp", destino)
    return zipfile.ZipFile(destino)


def _ler(z, nome):
    alvo = {n.lower(): n for n in z.namelist()}[nome.lower()]
    return z.read(alvo).decode("latin-1")


def ler_cnv(texto):
    """Linhas de um .CNV → lista de dicts {pai, seq, rotulo, codigos}. Colunas fixas: 0–7 (pai/seq),
    9–59 (rótulo), 59+ (códigos separados por vírgula, com faixas 'A00-A09' ou 'A17 -A179')."""
    itens = []
    for ln in texto.splitlines()[1:]:
        if len(ln) < 10 or not ln[:8].strip():
            continue
        cab = ln[:8].split()
        rotulo = ln[9:59].strip()
        codigos = ln[59:].strip()
        if not rotulo:
            continue
        pai, seq = (cab[0], cab[1]) if len(cab) == 2 else ("", cab[0])
        itens.append({"pai": pai, "seq": seq, "rotulo": rotulo, "codigos": codigos})
    return itens


def _faixas(spec):
    """'A00-A09,A15 -A179,U04' → [(ini, fim)] (strings maiúsculas, sem espaços/pontos)."""
    out = []
    for parte in spec.replace(" ", "").replace(".", "").upper().split(","):
        if not parte or set(parte) <= {"-"}:
            continue
        if "-" in parte:
            ini, fim = parte.split("-", 1)
            out.append((ini, fim))
        else:
            out.append((parte, parte))
    return out


def _casa(cods: pd.Series, faixas) -> pd.Series:
    m = pd.Series(False, index=cods.index)
    for ini, fim in faixas:
        m |= (cods.str[:len(ini)] >= ini) & (cods.str[:len(fim)] <= fim)
    return m.fillna(False)


# ------------------------------------------------------------------ territórios
TERRITORIOS = {  # coluna → (arquivo .cnv no TAB_SIH, rótulo)
    "regiao_saude": ("CNV/BR_regsaud.cnv", "Região de Saúde (CIR)"),
    "macrorregiao_saude": ("CNV/BR_macsaud.cnv", "Macrorregião de Saúde"),
    "microrregiao_ibge": ("CNV/BR_micibge.cnv", "Microrregião IBGE"),
    "regiao_metropolitana": ("CNV/br_regmetr.cnv", "Região Metropolitana/RIDE"),
}
SIGLA_POR_COD = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA",
                 "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA",
                 "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS",
                 "51": "MT", "52": "GO", "53": "DF"}


def territorios(pasta_cache) -> pd.DataFrame:
    """Município (cod6) → região de saúde, macrorregião, microrregião e região metropolitana (TabNet)."""
    arq = os.path.join(pasta_cache, PASTA_TABNET, "territorios.parquet")
    if os.path.exists(arq):
        return pd.read_parquet(arq)
    z = _zip(pasta_cache, ARQ_SIH)
    tab = None
    for col, (nome, _) in TERRITORIOS.items():
        linhas = []
        for it in ler_cnv(_ler(z, nome)):
            m = re.match(r"(\d+)\s+(.*)", it["rotulo"])
            cod_reg, nome_reg = (m.group(1), m.group(2).strip()) if m else ("", it["rotulo"])
            uf = SIGLA_POR_COD.get(cod_reg[:2], "")
            if nome_reg.isupper():
                nome_reg = re.sub(r"\b(Da|De|Do|Das|Dos|E)\b", lambda m: m.group(1).lower(), nome_reg.title())
            if uf and not nome_reg.endswith(f" - {uf}"):
                nome_reg = f"{nome_reg} ({uf})"
            for ini, fim in _faixas(it["codigos"]):
                if ini.isdigit() and fim.isdigit() and len(ini) == 6:
                    for c in range(int(ini), int(fim) + 1):
                        linhas.append((f"{c:06d}", nome_reg))
        t = pd.DataFrame(linhas, columns=["cod6", col]).drop_duplicates("cod6")
        tab = t if tab is None else tab.merge(t, on="cod6", how="outer")
    tab.to_parquet(arq, index=False)
    return tab


def adicionar_territorios(df, pasta_cache, prefixo="mun_residencia"):
    """Acrescenta colunas `regiao_saude` etc. a partir de `<prefixo>_cod_ibge6` (se ainda não houver)."""
    col = f"{prefixo}_cod_ibge6"
    if col not in df or all(c in df for c in TERRITORIOS):
        return df
    t = territorios(pasta_cache).set_index("cod6")
    cods = df[col].astype("string").str[:6]
    for c in TERRITORIOS:
        if c not in df:
            df[c] = cods.map(t[c]).astype("string")
    return df


# ------------------------------------------------------------------ listas de causas
LISTAS = {  # chave → (origem, arquivo, rótulo, sistemas)
    "grupos_cid10": (ARQ_SIH, "CNV/CID10GRUPO.CNV", "Grupos da CID-10", {"SIM", "SIM-NAC", "SIH"}),
    "lista_mort": (ARQ_SIM, "OBITOS_CID10_TAB/tabdo/CID10-Lista-02.cnv", "Lista de Mortalidade CID-10 (geral)",
                   {"SIM", "SIM-NAC"}),
    "lista_mort_inf": (ARQ_SIM, "OBITOS_CID10_TAB/tabdo/CID10-Lista-04.cnv",
                       "Lista de Mortalidade CID-10 (infância)", {"SIM", "SIM-NAC"}),
    "evit_0a4": (ARQ_SIM, "OBITOS_CID10_TAB/tabdo/CID10-Evit0a4.cnv", "Causas evitáveis – 0 a 4 anos",
                 {"SIM", "SIM-NAC"}),
    "evit_5a74": (ARQ_SIM, "OBITOS_CID10_TAB/tabdo/CID10-Evit5a74.cnv", "Causas evitáveis – 5 a 74 anos",
                  {"SIM"}),
}


def _limpar_rotulo(r):
    return re.sub(r"^[.\s]+", "", r).strip()


def lista(pasta_cache, chave):
    """Itens da lista com hierarquia: [{'seq', 'rotulo', 'faixas', 'filhos': [seq], 'nivel'}]."""
    origem, nome, _, _ = LISTAS[chave]
    itens = ler_cnv(_ler(_zip(pasta_cache, origem), nome))
    por_seq = {}
    for it in itens:
        por_seq[it["seq"]] = {"seq": it["seq"], "pai": it["pai"], "rotulo": _limpar_rotulo(it["rotulo"]),
                              "faixas": _faixas(it["codigos"]), "filhos": []}
    for it in por_seq.values():
        if it["pai"] in por_seq:
            por_seq[it["pai"]]["filhos"].append(it["seq"])
    return list(por_seq.values())


def classificar(cods: pd.Series, itens) -> pd.Series:
    """Rótulo da lista para cada código CID (primeiro item-folha que casa; itens 'A00-Z999' ficam por último,
    como 'demais causas')."""
    cods = cods.astype("string").str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
    out = pd.Series(pd.NA, index=cods.index, dtype="string")
    folhas = [i for i in itens if not i["filhos"] and i["faixas"]]
    resto = [i for i in folhas if any(a <= "A00" and b >= "Z99" for a, b in i["faixas"])]
    for it in [i for i in folhas if i not in resto] + resto:
        livre = out.isna() & cods.notna()
        if not livre.any():
            break
        m = livre & _casa(cods, it["faixas"])
        out[m] = it["rotulo"]
    return out


def grupos_de_titulos(itens):
    """{rótulo do título (ex.: '1.1. Reduzível pelas ações de imunização'): [rótulos das folhas abaixo]}."""
    por_seq = {i["seq"]: i for i in itens}

    def folhas(seq):
        it = por_seq[seq]
        if not it["filhos"]:
            return [it["rotulo"]]
        return [r for f in it["filhos"] for r in folhas(f)]
    return {i["rotulo"]: folhas(i["seq"]) for i in itens if i["filhos"]}
