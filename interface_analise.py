"""Página de análise: filtros por características → gráficos, taxas e testes estatísticos."""

import io
import json
import os
import re
from datetime import date

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from datasus_ciencia import estatistica as E
from datasus_ciencia import referencias as R
from datasus_ciencia import resumo as RS
from datasus_ciencia import tabnet as T
from datasus_ciencia.indicadores import idade_dias
from datasus_ciencia.catalogo import UF_POR_CODIGO, UFS
from datasus_ciencia.pipeline import PASTA_CACHE, PASTA_PROCESSADOS
from datasus_ciencia.saida import _rotulo
from datasus_ciencia.tratamento import COLUNA_CID, diagnostico, expandir_cids, universo, variaveis_extras
from interface_imagem import botao_zip, fonte_de_meta, iniciar_figuras, mostrar_grafico, mostrar_tabela

# ------------------------------------------------------------------ paleta (validada – skill dataviz)
# Dois temas (.streamlit/config.toml); os gráficos da tela seguem o ativo (`paleta()`).
# Escuro (fundo marinho #0B1A2E): passos "dark" da paleta categórica, validados contra o fundo (todos >= 3:1,
# CVD adjacente >= 8,4); sequencial escuro = pouco, claro = muito.
# Claro (fundo #F5F6F1): passos "light", os mesmos da imagem de publicação; sequencial claro = pouco.
CINZA = "#898781"
PALETAS = {
    "dark": {"fundo": "#0B1A2E",
             "series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#0ca30c", "#9085e9", "#e66767"],
             "seq": ["#184f95", "#1c5cab", "#2a78d6", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"],
             "eixo": {"gridColor": "#1F3A5C", "domainColor": "#2C4A6E", "tickColor": "#2C4A6E",
                      "labelColor": "#8FA6BF", "titleColor": "#8FA6BF"}},
    "light": {"fundo": "#F5F6F1",
              "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
              "seq": ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#2a78d6", "#1c5cab", "#184f95"],
              "eixo": {"gridColor": "#e1e0d9", "domainColor": "#898781", "tickColor": "#898781",
                       "labelColor": "#52514e", "titleColor": "#52514e"}},
}


def paleta():
    """Cores do tema ativo no navegador (sem tema conhecido, ex.: AppTest, usa o escuro)."""
    try:
        tipo = st.context.theme.type
    except Exception:
        tipo = None
    p = PALETAS["light" if tipo == "light" else "dark"]
    s = p["series"]
    return {**p, "azul": s[0], "contraf": s[1], "fixa": {"Masculino": s[0], "Feminino": s[1]}}

# a primeira coluna disponível é o padrão. No SINAN, o TabNet conta pelo ano de diagnóstico (sífilis em gestante RJ
# 2017: 7.949 por diagnóstico × 7.901 por notificação) – ele vem antes, se estiver bem preenchido (ver anos_disp)
ANO_COLS = ["ano_processamento", "ano_internacao", "ano_obito", "ano_nascimento", "ano_diagnostico",
            "ano_notificacao"]
MES_DO_ANO = {"ano_processamento": "mes_processamento", "ano_internacao": "mes_internacao", "ano_obito": "mes_obito",
              "ano_nascimento": "mes_nascimento", "ano_diagnostico": "mes_diagnostico",
              "ano_notificacao": "_mes_notificacao"}
ROT_ANO = {"ano_processamento": "Ano de processamento (competência – igual ao TabNet)",
           "ano_internacao": "Ano de internação", "ano_obito": "Ano do óbito", "ano_nascimento": "Ano do nascimento",
           "ano_diagnostico": "Ano de diagnóstico (igual ao TabNet)", "ano_notificacao": "Ano de notificação"}
DESFECHOS = {"obito_hospitalar": "Letalidade hospitalar (% das internações com óbito)",
             "obito_infantil": "% de óbitos em menores de 1 ano", "prematuro": "% de prematuros (<37 semanas)",
             "baixo_peso": "% de baixo peso ao nascer (<2.500 g)", "anomalia_congenita": "% com anomalia congênita"}
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
GEOGRAFICAS = {"mun_residencia_uf", "mun_residencia_regiao"}
# grupos de comparação que têm população correspondente no TabNet (coluna em rotular_populacao)
MAP_POP = {"mun_residencia_uf": "uf", "mun_residencia_regiao": "regiao", "sexo": "sexo", "faixa_etaria": "faixa_etaria"}
# comparação territorial (regiões de saúde, municípios): até 8 níveis escolhidos; a população do TabNet é municipal,
# então pop_base ganha a mesma coluna (cod6 → nível) e as taxas por grupo funcionam
GRUPOS_TERRIT = {*T.TERRITORIOS, "municipio_residencia"}
MAP_POP.update({c: c for c in GRUPOS_TERRIT})
# variáveis com muitos níveis: o usuário escolhe até 8 (as territoriais também têm taxa; as demais, só contagem)
GRUPOS_ESCOLHA = GRUPOS_TERRIT | {"municipio_prenatal", "mun_notificacao_nome"}
ROT_GRUPO = {"municipio_residencia": "Município de residência", **{c: r for c, (_, r) in T.TERRITORIOS.items()}}
GRUPOS_TAXA = set(MAP_POP)
NOTA_POP = "População: MS/SVSA – estimativas por município, idade e sexo (TabNet/DATASUS)."
EVENTO = {"SIM": ("óbitos", 100_000, "100 mil hab."), "SIM-NAC": ("óbitos", 100_000, "100 mil hab."),
          "SIH": ("internações", 10_000, "10 mil hab."), "SINAN": ("casos", 100_000, "100 mil hab."),
          "SINASC": ("nascidos vivos", 1_000, "1.000 hab."), "SIA": ("procedimentos", 1_000, "1.000 hab."),
          "CNES": ("estabelecimentos", None, None)}
FAIXAS_TABNET = {
    "Faixa etária OPS": [(0, 1, "<1"), (1, 5, "1-4"), (5, 10, "5-9"), (10, 15, "10-14"), (15, 20, "15-19"),
                         (20, 30, "20-29"), (30, 40, "30-39"), (40, 50, "40-49"), (50, 60, "50-59"),
                         (60, 70, "60-69"), (70, 80, "70-79"), (80, 999, "80+")],
    "Faixa etária ampla": [(0, 1, "<1"), (1, 5, "1-4"), (5, 15, "5-14"), (15, 60, "15-59"), (60, 999, "60+")],
    # em dias completos (ver indicadores.idade_dias: a idade em anos tem 3 casas e 7 dias viraria 6,9)
    "Menores de 1 ano": [(0, 7, "0 a 6 dias"), (7, 28, "7 a 27 dias"), (28, 365, "28 a 364 dias")],
}


def _faixa_por(idade, faixas):
    out = pd.Series(pd.NA, index=idade.index, dtype="string")
    for ini, fim, r in faixas:
        out[(idade >= ini) & (idade < fim)] = r
    return out


COL_CAUSA = {"SIM": "causa_basica_cat3", "SIM-NAC": "causa_basica_cat3", "SIH": "diag_principal_cat3"}


def fmt(n, casas=0):
    if n is None or (isinstance(n, float) and np.isnan(n)):
        return "–"
    return f"{n:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def rot(c):
    if c in ROT_GRUPO:
        return ROT_GRUPO[c]
    r = _rotulo(c)
    return r if r and not r.startswith("Variável original") else c


# ------------------------------------------------------------------ cache
def _colunas_analise(nomes):
    """Colunas que a página usa: as derivadas (minúsculas) e só as originais necessárias (CID e as que
    `variaveis_extras` decodifica em bases antigas). Ficam de fora os municípios de ocorrência/nascimento/internação
    (a análise é por residência) e o nome do arquivo de origem – em bases grandes isso corta centenas de MB."""
    from datasus_ciencia.tratamento import EXTRAS_DECOD
    nomes = set(nomes)
    originais = set(COLUNA_CID.values()) | {"ID_AGRAVO", "PRE_MUNIRE"}  # PRE_MUNIRE → municipio_prenatal
    if "ano_diagnostico" not in nomes:
        originais.add("DT_DIAG")  # bases antigas do SINAN: o ano de diagnóstico é calculado ao carregar
    originais |= {o for o, nova, _, _ in EXTRAS_DECOD if nova not in nomes}
    if "classificacao_final" not in nomes:
        originais.add("CLASSI_FIN")
    originais |= {o for o, n in (("APGAR1", "apgar1_cat"), ("APGAR5", "apgar5_cat")) if n not in nomes}

    def usa(c):
        if c.isupper():
            return c in originais
        if c == "_arquivo_origem":
            return False
        if c.startswith("mun_") and not c.startswith("mun_residencia_"):
            return c == "mun_notificacao_nome"
        return True
    return [c for c in nomes if usa(c)]


# cache_resource: a mesma tabela é reaproveitada entre cliques (cache_data desserializaria uma cópia inteira a cada
# interação, dobrando a memória). A página não altera df0 – só lê e filtra.
@st.cache_resource(show_spinner="Carregando base...", max_entries=2)
def _carregar(caminho, _mtime):
    import pyarrow.parquet as pq
    nomes = pq.read_schema(caminho).names
    usar = set(_colunas_analise(nomes))
    df = pd.read_parquet(caminho, columns=[c for c in nomes if c in usar])
    if "data_notificacao" in df and "_mes_notificacao" not in df:
        df["_mes_notificacao"] = pd.to_datetime(df["data_notificacao"], errors="coerce").dt.month.astype("Int64")
    diagnostico(df)  # SINAN processado antes de existir ano_diagnostico
    variaveis_extras(df)  # bases processadas antes de existir a variável
    if "PRE_MUNIRE" in df and "municipio_prenatal" not in df:  # sífilis em gestante: município do pré-natal
        try:
            from datasus_ciencia.tratamento import Municipios
            mp = Municipios(PASTA_CACHE, log=lambda *_: None).mapa()
            cods = df.pop("PRE_MUNIRE").astype("string").str.strip().str[:6]
            rotulos = {c: f"{v['nome']} – {v['uf']}" for c in cods.dropna().unique() if (v := mp.get(c))}
            df["municipio_prenatal"] = cods.map(rotulos).astype("category")
        except Exception:
            pass
    df.drop(columns=["PRE_MUNIRE"], errors="ignore", inplace=True)
    try:
        T.adicionar_territorios(df, PASTA_CACHE)
    except Exception:  # sem FTP: segue sem os filtros territoriais
        pass
    return df


def _csv_selecao(caminho, linhas, lote=100_000):
    """CSV (bytes) das linhas `linhas` (posições no parquet) com todas as variáveis da base, lido em lotes."""
    import pyarrow.parquet as pq
    linhas = np.sort(np.asarray(linhas))
    buf, ini, cab = io.StringIO(), 0, True
    for b in pq.ParquetFile(caminho).iter_batches(batch_size=lote):
        fim = ini + b.num_rows
        sel = linhas[(linhas >= ini) & (linhas < fim)] - ini
        if len(sel):
            parte = b.take(sel).to_pandas()
            parte.to_csv(buf, index=False, header=cab, date_format="%Y-%m-%d")
            cab = False
        ini = fim
    return ("﻿" + buf.getvalue()).encode("utf-8")


@st.cache_data(show_spinner=False, ttl=86400)
def _territorios():
    try:
        return T.territorios(PASTA_CACHE)
    except Exception:
        return None


@st.cache_data(show_spinner="Classificando causas pela lista do TabNet...")
def _classificar_lista(chave_base, col, chave_lista, _serie):
    itens = T.lista(PASTA_CACHE, chave_lista)
    return T.classificar(_serie, itens), T.grupos_de_titulos(itens)


@st.cache_data(show_spinner=False, ttl=86400)
def _grupos_cid10_oficiais():
    try:
        itens = T.lista(PASTA_CACHE, "grupos_cid10")
    except Exception:
        return []
    return [(i["rotulo"], ",".join(a if a == b else f"{a}-{b}" for a, b in i["faixas"]))
            for i in itens if i["faixas"]]


@st.cache_data(show_spinner="Obtendo população do TabNet (DATASUS)...", ttl=86400)
def _pop_svs(ufs, anos):
    """População do TabNet por município, ano, sexo e idade, com UF, região e faixas etárias."""
    p = R.populacao_svs(PASTA_CACHE, list(ufs), list(anos), log=lambda *_: None)
    return R.rotular_populacao(p) if len(p) else p


@st.cache_data(show_spinner=False, ttl=86400)
def _cid():
    return R.cid10_descricoes(PASTA_CACHE)


@st.cache_data(show_spinner="Montando lista de CID-10 da base...")
def _opcoes_cid_base(chave_base, col, _serie):
    """{rótulo: prefixos} apenas com códigos presentes na base, com contagem de registros."""
    v = _serie.astype("string").str.upper().str.replace(r"[^A-Z0-9]", "", regex=True).dropna()
    vc_full = v.value_counts()
    idx = vc_full.index.to_series()
    desc = _cid()
    ops = {}

    def n_pref(prefs):
        return int(vc_full[idx.str.startswith(tuple(prefs)).values].sum())

    for nome, cods in R.GRUPOS_CID:
        n = n_pref(expandir_cids(cods.split(",")))
        if n:
            ops[f"Grupo: {nome} ({cods.replace(',', ', ')}) · n={fmt(n)}"] = cods
    for nome, cods in _grupos_cid10_oficiais():  # grupos da CID-10 (como no TabNet)
        n = n_pref(expandir_cids(cods.split(",")))
        if n:
            ops[f"Grupo CID-10: {nome} ({cods.replace(',', ', ')}) · n={fmt(n)}"] = cods
    from datasus_ciencia.tratamento import CAPITULOS_CID10
    for ini, fim, num, nome in CAPITULOS_CID10:
        n = n_pref(expandir_cids([f"{ini}-{fim}"]))
        if n:
            ops[f"Capítulo {num}: {nome} ({ini}-{fim}) · n={fmt(n)}"] = f"{ini}-{fim}"
    cat3 = v.str[:3].value_counts()
    for cod, n in cat3.items():
        ops[f"{cod} – {desc.get(cod, 'sem descrição')} · n={fmt(n)}"] = cod
    return ops


