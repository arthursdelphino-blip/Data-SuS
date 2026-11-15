"""Página Indicadores: mortalidade infantil/materna, letalidade SIM ÷ SIH, mortalidade prematura por DCNT e razão
de mortalidade por sexo, juntando bases já baixadas (e a população do TabNet)."""

import io
import json
import os
from datetime import date

import pandas as pd
import streamlit as st

import interface_analise as IA
from datasus_ciencia import estatistica as E
from datasus_ciencia import indicadores as I
from datasus_ciencia.pipeline import PASTA_PROCESSADOS

COMANDO = {"SINASC": ".\\datasus.bat baixar SINASC --uf {uf} --anos {anos}",
           "SIH": ".\\datasus.bat baixar SIH --tipo RD --uf {uf} --anos {anos} --cid <CIDs> --leve",
           "SIM": ".\\datasus.bat baixar SIM --uf {uf} --anos {anos}",
           "SIM-NAC": ".\\datasus.bat baixar SIM-NAC --tipo DOFET --uf {uf} --anos {anos}"}


def _bases():
    out = []
    if not os.path.isdir(PASTA_PROCESSADOS):
        return out
    for n in sorted(os.listdir(PASTA_PROCESSADOS)):
        p = os.path.join(PASTA_PROCESSADOS, n, "metadados.json")
        pq = [f for f in os.listdir(os.path.join(PASTA_PROCESSADOS, n))
              if f.endswith(".parquet") and not f.startswith("agregado")] if os.path.exists(p) else []
        if pq:
            with open(p, encoding="utf-8") as fh:
                meta = json.load(fh)
            out.append({"nome": n, "sistema": meta["sistema"], "meta": meta,
                        "caminho": os.path.join(PASTA_PROCESSADOS, n, pq[0])})
    return out


# só as colunas que os indicadores usam: ler a base inteira (100+ colunas) estoura a memória em PCs de 8 GB
COLUNAS = ["ano_obito", "ano_nascimento", "ano_processamento", "ano_internacao", "ano_notificacao",
           "mun_residencia_cod_ibge6", "mun_residencia_nome", "mun_residencia_uf", "sexo", "idade_anos",
           "causa_basica", "CAUSABAS", "DIAG_PRINC", "diag_principal", "tipo_obito", "semanas_gestacao", "peso_g",
           "_status_dado", "ID_AGRAVO", "TRATAMENTO", "DT_DIAG", "CLASSI_FIN", "tipo_entrada_tb", "classificacao_final",
           # arquivo .dbc de origem: ao juntar bases, um mesmo arquivo do DATASUS entra uma vez só
           "_arquivo_origem"]


@st.cache_data(show_spinner="Carregando base...", max_entries=6)
def _ler_colunas(caminho, _mtime):
    import pyarrow.parquet as pq
    nomes = set(pq.read_schema(caminho).names)
    df = pd.read_parquet(caminho, columns=[c for c in COLUNAS if c in nomes])
    from datasus_ciencia.tratamento import variaveis_extras
    if "DT_DIAG" in df:  # SINAN: o TabNet conta casos pelo ano de diagnóstico
        dt = df["DT_DIAG"] if pd.api.types.is_datetime64_any_dtype(df["DT_DIAG"]) else \
            pd.to_datetime(df["DT_DIAG"].astype("string"), format="%Y%m%d", errors="coerce")
        df["ano_diagnostico"] = dt.dt.year.astype("Int64")
    return variaveis_extras(df)


def _tem_prelim(meta):
    """A base inclui arquivos preliminares? (o pipeline grava o status de cada arquivo em meta['arquivos'])."""
    return meta.get("preliminares") or any(a.get("status") == "preliminar" for a in meta.get("arquivos") or [])


def _ler(b):
    return _ler_colunas(b["caminho"], os.path.getmtime(b["caminho"]))


def _ano_col(df, sistema):
    if sistema == "SIH" and "ano_processamento" not in df:
        return "ano_internacao"
    if sistema == "SINAN" and "ano_diagnostico" in df and df["ano_diagnostico"].notna().mean() > 0.9:
        return "ano_diagnostico"
    return I.COL_ANO[sistema]


def _juntar(bases):
    """Concatena bases; quando duas bases trazem o mesmo arquivo do DATASUS (períodos sobrepostos), os registros
    desse arquivo entram uma vez só. (Comparar colunas não serve: dois bebês nascidos no mesmo dia, sexo e
    município são registros diferentes.)"""
    dfs = [_ler(b).assign(_sistema=b["sistema"]) for b in bases]
    if len(dfs) == 1:
        return dfs[0], 0
    vistos, partes, removidos = set(), [], 0
    for df in dfs:
        if "_arquivo_origem" in df:
            arq = df["_arquivo_origem"].astype("string").str.upper()
            rep = arq.isin(vistos).fillna(False)
            removidos += int(rep.sum())
            vistos |= set(arq.dropna().unique())
            df = df[~rep]
        partes.append(df)
    return pd.concat(partes, ignore_index=True), removidos


