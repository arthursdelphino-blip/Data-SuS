"""Leitura de arquivos .dbc (DBF comprimido do DATASUS) para pandas."""

import datetime as dt
import os
import re
import struct
import tempfile

import numpy as np
import pandas as pd
import pyreaddbc
from dbfread import DBF


def ler_dbc(caminho_dbc, colunas=None, filtros=None):
    """Descomprime o .dbc e lê o DBF. Textos preservam zeros à esquerda; números e datas mantêm o tipo do DBF.

    `filtros`: lista de (coluna, prefixos) aplicada ANTES de decodificar as demais colunas (muito mais
    rápido quando o filtro é seletivo, ex.: um procedimento ou CID em todo o Brasil).
    """
    with tempfile.TemporaryDirectory() as tmp:
        dbf = os.path.join(tmp, "arquivo.dbf")
        pyreaddbc.dbc2dbf(caminho_dbc, dbf)
        try:
            return ler_dbf_rapido(dbf, colunas, filtros)
        except Exception:
            df = _ler_dbf_dbfread(dbf, colunas)
    return df


def _ler_dbf_dbfread(dbf, colunas):
    """Leitor de reserva (lento, porém tolerante) para DBFs fora do padrão."""
    tabela = DBF(dbf, encoding="latin-1", char_decode_errors="replace", load=False, ignore_missing_memofile=True)
    usar = [c for c in tabela.field_names if colunas is None or c.upper() in colunas]
    registros = {c: [] for c in usar}
    for reg in tabela:
        for c in usar:
            registros[c].append(reg[c])
    return limpar_tipos(pd.DataFrame(registros, columns=usar))


def _cabecalho(buf):
    n, hdr_len, rec_len = struct.unpack("<IHH", buf[4:12])
    campos, pos, off = [], 32, 1  # byte 0 de cada registro = marca de exclusão
    while pos < hdr_len - 1 and buf[pos] != 0x0D:
        nome = buf[pos:pos + 11].split(b"\x00")[0].decode("latin-1").strip().upper()
        tipo = chr(buf[pos + 11])
        tam, dec = buf[pos + 16], buf[pos + 17]
        campos.append((nome, tipo, off, tam, dec))
        off += tam
        pos += 32
    if off != rec_len:
        raise ValueError("cabeçalho DBF inconsistente")
    return n, hdr_len, rec_len, campos


def _bytes_coluna(mat, off, tam):
    return np.ascontiguousarray(mat[:, off:off + tam]).view(f"S{tam}").ravel()


def _texto(b):
    s = pd.Series(b, dtype=object).str.decode("latin-1", errors="replace").str.strip()
    return s.mask(s == "").astype("string")


def ler_dbf_rapido(caminho, colunas=None, filtros=None):
    with open(caminho, "rb") as fh:
        buf = fh.read()
    n, hdr_len, rec_len, campos = _cabecalho(buf)
    n = min(n, (len(buf) - hdr_len) // rec_len)
    mat = np.frombuffer(buf, dtype=np.uint8, count=n * rec_len, offset=hdr_len).reshape(n, rec_len)
    mat = mat[mat[:, 0] != ord("*")]  # remove registros excluídos
    n_total = len(mat)
    info = {c[0]: c for c in campos}

    for col, prefixos in (filtros or []):
        if col not in info or not prefixos:
            continue
        _, _, off, tam, _ = info[col]
        v = _texto(_bytes_coluna(mat, off, tam)).str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
        mask = v.str.startswith(tuple(prefixos)).fillna(False).to_numpy(dtype=bool)
        mat = mat[mask]

    dados = {}
    for nome, tipo, off, tam, dec in campos:
        if colunas is not None and nome not in colunas:
            continue
        b = _bytes_coluna(mat, off, tam)
        if tipo in "NF":
            s = _texto(b)
            num = pd.to_numeric(s, errors="coerce")
            dados[nome] = num.astype("Int64") if dec == 0 and num.dropna().mod(1).eq(0).all() else num.astype("Float64")
        elif tipo == "D":
            dados[nome] = pd.to_datetime(_texto(b), format="%Y%m%d", errors="coerce")
        elif tipo == "L":
            dados[nome] = _texto(b).str.upper().map({"T": True, "Y": True, "F": False, "N": False}).astype("boolean")
        else:
            dados[nome] = _texto(b)
    df = pd.DataFrame(dados, index=pd.RangeIndex(len(mat)))
    df.attrs["n_total"] = n_total
    return df


def limpar_tipos(df):
    """Padroniza: textos sem espaços extras e vazios como NA; datas do DBF como datetime."""
    for c in df.columns:
        s = df[c]
        if s.dtype == object or pd.api.types.is_string_dtype(s):
            amostra = s.dropna()
            amostra = amostra[amostra.map(lambda v: v != "")] if len(amostra) else amostra
            if len(amostra) and amostra.map(lambda v: isinstance(v, (dt.date, dt.datetime))).all():
                df[c] = pd.to_datetime(s, errors="coerce")
            elif len(amostra) and amostra.map(lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)).all():
                df[c] = pd.to_numeric(s, errors="coerce")
            else:
                s = s.astype(object).map(lambda v: (v.strip() or None) if isinstance(v, str)
                                         else (None if v is None or v is pd.NA else str(v)))
                df[c] = s.astype("string")
    return df


def harmonizar(partes):
    """Concatena DataFrames de arquivos diferentes, resolvendo colunas com tipos divergentes entre anos."""
    partes = [p for p in partes if p is not None and len(p.columns)]
    if not partes:
        return pd.DataFrame()
    tipos = {}
    for p in partes:
        for c in p.columns:
            tipos.setdefault(c, set()).add(_familia(p[c]))
    for c, fams in tipos.items():
        if len(fams - {"vazio"}) > 1:
            for p in partes:
                if c in p.columns:
                    p[c] = p[c].astype("string")
    df = pd.concat(partes, ignore_index=True, sort=False)
    return df


def _familia(s):
    if s.isna().all():
        return "vazio"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "data"
    if pd.api.types.is_numeric_dtype(s):
        return "numero"
    return "texto"