def seletor_cid(container, rotulo, df0, col, chave_base, key):
    """Menu suspenso de CID-10; devolve (prefixos, descrição curta) ou (None, None)."""
    ops = _opcoes_cid_base(chave_base, col, df0[col])
    if df0[col].astype("string").str.upper().str[:3].nunique() < 2:  # um só código: nada a escolher
        return None, None
    sel = container.multiselect(rotulo, list(ops), key=key, placeholder="Todas – digite código ou nome")
    if not sel:
        return None, None
    prefs = tuple(expandir_cids([p for s in sel for p in ops[s].split(",")]))
    desc = "; ".join(s.split(" · ")[0] for s in sel)
    return prefs, desc


@st.cache_data(show_spinner="Obtendo malha municipal do IBGE...", ttl=86400)
def _malha(uf):
    return R.malha_municipios(PASTA_CACHE, uf)


@st.cache_data(show_spinner="Obtendo malha das UFs...", ttl=86400)
def _malha_ufs():
    return R.malha_ufs(PASTA_CACHE)


# ------------------------------------------------------------------ cores
def escala_cores(niveis):
    """Cor segue a entidade: Masculino/Feminino fixos, Ignorado/Outros em cinza, demais na ordem da paleta."""
    p = paleta()
    fixa, series = p["fixa"], p["series"]
    usa_fixas = bool(set(niveis) & set(fixa))
    livres = [c for c in series if c not in fixa.values()] if usa_fixas else series
    faixa, i = [], 0
    for n in niveis:
        if n in fixa:
            faixa.append(fixa[n])
        elif n in E.AUSENTES or n == "Outros":
            faixa.append(CINZA)
        else:
            faixa.append(livres[i % len(livres)])
            i += 1
    return alt.Scale(domain=list(niveis), range=faixa)


def limitar_niveis(s, maximo=8):
    """Mantém as `maximo` categorias mais frequentes; o restante vira 'Outros' (regra: sem 9ª cor)."""
    s = s.astype("string").fillna("Sem informação")
    vc = s.value_counts()
    validos = [v for v in vc.index if v not in E.AUSENTES]
    if len(validos) <= maximo:
        return s
    manter = set(validos[:maximo - 1]) | E.AUSENTES
    return s.where(s.isin(manter), "Outros")


def preparar_comparacao(d, grupo, excl, maximo=8):
    """Cópia de `d` com o grupo em no máx. `maximo` níveis, sem os ignorados (se `excl`) e, na comparação territorial,
    só com os níveis escolhidos (os demais registros estão com o grupo vazio)."""
    if grupo in GRUPOS_ESCOLHA:
        d = d[d[grupo].notna()]
    d = d.copy()
    d[grupo] = limitar_niveis(d[grupo], maximo)
    if excl:
        d = d[~d[grupo].isin(E.AUSENTES)]
    return d


def _eixo():
    return dict(paleta()["eixo"])


def _cfg(ch):
    e = _eixo()
    return ch.configure_axis(**e).configure_view(strokeWidth=0).configure_legend(
        labelColor=e["labelColor"], titleColor=e["titleColor"], orient="top")


# ------------------------------------------------------------------ gráficos
def g_linha(d, x, y, cor=None, titulo_y="n", banda=None):
    p = paleta()
    enc = {"x": alt.X(f"{x}:O", title=None, axis=alt.Axis(labelAngle=0)),
           "y": alt.Y(f"{y}:Q", title=titulo_y, scale=alt.Scale(zero=True)),
           "tooltip": [alt.Tooltip(c) for c in d.columns if not c.startswith("_")]}
    if cor:
        niveis = E.ordenar_categorias(list(d[cor].unique()), d.groupby(cor)[y].sum())
        enc["color"] = alt.Color(f"{cor}:N", scale=escala_cores(niveis), sort=niveis, title=rot(cor))
    else:
        enc["color"] = alt.value(p["azul"])
    base = alt.Chart(d)
    camadas = []
    if banda:
        b_enc = {"x": enc["x"], "y": alt.Y(f"{banda[0]}:Q"), "y2": f"{banda[1]}:Q"}
        if cor:
            b_enc["color"] = enc["color"]
        else:
            b_enc["color"] = alt.value(p["azul"])
        camadas.append(base.mark_area(opacity=0.15).encode(**b_enc))
    camadas.append(base.mark_line(strokeWidth=2).encode(**enc))
    camadas.append(base.mark_point(size=64, filled=True, stroke=p["fundo"], strokeWidth=2).encode(**enc))
    return _cfg(alt.layer(*camadas).properties(height=320))


def g_barras_h(d, cat, val="n", ordem=None, cor=None, titulo_x="n", altura_linha=24):
    fixa = paleta()["fixa"]
    cor = cor or paleta()["azul"]
    d = d.copy()
    d[cat] = d[cat].astype(str)
    sort = ordem if ordem else "-x"
    enc = {"y": alt.Y(f"{cat}:N", sort=sort, title=None,
                      axis=alt.Axis(labelLimit=320, labelOverlap=False)),  # nunca esconder rótulos
           "x": alt.X(f"{val}:Q", title=titulo_x),
           "tooltip": [alt.Tooltip(c) for c in d.columns if not c.startswith("_")]}
    if set(d[cat]) & set(fixa):  # sexo: cores fixas (Masculino/Feminino), demais categorias em cinza
        dom = list(d[cat])
        enc["color"] = alt.Color(f"{cat}:N", legend=None, scale=alt.Scale(
            domain=dom, range=[fixa.get(c, CINZA) for c in dom]))
        ch = alt.Chart(d).mark_bar(cornerRadiusEnd=4, height={"band": 0.8}).encode(**enc)
    else:
        ch = alt.Chart(d).mark_bar(cornerRadiusEnd=4, color=cor, height={"band": 0.8}).encode(**enc)
    # altura por categoria (step): cada barra tem espaço para o rótulo, mesmo com poucas categorias
    return _cfg(ch.properties(height=alt.Step(max(altura_linha, 28))))