def _cobertura(candidatas, ufs, anos, cids=None):
    """Bases já baixadas que cobrem (UF, ano) do numerador → (bases usadas, {uf: [anos que faltam]}).
    Com `cids` (SIH na letalidade), só servem bases sem filtro de CID ou com filtro que contenha essas causas."""
    def serve(b):
        c = b["meta"].get("cids")
        return not (cids and c) or set(cids) <= set(IA.expandir_cids(c))

    usadas, coberto = [], set()
    for b in sorted(candidatas, key=lambda b: -len(b["meta"].get("anos") or [])):
        if not serve(b):
            continue
        ufs_b = set(b["meta"].get("ufs") or []) | set(b["meta"].get("ufs_residencia") or [])
        par = {(u, int(a)) for u in ufs_b for a in (b["meta"].get("anos") or []) if u in ufs and int(a) in anos}
        if par - coberto:
            usadas.append(b)
            coberto |= par
    faltam = {}
    for u in ufs:
        for a in anos:
            if (u, a) not in coberto:
                faltam.setdefault(u, []).append(a)
    return usadas, faltam


def _baixar(sistema, faltam, cids=None):
    """Baixa do FTP do DATASUS (mesma fonte do TabNet) os anos/UFs que faltam para o denominador."""
    from datasus_ciencia.pipeline import executar
    n_arq = sum(len(a) for a in faltam.values()) * (12 if sistema == "SIH" else 1)
    with st.status(f"Baixando o {sistema} que falta para o denominador ({n_arq} arquivo(s) do DATASUS)...",
                   expanded=True) as status:
        if sistema == "SIH":
            st.write(f"O SIH tem um arquivo por mês; leva cerca de 1 min por arquivo grande "
                     f"(~{max(1, n_arq // 2)}–{n_arq} min). Só as internações por {', '.join(cids or [])} são "
                     "guardadas.")
        barra = st.progress(0.0)
        ok = True
        for i, (uf, anos) in enumerate(sorted(faltam.items())):
            st.write(f"{sistema} {uf}: {_anos_txt(anos)}")
            try:
                executar(sistema, anos, ufs=[uf], tipo="RD" if sistema == "SIH" else None,
                         cids=cids if sistema == "SIH" else None, formatos=("parquet",), modo_leve=True,
                         guardar_brutos=False, log=lambda *_: None,
                         progresso=lambda f, t, i=i: barra.progress(min((i + f) / len(faltam), 1.0), text=t))
            except Exception as e:
                ok = False
                st.write(f"Falhou ({type(e).__name__}: {e}).")
        status.update(label="Denominador baixado." if ok else "Download do denominador incompleto.",
                      state="complete" if ok else "error", expanded=not ok)
    return ok


def _anos_txt(anos):
    """[2014, 2015, 2016, 2019] → '2014–2016, 2019'."""
    anos = sorted(int(a) for a in anos)
    blocos, ini = [], None
    for i, a in enumerate(anos):
        ini = a if ini is None else ini
        if i == len(anos) - 1 or anos[i + 1] != a + 1:
            blocos.append(f"{ini}–{a}" if a > ini else str(a))
            ini = None
    return ", ".join(blocos) or "–"


def _anos_cmd(anos):
    anos = sorted(int(a) for a in anos)
    return f"{anos[0]}-{anos[-1]}" if len(anos) > 1 else str(anos[0])


def _excel(abas):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for nome, t in abas.items():
            t.to_excel(xw, sheet_name=nome[:31], index=False)
    return buf.getvalue()


