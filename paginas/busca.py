"""Página 'Buscar dados': nova busca, minhas bases, disponibilidade e ajuda."""

import json
import os
from collections import defaultdict
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from datasus_ciencia import __version__
from datasus_ciencia.catalogo import SISTEMAS, UFS
from datasus_ciencia.ftp import ClienteFTP, periodos_disponiveis
from datasus_ciencia.pipeline import (PASTA_CACHE, PASTA_PROCESSADOS, ErroPedido, campos_disponiveis,
                                      campos_em_cache, executar, montar_comando)
from datasus_ciencia.referencias import cid10_opcoes
from datasus_ciencia.saida import _rotulo, descricao_campo
from datasus_ciencia.tratamento import Municipios, expandir_cids


ANO_ATUAL = date.today().year
NOMES_UF = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia", "CE": "Ceará",
    "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso",
    "MS": "Mato Grosso do Sul", "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo",
    "SE": "Sergipe", "TO": "Tocantins",
}
REGIOES_UF = {
    "Norte": ["AC", "AP", "AM", "PA", "RO", "RR", "TO"],
    "Nordeste": ["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"],
    "Sudeste": ["ES", "MG", "RJ", "SP"], "Sul": ["PR", "RS", "SC"], "Centro-Oeste": ["DF", "GO", "MT", "MS"],
}
ROTULO_SISTEMA = {
    "SIM": "SIM – Óbitos", "SIM-NAC": "SIM – Óbitos fetais/infantis/maternos/externos (Brasil)",
    "SINASC": "SINASC – Nascidos vivos", "SIH": "SIH – Internações hospitalares",
    "SIA": "SIA – Produção ambulatorial", "SINAN": "SINAN – Agravos de notificação",
    "CNES": "CNES – Estabelecimentos de saúde",
}
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