def g_barras_v(d, cat, val="n", ordem=None):
    ch = alt.Chart(d).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, color=paleta()["azul"]).encode(
        x=alt.X(f"{cat}:N", sort=ordem, title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y(f"{val}:Q", title="n"), tooltip=[alt.Tooltip(c) for c in d.columns])
    return _cfg(ch.properties(height=260))


def g_piramide(d):
    ordem = [o for o in E.ORDENS[0] if o in set(d["faixa_etaria"])][::-1]
    d = d.copy()
    d["valor"] = np.where(d["sexo"] == "Masculino", -d["n"], d["n"])
    d["pct"] = (100 * d["n"] / d["n"].sum()).round(1)
    m = float(d["n"].max()) * 1.05
    ch = alt.Chart(d).mark_bar(height={"band": 0.85}).encode(
        y=alt.Y("faixa_etaria:N", sort=ordem, title="Faixa etária", axis=alt.Axis(labelOverlap=False)),
        x=alt.X("valor:Q", title="n", scale=alt.Scale(domain=[-m, m]),
                axis=alt.Axis(labelExpr="format(abs(datum.value), ',.0f')")),
        color=alt.Color("sexo:N", scale=escala_cores(["Masculino", "Feminino"]), title="Sexo"),
        tooltip=["sexo", "faixa_etaria", "n", alt.Tooltip("pct", title="% do total")])
    return _cfg(ch.properties(height=max(300, 30 * len(ordem))))


def serie_proporcao(d, y, chaves):
    """Agrega por `chaves`: n (com desfecho definido), eventos, % e IC95% de Wilson."""
    d = d.assign(_y=y.loc[d.index].astype("Float64"))
    d = d[d["_y"].notna()]
    s = d.groupby(chaves, observed=True)["_y"].agg(n="count", eventos="sum").reset_index()
    s["eventos"] = s["eventos"].astype(float)
    s["pct"] = (100 * s["eventos"] / s["n"]).round(3)
    i, u = E.ic_wilson(s["eventos"], s["n"])
    s["ic95_inf"], s["ic95_sup"] = np.round(i, 3), np.round(u, 3)
    return s


def g_its(d, x, titulo_y, x_tipo="T"):
    """Observado (pontos), ajustado (linha) e contrafactual (tracejado) da série interrompida."""
    p = paleta()
    base = alt.Chart(d)
    xenc = alt.X(f"{x}:{x_tipo}", title=None)
    obs = base.mark_point(size=40, filled=True, color=CINZA, opacity=0.8).encode(
        x=xenc, y=alt.Y("observado:Q", title=titulo_y, scale=alt.Scale(zero=False)),
        tooltip=[x, alt.Tooltip("observado:Q", format=".2f"), alt.Tooltip("ajustado:Q", format=".2f")])
    aj = base.mark_line(strokeWidth=2, color=p["azul"]).encode(x=xenc, y="ajustado:Q", detail="segmento:N")
    cf = base.transform_filter("datum.segmento == 'pós'").mark_line(
        strokeWidth=2, strokeDash=[6, 4], color=p["contraf"]).encode(x=xenc, y="contrafactual:Q")
    corte = d[d["segmento"] == "pós"][x].min()
    regra = alt.Chart(pd.DataFrame({x: [corte]})).mark_rule(color=CINZA, strokeDash=[3, 3]).encode(x=f"{x}:{x_tipo}")
    return _cfg(alt.layer(obs, aj, cf, regra).properties(height=340))


def g_mapa(geo, valores, campo, titulo):
    feats = geo["features"]
    p = paleta()
    ch = alt.Chart(alt.Data(values=feats)).mark_geoshape(stroke=p["fundo"], strokeWidth=0.5).transform_lookup(
        lookup="properties.codarea",
        from_=alt.LookupData(alt.Data(values=valores), "codarea", list(dict.fromkeys([campo, "nome", "n"])))
    ).encode(
        color=alt.Color(f"{campo}:Q", title=titulo, scale=alt.Scale(range=p["seq"], zero=True)),
        tooltip=[alt.Tooltip("nome:N", title="Local"), alt.Tooltip("n:Q", title="n"),
                 alt.Tooltip(f"{campo}:Q", title=titulo, format=".1f")],
    ).project("mercator")
    return ch.configure_view(strokeWidth=0).configure_legend(orient="right").properties(height=480)


def g_forest(tab):
    d = tab[tab["_or"].notna() & (tab["_inf"] > 0)].copy()
    d["rotulo"] = [(f"{v}: " if v else "") + str(c) for v, c in zip(d["_var"].fillna(""), d["Categoria"])]
    d = d[~d["Categoria"].astype(str).str.endswith("(ref.)")]
    if d.empty:
        return None
    ordem = list(d["rotulo"])
    p = paleta()
    base = alt.Chart(d).encode(y=alt.Y("rotulo:N", sort=ordem, title=None, axis=alt.Axis(labelLimit=300)))
    regra = base.mark_rule(strokeWidth=2, color=p["azul"]).encode(
        x=alt.X("_inf:Q", scale=alt.Scale(type="log"), title="OR ajustado (IC95%, escala log)"), x2="_sup:Q")
    ponto = base.mark_point(filled=True, size=80, color=p["azul"], stroke=p["fundo"], strokeWidth=2).encode(
        x="_or:Q", tooltip=["rotulo", alt.Tooltip("OR ajustado (IC95%)"), alt.Tooltip("p ajustado")])
    ref = alt.Chart(pd.DataFrame({"x": [1]})).mark_rule(color=CINZA, strokeDash=[4, 4]).encode(x="x:Q")
    return _cfg((ref + regra + ponto).properties(height=max(150, 26 * len(d))))


# ------------------------------------------------------------------ aba Períodos
def aba_periodos(df, ano_col, mes_col, grupo, excl, y_ind, nome_ind, pop, mult, por_txt, evento, k, relatorio,
                 pop_por=None, pad_por=None, no_escopo=None):
    if not ano_col:
        st.info("Esta base não tem variável de ano.")
        return
    anos = sorted(int(a) for a in df[ano_col].dropna().unique())
    if len(anos) < 2:
        st.info("A comparação de períodos exige pelo menos 2 anos na seleção.")
        return
    corte = 2020 if anos[0] < 2020 <= anos[-1] else anos[len(anos) // 2]
    st.markdown("Compare dois períodos (ex.: **pré × pós-pandemia**) e avalie a mudança por **série temporal "
                "interrompida**." + (f" Indicador: **{nome_ind}**." if nome_ind else f" Indicador: **número de {evento}**."))
    c1, c2, c3 = st.columns(3)
    pa = c1.select_slider("Período A (antes)", options=anos, value=(anos[0], max(anos[0], corte - 1)), key=k + "pA")
    pb = c2.select_slider("Período B (depois)", options=anos, value=(corte, anos[-1]), key=k + "pB")
    excluir = c3.multiselect("Excluir anos (opcional)", anos, key=k + "pX",
                             help="Ex.: excluir 2020–2021 para separar o período agudo da pandemia.")
    if pa[1] >= pb[0]:
        st.warning("Os períodos se sobrepõem: o fim do período A deve ser anterior ao início do período B.")
        return
    anos_a = [a for a in range(pa[0], pa[1] + 1) if a not in excluir]
    anos_b = [a for a in range(pb[0], pb[1] + 1) if a not in excluir]
    if not anos_a or not anos_b:
        st.warning("Algum período ficou sem anos.")
        return
    rot_a, rot_b = f"A ({anos_a[0]}–{anos_a[-1]})", f"B ({anos_b[0]}–{anos_b[-1]})"

    d = preparar_comparacao(df, grupo, excl) if grupo else df
    # comparação territorial: o Total continua com todos os registros (não só os níveis escolhidos)
    total = df if grupo in GRUPOS_ESCOLHA else d
    blocos = [("Total", total)] + ([(g, sub) for g, sub in d.groupby(grupo, observed=True)] if grupo else [])
    usar_pop = (y_ind is None and pop_por is not None and pop is not None and len(pop) > 0
                and (grupo is None or grupo in GRUPOS_TAXA))
    usar_pad = usar_pop and pad_por is not None

    # ---------------- comparação A × B
    linhas, graf = [], []
    for nome_g, sub in blocos:
        sa, sb_ = sub[sub[ano_col].isin(anos_a)], sub[sub[ano_col].isin(anos_b)]
        if y_ind is not None:
            ya, yb = y_ind.loc[sa.index].dropna(), y_ind.loc[sb_.index].dropna()
            if not len(ya) or not len(yb):
                continue
            r = E.comparar_proporcoes(float(ya.sum()), len(ya), float(yb.sum()), len(yb))
            linhas.append({
                "Grupo": nome_g, f"n {rot_a}": len(ya), f"eventos {rot_a}": int(ya.sum()),
                f"% {rot_a} (IC95%)": f"{fmt(r['pA'], 2)} ({fmt(r['icA'][0], 2)}–{fmt(r['icA'][1], 2)})",
                f"n {rot_b}": len(yb), f"eventos {rot_b}": int(yb.sum()),
                f"% {rot_b} (IC95%)": f"{fmt(r['pB'], 2)} ({fmt(r['icB'][0], 2)}–{fmt(r['icB'][1], 2)})",
                "Diferença (p.p.)": round(r["dif_pp"], 2),
                "Variação relativa (%)": round(100 * (r["razao"] - 1), 1) if np.isfinite(r["razao"]) else None,
                "Razão B/A (IC95%)": f"{fmt(r['razao'], 3)} ({fmt(r['razao_ic'][0], 3)}–{fmt(r['razao_ic'][1], 3)})",
                "p": E.fmt_p(r["p"]), "Teste": r["teste"]})
            for per, v, ic in ((rot_a, r["pA"], r["icA"]), (rot_b, r["pB"], r["icB"])):
                graf.append({"Grupo": str(nome_g), "Período": per, "valor": v, "inf": ic[0], "sup": ic[1]})
        elif usar_pad:
            g_var, nivel = (grupo, nome_g) if (grupo and nome_g != "Total") else (None, None)
            ra, rb = pad_por(sub, anos_a, g_var, nivel), pad_por(sub, anos_b, g_var, nivel)
            if not ra or not rb:
                continue
            rz = E.razao_padronizada(ra, rb)
            linhas.append({
                "Grupo": nome_g, f"Total {rot_a}": int(no_escopo(sa).shape[0]), f"Total {rot_b}": int(no_escopo(sb_).shape[0]),
                f"Taxa padronizada {rot_a} (IC95%)": f"{fmt(ra['taxa'], 2)} ({fmt(ra['ic95_inf'], 2)}–{fmt(ra['ic95_sup'], 2)})",
                f"Taxa padronizada {rot_b} (IC95%)": f"{fmt(rb['taxa'], 2)} ({fmt(rb['ic95_inf'], 2)}–{fmt(rb['ic95_sup'], 2)})",
                "Variação (%)": round(100 * (rz["razao"] - 1), 1),
                "Razão B/A (IC95%)": f"{fmt(rz['razao'], 3)} ({fmt(rz['ic'][0], 3)}–{fmt(rz['ic'][1], 3)})",
                "p": E.fmt_p(rz["p"]), "Teste": "Razão de taxas padronizadas (log-normal)"})
            for per, r_ in ((rot_a, ra), (rot_b, rb)):
                graf.append({"Grupo": str(nome_g), "Período": per, "valor": r_["taxa"],
                             "inf": r_["ic95_inf"], "sup": r_["ic95_sup"]})
        else:
            ka, kb = len(sa), len(sb_)
            if usar_pop:
                g_var, nivel = (grupo, nome_g) if (grupo and nome_g != "Total") else (None, None)
                ka, kb = len(no_escopo(sa)), len(no_escopo(sb_))
                ea = float(pop_por(g_var, anos_a, nivel)["populacao"].sum())
                eb = float(pop_por(g_var, anos_b, nivel)["populacao"].sum())
                unidade = f"taxa/{por_txt}"
                m = mult
            else:
                ea, eb, unidade, m = float(len(anos_a)), float(len(anos_b)), "média anual", 1
            if not ea or not eb:
                continue
            r = E.comparar_taxas(ka, ea, kb, eb)
            linhas.append({
                "Grupo": nome_g, f"Total {rot_a}": ka, f"Total {rot_b}": kb,
                f"{unidade} {rot_a}": round(r["tA"] * m, 2), f"{unidade} {rot_b}": round(r["tB"] * m, 2),
                "Variação (%)": round(r["var_pct"], 1),
                "Razão B/A (IC95%)": f"{fmt(r['razao'], 3)} ({fmt(r['razao_ic'][0], 3)}–{fmt(r['razao_ic'][1], 3)})",
                "p": E.fmt_p(r["p"]), "Teste": "Binomial condicional"})
            for per, v in ((rot_a, r["tA"] * m), (rot_b, r["tB"] * m)):
                graf.append({"Grupo": str(nome_g), "Período": per, "valor": v, "inf": None, "sup": None})
    if linhas:
        tab = pd.DataFrame(linhas)
        tab["Grupo"] = tab["Grupo"].astype(str)
        mostrar_tabela(st, tab, "comparacao_periodos", hide_index=True, width="stretch")
        relatorio["Comparação de períodos"] = tab
        gd = pd.DataFrame(graf)
        ordem_g = list(dict.fromkeys(gd["Grupo"]))
        base = alt.Chart(gd).encode(
            y=alt.Y("Grupo:N", sort=ordem_g, title=None, axis=alt.Axis(labelLimit=260)),
            yOffset=alt.YOffset("Período:N"),
            color=alt.Color("Período:N", scale=alt.Scale(range=[CINZA, paleta()["azul"]]), title=None))
        pts = base.mark_point(filled=True, size=80, stroke=paleta()["fundo"], strokeWidth=2).encode(
            x=alt.X("valor:Q", title="%" if y_ind is not None else ("taxa" if usar_pop else "média anual"),
                    scale=alt.Scale(zero=y_ind is None)),
            tooltip=["Grupo", "Período", alt.Tooltip("valor:Q", format=".2f")])
        camadas = [pts]
        if y_ind is not None or usar_pad:
            camadas.insert(0, base.mark_rule(strokeWidth=2).encode(x="inf:Q", x2="sup:Q"))
        mostrar_grafico(st, _cfg(alt.layer(*camadas).properties(height=max(120, 46 * len(ordem_g)))),
                        "comparacao_periodos")
        if y_ind is not None:
            nota = "Proporções com IC95% de Wilson; razão B/A com IC95% (método log); qui-quadrado ou exato de Fisher."
        elif usar_pad:
            nota = ("Taxas padronizadas por idade (método direto, padrão OMS; IC95% gama de Fay-Feuer), com a população "
                    "dos anos de cada período somada (pessoas-ano); razão B/A com IC95% log-normal. " + NOTA_POP)
        elif usar_pop:
            nota = ("Taxas brutas com denominador em pessoas-ano; razão de taxas com IC95% e teste binomial "
                    "condicional. " + NOTA_POP)
        else:
            nota = ("Média anual de registros (sem denominador populacional); razão com IC95% e teste binomial "
                    "condicional.")
        st.caption(nota + (f" Anos excluídos: {', '.join(map(str, excluir))}." if excluir else ""))

    # ---------------- série temporal interrompida
    st.markdown("#### Série temporal interrompida (regressão segmentada)")
    escalas = ["Mensal", "Anual"] if mes_col else ["Anual"]
    a, b, c = st.columns(3)
    escala = a.radio("Escala", escalas, horizontal=True, key=k + "its_esc")
    sazonal = b.checkbox("Ajustar sazonalidade (meses)", value=True, key=k + "its_saz",
                         disabled=escala != "Mensal")
    alvo = c.selectbox("Grupo do gráfico", [str(n) for n, _ in blocos], key=k + "its_g")
    ini, fim = anos_a[0], anos_b[-1]
    res, dados_graf = [], None
    for nome_g, sub in blocos:
        sub = sub[sub[ano_col].between(ini, fim)]
        if escala == "Mensal":
            chaves = [ano_col, mes_col]
            grade = pd.MultiIndex.from_product([range(ini, fim + 1), range(1, 13)], names=chaves).to_frame(index=False)
        else:
            chaves = [ano_col]
            grade = pd.DataFrame({ano_col: range(ini, fim + 1)})
        if y_ind is not None:
            s = serie_proporcao(sub, y_ind, chaves)[chaves + ["pct", "n"]].rename(columns={"pct": "y"})
            s.loc[s["n"] < 1, "y"] = np.nan
        else:
            s = sub.groupby(chaves, observed=True).size().reset_index(name="y")
        s = grade.merge(s, on=chaves, how="left")
        if y_ind is None:
            s["y"] = s["y"].fillna(0)
        # remove meses além do último dado disponível e anos excluídos
        tem = sub.groupby(chaves, observed=True).size().reset_index(name="_n")
        if len(tem):
            ult = tem[chaves].apply(tuple, axis=1).max()
            s = s[s[chaves].apply(tuple, axis=1) <= ult]
        s.loc[s[ano_col].isin(excluir), "y"] = np.nan
        s = s.reset_index(drop=True)
        inicio = int((s[ano_col] >= anos_b[0]).idxmax()) if (s[ano_col] >= anos_b[0]).any() else None
        if inicio is None:
            continue
        r = E.serie_interrompida(s[ano_col], s["y"].astype(float), inicio,
                                 periodo_sazonal=s[mes_col] if (escala == "Mensal" and sazonal) else None,
                                 maxlags=12 if escala == "Mensal" else 1)
        if not r:
            continue
        cf = r["coef"]
        un = "mês" if escala == "Mensal" else "ano"
        linhas_its = {"Grupo": str(nome_g), "Pontos": r["n"],
                      f"Tendência pré (por {un})": f"{fmt(cf['tempo']['b'], 3)} (p={E.fmt_p(cf['tempo']['p'])})",
                      "Mudança de nível (IC95%)": f"{fmt(cf['nivel_pos']['b'], 2)} ({fmt(cf['nivel_pos']['ic'][0], 2)} a {fmt(cf['nivel_pos']['ic'][1], 2)})",
                      "p nível": E.fmt_p(cf["nivel_pos"]["p"]),
                      f"Mudança de tendência por {un} (IC95%)": f"{fmt(cf['tendencia_pos']['b'], 3)} ({fmt(cf['tendencia_pos']['ic'][0], 3)} a {fmt(cf['tendencia_pos']['ic'][1], 3)})",
                      "p tendência": E.fmt_p(cf["tendencia_pos"]["p"]),
                      "R²": round(r["r2"], 3), "Durbin-Watson": round(r["durbin_watson"], 2)}
        res.append(linhas_its)
        if str(nome_g) == alvo:
            g = s.copy()
            g["observado"] = g["y"]
            g["ajustado"], g["contrafactual"] = r["ajustado"], r["contrafactual"]
            g["segmento"] = np.where(np.arange(len(g)) >= inicio, "pós", "pré")
            if escala == "Mensal":
                g["data"] = pd.to_datetime(dict(year=g[ano_col], month=g[mes_col], day=1))
                dados_graf = (g, "data", "T")
            else:
                g["ano"] = g[ano_col].astype(int).astype(str)
                dados_graf = (g, "ano", "O")
    if dados_graf:
        g, x, tipo = dados_graf
        mostrar_grafico(st, g_its(g[[x, "observado", "ajustado", "contrafactual", "segmento"]], x,
                                  "%" if y_ind is not None else f"Número de {evento}", tipo), "serie_interrompida")
        st.caption("Pontos = observado · linha azul = modelo ajustado · tracejado laranja = contrafactual "
                   "(tendência do período A projetada) · linha vertical = início do período B.")
    if res:
        tr = pd.DataFrame(res)
        mostrar_tabela(st, tr, "serie_interrompida", hide_index=True, width="stretch")
        relatorio["Série interrompida"] = tr
        st.caption("Modelo: y = β0 + β1·tempo + β2·pós + β3·tempo desde a interrupção"
                   + (" + meses (sazonalidade)" if escala == "Mensal" and sazonal else "")
                   + ". Mudança de nível = salto imediato no início do período B; mudança de tendência = "
                     "alteração da inclinação. Erros-padrão de Newey-West. Unidades: "
                   + ("pontos percentuais." if y_ind is not None else "número de registros."))
    else:
        st.info("Pontos insuficientes para a série interrompida (mínimo 8, com ao menos 3 em cada período). "
                "Use a escala mensal ou um período mais longo.")


# ------------------------------------------------------------------ título
def local_filtro(ufs, municipios=(), regioes=()):
    """'RJ' · 'SP, MG' · 'Niterói – RJ' · 'Sudeste' · 'Brasil' (para a linha de filtros)."""
    if municipios:
        return ", ".join(municipios)
    if regioes:
        return ", ".join(regioes)
    ufs = [u for u in ufs if u]
    return "Brasil" if not ufs or len(ufs) >= 27 else ", ".join(ufs)


def subtitulo_analise(meta, sistema, evento):
    """O que a base contém, ex.: 'Sífilis em gestante – SINAN'; 'Internações por CID-10 I21, I22 – SIH'."""
    from datasus_ciencia.catalogo import SISTEMAS
    tipos = SISTEMAS.get(sistema, {}).get("tipos") or {}
    tipo = meta.get("tipo")
    if sistema in ("SINAN", "SIM-NAC", "CNES") and tipo in tipos:
        assunto = tipos[tipo]
    elif sistema == "SIA":
        assunto = "Procedimentos ambulatoriais"
    else:
        assunto = evento.capitalize()
    # recorte feito no download (os filtros da barra lateral vão na linha de filtros)
    if meta.get("procedimentos_nomes"):
        nomes = [str(n).capitalize() for n in meta["procedimentos_nomes"] if n]
        assunto += " – " + "; ".join(nomes[:2]) + ("…" if len(nomes) > 2 else "")
    elif meta.get("cids"):
        assunto += " por CID-10 " + ", ".join(meta["cids"])
    return f"{assunto} – {sistema.split('-')[0]}"


# ------------------------------------------------------------------ página
def pagina_analise():
    bases = []
    if os.path.isdir(PASTA_PROCESSADOS):
        for n in os.listdir(PASTA_PROCESSADOS):
            p = os.path.join(PASTA_PROCESSADOS, n, "metadados.json")
            if os.path.exists(p):
                bases.append((os.path.getmtime(p), n))
    bases = [n for _, n in sorted(bases, reverse=True)]
    st.title("📈 Análise")
    if not bases:
        st.info("Nenhuma base disponível. Use **Buscar dados** para baixar uma base primeiro.")
        return

    sb = st.sidebar
    padrao = st.session_state.get("base_atual")
    nome = sb.selectbox("Base de dados", bases, index=bases.index(padrao) if padrao in bases else 0)
    with open(os.path.join(PASTA_PROCESSADOS, nome, "metadados.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    sistema = meta["sistema"]
    pq = [f for f in os.listdir(os.path.join(PASTA_PROCESSADOS, nome))
          if f.endswith(".parquet") and not f.startswith("agregado")]
    if not pq:
        st.error("Esta base não tem arquivo .parquet.")
        return
    cam = os.path.join(PASTA_PROCESSADOS, nome, pq[0])
    df0 = _carregar(cam, os.path.getmtime(cam))
    k = f"{nome}_"  # prefixo de chaves dos widgets

    # ---------------- filtros
    sb.markdown("### Filtros")
    anos_disp = [c for c in ANO_COLS if c in df0 and df0[c].notna().any()]
    # agravos sem data de diagnóstico bem preenchida: o ano de notificação fica como padrão
    if "ano_diagnostico" in anos_disp and df0["ano_diagnostico"].notna().mean() < 0.9:
        anos_disp.remove("ano_diagnostico")
        anos_disp.append("ano_diagnostico")
    ano_col = None
    if len(anos_disp) > 1:
        ano_col = sb.selectbox("Ano de referência", anos_disp, format_func=lambda c: ROT_ANO.get(c, c),
                               key=k + "anoref",
                               help="SIH/SIA: 'processamento' é a competência em que a AIH foi apresentada "
                                    "(como no TabNet); 'internação' usa a data de admissão.")
    elif anos_disp:
        ano_col = anos_disp[0]
    mes_col = MES_DO_ANO.get(ano_col)
    mes_col = mes_col if mes_col in df0 else None
    mask = pd.Series(True, index=df0.index)
    filtros_txt, demograficos = [], False
    if ano_col and df0[ano_col].notna().any():
        a_min, a_max = int(df0[ano_col].min()), int(df0[ano_col].max())
        ini = a_min
        anos_meta = [int(a) for a in meta.get("anos") or []]
        if ano_col == "ano_diagnostico" and anos_meta and a_min < min(anos_meta) <= a_max:
            # os arquivos do SINAN são por ano de NOTIFICAÇÃO: diagnósticos anteriores ao 1º ano baixado só trazem
            # os casos notificados depois (ex.: base 2017–2025 tem só parte dos diagnosticados em 2016)
            ini = min(anos_meta)
            sb.caption(f"Diagnósticos antes de {ini} estão incompletos (só os notificados a partir de {ini}); "
                       f"por isso o período começa em {ini}. Para incluí-los, baixe também os anos anteriores.")
        if a_max > a_min:
            a1, a2 = sb.slider("Período", a_min, a_max, (ini, a_max), key=k + "ano_" + ano_col)
            mask &= df0[ano_col].between(a1, a2)
            if (a1, a2) != (a_min, a_max):
                filtros_txt.append(f"{a1}–{a2}")

    def multi(col, rotulo, demo=True):
        """`demo=True`: filtro sem população correspondente no TabNet (bloqueia taxas)."""
        nonlocal mask, demograficos
        if col not in df0:
            return []
        vc = df0[col].astype("string").fillna("Sem informação").value_counts()
        if len(vc) < 2:  # só mostra o filtro se houver escolha possível
            return []
        opcoes = E.ordenar_categorias(list(vc.index), vc)
        sel = sb.multiselect(rotulo, opcoes, key=k + col, placeholder="Todos")
        if sel:
            mask &= df0[col].astype("string").fillna("Sem informação").isin(sel)
            filtros_txt.append(f"{rotulo.lower()}: {', '.join(sel)}")
            demograficos = demograficos or demo
        return sel

    # sexo, faixa etária e local têm população no TabNet → as taxas usam o subgrupo correspondente
    sel_sexo = multi("sexo", "Sexo", demo=False)
    multi("raca_cor", "Raça/cor")
    sel_faixa = multi("faixa_etaria", "Faixa etária", demo=False)
    sel_reg = multi("mun_residencia_regiao", "Região de residência", demo=False)
    sel_uf = multi("mun_residencia_uf", "UF de residência", demo=False)
    # territórios do TabNet (por município de residência): mantêm as taxas, pois a população é municipal
    sel_terr = {}
    for col_t, (_, rot_t) in T.TERRITORIOS.items():
        if col_t in df0:
            s = multi(col_t, rot_t, demo=False)
            if s:
                sel_terr[col_t] = s

    mun_sel = []
    if "mun_residencia_nome" in df0:
        mun = (df0[["mun_residencia_cod_ibge6", "mun_residencia_nome", "mun_residencia_uf"]].dropna()
               .drop_duplicates("mun_residencia_cod_ibge6"))
        mun = mun.assign(r=mun["mun_residencia_nome"] + " – " + mun["mun_residencia_uf"]).sort_values("r")
        mapa_mun = dict(zip(mun["r"], mun["mun_residencia_cod_ibge6"]))
        if len(mapa_mun) > 1:
            mun_sel = sb.multiselect("Município de residência", list(mapa_mun), key=k + "mun",
                                     placeholder="Todos (digite para buscar)")
        if mun_sel:
            mask &= df0["mun_residencia_cod_ibge6"].isin([mapa_mun[m] for m in mun_sel])
            filtros_txt.append("município: " + ", ".join(mun_sel))

    col_cid = COLUNA_CID.get(sistema)
    if col_cid and col_cid in df0:
        pref, desc_cid = seletor_cid(sb, "CID-10", df0, col_cid, nome, k + "cid")
        if pref:
            v = df0[col_cid].astype("string").str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
            mask &= v.str.startswith(pref).fillna(False)
            filtros_txt.append(f"CID-10: {desc_cid}")  # taxa por causa usa a população total: não bloqueia

    # causas: mal definidas e listas do TabNet (só para a causa básica do SIM e o diagnóstico do SIH)
    if col_cid and col_cid in df0 and sistema in ("SIM", "SIM-NAC", "SIH"):
        cods_cid = df0[col_cid].astype("string").str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
        mal_def = cods_cid.str.startswith("R").fillna(False)
        if 0 < int(mal_def.sum()) < len(df0):
            if sb.checkbox(f"Excluir causas mal definidas (R00–R99; {fmt(100 * mal_def.mean(), 1)}%)",
                           key=k + "maldef"):
                mask &= ~mal_def
                filtros_txt.append("sem causas mal definidas (R00–R99)")
        listas = {ch: v[2] for ch, v in T.LISTAS.items() if sistema in v[3] and ch != "grupos_cid10"}
        if listas:
            lst = sb.selectbox("Lista de causas do TabNet", ["—"] + list(listas), key=k + "lista",
                               format_func=lambda c: "Nenhuma" if c == "—" else listas[c])
            if lst != "—":
                try:
                    cls, titulos = _classificar_lista(nome, col_cid, lst, df0[col_cid])
                    vc_l = cls.value_counts()
                    ops_l = [t for t, fs in titulos.items() if vc_l.reindex(fs).fillna(0).sum() > 0]
                    ops_l += [c for c in vc_l.index]
                    sel_l = sb.multiselect("Causas da lista", ops_l, key=k + "lista_v", placeholder="Todas",
                                           format_func=lambda c: f"{c} · n={fmt(vc_l.get(c, 0) or sum(vc_l.get(f, 0) for f in titulos.get(c, [])))}")
                    if sel_l:
                        alvo = {f for s in sel_l for f in titulos.get(s, [s])}
                        mask &= cls.isin(alvo).fillna(False)
                        filtros_txt.append(f"{listas[lst]}: {', '.join(sel_l)}")
                except Exception as e:
                    sb.caption(f"Lista do TabNet indisponível ({e}).")

    # idade: intervalo em anos e faixas do TabNet
    if "idade_anos" in df0:
        ida = pd.to_numeric(df0["idade_anos"], errors="coerce")
        i_min, i_max = ida.min(), ida.max()
        if pd.notna(i_min) and int(i_max) > int(i_min):
            i1, i2 = sb.slider("Idade (anos)", int(i_min), int(i_max), (int(i_min), int(i_max)), key=k + "idade")
            if (i1, i2) != (int(i_min), int(i_max)):
                mask &= ida.between(i1, i2 + 0.999)
                filtros_txt.append(f"idade {i1}–{i2} anos")
                demograficos = True
        esquemas = {}
        ida_dias = idade_dias(df0)
        for nome_e, faixas_e in FAIXAS_TABNET.items():
            cat = _faixa_por(ida_dias if nome_e == "Menores de 1 ano" else ida, faixas_e)
            if cat.nunique() >= 2:
                esquemas[nome_e] = cat
        if esquemas:
            esq = sb.selectbox("Faixas etárias do TabNet", ["—"] + list(esquemas), key=k + "fx_esq",
                               format_func=lambda c: "Padrão (5 em 5 anos)" if c == "—" else c)
            if esq != "—":
                cat = esquemas[esq]
                vc_f = cat.value_counts()
                ordem_f = [r for _, _, r in FAIXAS_TABNET[esq] if r in vc_f.index]
                sel_f = sb.multiselect(f"Faixas ({esq})", ordem_f, key=k + "fx_v", placeholder="Todas",
                                       format_func=lambda c: f"{c} · n={fmt(vc_f[c])}")
                if sel_f:
                    mask &= cat.isin(sel_f).fillna(False)
                    filtros_txt.append(f"{esq.lower()}: {', '.join(sel_f)}")
                    demograficos = True

    if "mun_notificacao_nome" in df0:
        multi("mun_notificacao_nome", "Município de notificação")

    ja_filtradas = {"sexo", "raca_cor", "faixa_etaria", *T.TERRITORIOS}
    outras = [c for c in df0.columns if not c.isupper() and not c.startswith(("_", "mun_"))
              and c not in ja_filtradas
              and (df0[c].dtype == "bool" or str(df0[c].dtype) in ("string", "str", "boolean", "object"))
              and 1 < df0[c].nunique() <= 40]
    with (sb.expander("Outros filtros") if outras else st.empty()):
        extras = [] if not outras else st.multiselect("Variáveis", outras, format_func=rot, key=k + "extras",
                                placeholder="Escolha uma ou mais variáveis")
        for extra in extras:
            vc = df0[extra].astype("string").fillna("Sem informação").value_counts()
            vals = st.multiselect(rot(extra), E.ordenar_categorias(list(vc.index), vc), key=k + "extra_v_" + extra,
                                  format_func=lambda c, vc=vc: f"{c} · n={fmt(vc[c])}", placeholder="Todos")
            if vals:
                mask &= df0[extra].astype("string").fillna("Sem informação").isin(vals)
                filtros_txt.append(f"{rot(extra).lower()}: {', '.join(vals)}")
                demograficos = True

    # excluir registros com 'Ignorado' / 'Sem informação' nas variáveis escolhidas
    ausentes = list(E.AUSENTES)

    def _sem_info(c):
        """Sem informação ENTRE os registros a que a variável se aplica (ex.: tipo de parto só nos óbitos fetais e
        de <1 ano): excluir os ignorados de tipo de parto não pode apagar os óbitos de adultos."""
        m = df0[c].isna() | df0[c].astype("string").isin(ausentes).fillna(False)
        u = universo(df0, c, sistema)
        return m & u[0] if u is not None else m

    cand_ign, base_ign = {}, {}  # nº de ignorados e nº de registros a que a variável se aplica
    for c in df0.columns:
        if c.isupper() or c.startswith("_") or c in {"mun_residencia_cod_ibge6", "mun_residencia_cod_ibge7"}:
            continue
        if not (df0[c].dtype == "bool" or str(df0[c].dtype) in ("string", "str", "boolean", "object", "category")):
            continue
        if df0[c].nunique() > 60:
            continue
        n_ign = int(_sem_info(c).sum())
        u = universo(df0, c, sistema)
        n_base = int(u[0].sum()) if u is not None else len(df0)
        if 0 < n_ign < n_base:
            cand_ign[c], base_ign[c] = n_ign, n_base
    if cand_ign:
        ordem_ign = sorted(cand_ign, key=lambda c: (c not in ("sexo", "raca_cor", "faixa_etaria", "escolaridade"),
                                                    -cand_ign[c]))
        sel_ign = sb.multiselect(
            "Excluir 'Ignorado' / 'Sem informação' em", ordem_ign, key=k + "excl_ign", placeholder="Nenhuma variável",
            format_func=lambda c: f"{rot(c)} ({fmt(100 * cand_ign[c] / base_ign[c], 1)}%)",
            help="Remove da análise os registros sem informação nas variáveis escolhidas (% = proporção de "
                 "ignorados entre os registros a que a variável se aplica – ex.: tipo de parto só nos óbitos fetais "
                 "e de menores de 1 ano; os demais registros não são removidos). Atenção: as taxas populacionais ficam desativadas, porque o denominador "
                 "incluiria essas pessoas.")
        if sel_ign:
            m_ign = pd.Series(False, index=df0.index)
            for c in sel_ign:
                m_ign |= _sem_info(c)
            mask &= ~m_ign
            filtros_txt.append("sem ignorados em: " + ", ".join(re.sub(r"\s*\(.*\)$", "", rot(c)).lower()
                                                                for c in sel_ign))
            demograficos = True

    sb.markdown("### Comparação")
    cands = [c for c in ["sexo", "raca_cor", "faixa_etaria", "escolaridade", "estado_civil", "local_ocorrencia",
                         "circunstancia_obito", "tipo_parto", "faixa_etaria_mae", "escolaridade_mae",
                         "consultas_prenatal", "carater_internacao", "evolucao", "procedimento_nome",
                         "tipo_obito", "componente_infantil", "peso_nascer_cat", "gestacao_semanas_cat",
                         "tipo_gravidez", "obito_relacao_parto", "obito_investigado",
                         "mun_residencia_regiao", "mun_residencia_uf", "_status_dado"]
             if c in df0 and 2 <= df0[c].nunique() <= 30]
    # demais variáveis categóricas desta base (ex.: SIFG – classificação clínica, testes, UF do pré-natal): só
    # aparecem as que existem e variam nela, então cada agravo/sistema mostra só os seus marcadores
    cands += sorted((c for c in df0.columns
                     if c not in cands and not c.isupper() and not c.startswith(("_", "mun_"))
                     and c not in GRUPOS_ESCOLHA and c != "cid10_capitulo"  # duplica cid10_capitulo_nome
                     and str(df0[c].dtype) in ("string", "str", "object", "category")
                     and 2 <= df0[c].nunique() <= 30), key=lambda c: rot(c).lower())
    # muitos níveis (territórios, municípios): sem teto, o usuário escolhe até 8 logo abaixo
    cands += [c for c in T.TERRITORIOS if c in df0 and df0[c].nunique() >= 2]
    if "mun_residencia_nome" in df0 and len(mapa_mun) >= 2:
        cands.append("municipio_residencia")
    cands += [c for c in ("municipio_prenatal", "mun_notificacao_nome") if c in df0 and df0[c].nunique() >= 2]
    grupo = sb.selectbox("Comparar grupos por", ["(nenhum)"] + cands,
                         format_func=lambda c: c if c == "(nenhum)" else rot(c), key=k + "grupo")
    grupo = None if grupo == "(nenhum)" else grupo
    rot_cmp, niveis_cmp, cod_cmp = None, None, {}  # muitos níveis: rótulo por registro, níveis escolhidos, cod6 → nível
    if grupo in GRUPOS_ESCOLHA:
        if grupo == "municipio_residencia":
            cod_cmp = {c: r for r, c in mapa_mun.items()}
            rot_cmp = df0["mun_residencia_cod_ibge6"].map(cod_cmp).astype("category")
        else:
            rot_cmp = df0[grupo]
        vc_cmp = rot_cmp[mask].astype("string").value_counts()
        ops_cmp = list(vc_cmp.index)
        niveis_cmp = sb.multiselect(f"{rot(grupo)}: quais comparar (até 8)", ops_cmp, default=ops_cmp[:8],
                                    max_selections=8, key=k + "cmp_" + grupo,
                                    format_func=lambda c: f"{c} · n={fmt(vc_cmp.get(c, 0))}",
                                    help="Vêm marcados os 8 com mais registros. Os não escolhidos ficam fora da "
                                         "comparação, mas continuam no total.")
        if not niveis_cmp:
            sb.caption("Escolha ao menos um nível para comparar.")
            grupo = None
    excl = sb.checkbox("Excluir 'Ignorado' das comparações", value=True, key=k + "excl")

    # ---------------- indicador
    sb.markdown("### Indicador")
    bools = [c for c in df0.columns if str(df0[c].dtype) in ("boolean", "bool") and not c.startswith("_")]
    # letalidade do SINAN: óbito pelo agravo (evolução) ou, na tuberculose, encerramento por óbito por TB
    col_letal = None
    if sistema == "SINAN":
        for c_l, v_l in (("evolucao", "Óbito pelo agravo"), ("encerramento_tb", "Óbito por tuberculose")):
            if c_l in df0 and (df0[c_l] == v_l).any():
                col_letal = (c_l, v_l)
                break
    pode_mp = sistema in ("SIM", "SIM-NAC") and col_cid in df0 and \
        df0[col_cid].astype("string").str[:3].nunique() >= 2
    medidas = ["Número de registros", "Proporção de um desfecho (%)"]
    if col_letal:
        medidas.append("Letalidade (% de casos com óbito pelo agravo)")
    if pode_mp:
        medidas.append("Mortalidade proporcional (% dos óbitos)")
    ind = sb.radio("Medir", medidas, index=1 if "obito_hospitalar" in bools else 0, key=k + "ind",
                   help="Ex.: letalidade hospitalar = % de internações que terminaram em óbito.")
    y_ind, nome_ind = None, None
    if ind.startswith("Letalidade"):
        c_l, v_l = col_letal
        s_l = df0[c_l].astype("string")
        dens = ["Todos os casos notificados"]
        descart = df0["classificacao_final"].astype("string").eq("Descartado").fillna(False) \
            if "classificacao_final" in df0 else None
        if descart is not None and descart.any():
            dens.append("Casos confirmados (sem descartados)")
        preench = s_l.notna() & ~s_l.isin(list(E.AUSENTES))
        if not preench.all():
            dens.append("Casos com desfecho informado")
        den = sb.radio("Denominador", dens, key=k + "letal_den", index=len(dens) - 1,
                       help="TabNet/MS: letalidade = óbitos pelo agravo ÷ casos (confirmados) × 100.")
        y_ind = (s_l == v_l).fillna(False).astype("boolean")
        if den.startswith("Casos confirmados"):
            y_ind = y_ind.where(~descart)
        elif den.startswith("Casos com desfecho"):
            y_ind = y_ind.where(preench)
            if descart is not None:
                y_ind = y_ind.where(~descart)
        nome_ind = "Letalidade (% de casos com óbito pelo agravo)"
    elif ind.startswith("Mortalidade proporcional"):
        pref_mp, desc_mp = seletor_cid(sb, "Causa do numerador (CID-10)", df0, col_cid, nome + "_mp", k + "mp_cid")
        if meta.get("cids"):
            sb.caption(f"Atenção: esta base foi baixada só com CID {', '.join(meta['cids'])}; o denominador são "
                       "esses óbitos, não o total de óbitos. Para mortalidade proporcional geral, baixe o SIM sem "
                       "filtro de CID.")
        if pref_mp:
            v_mp = df0[col_cid].astype("string").str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
            y_ind = v_mp.str.startswith(pref_mp).fillna(False).astype("boolean")
            nome_ind = f"Mortalidade proporcional – {desc_mp} (% dos óbitos)"
        else:
            sb.caption("Escolha a causa do numerador.")
    elif ind.startswith("Proporção"):
        rotulos_b = {DESFECHOS.get(c, rot(c)): c for c in bools}
        escolha = sb.selectbox("Desfecho", list(rotulos_b) + ["Categoria de uma variável…"], key=k + "desf")
        if escolha in rotulos_b:
            cb = rotulos_b[escolha]
            y_ind, nome_ind = df0[cb].astype("boolean"), escolha
        else:
            cv = [c for c in df0.columns if not c.isupper() and not c.startswith("_")
                  and str(df0[c].dtype) in ("string", "str", "object") and 1 < df0[c].nunique() <= 60]
            vv = sb.selectbox("Variável", cv, format_func=rot, key=k + "desf_v")
            vcv = df0[vv].astype("string").value_counts()
            cats = sb.multiselect("Categoria(s) que contam como evento", E.ordenar_categorias(list(vcv.index), vcv),
                                  key=k + "desf_c")
            if cats:
                y_ind = df0[vv].astype("string").isin(cats).astype("boolean").where(df0[vv].notna())
                nome_ind = f"% {rot(vv)}: {', '.join(c[:40] for c in cats)}"
            else:
                sb.caption("Escolha a(s) categoria(s) do evento.")
    padronizar = False
    if y_ind is None and EVENTO.get(sistema, (None, None))[1] and "idade_anos" in df0:
        padronizar = sb.toggle("Padronizar por idade (OMS)", key=k + "pad",
                               help="Taxas padronizadas pelo método direto (população-padrão mundial da OMS), "
                                    "com a população por idade do TabNet. Use para comparar períodos ou locais "
                                    "com estruturas etárias diferentes.")

    # sem filtro: cópia rasa (copy-on-write do pandas 3) em vez de duplicar a base; df0 fica intacto no cache
    df = df0.copy(deep=False) if bool(mask.all()) else df0[mask]
    if grupo in GRUPOS_ESCOLHA:  # níveis não escolhidos ficam vazios (fora da comparação); df0 não é alterado
        r_ = rot_cmp.loc[df.index].astype("string")
        df[grupo] = r_.where(r_.isin(niveis_cmp))
    evento, mult, por_txt = EVENTO.get(sistema, ("registros", None, None))
    periodo_tit = None
    if ano_col and not df.empty:
        anos_t = df[ano_col].dropna()
        if len(anos_t):
            a_i, a_f = int(anos_t.min()), int(anos_t.max())
            periodo_tit = str(a_i) if a_i == a_f else f"{a_i}–{a_f}"
    ufs_tit = sel_uf or meta.get("ufs_residencia") or meta.get("ufs") or []
    if not sel_uf and "mun_residencia_uf" in df0 and df0["mun_residencia_uf"].nunique() == 1:
        ufs_tit = [str(df0["mun_residencia_uf"].dropna().iloc[0])]
    st.subheader(subtitulo_analise(meta, sistema, evento), anchor=False)
    # local e período sempre aparecem; os demais filtros da barra lateral vêm depois
    ja_ditos = ("uf de residência:", "município:", "região de residência:")
    outros_f = [f for f in filtros_txt if not f.startswith(ja_ditos) and not re.fullmatch(r"\d{4}–\d{4}", f)]
    st.markdown("**Filtros:** " + " · ".join([local_filtro(ufs_tit, mun_sel, sel_reg)]
                                             + ([periodo_tit] if periodo_tit else []) + outros_f))
    st.caption(f"{meta['sistema_nome']} · base `{nome}`")
    if df.empty:
        st.warning("Nenhum registro com esses filtros.")
        return

    # ---------------- indicadores
    c = st.columns([1, 1.25, 1, 1])
    c[0].metric(evento.capitalize(), fmt(len(df)), help=f"{fmt(100 * len(df) / len(df0), 1)}% dos registros da base")
    if ano_col:
        anos_df = df[ano_col].dropna()
        c[1].metric("Período", f"{int(anos_df.min())}–{int(anos_df.max())}" if len(anos_df) else "–")
    if "idade_anos" in df:
        ida = pd.to_numeric(df["idade_anos"], errors="coerce").dropna()
        c[2].metric("Idade mediana (anos)", fmt(ida.median(), 0) if len(ida) else "–")
    if "sexo" in df:
        c[3].metric("% sexo masculino", fmt(100 * (df["sexo"] == "Masculino").mean(), 1))
    if y_ind is not None:
        yy = y_ind.loc[df.index].dropna()
        if len(yy):
            kk, nn = float(yy.sum()), len(yy)
            i_, s_ = E.ic_wilson(kk, nn)
            st.metric(nome_ind, f"{fmt(100 * kk / nn, 2)}%",
                      help=f"{fmt(kk)} eventos em {fmt(nn)} registros · IC95% (Wilson) {fmt(float(i_), 2)}–{fmt(float(s_), 2)}%")
    if (df["_status_dado"] == "preliminar").any() if "_status_dado" in df else False:
        st.warning("A seleção inclui dados **preliminares**.")
    if ano_col and len(df):
        ult = int(df[ano_col].max())
        if mes_col and mes_col in df:
            meses_ult = df.loc[df[ano_col] == ult, mes_col].dropna().nunique()
            if meses_ult < 12:
                st.info(f"O ano de {ult} tem dados de apenas {meses_ult} mês(es). Compare totais anuais com cautela "
                        "(prefira proporções, médias mensais ou séries mensais).")

    # ---------------- população (para taxas) – base do TabNet (MS/SVSA), por município, sexo e idade
    pop, pop_base = None, None
    pode_taxa = bool(mult is not None and ano_col and "mun_residencia_cod_ibge6" in df and not demograficos)
    ufs_escopo = []
    if pode_taxa:
        # escopo populacional = UFs dos arquivos baixados (ou de residência pedidas), restritas ao filtro de UF
        ufs_meta = [u for u in (meta.get("ufs") or []) if u in UFS] or \
                   [u for u in (meta.get("ufs_residencia") or []) if u in UFS]
        ufs_escopo = sorted(ufs_meta) if ufs_meta else sorted(
            {u for u in df["mun_residencia_uf"].dropna().unique() if u in UFS})
        if sel_uf:
            ufs_escopo = [u for u in ufs_escopo if u in sel_uf]
        anos_escopo = tuple(sorted(int(a) for a in df[ano_col].dropna().unique()))
        try:
            pop_base = _pop_svs(tuple(ufs_escopo), anos_escopo)
        except Exception as e:
            st.info(f"População do TabNet indisponível no momento ({e}); taxas não serão calculadas.")
        if pop_base is not None and len(pop_base):
            pb = pop_base
            if sel_sexo:
                pb = pb[pb["sexo"].isin(sel_sexo)]
            if sel_faixa:
                pb = pb[pb["faixa_etaria"].isin(sel_faixa)]
            if sel_reg:
                pb = pb[pb["regiao"].isin(sel_reg)]
            if mun_sel:
                pb = pb[pb["cod6"].isin(df["mun_residencia_cod_ibge6"].unique())]
            terr = _territorios() if sel_terr else None
            if terr is not None:
                m_t = pd.Series(True, index=terr.index)
                for col_t, s in sel_terr.items():
                    m_t &= terr[col_t].isin(s)
                pb = pb[pb["cod6"].isin(terr.loc[m_t, "cod6"])]
            if grupo in GRUPOS_TERRIT:  # mesma coluna do grupo na população (por cod6) → taxas por nível
                if not cod_cmp:
                    terr_ = _territorios()
                    cod_cmp = dict(zip(terr_["cod6"], terr_[grupo])) if terr_ is not None else {}
                niv_ = pb["cod6"].map(cod_cmp)
                pb = pb.assign(**{grupo: niv_.where(niv_.isin(niveis_cmp))})
            pop_base = pb
            pop = pb.groupby(["cod6", "ano", "uf"], as_index=False)["pop"].sum().rename(columns={"pop": "populacao"})
            fora = int((~df["mun_residencia_uf"].isin(ufs_escopo)).sum())
            if fora:
                st.caption(f"Nas taxas, {fmt(fora)} registro(s) de residentes fora de {', '.join(ufs_escopo)} "
                           "não entram no numerador (o denominador é a população dessas UFs).")
        else:
            pop_base = None
    if not pode_taxa and mult:
        motivo = ("filtros por raça/cor, exclusão de ignorados ou outras características não têm população "
                  "correspondente no TabNet"
                  if demograficos else "faltam ano ou município de residência")
        nota_taxa = f"Taxas populacionais não exibidas: {motivo}. Use contagens/proporções."
    else:
        nota_taxa = None

    def no_escopo(d):
        return d[d["mun_residencia_uf"].isin(ufs_escopo)] if ufs_escopo and "mun_residencia_uf" in d else d

    def pop_por(g_var=None, anos=None, nivel=None):
        """População por ano (e por grupo, se o grupo tiver correspondente no TabNet)."""
        pb = pop_base if anos is None else pop_base[pop_base["ano"].isin(list(anos))]
        col = MAP_POP.get(g_var) if g_var else None
        if col and nivel is not None:
            pb = pb[pb[col] == nivel]
        g = pb.groupby(["ano"] + ([col] if col and nivel is None else []), observed=True)["pop"].sum().reset_index()
        g = g.rename(columns={"pop": "populacao"})
        return g.rename(columns={col: g_var}) if col and nivel is None else g

    def pad_por(d, anos, g_var=None, nivel=None):
        """Taxa padronizada por idade (OMS) de `d` nos `anos` (somados), opcionalmente para um nível do grupo."""
        pb = pop_base[pop_base["ano"].isin(list(anos))]
        col = MAP_POP.get(g_var) if g_var else None
        if col and nivel is not None:
            pb = pb[pb[col] == nivel]
        popf = pb.groupby("faixa5")["pop"].sum().reindex(R.FAIXAS_5_80).fillna(0)
        dd = no_escopo(d)
        dd = dd[dd[ano_col].isin(list(anos))]
        obf = pd.Series(R.faixa5_80(dd["idade_anos"])).value_counts().reindex(R.FAIXAS_5_80).fillna(0)
        if popf.sum() <= 0 or obf.sum() <= 0:
            return None
        return E.padronizacao_direta(obf.values, popf.values, R.PADRAO_OMS_80, mult)

    def serie_padronizada(d, g_var=None):
        linhas = []
        niveis = [None] if not g_var else [n for n in d[g_var].dropna().unique()]
        for nv in niveis:
            sub = d if nv is None else d[d[g_var] == nv]
            for ano in sorted(int(a) for a in sub[ano_col].dropna().unique()):
                r = pad_por(sub, [ano], g_var, nv)
                if r:
                    linhas.append({"ano": ano, **({g_var: nv} if g_var else {}),
                                   "n": int((no_escopo(sub)[ano_col] == ano).sum()),
                                   "taxa": round(r["taxa"], 2), "ic95_inf": round(r["ic95_inf"], 2),
                                   "ic95_sup": round(r["ic95_sup"], 2)})
        return pd.DataFrame(linhas)

    pode_pad = padronizar and pop_base is not None and len(pop_base) > 0
    if padronizar and not pode_pad:
        st.caption("Padronização por idade indisponível com os filtros atuais.")
    if pode_pad and grupo == "faixa_etaria":
        st.caption("Com comparação por faixa etária, as taxas são específicas por idade (padronização não se aplica).")
        pode_pad = False
    sem_idade = int(df["idade_anos"].isna().sum()) if pode_pad and "idade_anos" in df else 0
    if pode_pad and sem_idade:
        st.caption(f"Taxas padronizadas: {fmt(sem_idade)} registro(s) sem idade informada ficam fora do numerador.")

    abas = st.tabs(["Panorama", "Perfil", "Geografia", "Causas", "Tabela 1", "Tendência", "Períodos",
                    "Regressão", "Relatório"])
    relatorio = {}
    # cada gráfico/tabela exibido ganha "Baixar imagem"/"Personalizar" e entra no ZIP do Relatório; a fonte padrão
    # das imagens segue o recorte (UFs e anos da seleção) e cita a população do TabNet quando há taxas
    ufs_fonte = ufs_escopo or ([u for u in sel_uf] if sel_uf else None)
    anos_fonte = df[ano_col].dropna().unique() if ano_col and ano_col in df else None
    iniciar_figuras("analise", fonte_de_meta(meta, ufs_fonte, anos_fonte,
                                             extra=NOTA_POP if pop is not None and len(pop) else None))

    def preparar_grupo(d):
        return preparar_comparacao(d, grupo, excl) if grupo else d

    # =============== Panorama
    with abas[0]:
        if ano_col:
            g_var = grupo if grupo else None
            d = preparar_grupo(df)
            chaves = [ano_col] + ([g_var] if g_var else [])
            serie = d.groupby(chaves, observed=True).size().reset_index(name="n").rename(columns={ano_col: "ano"})
            usar_taxa = False
            if y_ind is not None:
                serie = serie_proporcao(d, y_ind, chaves).rename(columns={ano_col: "ano"})
                mostrar_grafico(st, g_linha(serie, "ano", "pct", g_var, "%", banda=("ic95_inf", "ic95_sup")),
                                "serie_anual_proporcao")
                st.caption(f"{nome_ind} por ano (faixa = IC95% de Wilson).")
            elif pop is not None and len(pop) and (g_var is None or g_var in GRUPOS_TAXA):
                usar_taxa = st.toggle(f"Mostrar taxa por {por_txt}", value=True, key=k + "tx")
            elif pop is not None and len(pop) and g_var:
                st.caption(f"Taxas por '{rot(g_var)}' não estão disponíveis (o TabNet não tem população por essa "
                           "variável); mostrando contagens.")
            if usar_taxa and pode_pad:
                serie = serie_padronizada(d, g_var)
                mostrar_grafico(st, g_linha(serie, "ano", "taxa", g_var, f"Taxa padronizada por {por_txt}",
                                            banda=("ic95_inf", "ic95_sup")), "serie_anual_taxa_padronizada")
                st.caption(f"Taxa de {evento} por {por_txt} **padronizada por idade** (método direto, população-padrão "
                           f"mundial da OMS; faixa = IC95% gama de Fay-Feuer). {NOTA_POP}")
            elif usar_taxa:
                serie = no_escopo(d).groupby(chaves, observed=True).size().reset_index(name="n").rename(
                    columns={ano_col: "ano"})
                serie = serie.merge(pop_por(g_var), on=["ano"] + ([g_var] if g_var else []), how="left")
                tx = E.taxas(serie["n"], serie["populacao"], mult)
                serie = pd.concat([serie, tx.round(2)], axis=1)
                mostrar_grafico(st, g_linha(serie, "ano", "taxa", g_var, f"Taxa por {por_txt}",
                                            banda=("ic95_inf", "ic95_sup")), "serie_anual_taxa")
                st.caption(f"Taxa bruta de {evento} por {por_txt} (faixa sombreada = IC95% exato de Poisson). "
                           + (f"Denominador restrito ao mesmo subgrupo (sexo/faixa etária) do filtro. " if
                              (sel_sexo or sel_faixa) else "") + NOTA_POP)
            elif y_ind is None:
                mostrar_grafico(st, g_linha(serie, "ano", "n", g_var, f"Número de {evento}"), "serie_anual")
                if nota_taxa:
                    st.caption(nota_taxa)
            relatorio["Série anual"] = serie
            with st.expander("Ver tabela da série"):
                mostrar_tabela(st, serie, "serie_anual", hide_index=True, width="stretch")

        if mes_col:
            st.markdown("##### Distribuição mensal (sazonalidade)")
            m = df.groupby(mes_col).size().reindex(range(1, 13), fill_value=0).reset_index(name="n")
            m["mês"] = [MESES[i - 1] for i in m[mes_col]]
            m["%"] = (100 * m["n"] / m["n"].sum()).round(1)
            mostrar_grafico(st, g_barras_v(m[["mês", "n", "%"]], "mês", ordem=MESES), "sazonalidade")
            relatorio["Sazonalidade"] = m[["mês", "n", "%"]]

    # =============== Perfil
    with abas[1]:
        if {"sexo", "faixa_etaria"} <= set(df.columns):
            st.markdown("##### Pirâmide etária")
            p = df[df["sexo"].isin(["Masculino", "Feminino"]) & df["faixa_etaria"].notna()]
            p = p.groupby(["faixa_etaria", "sexo"], observed=True).size().reset_index(name="n")
            if len(p):
                mostrar_grafico(st, g_piramide(p), "piramide_etaria")
                relatorio["Pirâmide etária"] = p
        perfil_vars = [v for v in ["sexo", "raca_cor", "faixa_etaria", "escolaridade", "estado_civil",
                                   "local_ocorrencia", "circunstancia_obito", "tipo_parto", "consultas_prenatal",
                                   "faixa_etaria_mae", "escolaridade_mae", "gestacao_semanas_cat", "tipo_gravidez",
                                   "peso_nascer_cat", "obito_relacao_parto", "obito_investigado", "tipo_obito",
                                   "componente_infantil", "faixa_etaria_infantil", "momento_obito_materno",
                                   "carater_internacao", "evolucao", "cid10_capitulo_nome"]
                       if v in df]
        # variáveis que só se aplicam a parte dos óbitos (tipo de parto → fetais e <1 ano; circunstância → causas
        # externas...) são descritas só nesse universo: nos demais registros o campo é vazio por NÃO SE APLICAR
        def _perfil(v):
            u = universo(df, v, sistema)
            return (df[v], None) if u is None else (df.loc[u[0], v], u[1])

        def _validos(s):
            s = s.astype("string")
            return s[s.notna() & ~s.isin(list(E.AUSENTES))]

        sem_info, unica = [], []
        for v in perfil_vars:
            s, _ = _perfil(v)
            val = _validos(s)
            if not len(s) or len(val) / len(s) < 0.01:  # <1% preenchido (ou ninguém a quem se aplique)
                sem_info.append(v)
            elif val.nunique() < 2:
                unica.append(v)
        perfil_vars = [v for v in perfil_vars if v not in sem_info and v not in unica]
        if sem_info:
            st.caption("Sem gráfico por falta de informação (menos de 1% preenchido) ou por não se aplicar aos "
                       "registros da seleção: " + ", ".join(rot(v) for v in sem_info) + ".")
        if unica:
            st.caption("Sem gráfico por ter uma única categoria preenchida: " + "; ".join(
                f"{rot(v)} = {_validos(_perfil(v)[0]).iloc[0]}" for v in unica) + ".")
        cols = st.columns(2)
        for i, v in enumerate(perfil_vars):
            s, desc_u = _perfil(v)
            s = s.astype("string").fillna("Sem informação")
            vc = s.value_counts()
            d = vc.rename_axis("categoria").reset_index(name="n")
            d["%"] = (100 * d["n"] / d["n"].sum()).round(1)
            ordem = E.ordenar_categorias(list(vc.index), vc)
            with cols[i % 2]:
                st.markdown(f"##### {rot(v)}")
                if desc_u:
                    st.caption(f"Só entre {desc_u} (n={fmt(len(s))}); nos demais registros a variável não se aplica.")
                mostrar_grafico(st, g_barras_h(d, "categoria", ordem=ordem), f"perfil_{v}")
            relatorio[f"Perfil – {v}"[:31]] = d
        num = [v for v in ["idade_anos", "idade_mae", "peso_g", "semanas_gestacao", "permanencia_dias",
                           "valor_total_rs"] if v in df]
        if num:
            st.markdown("##### Variáveis numéricas")
            linhas = []
            for v in num:
                x = pd.to_numeric(df[v], errors="coerce").dropna().astype(float)
                if len(x):
                    linhas.append({"Variável": rot(v), "n": len(x), "Média": round(x.mean(), 2),
                                   "DP": round(x.std(), 2), "Mediana": round(x.median(), 2),
                                   "P25": round(x.quantile(.25), 2), "P75": round(x.quantile(.75), 2),
                                   "Mín": round(x.min(), 2), "Máx": round(x.max(), 2)})
            mostrar_tabela(st, pd.DataFrame(linhas), "variaveis_numericas", hide_index=True, width="stretch")
            relatorio["Numéricas"] = pd.DataFrame(linhas)

    # =============== Geografia
    with abas[2]:
        if "mun_residencia_cod_ibge7" not in df:
            st.info("Esta base não tem município de residência.")
        else:
            ufs_dados = sorted(df["mun_residencia_uf"].dropna().unique())
            g = df.groupby(["mun_residencia_cod_ibge6", "mun_residencia_cod_ibge7", "mun_residencia_nome",
                            "mun_residencia_uf"]).size().reset_index(name="n")
            usar_taxa = pop is not None and len(pop) > 0
            if usar_taxa:
                anos_sel = df[ano_col].dropna().unique()
                pm = pop[pop["ano"].isin(anos_sel)].groupby("cod6")["populacao"].sum().reset_index()
                g = g.merge(pm, left_on="mun_residencia_cod_ibge6", right_on="cod6", how="left").drop(columns="cod6")
                g["pessoas_ano"] = g["populacao"]
                tx = E.taxas(g["n"], g["pessoas_ano"], mult)
                g = pd.concat([g, tx.round(2)], axis=1).drop(columns="populacao")
                st.caption(f"Taxa média anual por {por_txt} no período (denominador = soma das populações anuais).")
            elif nota_taxa:
                st.caption(nota_taxa)
            campo = "taxa" if usar_taxa else "n"
            titulo = f"Taxa/{por_txt}" if usar_taxa else "n"
            if 0 < len(ufs_dados) <= 3:
                feats = []
                try:
                    for uf in ufs_dados:
                        feats += _malha(uf)["features"]
                    vals = g.rename(columns={"mun_residencia_cod_ibge7": "codarea", "mun_residencia_nome": "nome"})
                    vals = vals[["codarea", "nome", "n", campo]].to_dict("records") if campo != "n" else \
                        vals[["codarea", "nome", "n"]].to_dict("records")
                    mostrar_grafico(st, g_mapa({"features": feats}, vals, campo, titulo), "mapa_municipios")
                except Exception as e:
                    st.info(f"Mapa indisponível ({e}).")
            elif len(ufs_dados) > 3:
                try:
                    gu = df.groupby("mun_residencia_uf").size().reset_index(name="n")
                    gu["codarea"] = gu["mun_residencia_uf"].map(lambda u: UFS.get(u))
                    gu["nome"] = gu["mun_residencia_uf"]
                    campo_u = "n"
                    if usar_taxa:
                        pu = pop[pop["ano"].isin(df[ano_col].dropna().unique())].groupby("uf")["populacao"].sum()
                        gu["taxa"] = (gu["n"] / gu["mun_residencia_uf"].map(pu) * mult).round(2)
                        campo_u = "taxa"
                    mostrar_grafico(st, g_mapa(_malha_ufs(), gu[["codarea", "nome", "n"] + (["taxa"] if usar_taxa else [])]
                                               .to_dict("records"), campo_u, titulo), "mapa_ufs")
                    st.caption("Mapa por UF (mais de 3 UFs na seleção).")
                except Exception as e:
                    st.info(f"Mapa indisponível ({e}).")
            ordem_col = "taxa" if usar_taxa else "n"
            top = g.sort_values(ordem_col, ascending=False)
            if usar_taxa:
                st.caption("Atenção: municípios pequenos têm taxas instáveis — observe o IC95%.")
            mostrar_tabela(st, top.drop(columns=["mun_residencia_cod_ibge7"]).rename(columns={
                "mun_residencia_cod_ibge6": "cód. IBGE", "mun_residencia_nome": "Município",
                "mun_residencia_uf": "UF", "pessoas_ano": "pessoas-ano"}), "ranking_municipios",
                hide_index=True, width="stretch", height=360)
            relatorio["Municípios"] = top

    # =============== Causas
    with abas[3]:
        ccol = COL_CAUSA.get(sistema)
        if not ccol or ccol not in df:
            st.info("Análise de causas disponível para SIM (causa básica) e SIH (diagnóstico principal).")
        else:
            desc = _cid()
            n_top = st.slider("Quantas causas mostrar", 5, 30, 15, key=k + "ntop")
            vc = df[ccol].dropna().value_counts().head(n_top)
            d = vc.rename_axis("CID").reset_index(name="n")
            d["Descrição"] = d["CID"].map(lambda c: desc.get(c, ""))
            d["%"] = (100 * d["n"] / len(df)).round(1)
            d["causa"] = d["CID"] + " " + d["Descrição"].str.slice(0, 45)
            mostrar_grafico(st, g_barras_h(d[["causa", "n", "%", "CID", "Descrição"]], "causa"), "principais_causas")
            st.caption(f"Principais categorias CID-10 (3 caracteres); % sobre {fmt(len(df))} registros.")
            relatorio["Principais causas"] = d.drop(columns="causa")
            if "cid10_capitulo_nome" in df:
                cap = df.groupby(["cid10_capitulo", "cid10_capitulo_nome"]).size().reset_index(name="n")
                cap["%"] = (100 * cap["n"] / cap["n"].sum()).round(1)
                with st.expander("Por capítulo da CID-10"):
                    mostrar_tabela(st, cap.sort_values("n", ascending=False), "capitulos_cid10", hide_index=True,
                                   width="stretch")
                relatorio["Capítulos CID-10"] = cap

    # =============== Tabela 1
    with abas[4]:
        if not grupo:
            st.info("Escolha uma variável em **Comparar grupos por** (barra lateral) para gerar a Tabela 1 com testes.")
        else:
            cat_disp = [v for v in ["sexo", "raca_cor", "faixa_etaria", "escolaridade", "estado_civil",
                                    "local_ocorrencia", "tipo_parto", "consultas_prenatal", "faixa_etaria_mae",
                                    "escolaridade_mae", "prematuro", "baixo_peso", "carater_internacao",
                                    "obito_hospitalar", "evolucao", "cid10_capitulo_nome", "mun_residencia_regiao",
                                    "obito_infantil", "gestacao_semanas_cat", "tipo_gravidez", "peso_nascer_cat",
                                    "obito_relacao_parto", "obito_investigado", "componente_infantil"]
                        if v in df and v != grupo]
            num_disp = [v for v in ["idade_anos", "idade_mae", "peso_g", "semanas_gestacao", "apgar5",
                                    "permanencia_dias", "valor_total_rs"] if v in df]
            a, b = st.columns(2)
            vc_ = a.multiselect("Variáveis categóricas", cat_disp, default=cat_disp[:4], format_func=rot, key=k + "t1c")
            vn_ = b.multiselect("Variáveis numéricas", num_disp, default=num_disp[:2], format_func=rot, key=k + "t1n")
            d = preparar_comparacao(df, grupo, False, 10)  # ignorados: tratados por excluir_ignorados
            univ = {v: u[0] for v in vc_ if (u := universo(d, v, sistema)) is not None}
            t1 = E.tabela1(d, grupo, vc_, vn_, excluir_ignorados=excl, universos=univ)
            t1["Variável"] = t1["Variável"].map(lambda v: rot(v) if v and v != "n" else v)
            mostrar_tabela(st, t1, "tabela_1", hide_index=True, width="stretch", height=min(700, 38 + 35 * len(t1)))
            st.caption("Categóricas: n (%) na coluna; teste qui-quadrado de Pearson ou exato de Fisher; efeito = V de "
                       "Cramér (≈0,1 pequeno, 0,3 médio, 0,5 grande). Numéricas: mediana (P25–P75) e média (DP); "
                       "Mann-Whitney ou Kruskal-Wallis. Com amostras grandes, diferenças pequenas ficam "
                       "significativas — interprete junto ao tamanho de efeito.")
            relatorio["Tabela 1"] = t1

    # =============== Tendência
    with abas[5]:
        if not ano_col or df[ano_col].nunique() < 4:
            st.info("A análise de tendência exige pelo menos 4 anos na seleção. Baixe uma série mais longa em "
                    "**Buscar dados** (ex.: 2010–2023).")
        else:
            usa_tx = pop is not None and len(pop) > 0 and (grupo is None or grupo in GRUPOS_TAXA)
            g_var = grupo
            d = preparar_comparacao(df, g_var, excl) if g_var else df
            serie = d.groupby([ano_col] + ([g_var] if g_var else []), observed=True).size().reset_index(name="n")
            serie = serie.rename(columns={ano_col: "ano"})
            medida = "n"
            if y_ind is not None:
                serie = serie_proporcao(d, y_ind, [ano_col] + ([g_var] if g_var else [])).rename(columns={ano_col: "ano"})
                medida = "pct"
                usa_tx = False
            if usa_tx and pode_pad:
                serie = serie_padronizada(d, g_var)
                medida = "taxa"
            elif usa_tx:
                serie = no_escopo(d).groupby([ano_col] + ([g_var] if g_var else []), observed=True).size() \
                    .reset_index(name="n").rename(columns={ano_col: "ano"})
                serie = serie.merge(pop_por(g_var), on=["ano"] + ([g_var] if g_var else []), how="left")
                serie["taxa"] = serie["n"] / serie["populacao"] * mult
                medida = "taxa"
            res = []
            grupos_iter = [(None, serie)] if not g_var else list(serie.groupby(g_var))
            for nome_g, sub in grupos_iter:
                # anos sem taxa (ex.: população do TabNet ainda não publicada para o último ano) ficam de fora
                sub = sub.sort_values("ano")
                sub = sub[pd.to_numeric(sub[medida], errors="coerce").notna()]
                if sub.empty:
                    continue
                r = E.prais_winsten(sub["ano"], sub[medida])
                if r:
                    res.append({"Grupo": nome_g or "Total", "Anos": f"{int(sub['ano'].min())}–{int(sub['ano'].max())}",
                                "Medida": {"taxa": f"taxa{' padronizada' if pode_pad else ''}/{por_txt}",
                                           "pct": nome_ind or "%"}.get(medida, "contagem"),
                                "Inicial": round(float(sub[medida].iloc[0]), 2),
                                "Final": round(float(sub[medida].iloc[-1]), 2),
                                "VPA (%)": round(r["vpa"], 2),
                                "IC95%": f"{fmt(r['ic95_inf'], 2)} a {fmt(r['ic95_sup'], 2)}",
                                "p": E.fmt_p(r["p"]), "Tendência": r["tendencia"],
                                "Durbin-Watson": round(r["durbin_watson"], 2)})
            mostrar_grafico(st, g_linha(serie.round(2), "ano", medida, g_var,
                                        {"taxa": f"Taxa por {por_txt}", "pct": "%"}.get(medida, f"Número de {evento}")),
                            "tendencia")
            if res:
                tr = pd.DataFrame(res)
                mostrar_tabela(st, tr, "tendencia_prais_winsten", hide_index=True, width="stretch")
                relatorio["Tendência (Prais-Winsten)"] = tr
            st.caption("Regressão de Prais-Winsten sobre log10 da medida (Antunes & Cardoso, 2015). "
                       "VPA = variação percentual anual = (10^β − 1)×100. Tendência estacionária quando p ≥ 0,05. "
                       + (nota_taxa or ""))

    # =============== Períodos (pré × pós) e série temporal interrompida
    with abas[6]:
        aba_periodos(df, ano_col, mes_col, grupo, excl, y_ind, nome_ind, pop, mult, por_txt, evento, k, relatorio,
                     pop_por=pop_por if pop_base is not None else None,
                     pad_por=pad_por if pode_pad else None, no_escopo=no_escopo)

    # =============== Regressão
    with abas[7]:
        st.markdown("Estime a associação entre características e um **desfecho binário** (razão de chances).")
        booleanas = [c for c in df.columns if str(df[c].dtype) in ("boolean", "bool") and not c.startswith("_")]
        tipo_d = st.radio("Desfecho", ["Variável sim/não da base", "Categoria de uma variável"]
                          + (["CID-10 específica"] if col_cid and col_cid in df else []),
                          horizontal=True, key=k + "tipo_d")
        y = None
        if tipo_d == "Variável sim/não da base":
            if booleanas:
                vb = st.selectbox("Desfecho", booleanas, format_func=rot, key=k + "vb")
                y = df[vb]
                desc_y = rot(vb)
            else:
                st.info("Esta base não tem variáveis sim/não; use outra opção.")
        elif tipo_d == "Categoria de uma variável":
            cv = [c for c in df.columns if not c.isupper() and not c.startswith(("_",)) and
                  str(df[c].dtype) in ("string", "str", "object") and 1 < df[c].nunique() <= 40]
            a, b = st.columns(2)
            vv = a.selectbox("Variável", cv, format_func=rot, key=k + "vv")
            vcv = df[vv].astype("string").value_counts()
            cat = b.selectbox("Categoria = evento", E.ordenar_categorias(list(vcv.index), vcv), key=k + "cat")
            y = (df[vv].astype("string") == cat).astype("boolean").where(df[vv].notna())
            desc_y = f"{rot(vv)} = {cat}"
        else:
            pref_y, desc_cid_y = seletor_cid(st, "CID-10 do evento", df0, col_cid, nome, k + "cidy")
            if pref_y:
                v = df[col_cid].astype("string").str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
                y = v.str.startswith(pref_y).astype("boolean")
                desc_y = f"CID-10: {desc_cid_y}"
        covs_disp = [c for c in ["sexo", "raca_cor", "faixa_etaria", "escolaridade", "estado_civil",
                                 "faixa_etaria_mae", "escolaridade_mae", "consultas_prenatal", "tipo_parto",
                                 "carater_internacao", "mun_residencia_regiao", "mun_residencia_uf",
                                 "local_ocorrencia", "tipo_gravidez", "gestacao_semanas_cat", "peso_nascer_cat",
                                 "obito_relacao_parto", "componente_infantil"]
                     if c in df and df[c][~df[c].isin(E.AUSENTES)].nunique() >= 2]
        covs = st.multiselect("Variáveis explicativas", covs_disp, default=[c for c in ["sexo", "faixa_etaria", "raca_cor"]
                                                                              if c in covs_disp],
                              format_func=rot, key=k + "covs")
        refs = {}
        if covs:
            with st.expander("Categorias de referência"):
                cs = st.columns(min(3, len(covs)))
                for i, cv_ in enumerate(covs):
                    vcc = df[cv_].astype("string").value_counts()
                    ops = [o for o in E.ordenar_categorias(list(vcc.index), vcc) if o not in E.AUSENTES]
                    if not ops:
                        continue
                    padrao_ref = vcc.index[0] if vcc.index[0] in ops else ops[0]
                    refs[cv_] = cs[i % len(cs)].selectbox(rot(cv_), ops, index=ops.index(padrao_ref), key=k + "ref" + cv_)
        if y is not None and covs and st.button("Ajustar modelo", type="primary", key=k + "fit"):
            if tipo_d == "Categoria de uma variável" and vv in covs:
                st.error("O desfecho não pode estar entre as variáveis explicativas.")
            else:
                try:
                    with st.spinner("Ajustando regressão logística..."):
                        tab, resumo = E.regressao_logistica(df, y, covs, excluir_ignorados=excl, referencias=refs)
                    st.session_state[k + "modelo"] = (tab, resumo, desc_y)
                except Exception as e:
                    st.error(f"Não foi possível ajustar o modelo: {e}")
        if st.session_state.get(k + "modelo"):
            tab, resumo, desc_y = st.session_state[k + "modelo"]
            st.markdown(f"**Desfecho:** {desc_y} · n = {fmt(resumo['n'])} · eventos = {fmt(resumo['eventos'])} "
                        f"({fmt(100 * resumo['eventos'] / resumo['n'], 1)}%) · pseudo-R² de McFadden = "
                        f"{fmt(resumo['pseudo_r2'], 3)}" + (" · *amostra aleatória de 400 mil*" if resumo["amostrado"] else ""))
            if resumo.get("omitidas"):
                st.warning("Categorias omitidas por terem menos de 5 registros ou nenhuma variação no desfecho "
                           "(possível separação perfeita – ex.: desfecho definido pela própria variável): "
                           + ", ".join(resumo["omitidas"][:15]))
            vis = tab.drop(columns=[c for c in tab.columns if c.startswith("_")]).copy()
            vis["Variável"] = vis["Variável"].map(lambda v: rot(v) if v else v)
            mostrar_tabela(st, vis, "regressao_logistica", hide_index=True, width="stretch")
            fp = g_forest(tab)
            if fp is not None:
                mostrar_grafico(st, fp, "grafico_floresta")
            st.caption("OR bruto: um modelo por variável. OR ajustado: todas as variáveis no mesmo modelo. "
                       "Categorias com menos de 5 registros ou sem variação no desfecho são omitidas.")
            relatorio["Regressão logística"] = vis

    # =============== Relatório
    with abas[8]:
        st.markdown("Baixe todas as tabelas desta análise em um único Excel, com o texto de métodos estatísticos.")
        filtros_desc = "; ".join(filtros_txt) if filtros_txt else "nenhum"
        st.markdown(f"**Seleção:** {meta['sistema_nome']} · {fmt(len(df))} {evento} · filtros: {filtros_desc}")
        st.markdown("##### Texto sugerido – Análise estatística")
        st.write(E.TEXTO_METODOS + " " + E.TEXTO_METODOS_PERIODOS)
        # contexto do resumo para congresso (montado antes do Excel para o resumo entrar nele)
        ctx_resumo = {
            "sistema": meta["sistema_nome"], "evento": evento, "n": fmt(len(df)),
            "periodo": (f"{int(df[ano_col].min())}–{int(df[ano_col].max())}"
                        if ano_col and df[ano_col].notna().any() else None),
            "ufs": ufs_escopo, "filtros": filtros_desc,
            "recorte": "; ".join(p for p in (
                ("CID-10 " + ", ".join(meta["cids"])) if meta.get("cids") else "",
                ("procedimentos " + ", ".join(meta.get("procedimentos_nomes") or meta["procedimentos"]))
                if meta.get("procedimentos") else "") if p), "taxa": por_txt if pop is not None and len(pop) else None,
            "padronizada": "sim (método direto, população-padrão OMS)" if pode_pad else None,
            "grupo": rot(grupo) if grupo else None, "indicador": nome_ind,
            "preliminar": "sim" if "_status_dado" in df and (df["_status_dado"] == "preliminar").any() else None,
        }
        ctx_txt = RS.serializar_contexto(ctx_resumo, relatorio)
        assin = RS.assinatura(ctx_txt)
        k_rs = k + "rs_"
        resumo_atual = st.session_state.get(k_rs + "resumo")
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as xw:
            itens = ["Base", "Sistema", "Registros na seleção", "Filtros", "Gerado em", "Métodos"]
            valores = [nome, meta["sistema_nome"], len(df), filtros_desc, date.today().isoformat(),
                       E.TEXTO_METODOS + " " + E.TEXTO_METODOS_PERIODOS]
            if resumo_atual:
                itens.append("Resumo congresso")
                valores.append(RS.texto_final(_resumo_editado(k_rs, resumo_atual)))
            pd.DataFrame({"Item": itens, "Valor": valores}).to_excel(xw, sheet_name="Resumo", index=False)
            for aba, tabela in relatorio.items():
                nome_aba = "".join(ch for ch in aba if ch not in "[]:*?/\\")[:31]
                t = tabela.drop(columns=[c for c in tabela.columns if str(c).startswith("_")], errors="ignore")
                t.to_excel(xw, sheet_name=nome_aba, index=False)
        st.download_button("⬇️ Baixar relatório (Excel)", buf.getvalue(), type="primary",
                           file_name=f"analise_{nome}_{date.today().isoformat()}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        botao_zip(st, "analise", f"figuras_{nome}_{date.today().isoformat()}")
        if len(df) <= 300_000:
            # montado só quando pedido (antes era refeito a cada clique) e com todas as variáveis, inclusive as
            # originais que a página não carrega: lê o parquet em lotes e guarda só as linhas filtradas
            k_csv = k + "csv_sel"
            pos = df.index.to_numpy()
            assin_csv = (len(pos), int(pos.sum()), int((pos[::97] * 31).sum()))
            if st.session_state.get(k_csv, (None,))[0] != assin_csv:
                if st.button(f"📄 Preparar CSV dos {fmt(len(df))} registros filtrados", key=k + "csv_btn"):
                    with st.spinner("Montando o CSV com todas as variáveis..."):
                        st.session_state[k_csv] = (assin_csv, _csv_selecao(cam, df.index.to_numpy()))
            if st.session_state.get(k_csv, (None,))[0] == assin_csv:
                st.download_button("⬇️ Baixar registros filtrados (CSV)", st.session_state[k_csv][1],
                                   file_name=f"selecao_{nome}.csv", mime="text/csv")
        st.caption("Planilhas incluídas: " + ", ".join(relatorio) + ". A regressão entra depois de ajustada "
                   "na aba Regressão; a Tabela 1, depois de escolher um grupo de comparação.")
        st.divider()
        secao_resumo_congresso(k_rs, ctx_resumo, assin, relatorio, nome)


# ------------------------------------------------------------------ resumo para congresso
def _resumo_editado(k_rs, resumo):
    """Resumo com as edições feitas pelo usuário nas caixas de texto."""
    return {c: st.session_state.get(k_rs + "sec_" + c, resumo.get(c, "")) for c, _ in RS.SECOES}


def _carregar_resumo(k_rs, resumo, assin, origem):
    st.session_state[k_rs + "resumo"] = resumo
    st.session_state[k_rs + "resumo_meta"] = (assin, origem)
    for c, _ in RS.SECOES:
        st.session_state[k_rs + "sec_" + c] = resumo.get(c, "")


def secao_resumo_congresso(k_rs, ctx, assin, relatorio, nome):
    st.markdown("##### Resumo para congresso")
    st.markdown("O programa lê os resultados desta análise e lista os **achados ranqueados por relevância "
                "estatística** (significância, tamanho de efeito e magnitude). Marque os que devem entrar e monte um "
                "resumo estruturado de 250–300 palavras. Gratuito e offline.")
    st.caption("Achados vêm das abas já calculadas (" + ", ".join(relatorio) + "). Para incluir Tabela 1 ou "
               "regressão, gere-as nas respectivas abas antes.")
    a, b = st.columns(2)
    titulo = a.text_input("Título provisório (opcional)", key=k_rs + "titulo")
    autores = b.text_input("Autores (opcional, só no arquivo)", key=k_rs + "autores")
    contexto_usuario = st.text_area("Contexto ou hipótese para a Introdução (opcional)", key=k_rs + "ctxu",
                                    height=70, placeholder="Ex.: O infarto é a principal causa de morte no estado e "
                                                           "houve mudança na rede de hemodinâmica em 2018.")

    achados = RS.extrair_achados(ctx, relatorio)
    if not achados:
        st.info("Nenhum achado disponível para esta seleção.")
        return
    icone = {"alta": "🟢 alta", "media": "🟡 média", "baixa": "⚪ baixa"}
    n_alta = sum(a_["relevancia"] == "alta" for a_ in achados)
    st.markdown(f"**Achados** ({len(achados)}; {n_alta} de alta relevância já marcados) – marque os que devem "
                "entrar no resumo:")
    for a_ in achados:
        chave = k_rs + "ach_" + a_["id"]
        if chave not in st.session_state:
            st.session_state[chave] = a_["relevancia"] == "alta"
        st.checkbox(a_["texto"], key=chave)
        st.caption(f"{icone[a_['relevancia']]} · {a_['secao']} · {a_['motivo']}")
    marcados = [a_ for a_ in achados if st.session_state.get(k_rs + "ach_" + a_["id"])]
    previa = RS.montar_resumo(ctx, marcados, contexto_usuario)
    n_prev = RS.contar_palavras(" ".join(previa.values()))
    st.caption(f"Com {len(marcados)} achado(s) marcado(s), o resumo terá cerca de **{n_prev} palavras** "
               f"(meta {RS.PALAVRAS_MIN}–{RS.PALAVRAS_MAX}).")

    pasta_base = os.path.join(PASTA_PROCESSADOS, nome)
    c1, c2 = st.columns(2)
    if c1.button(f"🧩 Montar resumo com {len(marcados)} achado(s)", type="primary", key=k_rs + "montar",
                 disabled=not marcados):
        _carregar_resumo(k_rs, previa, assin, "regras")
    if c2.button("📤 Preparar para o Claude (usa sua assinatura)", key=k_rs + "preparar", disabled=not marcados):
        atual = st.session_state.get(k_rs + "resumo")
        caminho = RS.salvar_contexto(pasta_base, nome, ctx, relatorio, marcados,
                                     _resumo_editado(k_rs, atual) if atual else previa, titulo, autores,
                                     contexto_usuario)
        st.success(f"Contexto salvo em `{os.path.relpath(caminho)}`. No chat do Claude Code (Claude Desktop, aba "
                   "Code, nesta pasta), peça:")
        st.code(f"Monta o resumo para congresso da base {nome}", language=None)
        st.caption("Depois que o Claude salvar o texto, volte aqui e clique em **Carregar resumo do Claude**.")
    resumo_claude = RS.ler_resumo_claude(pasta_base)
    if resumo_claude and st.button("📥 Carregar resumo do Claude nas caixas de texto", key=k_rs + "carregar"):
        _carregar_resumo(k_rs, resumo_claude, assin, "Claude")

    resumo = st.session_state.get(k_rs + "resumo")
    if not resumo:
        return
    assin_r, origem = st.session_state.get(k_rs + "resumo_meta", (assin, "regras"))
    if assin_r != assin:
        st.warning("A seleção ou as tabelas mudaram depois que o resumo foi montado. Monte de novo para atualizar.")
    st.markdown(f"**Resumo** ({'redigido pelo Claude' if origem == 'Claude' else 'montado por regras'}; "
                "edite à vontade):")
    for c, rotulo in RS.SECOES:
        st.text_area(rotulo, key=k_rs + "sec_" + c, height=70 if c in ("introducao", "objetivo", "conclusao") else 140)
    final = _resumo_editado(k_rs, resumo)
    corpo = " ".join(final.values())
    n_pal = RS.contar_palavras(corpo)
    if RS.PALAVRAS_MIN <= n_pal <= RS.PALAVRAS_MAX:
        st.success(f"{n_pal} palavras (limite {RS.PALAVRAS_MIN}–{RS.PALAVRAS_MAX}) · {len(corpo)} caracteres com espaços")
    else:
        st.warning(f"{n_pal} palavras – fora do limite de {RS.PALAVRAS_MIN}–{RS.PALAVRAS_MAX} · "
                   f"{len(corpo)} caracteres com espaços")
    if "[completar" in corpo:
        st.caption("Há trechos marcados com **[completar: ...]** para você preencher.")
    txt = RS.texto_final(final, titulo, autores)
    md = RS.texto_final({c: f"{v}" for c, v in final.items()}, f"# {titulo}" if titulo else "", autores)
    md = re.sub(r"^(Introdução|Objetivo|Métodos|Resultados|Conclusão):", r"**\1:**", md, flags=re.M)
    c1, c2 = st.columns(2)
    c1.download_button("⬇️ Baixar resumo (.txt)", txt.encode("utf-8-sig"), file_name=f"resumo_{nome}.txt",
                       mime="text/plain", key=k_rs + "dl_txt")
    c2.download_button("⬇️ Baixar resumo (.md)", md.encode("utf-8"), file_name=f"resumo_{nome}.md",
                       mime="text/markdown", key=k_rs + "dl_md")
    st.caption("É um rascunho: revise a redação e confira os números contra as tabelas antes de submeter. "
               "O resumo também entra na planilha 'Resumo' do relatório Excel.")