def pagina_indicadores():
    st.title("🧮 Indicadores")
    st.caption("Indicadores prontos de mortalidade e letalidade (definições do Ministério da Saúde/RIPSA), juntando "
               "as bases que você já baixou e a população do TabNet.")
    bases = _bases()
    por_sis = {}
    for b in bases:
        por_sis.setdefault(b["sistema"], []).append(b)

    disponiveis, faltam = {}, []
    for ch, d in I.INDICADORES.items():
        tem_num = any(I.serve_numerador(ch, b["sistema"], b["meta"].get("tipo")) for b in bases)
        if tem_num:  # o denominador (SINASC/SIH/população) é obtido automaticamente se faltar
            disponiveis[ch] = d
        else:
            faltam.append((d["nome"], ["SIM-NAC" if ch == "fetal" else d["num"][0]]))
    if not disponiveis:
        st.info("Nenhum indicador disponível: baixe primeiro a base do numerador (SIM, SINAN ou SIH) em "
                "**Buscar dados**; o denominador é obtido automaticamente.")
        return
    if faltam:
        with st.expander(f"Indicadores que precisam de outras bases ({len(faltam)})"):
            for nome, falta in faltam:
                cmds = "; ".join(f"`{COMANDO[s].format(uf='<UF>', anos='<AAAA-AAAA>')}`" for s in falta if s in COMANDO)
                txt = "SIM-NAC de óbitos fetais (DOFET)" if falta == ["SIM-NAC"] else ", ".join(falta)
                st.markdown(f"- **{nome}**: falta base do {txt}. {cmds}")

    ch = st.selectbox("Indicador", list(disponiveis), format_func=lambda c: disponiveis[c]["nome"], key="ind_ch")
    d = disponiveis[ch]
    st.caption(f"**Definição:** {d['def']}")

    # ---------------- numerador (o denominador é montado automaticamente a partir dele)
    c1, c2 = st.columns(2)

    def _nota(b):
        """Quanto maior, melhor a base para o numerador: mais anos e sem filtro de CID (na letalidade SIM ÷ SIH,
        com filtro de CID: o SIH a baixar fica bem menor)."""
        m = b["meta"]
        s = len(m.get("anos") or [])
        if ch == "letal_sim_sih":
            s += 1_000 * bool(m.get("cids"))
        else:
            s += 1_000 * (not m.get("cids"))
        return s

    cand = sorted([b for b in bases if I.serve_numerador(ch, b["sistema"], b["meta"].get("tipo"))],
                  key=_nota, reverse=True)
    op_num = [b["nome"] for b in cand]
    padrao_num = [op_num[0]]
    if ch in ("fetal", "perinatal"):  # sugere juntar a base de óbitos fetais
        fet = [b["nome"] for b in cand if "DOFET" in b["nome"].upper()]
        nao = [n for n in op_num if n not in fet]
        padrao_num = fet[:1] or [op_num[0]]
        if ch == "perinatal" and nao and fet:  # óbitos de 0–6 dias + fetais da MESMA UF (e mais anos em comum)
            ufs_de = lambda n: set(next(b for b in cand if b["nome"] == n)["meta"].get("ufs") or [])  # noqa: E731
            pares = [(n, f) for n in nao for f in fet if ufs_de(n) & ufs_de(f)]
            padrao_num = list(pares[0]) if pares else [nao[0]]
    k_num = f"ind_num_{ch}"
    if k_num in st.session_state:  # escolha antiga que deixou de servir (ex.: DOFET na mortalidade infantil)
        valido = [n for n in st.session_state[k_num] if n in op_num]
        if valido != st.session_state[k_num]:
            st.session_state[k_num] = valido
    sel_num = c1.multiselect("Base(s) do numerador", op_num, default=padrao_num, key=f"ind_num_{ch}",
                             help="Pode juntar mais de uma (ex.: SIM + óbitos fetais do SIM-NAC). Registros repetidos "
                                  "de bases com períodos sobrepostos são removidos.")
    if not sel_num:
        st.info("Escolha a base do numerador.")
        return
    b_num = [b for b in bases if b["nome"] in sel_num]
    if ch == "perinatal":
        fetais = [(b["meta"].get("tipo") or "").upper() == "DOFET" for b in b_num]
        if all(fetais):
            st.warning("Só óbitos fetais no numerador: faltam os óbitos de 0 a 6 dias (base do SIM ou SIM-NAC DOINF).")
        elif not any(fetais):
            st.warning("Sem óbitos fetais no numerador: junte a base do SIM-NAC DOFET (`"
                       + COMANDO["SIM-NAC"].format(uf="<UF>", anos="<AAAA-AAAA>") + "`).")
    num_df, dup = _juntar(b_num)
    if dup:
        st.caption(f"{IA.fmt(dup)} registro(s) repetido(s) entre as bases do numerador foram removidos.")
    sis_num = b_num[0]["sistema"]
    ano_num = _ano_col(num_df, sis_num)

    # ---------------- CID (letalidade SIM ÷ SIH): define também o que baixar do SIH
    cid_spec, desc_cid = None, None
    if ch == "letal_sim_sih":
        col_c = "CAUSABAS" if "CAUSABAS" in num_df else I.COL_CID[sis_num]
        prefs, desc_cid = IA.seletor_cid(c1, "Causa (CID-10) – a mesma no SIM e no SIH", num_df, col_c,
                                         "ind_" + "_".join(sel_num), "ind_cid")
        if not prefs:
            st.info("Escolha a causa.")
            return
        cid_spec = ",".join(prefs)

    # ---------------- denominador automático: mesmas UFs e anos do numerador; o que faltar é baixado do DATASUS
    den_df, b_den, ano_den = None, None, None
    faltam = {}
    if d["den"] == "POP":
        c2.markdown("**Denominador:** população do TabNet (MS/SVSA) – mesmos anos e UFs do numerador.")
    else:
        sis_den = d["den"]
        ufs_b = [set(b["meta"].get("ufs") or []) for b in b_num]
        if ch == "perinatal" and len(ufs_b) > 1:  # fetais + 0–6 dias: só as UFs com as duas partes
            ufs_b = [set.intersection(*ufs_b)]
        ufs_alvo = sorted(set().union(*ufs_b) & set(IA.UFS)) or \
            sorted(num_df["mun_residencia_uf"].dropna().value_counts().index[:1])
        anos_alvo = sorted(int(a) for a in num_df[ano_num].dropna().unique())
        cids_alvo = sorted(IA.expandir_cids(cid_spec.split(","))) if cid_spec else None
        usadas, faltam = _cobertura(por_sis.get(sis_den, []), ufs_alvo, anos_alvo, cids_alvo)
        if faltam:
            # os períodos têm de corresponder: oferece baixar exatamente o que falta do denominador
            n_arq = sum(len(a) for a in faltam.values()) * (12 if sis_den == "SIH" else 1)
            tempo = "alguns segundos por ano" if sis_den != "SIH" else f"cerca de {max(1, n_arq // 2)}–{n_arq} min"
            txt = "; ".join(f"{u} {_anos_txt(a)}" for u, a in sorted(faltam.items()))
            st.warning(f"**Para o denominador ficar no mesmo período do numerador, falta o {sis_den} de {txt}.** "
                       + ("Até baixar, o indicador é calculado só nos anos que já existem nas duas bases."
                          if usadas else "Baixe para calcular o indicador."))
            if st.button(f"⬇️ Baixar {sis_den} {txt} do DATASUS ({n_arq} arquivo(s), {tempo})", type="primary",
                         key=f"dl_{ch}"):
                if _baixar(sis_den, faltam, cids_alvo):
                    st.rerun()
        if not usadas:
            return
        den_df, dup_d = _juntar(usadas)
        uniao = lambda k: sorted({x for b in usadas for x in (b["meta"].get(k) or [])})  # noqa: E731
        b_den = {"nome": ", ".join(b["nome"] for b in usadas), "sistema": sis_den,
                 "meta": {"ufs": uniao("ufs"), "ufs_residencia": uniao("ufs_residencia"), "anos": uniao("anos"),
                          "cids": usadas[0]["meta"].get("cids"),
                          "preliminares": any(_tem_prelim(b["meta"]) for b in usadas)}}
        ano_den = _ano_col(den_df, sis_den)
        c2.markdown(f"**Denominador:** {sis_den} – {', '.join(ufs_alvo)}, {_anos_txt(anos_alvo)} (mesmo período "
                    "do numerador; obtido automaticamente do DATASUS).")
        c2.caption("Bases usadas: " + ", ".join(b["nome"] for b in usadas)
                   + (f" · {IA.fmt(dup_d)} registro(s) repetido(s) removidos" if dup_d else ""))

    # ---------------- recorte comum
    anos = I.anos_em_comum(num_df[ano_num], den_df[ano_den]) if den_df is not None else \
        sorted(int(a) for a in num_df[ano_num].dropna().unique())
    if not anos:
        st.error("As bases do numerador e do denominador não têm nenhum ano em comum.")
        return
    so_num = sorted(set(int(a) for a in num_df[ano_num].dropna().unique()) - set(anos))
    if den_df is not None:
        so_den = sorted(set(int(a) for a in den_df[ano_den].dropna().unique()) - set(anos))
        if so_num and not faltam:  # baixado, mas o DATASUS não tem esses anos
            st.warning(
                f"**O DATASUS ainda não tem {d['den']} para {_anos_txt(so_num)}.** Para numerador e "
                f"denominador ficarem no mesmo período, esses anos saem também do numerador: o indicador é "
                f"calculado em {_anos_txt(anos)}.")
        if so_den:
            st.caption(f"Anos só no denominador (sem numerador, ignorados): {_anos_txt(so_den)}.")
    f1, f2, f3 = st.columns([2, 2, 1.4])
    if len(anos) > 1:
        a1, a2 = f1.slider("Período", anos[0], anos[-1], (anos[0], anos[-1]), key=f"ind_anos_{ch}")
        anos = [a for a in anos if a1 <= a <= a2]
    else:
        f1.markdown(f"**Período:** {anos[0]}")
    ufs_num = set(num_df["mun_residencia_uf"].dropna().unique()) if "mun_residencia_uf" in num_df else set()
    ufs_den = set(den_df["mun_residencia_uf"].dropna().unique()) if den_df is not None and \
        "mun_residencia_uf" in den_df else ufs_num
    ufs_meta = set(b_num[0]["meta"].get("ufs") or []) & set(IA.UFS)
    ufs = sorted((ufs_num & ufs_den) & (ufs_meta or ufs_num))
    if not ufs:
        st.error("As bases do numerador e do denominador não têm UF de residência em comum "
                 f"(numerador: {', '.join(sorted(ufs_meta or ufs_num)[:5]) or '–'}; denominador: "
                 f"{', '.join(sorted(ufs_den)[:5]) or '–'}). Escolha bases da mesma UF.")
        return
    sel_uf = f2.multiselect("UF de residência", ufs, key=f"ind_uf_{ch}", placeholder="Todas") if len(ufs) > 1 else []
    ufs_usadas = sel_uf or ufs
    niveis = ["Total"] + (["UF de residência"] if len(ufs_usadas) > 1 else []) + ["Município de residência"]
    nivel = f3.radio("Desagregar por", niveis, key=f"ind_nivel_{ch}") if ch != "razao_sexo" else "Total"

    def recorte(df, col_ano):
        m = df[col_ano].isin(anos)
        if "mun_residencia_uf" in df and ufs_usadas:
            m &= df["mun_residencia_uf"].isin(ufs_usadas)
        return df[m]

    num_df = recorte(num_df, ano_num)
    if den_df is not None:
        den_df = recorte(den_df, ano_den)

    # ---------------- agrupar anos (biênios, triênios...): soma numeradores e denominadores do período
    tamanhos = {"Ano a ano": 1, "Biênios": 2, "Triênios": 3, "Quadriênios": 4, "Quinquênios": 5}
    ops_g = [k_ for k_, n_ in tamanhos.items() if n_ == 1 or len(anos) >= 2 * n_]
    agrup = st.radio("Agrupar anos", ops_g, horizontal=True, key=f"ind_agrup_{ch}",
                     help="Junta anos consecutivos a partir do primeiro ano do período: soma os casos/óbitos e os "
                          "denominadores (população = pessoas-ano) de cada bloco. Útil quando há poucos eventos "
                          "por ano (municípios pequenos, mortalidade materna).") if len(ops_g) > 1 else "Ano a ano"
    n_g = tamanhos[agrup]
    inicio = {a: anos[0] + ((a - anos[0]) // n_g) * n_g for a in anos}
    blocos = {}
    for a, s_ in inicio.items():
        blocos.setdefault(s_, []).append(a)
    rotulo = {s_: (f"{min(v)}–{max(v)}" if len(v) > 1 else str(v[0])) for s_, v in blocos.items()}
    incompletos = [rotulo[s_] for s_, v in blocos.items() if len(v) < n_g]
    num_df = num_df.assign(_ano_orig=num_df[ano_num])
    if n_g > 1:
        num_df = num_df.assign(**{ano_num: num_df[ano_num].map(inicio)})
        if den_df is not None:
            den_df = den_df.assign(**{ano_den: den_df[ano_den].map(inicio)})
        if incompletos:
            st.caption(f"Período incompleto (menos de {n_g} anos): {', '.join(incompletos)} – compare com cautela.")
    anos_calc = sorted(blocos) if n_g > 1 else anos
    nome_tempo = "período" if n_g > 1 else "ano"

    def com_rotulo(tab):
        """Troca o ano inicial do bloco pelo rótulo do período (ex.: 2014–2016)."""
        if n_g == 1 or "ano" not in tab:
            return tab
        tab = tab.copy()
        tab.insert(0, "período", tab["ano"].map(rotulo))
        return tab.drop(columns="ano")


    # ---------------- recorte de causa, sexo e idade (taxas por população: a população é filtrada igual)
    so_novos = sem_desc = False
    idade_min, idade_max, sexo_sel = (30, 69, None) if ch == "dcnt" else (None, None, None)
    if d.get("por_pop"):
        o1, o2, o3 = st.columns([2, 1, 2])
        if ch in ("tx_mort", "tx_intern"):
            col_c = "CAUSABAS" if "CAUSABAS" in num_df else ("DIAG_PRINC" if "DIAG_PRINC" in num_df else
                                                               I.COL_CID[sis_num])
            prefs, desc_cid = IA.seletor_cid(o1, "Causa (CID-10) – vazio = todas", num_df, col_c,
                                             "ind_" + "_".join(sel_num), f"ind_cid_{ch}")
            cid_spec = ",".join(prefs) if prefs else None
            if b_num[0]["meta"].get("cids"):
                o1.caption(f"Base baixada só com CID {', '.join(b_num[0]['meta']['cids'])}: a taxa \"geral\" é "
                           "a desse grupo de causas.")
        else:
            if "tipo_entrada_tb" in num_df and (num_df["tipo_entrada_tb"] == "Caso novo").any():
                so_novos = o1.checkbox("Só casos novos (definição do MS para tuberculose)", value=True,
                                       key="ind_novos")
            if "classificacao_final" in num_df and (num_df["classificacao_final"] == "Descartado").any():
                sem_desc = o1.checkbox("Excluir casos descartados", value=True, key="ind_desc")
        sx = [s for s in ("Masculino", "Feminino") if "sexo" in num_df and (num_df["sexo"] == s).any()]
        if len(sx) == 2:
            esc = o2.radio("Sexo", ["Ambos"] + sx, key=f"ind_sexo_{ch}")
            sexo_sel = None if esc == "Ambos" else esc
        if "idade_anos" in num_df:
            i1_, i2_ = o3.slider("Idade (anos; 80 = 80 ou mais)", 0, 80, (0, 80), key=f"ind_idade_{ch}")
            if (i1_, i2_) != (0, 80):
                idade_min, idade_max = i1_, i2_
        if sexo_sel:
            num_df = num_df[num_df["sexo"] == sexo_sel]
        if idade_min is not None:
            ida_n = pd.to_numeric(num_df["idade_anos"], errors="coerce")
            num_df = num_df[(ida_n >= idade_min) & ((ida_n < idade_max + 1) | (idade_max >= 80))]
        sem_res = int(num_df["mun_residencia_cod_ibge6"].isna().sum()) if "mun_residencia_cod_ibge6" in num_df \
            else 0
        if sem_res:
            st.caption(f"{IA.fmt(sem_res)} registro(s) sem município de residência ficam fora do numerador.")

    mult = d["mult"]
    abas, avisos = {}, []
    pop = None
    if d["den"] == "POP":
        try:
            pop = IA._pop_svs(tuple(ufs_usadas), tuple(anos))
        except MemoryError:
            st.error("Memória insuficiente para carregar a população do TabNet. Feche outros programas ou "
                     "escolha um recorte menor (menos UFs ou anos).")
            return
        except Exception as e:
            st.error(f"População do TabNet indisponível ({type(e).__name__}: {e}).")
            return
        if pop is None or not len(pop):
            st.error("População do TabNet indisponível para essas UFs e anos.")
            return
        pop = pop[pop["uf"].isin(ufs_usadas)] if ufs_usadas else pop
        sem_pop = sorted(set(anos) - set(int(a) for a in pop["ano"].unique()))
        if sem_pop:  # mesmo período no numerador e no denominador: anos sem população saem do cálculo
            st.warning(f"**A população do TabNet ainda não tem {_anos_txt(sem_pop)}.** O indicador é calculado só "
                       f"em {_anos_txt(sorted(set(anos) - set(sem_pop)))}, para numerador e denominador ficarem "
                       "no mesmo período.")
            anos = [a for a in anos if a not in sem_pop]
            if not anos:
                return
            num_df = num_df[num_df["_ano_orig"].isin(anos)]
        if ch != "razao_sexo":  # população no mesmo recorte de sexo e idade do numerador
            if sexo_sel:
                pop = pop[pop["sexo"] == sexo_sel]
            if idade_min is not None:
                pop = pop[(pop["idade"].astype(int) >= idade_min) & (pop["idade"].astype(int) <= idade_max)]
        if n_g > 1:  # população somada no bloco = pessoas-ano
            pop = pop.assign(ano=pop["ano"].astype(int).map(inicio))
            pop = pop[pop["ano"].notna()]
    anos_calc = sorted({inicio[a] for a in anos}) if n_g > 1 else anos
    anos_todos, anos = anos, anos_calc

    # ---------------- cálculo
    if ch == "razao_sexo":
        pad = st.toggle("Padronizar por idade (OMS)", key="ind_rs_pad")
        ob = num_df[~I._fetal(num_df) & num_df["sexo"].isin(["Masculino", "Feminino"])]
        t = I.razao_por_sexo(ob, pop, ano_num, anos, padronizar=pad)
        if t.empty:
            st.warning("Sem dados suficientes.")
            return
        tot = I.razao_por_sexo(ob.assign(_a=0), pop.assign(ano=0), "_a", [0], padronizar=pad).iloc[0] \
            if not pad else None
        m1, m2 = st.columns(2)
        if tot is not None:
            m1.metric("Razão M/F no período", IA.fmt(tot["razão M/F"], 2),
                      help=f"IC95% {IA.fmt(tot['ic95_inf'], 2)}–{IA.fmt(tot['ic95_sup'], 2)}")
        g = com_rotulo(t.rename(columns={"razão M/F": "razao"}))
        st.altair_chart(IA.g_linha(g[[nome_tempo, "razao", "ic95_inf", "ic95_sup"]], nome_tempo, "razao",
                                   titulo_y="Razão M/F", banda=("ic95_inf", "ic95_sup")), width="stretch")
        st.dataframe(com_rotulo(t), hide_index=True, width="stretch")
        abas["Razão por sexo"] = com_rotulo(t)
        r = E.prais_winsten(t["ano"], t["razão M/F"]) if len(t) >= 4 and n_g == 1 else None
        serie = None
    else:
        mask = I.selecionar_numerador(ch, num_df, sis_num, cid_spec, so_novos=so_novos, sem_descartados=sem_desc)
        if ch in ("fetal", "perinatal") and not I._fetal(num_df).any():
            st.warning("A base do numerador não tem óbitos fetais. Junte uma base de óbitos fetais (SIM-NAC, tipo "
                       "DOFET) da mesma UF e período: `" + COMANDO["SIM-NAC"].format(
                           uf=",".join(ufs_usadas) or "<UF>", anos=f"{anos_todos[0]}-{anos_todos[-1]}") + "`")
            if ch == "fetal":
                return
        num = I.contar(num_df, ano_num, nivel, mask)
        if d["den"] == "POP":
            den = I.populacao_por(pop, nivel)  # pop já recortada em sexo/idade
        else:
            den = I.contar(den_df, ano_den, nivel)
            if ch in ("fetal", "perinatal"):
                # mesmo critério do numerador (≥22 semanas ou ≥500 g): sem isso o denominador fica inflado
                fet = I.contar(num_df, ano_num, nivel, I._fetal_viavel(num_df))
                chaves = [c for c in den.columns if c != "n"]
                den = den.merge(fet, on=[c for c in chaves if c in fet], how="outer", suffixes=("", "_f"))
                den["n"] = den["n"].fillna(0) + den["n_f"].fillna(0)
                den = den.drop(columns="n_f")
        t = I.combinar(num, den, nivel, mult, anos)
        serie = I.combinar(I.contar(num_df, ano_num, "Total", mask),
                           I.populacao_por(pop, "Total") if d["den"] == "POP" else
                           (I.contar(den_df, ano_den, "Total") if ch not in ("fetal", "perinatal") else
                            den.groupby("ano", as_index=False)["n"].sum()), "Total", mult, anos)
        if serie.empty:
            st.warning("Sem denominador para o recorte escolhido.")
            return
        tot = I.total_periodo(serie, mult)
        casas = 1 if mult >= 1000 else 2
        m1, m2, m3 = st.columns(3)
        m1.metric(f"{d['nome']} ({anos_todos[0]}–{anos_todos[-1]})" if len(anos_todos) > 1 else d["nome"],
                  IA.fmt(tot["taxa"], casas), help=f"{d['unidade']} · IC95% {IA.fmt(tot['ic95_inf'], casas)}–"
                                                   f"{IA.fmt(tot['ic95_sup'], casas)} (Poisson exato)")
        m2.metric("Numerador", IA.fmt(tot["numerador"]))
        m3.metric("Denominador", IA.fmt(tot["denominador"]))
        serie_v = com_rotulo(serie)
        serie_v = serie_v[[nome_tempo, "numerador", "denominador", "taxa", "ic95_inf", "ic95_sup"]]
        st.altair_chart(IA.g_linha(serie_v[[nome_tempo, "taxa", "ic95_inf", "ic95_sup", "numerador", "denominador"]],
                                   nome_tempo, "taxa", titulo_y=d["unidade"], banda=("ic95_inf", "ic95_sup")),
                        width="stretch")
        st.caption(f"{d['nome']} {d['unidade']}; faixa = IC95% exato de Poisson.")
        st.markdown(f"##### {'Por período' if n_g > 1 else 'Ano a ano'}")
        st.dataframe(serie_v.rename(columns={"numerador": "Numerador", "denominador": "Denominador",
                                             "taxa": f"Taxa ({d['unidade']})", "ic95_inf": "IC95% inf",
                                             "ic95_sup": "IC95% sup"}),
                     hide_index=True, width="stretch")
        abas["Série por período" if n_g > 1 else "Série anual"] = serie_v
        r = I.tendencia(serie) if n_g == 1 else None
        if ch == "dcnt":
            pp = pop[(pop["idade"].astype(int) >= 30) & (pop["idade"].astype(int) <= 69)]
            pad = I.padronizada_dcnt(num_df[mask], pp, ano_num, anos)
            grp = num_df[mask].assign(grupo=I.grupo_dcnt(num_df[mask], sis_num))
            pg = grp.groupby([ano_num, "grupo"]).size().reset_index(name="numerador").rename(
                columns={ano_num: "ano"})
            pg = pg.merge(I.populacao_por(pop, "Total", 30, 69).rename(columns={"n": "denominador"}), on="ano")
            pg[["taxa", "ic95_inf", "ic95_sup"]] = E.taxas(pg["numerador"], pg["denominador"], mult).round(2).to_numpy()
            st.markdown("##### Por grupo de causas")
            pg = com_rotulo(pg)
            st.altair_chart(IA.g_linha(pg[[nome_tempo, "grupo", "taxa"]], nome_tempo, "taxa", "grupo",
                                       d["unidade"]), width="stretch")
            if not pad.empty:
                st.markdown("##### Taxa padronizada por idade (OMS, 30–69 anos)")
                st.dataframe(com_rotulo(pad), hide_index=True, width="stretch")
                abas["Padronizada"] = com_rotulo(pad)
            abas["Por grupo"] = pg
            cids_meta = b_num[0]["meta"].get("cids")
            if cids_meta:
                avisos.append(f"A base do SIM foi baixada só com CID {', '.join(cids_meta)}; grupos de DCNT fora "
                              "desse recorte ficam de fora do numerador.")
        if d.get("por_pop") and "idade_anos" in num_df:
            pad = I.padronizada(num_df[mask], pop, ano_num, anos, idade_min or 0,
                                80 if idade_max is None else idade_max, mult)
            if not pad.empty:
                st.markdown("##### Taxa padronizada por idade (OMS)")
                g_pad = com_rotulo(pad.rename(columns={"taxa_padronizada": "taxa", "ic95_inf_pad": "ic95_inf",
                                                       "ic95_sup_pad": "ic95_sup"}))
                st.altair_chart(IA.g_linha(g_pad, nome_tempo, "taxa", titulo_y=f"Padronizada {d['unidade']}",
                                           banda=("ic95_inf", "ic95_sup")), width="stretch")
                st.caption("Método direto, população-padrão mundial da OMS (faixas quinquenais, 80+), IC95% gama "
                           "de Fay-Feuer. Use para comparar anos ou locais com estruturas etárias diferentes.")
                abas["Padronizada"] = g_pad
        if ch == "tx_intern":
            avisos.append("A base do SIH vem dos arquivos dos hospitais da UF baixada: moradores internados em "
                          "outras UFs ficam fora do numerador (no TabNet \"por local de residência\" eles entram; "
                          "diferença típica < 1%).")
        if nivel != "Total":
            st.markdown(f"##### Por {nivel.lower()}")
            vis = com_rotulo(t.drop(columns=["mun_residencia_uf"] if nivel == "Município de residência" and
                                    "mun_residencia_nome" not in t else [], errors="ignore"))
            st.dataframe(vis, hide_index=True, width="stretch", height=360)
            if nivel == "Município de residência":
                st.caption("Municípios pequenos têm taxas muito instáveis – observe o IC95%" +
                           ("; agrupar anos (biênios, triênios) ajuda." if n_g == 1 else "."))
            abas[f"Por {nivel}"] = com_rotulo(t)

    # ---------------- tendência
    if r:
        st.markdown("##### Tendência (Prais-Winsten)")
        st.markdown(f"VPA = **{IA.fmt(r['vpa'], 2)}%** ao ano (IC95% {IA.fmt(r['ic95_inf'], 2)} a "
                    f"{IA.fmt(r['ic95_sup'], 2)}; p {E.fmt_p(r['p'])}) · tendência **{r['tendencia'].lower()}**.")
        abas["Tendência"] = pd.DataFrame([{k_: (round(v, 4) if isinstance(v, float) else v) for k_, v in r.items()
                                           if k_ in ("n_pontos", "vpa", "ic95_inf", "ic95_sup", "p", "tendencia",
                                                     "durbin_watson")}])
    elif n_g > 1:
        st.caption("Tendência (Prais-Winsten): calculada só na série ano a ano – escolha \"Ano a ano\" para vê-la.")
    elif len(anos) < 4:
        st.caption("Tendência: são necessários pelo menos 4 anos.")

    # ---------------- avisos e notas
    if ch == "letal_sim_sih":
        avisos.append("Moradores internados em outras UFs não estão na base do SIH (baixada pelos hospitais da UF).")
        avisos.append("Indicador aproximado: SIM e SIH não são ligados por pessoa; o SIH cobre só internações do SUS "
                      "e o SIM inclui óbitos fora do hospital, então o valor pode passar de 100%. Para a letalidade "
                      "dentro do hospital, use a letalidade hospitalar da página Análise.")
    if ch in ("tmi", "neo", "neo_precoce", "neo_tardia", "pos_neo", "rmm", "fetal", "perinatal"):
        avisos.append("Cálculo direto (óbitos ÷ nascidos vivos), sem os fatores de correção de sub-registro usados "
                      "pelo MS em algumas UFs. Com poucos nascidos vivos (municípios pequenos), as taxas são instáveis.")
    prelim = [b["nome"] for b in b_num + ([b_den] if b_den else []) if _tem_prelim(b["meta"])]
    for nome_df, df_ in (("numerador", num_df), ("denominador", den_df)):
        if df_ is not None and "_status_dado" in df_ and (df_["_status_dado"] == "preliminar").any():
            prelim.append(nome_df)
    if prelim:
        avisos.append("Há dados **preliminares** no recorte.")
    for a in avisos:
        st.info(a)
    ref = " e ".join([", ".join(sel_num)] + ([b_den["nome"]] if b_den else ["população do TabNet (MS/SVSA)"]))
    st.caption(f"Fonte: DATASUS – {ref}. Definição: {d['def']}")
    faixa_txt = "" if idade_min is None else f"{idade_min}–{idade_max}{'+' if idade_max >= 80 else ''} anos"
    abas["Notas"] = pd.DataFrame({"Item": ["Indicador", "Definição", "Unidade", "Bases", "Período", "UFs", "CID",
                                           "Sexo", "Idade", "Só casos novos", "Sem descartados", "Gerado em"],
                                  "Valor": [d["nome"], d["def"], d["unidade"], ref,
                                            f"{anos_todos[0]}–{anos_todos[-1]}" + (f" ({agrup.lower()})" if n_g > 1
                                                                                   else ""),
                                            ", ".join(ufs_usadas), desc_cid or "", sexo_sel or "ambos", faixa_txt,
                                            "sim" if so_novos else "", "sim" if sem_desc else "",
                                            date.today().isoformat()]})
    st.download_button("⬇️ Baixar indicador (Excel)", _excel(abas), file_name=f"indicador_{ch}_{date.today()}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