# ================================================================= utilidades
def bases_processadas():
    if not os.path.isdir(PASTA_PROCESSADOS):
        return []
    out = []
    for n in os.listdir(PASTA_PROCESSADOS):
        p = os.path.join(PASTA_PROCESSADOS, n, "metadados.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                m = json.load(fh)
            out.append((os.path.getmtime(p), n, m))
    return [(n, m) for _, n, m in sorted(out, reverse=True)]


# A aba "Minhas bases" nunca lê a base inteira: bases grandes (ex.: SINASC de uma UF em 5 anos, ~100 colunas)
# passam de 1 GB na memória e derrubam a página em PCs de 8 GB. Lê só a prévia, o esquema e, no agregado, as
# colunas escolhidas; o cache guarda poucas entradas.
@st.cache_data(show_spinner="Carregando prévia...", max_entries=4)
def previa_base(caminho, _mtime, n=2000):
    import pyarrow as pa
    import pyarrow.parquet as pq
    f = pq.ParquetFile(caminho)
    lote = next(f.iter_batches(batch_size=n), None)
    tab = pa.Table.from_batches([lote]) if lote is not None else f.schema_arrow.empty_table()
    return tab.replace_schema_metadata(f.schema_arrow.metadata).to_pandas()


@st.cache_data(max_entries=16)
def esquema_base(caminho, _mtime):
    """(nº de registros, colunas, colunas numéricas) lidos só dos metadados do parquet."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    f = pq.ParquetFile(caminho)
    sch = f.schema_arrow
    numericas = [c.name for c in sch if pa.types.is_integer(c.type) or pa.types.is_floating(c.type)]
    return f.metadata.num_rows, sch.names, numericas


@st.cache_data(show_spinner="Lendo as colunas escolhidas...", max_entries=2)
def colunas_base(caminho, _mtime, colunas):
    return pd.read_parquet(caminho, columns=list(colunas))


def arquivo_base(pasta, extensoes=(".parquet",)):
    for f in os.listdir(pasta):
        if f.endswith(extensoes) and not f.startswith("agregado"):
            return os.path.join(pasta, f)
    return None


def fmt(n):
    return f"{n:,}".replace(",", ".")


@st.cache_data(show_spinner="Carregando tabela CID-10...", ttl=86400)
def opcoes_cid():
    return cid10_opcoes(PASTA_CACHE)


@st.cache_data(show_spinner="Carregando tabela de procedimentos (SIGTAP)...", ttl=86400)
def opcoes_procedimentos():
    try:
        from datasus_ciencia.referencias import procedimentos_opcoes
        return procedimentos_opcoes(PASTA_CACHE)
    except Exception:
        return {}


@st.cache_data(show_spinner="Estimando o tamanho do download...", ttl=3600)
def estimar_download(sistema, tipo, ufs, anos, meses, somente_finais):
    """(nº de arquivos, bytes totais, bytes ainda não baixados) ou None."""
    from datasus_ciencia.ftp import localizar_arquivos
    from datasus_ciencia.pipeline import PASTA_DADOS
    try:
        cli = ClienteFTP(PASTA_CACHE, log=lambda *_: None)
        try:
            arqs, _ = localizar_arquivos(cli, sistema, (tipo or SISTEMAS[sistema]["tipo_padrao"] or "").upper() or None,
                                         list(ufs), list(anos), list(meses) or list(range(1, 13)),
                                         incluir_preliminares=not somente_finais)
            tams = {}
            for d in {a["diretorio"] for a in arqs}:
                tams.update(cli.listar_tamanhos(d))
        finally:
            cli.fechar()
        total = falta = 0
        for a in arqs:
            t = tams.get(a["nome"], 0)
            total += t
            local = os.path.join(PASTA_DADOS, "brutos", sistema, a["nome"].upper().replace(".DBC", ".dbc"))
            if not (os.path.exists(local) and os.path.getsize(local) == t):
                falta += t
        return len(arqs), total, falta
    except Exception:
        return None


@st.cache_data(show_spinner="Carregando municípios do IBGE...", ttl=86400)
def opcoes_municipios(ufs):
    """{'Nome – UF': código IBGE 6 díg.}, restrito às UFs escolhidas (todas se vazio)."""
    mapa = Municipios(PASTA_CACHE, log=lambda *_: None).mapa()
    cod_ufs = {UFS[u] for u in ufs if u in UFS}
    from datasus_ciencia.catalogo import UF_POR_CODIGO
    itens = sorted(((f"{v['nome']} – {v.get('uf') or UF_POR_CODIGO.get(k[:2], '')}", k) for k, v in mapa.items()
                    if not cod_ufs or k[:2] in cod_ufs), key=lambda x: x[0])
    return dict(itens)


def grafico_barras(tab, cat_col, n_col="n"):
    d = tab[[cat_col, n_col]].copy()
    d[cat_col] = d[cat_col].astype(str)
    ch = alt.Chart(d).mark_bar(cornerRadiusEnd=3).encode(
        x=alt.X(f"{n_col}:Q", title="n"),
        y=alt.Y(f"{cat_col}:N", sort="-x", title=None),
        tooltip=[cat_col, n_col])
    return ch.properties(height=max(120, 24 * len(d)))


def grafico_agregado(ag, por):
    d = ag.copy()
    x = por[0]
    d[x] = d[x].astype(str)
    temporal = any(s in x for s in ("ano", "mes", "competencia", "semana"))
    cor = {}
    if len(por) == 2:
        d[por[1]] = d[por[1]].astype(str)
        cor = {"color": alt.Color(f"{por[1]}:N", title=por[1])}
    if temporal:
        base = alt.Chart(d).mark_line(point=True).encode(
            x=alt.X(f"{x}:O", title=x), y=alt.Y("n:Q", scale=alt.Scale(zero=True)),
            tooltip=list(d.columns), **cor)
    else:
        base = alt.Chart(d).mark_bar().encode(
            y=alt.Y(f"{x}:N", sort="-x", title=None), x=alt.X("n:Q", stack=True),
            tooltip=list(d.columns), **cor).properties(height=max(150, 22 * d[x].nunique()))
    return base


@st.cache_data(ttl=3600, show_spinner="Consultando o FTP do DATASUS...")
def disponibilidade(sistema, tipo, uf):
    cli = ClienteFTP(PASTA_CACHE, log=lambda *_: None)
    try:
        return periodos_disponiveis(cli, sistema, tipo, uf)
    finally:
        cli.fechar()


# ================================================================= cabeçalho
st.title("📊 DATASUS para Pesquisa")
st.caption("Busque microdados do DATASUS e receba a base tratada, o dicionário, a tabela descritiva e a "
           f"citação prontos para o seu trabalho científico · v{__version__}")

aba_busca, aba_bases, aba_disp, aba_ajuda = st.tabs(
    ["🔎 Nova busca", "📂 Minhas bases", "📅 Disponibilidade", "❓ Ajuda"])


# ================================================================= visualização de uma base
def mostrar_base(nome, meta, chave):
    pasta = os.path.join(PASTA_PROCESSADOS, nome)
    prelim = sorted({a["nome"] for a in meta["arquivos"] if a["status"] == "preliminar"})

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Registros", fmt(meta["n_registros"]))
    c2.metric("Variáveis", meta["n_variaveis"])
    c3.metric("Arquivos de origem", len(meta["arquivos"]))
    c4.metric("Acesso em", "/".join(reversed(meta["data_acesso"][:10].split("-"))))
    if prelim:
        st.warning(f"Contém dados **preliminares** (podem mudar até o fechamento oficial): {', '.join(prelim)}")
    if meta.get("ausentes"):
        st.info("Períodos não encontrados no FTP: " + ", ".join(meta["ausentes"]))

    caminho = arquivo_base(pasta)
    if not caminho:
        st.error("Esta base não tem arquivo .parquet; gere novamente incluindo o formato parquet.")
        return
    mtime = os.path.getmtime(caminho)
    n_reg, todas, numericas_pq = esquema_base(caminho, mtime)

    t_dados, t_desc, t_agreg, t_dic, t_cit, t_arq = st.tabs(
        ["Dados", "Tabela descritiva", "Agregar / gráfico", "Dicionário", "Citação e Métodos", "Arquivos"])

    with t_dados:
        derivadas = [c for c in todas if not c.isupper() and not c.startswith("_")]
        so_deriv = st.toggle("Mostrar só variáveis tratadas (derivadas)", value=bool(derivadas), key=f"tg{chave}")
        cols = derivadas if so_deriv and derivadas else list(todas)
        with st.expander(f"Escolher colunas ({len(cols)} selecionadas)"):
            cols = st.multiselect("Colunas", list(todas), default=cols, key=f"cols{chave}",
                                  placeholder="Escolha as colunas")
        st.dataframe(previa_base(caminho, mtime)[cols], width="stretch", height=420)
        st.caption(f"Mostrando até 2.000 de {fmt(n_reg)} registros.")

    with t_desc:
        p = os.path.join(pasta, "tabela_descritiva.xlsx")
        if os.path.exists(p):
            cat = pd.read_excel(p, sheet_name="categoricas")
            num = pd.read_excel(p, sheet_name="numericas")
            if "variavel" in cat:
                st.subheader("Variáveis categóricas")
                vars_cat = list(dict.fromkeys(cat["variavel"]))
                escolha = st.selectbox("Variável", vars_cat,
                                       format_func=lambda v: f"{_rotulo(v)} ({v})", key=f"vc{chave}")
                sub = cat[cat["variavel"] == escolha][["categoria", "n", "pct"]].rename(
                    columns={"categoria": "Categoria", "pct": "%"})
                a, b = st.columns([1, 1])
                a.dataframe(sub, hide_index=True, width="stretch")
                b.altair_chart(grafico_barras(sub, "Categoria"), width="stretch")
                with st.expander("Ver todas as categóricas"):
                    st.dataframe(cat, hide_index=True, width="stretch")
            if "variavel" in num:
                st.subheader("Variáveis numéricas")
                st.dataframe(num, hide_index=True, width="stretch")

    with t_agreg:
        st.write("Monte contagens agregadas (ex.: óbitos por ano e UF) para estudos ecológicos, séries temporais ou taxas.")
        # nº de valores distintos vem do dicionário gerado no download (evita ler a base inteira)
        p_dic = os.path.join(pasta, "dicionario_variaveis.csv")
        distintos = {}
        if os.path.exists(p_dic):
            dic_ = pd.read_csv(p_dic, encoding="utf-8-sig", usecols=["variavel", "n_distintos"])
            distintos = dict(zip(dic_["variavel"], dic_["n_distintos"]))
        candidatas = [c for c in todas if distintos.get(c, 0) <= 6000 and not c.startswith("_arquivo")]
        sugest = [c for c in ("ano_obito", "ano_nascimento", "ano_internacao", "ano_diagnostico", "ano_notificacao",
                              "competencia")
                  if c in candidatas][:1]
        por = st.multiselect("Agrupar por", candidatas, default=sugest, placeholder="Escolha variáveis",
                             format_func=lambda v: f"{v} – {_rotulo(v)}" if _rotulo(v) else v, key=f"por{chave}")
        numericas = [c for c in numericas_pq if not c.isupper()]
        somas = st.multiselect("Somar também (opcional)", numericas, key=f"soma{chave}",
                               placeholder="ex.: valor_total_rs, permanencia_dias")
        if por:
            df = colunas_base(caminho, mtime, tuple(dict.fromkeys(por + somas)))
            ag = df.groupby(por, dropna=False, observed=True).size().reset_index(name="n")
            if somas:
                ag = ag.merge(df.groupby(por, dropna=False, observed=True)[somas].sum().reset_index(), on=por)
            st.dataframe(ag, hide_index=True, width="stretch", height=min(400, 38 + 35 * len(ag)))
            if len(por) <= 2 and len(ag) <= 500:
                st.altair_chart(grafico_agregado(ag, por), width="stretch")
            elif len(por) > 2:
                st.caption("Gráfico disponível para até 2 variáveis de agrupamento.")
            st.download_button("⬇️ Baixar agregado (CSV)", ag.to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"agregado_{'_'.join(por)}.csv", mime="text/csv", key=f"dl{chave}")

    with t_dic:
        p = os.path.join(pasta, "dicionario_variaveis.csv")
        if os.path.exists(p):
            dic = pd.read_csv(p, encoding="utf-8-sig")
            filtro = st.text_input("Procurar variável", key=f"fd{chave}")
            if filtro:
                dic = dic[dic.apply(lambda r: filtro.lower() in " ".join(map(str, r.values)).lower(), axis=1)]
            st.dataframe(dic, hide_index=True, width="stretch", height=460,
                         column_config={"pct_faltantes": st.column_config.ProgressColumn(
                             "% faltantes", min_value=0, max_value=100, format="%.1f%%")})

    with t_cit:
        p = os.path.join(pasta, "LEIA-ME.md")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                st.markdown(fh.read())

    with t_arq:
        st.write(f"Pasta: `{pasta}`")
        if st.button("📁 Abrir pasta no Explorador", key=f"ab{chave}"):
            os.startfile(pasta)
        for f in sorted(os.listdir(pasta)):
            fp = os.path.join(pasta, f)
            tam = os.path.getsize(fp)
            a, b = st.columns([3, 1])
            a.write(f"**{f}** · {tam / 1e6:.1f} MB")
            if tam < 200e6:
                with open(fp, "rb") as fh:
                    b.download_button("Baixar", fh.read(), file_name=f, key=f"f{chave}{f}")
            else:
                b.caption("grande: abra a pasta")


# ================================================================= aba: nova busca
with aba_busca:
    col_form, col_info = st.columns([3, 2], gap="large")
    with col_form:
        sistema = st.selectbox("Sistema de informação", list(SISTEMAS), format_func=lambda s: ROTULO_SISTEMA[s])
        fonte = SISTEMAS[sistema]

        tipo = None
        if fonte["tipos"]:
            opcoes = list(fonte["tipos"])
            idx = opcoes.index(fonte["tipo_padrao"]) if fonte["tipo_padrao"] in opcoes else None
            tipo = st.selectbox("Agravo" if sistema == "SINAN" else "Tipo de arquivo", opcoes, index=idx,
                                format_func=lambda t: f"{t} – {fonte['tipos'][t]}",
                                placeholder="Escolha...")

        rot_uf = "UFs" if fonte["por_uf"] else "Filtrar por UF de residência (opcional; vazio = Brasil)"
        r1, r2 = st.columns([3, 2])
        regiao = r2.selectbox("Atalho por região", ["—", "Brasil (todas)", *REGIOES_UF], key="regiao")
        if regiao != st.session_state.get("_regiao_ant"):
            st.session_state["_regiao_ant"] = regiao
            if regiao == "Brasil (todas)":
                st.session_state["ufs"] = list(UFS)
            elif regiao in REGIOES_UF:
                st.session_state["ufs"] = REGIOES_UF[regiao]
        ufs = r1.multiselect(rot_uf, list(UFS), format_func=lambda u: f"{u} – {NOMES_UF[u]}", key="ufs",
                             placeholder="Escolha uma ou mais UFs")

        anual = fonte["periodicidade"] == "anual"
        ano_min = {"SIH": 2008, "SIA": 2008, "CNES": 2005, "SINAN": 2007}.get(sistema, 1996)
        padrao = (ANO_ATUAL - 3, ANO_ATUAL - 2) if anual else (ANO_ATUAL - 1, ANO_ATUAL - 1)
        anos_sel = st.slider("Período (anos)", ano_min, ANO_ATUAL, padrao)
        anos = list(range(anos_sel[0], anos_sel[1] + 1))
        meses = None
        if not anual:
            m_sel = st.select_slider("Meses (competência)", options=list(range(1, 13)), value=(1, 12),
                                     format_func=lambda m: MESES[m - 1])
            meses = list(range(m_sel[0], m_sel[1] + 1))

        with st.expander("Filtros e opções avançadas"):
            cids = None
            if sistema in ("SIM", "SIM-NAC", "SIH", "SIA"):
                campo = {"SIM": "causa básica", "SIM-NAC": "causa básica", "SIH": "diagnóstico principal",
                         "SIA": "CID principal"}[sistema]
                ops_cid = opcoes_cid()
                sel_cid = st.multiselect(
                    f"CID-10 ({campo})", list(ops_cid), placeholder="Todas – digite código ou nome para buscar",
                    help="Escolha grupos prontos (ex.: suicídio, AVC), capítulos inteiros ou categorias. "
                         "Pode combinar várias opções.")
                if sel_cid:
                    cids = [p for s in sel_cid for p in ops_cid[s].split(",")]
                    exp = expandir_cids(cids)
                    st.caption(f"{len(exp)} categoria(s) CID-10: {', '.join(exp[:25])}{' ...' if len(exp) > 25 else ''}")
            procedimentos = None
            if sistema in ("SIH", "SIA"):
                ops_proc = opcoes_procedimentos()
                if ops_proc:
                    sel_proc = st.multiselect(
                        "Procedimento realizado (SIGTAP)", list(ops_proc),
                        placeholder="Todos – digite código ou nome (ex.: transplante de rim)",
                        help="Grupos, subgrupos, formas de organização ou procedimentos da Tabela SUS (SIGTAP). "
                             "Ex.: 05.05.02.009-2 Transplante de rim (doador falecido).")
                    procedimentos = [ops_proc[s] for s in sel_proc] or None
                else:
                    st.caption("Tabela SIGTAP indisponível no momento (sem conexão com o FTP do DATASUS).")
            ufs_res = []
            if fonte["por_uf"]:
                ufs_res = st.multiselect("Manter só residentes nas UFs (opcional)", list(UFS),
                                         format_func=lambda u: f"{u} – {NOMES_UF[u]}", placeholder="Todas")
            mapa_mun = opcoes_municipios(tuple(ufs_res or ufs))
            sel_mun = st.multiselect("Manter só residentes nos municípios (opcional)", list(mapa_mun),
                                     placeholder="Todos – digite o nome para buscar")
            municipios = [mapa_mun[m] for m in sel_mun] or None

            campos = campos_em_cache(sistema, tipo)
            colunas = None
            if campos:
                colunas = st.multiselect("Ler apenas estas variáveis originais (opcional, economiza memória)",
                                         campos, format_func=descricao_campo, placeholder="Todas as variáveis")
                colunas = colunas or None
            else:
                st.caption("Ler apenas algumas variáveis originais (opcional, economiza memória):")
                if st.button("📋 Carregar lista de variáveis deste sistema",
                             disabled=bool(fonte["tipos"] and not tipo)):
                    with st.spinner("Lendo as variáveis de um arquivo de referência no FTP..."):
                        try:
                            campos_disponiveis(sistema, tipo, log=lambda *_: None)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Não foi possível obter as variáveis: {e}")
            formatos = st.multiselect("Formatos de saída", ["parquet", "csv", "xlsx", "dta"],
                                      default=["parquet", "csv"],
                                      help="parquet é sempre gerado (necessário para visualizar aqui). "
                                           "dta = Stata; xlsx só até 1 milhão de linhas.")
            a, b = st.columns(2)
            somente_finais = a.checkbox("Somente dados finais (sem preliminares)")
            sem_derivadas = b.checkbox("Sem variáveis derivadas")
            modo_leve = a.checkbox("Modo leve (só variáveis essenciais)",
                                   help="Recomendado para bases grandes (ex.: SIH do Brasil inteiro): lê apenas as "
                                        "variáveis mais usadas em pesquisa, reduzindo tempo e memória.")
            sem_brutos = b.checkbox("Apagar arquivos brutos após ler",
                                    help="Economiza disco, mas uma nova busca do mesmo período precisará baixar de novo.")
            nome = st.text_input("Nome da pasta de saída (opcional)", placeholder="automático")

        formatos = list(dict.fromkeys(["parquet", *formatos]))
        if colunas:
            from datasus_ciencia.tratamento import COLUNA_CID, COLUNA_MUN_RES, COLUNA_PROC
            necessarias = [c for c in (COLUNA_CID.get(sistema) if cids else None,
                                       COLUNA_PROC.get(sistema) if procedimentos else None,
                                       COLUNA_MUN_RES.get(sistema) if (municipios or ufs_res) else None)
                           if c and c not in colunas]
            if necessarias:
                colunas = colunas + necessarias
                st.caption(f"Incluídas automaticamente por causa dos filtros: {', '.join(necessarias)}")

        pronto = (not fonte["tipos"] or tipo) and (ufs or not fonte["por_uf"])
        if pronto:
            comando = montar_comando(sistema, tipo, ufs, anos, meses, cids, ufs_res, municipios, colunas,
                                     formatos, nome or None, somente_finais, sem_derivadas,
                                     procedimentos=procedimentos, modo_leve=modo_leve)
            st.code(comando + (" --sem-brutos" if sem_brutos else ""), language="bash")
            est = estimar_download(sistema, tipo, tuple(ufs), tuple(anos), tuple(meses or []), somente_finais)
            if est:
                n_arq, total, falta = est
                min_est = falta / 2e6 / 60 + n_arq * (0.02 if (cids or procedimentos) else 0.15)
                st.caption(f"📦 {n_arq} arquivo(s) · {total / 1e9:.2f} GB no total · "
                           f"**{falta / 1e9:.2f} GB a baixar** (o restante já está em cache) · "
                           f"tempo estimado: ~{max(1, round(min_est))} min")
                if n_arq > 300:
                    st.warning("Pedido grande. Recomendado: **Modo leve** e filtros (CID/procedimento). "
                               "Mantenha esta página aberta até terminar; para algo muito grande, rode o "
                               "comando acima no terminal (`.\\datasus.bat ...`), que não depende do navegador.")
        buscar = st.button("🚀 Buscar e organizar dados", type="primary", disabled=not pronto,
                           width="stretch")

    with col_info:
        st.markdown(f"#### {fonte['nome']}")
        st.write(fonte["descricao"])
        st.write(f"**Periodicidade:** {fonte['periodicidade']}" + ("" if fonte["por_uf"] else " · arquivo nacional"))
        st.markdown(
            "**Você vai receber:**\n"
            "- base tratada (originais em MAIÚSCULAS + derivadas em minúsculas)\n"
            "- dicionário de variáveis com % de faltantes\n"
            "- tabela descritiva (base para a Tabela 1)\n"
            "- metadados com URLs e hash MD5 (reprodutibilidade)\n"
            "- citação ABNT/Vancouver e texto para Métodos")
        if not pronto:
            st.info("Escolha " + ("o tipo/agravo e " if fonte["tipos"] and not tipo else "")
                    + ("ao menos uma UF " if fonte["por_uf"] and not ufs else "") + "para continuar.")

    if buscar:
        barra = st.progress(0.0, text="Iniciando...")
        status = st.status("Executando...", expanded=True)
        caixa_log = status.empty()
        linhas = []

        def log(msg):
            linhas.append(str(msg))
            caixa_log.code("\n".join(linhas[-14:]), language=None)

        try:
            pasta, meta = executar(
                sistema, anos, ufs=ufs, tipo=tipo, meses=meses, cids=cids, ufs_residencia=ufs_res,
                municipios=municipios, colunas=colunas, formatos=formatos, nome=nome or None,
                somente_finais=somente_finais, sem_derivadas=sem_derivadas, log=log,
                progresso=lambda f, t: barra.progress(min(f, 1.0), text=t),
                procedimentos=procedimentos, modo_leve=modo_leve, guardar_brutos=not sem_brutos)
            status.update(label=f"Concluído: {fmt(meta['n_registros'])} registros", state="complete", expanded=False)
            st.session_state["base_atual"] = os.path.basename(pasta)
        except ErroPedido as e:
            status.update(label="Nada encontrado", state="error")
            st.error(f"{e} Veja a aba **Disponibilidade** para conferir os períodos existentes.")
        except Exception as e:
            status.update(label="Erro", state="error")
            st.exception(e)

    if st.session_state.get("base_atual"):
        nome_b = st.session_state["base_atual"]
        p = os.path.join(PASTA_PROCESSADOS, nome_b, "metadados.json")
        if os.path.exists(p):
            st.divider()
            a, b = st.columns([3, 1])
            a.subheader(f"Resultado: {nome_b}")
            if b.button("📈 Analisar esta base", type="primary", width="stretch"):
                st.switch_page("paginas/analise.py")
            with open(p, encoding="utf-8") as fh:
                mostrar_base(nome_b, json.load(fh), "atual")


# ================================================================= aba: minhas bases
with aba_bases:
    bases = bases_processadas()
    if not bases:
        st.info("Nenhuma base ainda. Faça uma busca na aba **Nova busca**.")
    else:
        resumo = pd.DataFrame([{
            "Base": n, "Sistema": m["sistema"], "Tipo": m.get("tipo") or "",
            "UFs": ", ".join(m.get("ufs") or m.get("ufs_residencia") or ["BR"]),
            "Anos": f"{min(m['anos'])}–{max(m['anos'])}", "Registros": m["n_registros"],
            "CID": " ".join(m.get("cids") or []), "Acesso": m["data_acesso"][:10],
            "Preliminar": any(a["status"] == "preliminar" for a in m["arquivos"]),
        } for n, m in bases])
        st.dataframe(resumo, hide_index=True, width="stretch",
                     column_config={"Registros": st.column_config.NumberColumn(format="%d")})
        a, b = st.columns([3, 1])
        escolha = a.selectbox("Abrir base", [n for n, _ in bases])
        meta = dict(bases)[escolha]
        b.write("")
        if b.button("📈 Analisar", width="stretch", key="analisar_lista"):
            st.session_state["base_atual"] = escolha
            st.switch_page("paginas/analise.py")
        mostrar_base(escolha, meta, "lista")


# ================================================================= aba: disponibilidade
with aba_disp:
    st.write("Consulte quais períodos existem no FTP do DATASUS antes de buscar.")
    a, b, c = st.columns(3)
    s_d = a.selectbox("Sistema", list(SISTEMAS), format_func=lambda s: ROTULO_SISTEMA[s], key="s_d")
    f_d = SISTEMAS[s_d]
    t_d = None
    if f_d["tipos"]:
        ops = list(f_d["tipos"])
        t_d = b.selectbox("Tipo/agravo", ops, index=ops.index(f_d["tipo_padrao"]) if f_d["tipo_padrao"] else 0,
                          format_func=lambda t: f"{t} – {f_d['tipos'][t]}", key="t_d")
    u_d = c.selectbox("UF", list(UFS), format_func=lambda u: f"{u} – {NOMES_UF[u]}", key="u_d") \
        if f_d["por_uf"] else None
    if st.button("Consultar"):
        itens = disponibilidade(s_d, t_d, u_d)
        if not itens:
            st.warning("Nenhum arquivo encontrado.")
        else:
            por_ano = defaultdict(lambda: {"final": set(), "preliminar": set()})
            for status, _uf, ano, mes, _n in itens:
                por_ano[ano][status].add(mes)
            linhas = []
            for ano in sorted(por_ano, reverse=True):
                d = por_ano[ano]
                for stt in ("final", "preliminar"):
                    if d[stt]:
                        ms = sorted(m for m in d[stt] if m)
                        linhas.append({"Ano": ano, "Situação": stt,
                                       "Meses": f"{len(ms)} ({MESES[ms[0]-1]}–{MESES[ms[-1]-1]})" if ms else "anual"})
            st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch")


# ================================================================= aba: ajuda
with aba_ajuda:
    st.markdown("""
### Como usar
1. Em **Nova busca**, escolha o sistema, as UFs e o período. Use os filtros avançados para CID-10, município ou colunas.
2. Clique em **Buscar e organizar dados**. Os arquivos são baixados do FTP oficial do DATASUS, tratados e salvos em `dados/processados/`.
3. Explore o resultado: dados, tabela descritiva, agregações com gráfico, dicionário e texto de citação/Métodos.
4. As bases ficam em **Minhas bases** para consultar depois. Os `.dbc` originais ficam em cache em `dados/brutos/`.

### Exemplos de busca
| Pergunta de pesquisa | Sistema | Filtros |
|---|---|---|
| Mortalidade por IAM | SIM | CID `I21 I22` |
| Suicídios | SIM | CID `X60-X84` |
| Prematuridade no Nordeste | SINASC | região Nordeste |
| Internações por AVC | SIH (RD) | CID `I60-I64` |
| Casos de dengue em PE | SINAN (DENG) | UF PE |

### Cuidados
- Anos recentes podem ser **preliminares** (sinalizados em amarelo).
- SIH: cada registro é uma AIH (internação), não um indivíduo.
- Consulte o dicionário oficial do DATASUS para variáveis originais não decodificadas.
- Também é possível usar a linha de comando (`datasus.bat`) ou pedir ao Claude em linguagem natural.
""")
