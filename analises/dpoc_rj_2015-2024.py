"""Mortalidade por DPOC (CID-10 J40–J44) no estado do Rio de Janeiro: 2015–2019 × 2020–2024.

Uso:  .venv\\Scripts\\python.exe analises\\dpoc_rj_2015-2024.py
Entrada: dados/processados/DPOC_RJ_2015-2024 (gerada por `datasus baixar SIM --uf RJ --anos 2015-2024 --cid J40-J44`)
Saída:   dados/processados/DPOC_RJ_2015-2024/analise/ (Excel, figuras PNG e RESULTADOS.md)
"""

import os
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, RAIZ)

import altair as alt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from datasus_ciencia import estatistica as E  # noqa: E402
from datasus_ciencia.referencias import (FAIXAS_5, PADRAO_OMS, cid10_descricoes, faixa5,  # noqa: E402
                                         populacao_uf_idade_sexo)

BASE = os.path.join(RAIZ, "dados", "processados", "DPOC_RJ_2015-2024")
SAIDA = os.path.join(BASE, "analise")
CACHE = os.path.join(RAIZ, "dados", ".cache")
A, B = list(range(2015, 2020)), list(range(2020, 2025))
B_SENS = [2022, 2023, 2024]
ROT_A, ROT_B = "2015–2019", "2020–2024"
AZUL, LARANJA, VERDE, CINZA = "#2a78d6", "#eb6834", "#1baf7a", "#898781"
COR_SEXO = {"Total": CINZA, "Masculino": AZUL, "Feminino": LARANJA}
GRANDES = {"40–59": FAIXAS_5[8:12], "60–69": FAIXAS_5[12:14], "70–79": FAIXAS_5[14:16], "80+": FAIXAS_5[16:]}

os.makedirs(SAIDA, exist_ok=True)
sys.stdout.reconfigure(encoding="utf-8")


def f(x, c=1):
    return "–" if x is None or (isinstance(x, float) and np.isnan(x)) else \
        f"{x:,.{c}f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ------------------------------------------------------------------ dados
df = pd.read_parquet(os.path.join(BASE, "DPOC_RJ_2015-2024.parquet"))
df = df[(df["mun_residencia_uf"] == "RJ") & df["ano_obito"].between(2015, 2024)].copy()
df["ano"] = df["ano_obito"].astype(int)
df["faixa5"] = faixa5(df["idade_anos"])
df["periodo"] = np.where(df["ano"] <= 2019, ROT_A, ROT_B)
print(f"Óbitos por DPOC, residentes no RJ, 2015–2024: {len(df):,}")

# população por ano, sexo e faixa etária: IBGE, Projeções da População – Revisão 2024 (compatível com o Censo 2022)
pis = populacao_uf_idade_sexo(CACHE, "RJ")
pis = pis[pis["ano"].between(2015, 2024)].copy()
pis["pop_aj"] = pis["pop"]
PESOS = pd.Series(PADRAO_OMS, index=FAIXAS_5)


def pop_idade(anos, sexo=None):
    p = pis[pis["ano"].isin(anos)]
    if sexo in ("Masculino", "Feminino"):
        p = p[p["sexo"] == sexo]
    return p.groupby("faixa")["pop_aj"].sum().reindex(FAIXAS_5).fillna(0)


def obitos_idade(d):
    return d.groupby("faixa5").size().reindex(FAIXAS_5).fillna(0)


def sub_sexo(d, sexo):
    return d if sexo == "Total" else d[d["sexo"] == sexo]


def asr(d, anos, sexo="Total"):
    return E.padronizacao_direta(obitos_idade(sub_sexo(d, sexo)[sub_sexo(d, sexo)["ano"].isin(anos)]),
                                 pop_idade(anos, sexo), PESOS.values)


tabelas = {}

# ------------------------------------------------------------------ 1. série anual
linhas = []
for ano in range(2015, 2025):
    for sexo in ("Total", "Masculino", "Feminino"):
        d = sub_sexo(df, sexo)
        k = int((d["ano"] == ano).sum())
        pop = float(pop_idade([ano], sexo).sum())
        bruta = E.taxas([k], [pop])
        p = asr(df, [ano], sexo)
        linhas.append({"Ano": ano, "Sexo": sexo, "Óbitos": k, "População": round(pop),
                       "Taxa bruta": round(bruta["taxa"][0], 2), "IC95% bruta": f"{f(bruta['ic95_inf'][0], 2)}–{f(bruta['ic95_sup'][0], 2)}",
                       "Taxa padronizada": round(p["taxa"], 2), "pad_inf": round(p["ic95_inf"], 2),
                       "pad_sup": round(p["ic95_sup"], 2)})
anual = pd.DataFrame(linhas)
tabelas["1 Série anual"] = anual.assign(**{"IC95% padronizada": anual["pad_inf"].map(lambda v: f(v, 2)) + "–" +
                                           anual["pad_sup"].map(lambda v: f(v, 2))}).drop(columns=["pad_inf", "pad_sup"])

# ------------------------------------------------------------------ 2. comparação de períodos
def comparar(anos_b, rot_b):
    out = []
    for sexo in ("Total", "Masculino", "Feminino"):
        d = sub_sexo(df, sexo)
        ka, kb = int(d["ano"].isin(A).sum()), int(d["ano"].isin(anos_b).sum())
        pa, pb = float(pop_idade(A, sexo).sum()), float(pop_idade(anos_b, sexo).sum())
        cb = E.comparar_taxas(ka, pa, kb, pb)
        sa, sb = asr(df, A, sexo), asr(df, anos_b, sexo)
        rz = E.razao_padronizada(sa, sb)
        out.append({"Sexo": sexo, f"Óbitos {ROT_A}": ka, f"Óbitos {rot_b}": kb,
                    f"Média anual {ROT_A}": round(ka / len(A), 1), f"Média anual {rot_b}": round(kb / len(anos_b), 1),
                    f"Taxa bruta {ROT_A}": round(cb["tA"] * 1e5, 2), f"Taxa bruta {rot_b}": round(cb["tB"] * 1e5, 2),
                    "Razão bruta B/A (IC95%)": f"{f(cb['razao'], 3)} ({f(cb['razao_ic'][0], 3)}–{f(cb['razao_ic'][1], 3)})",
                    f"Taxa padronizada {ROT_A} (IC95%)": f"{f(sa['taxa'], 2)} ({f(sa['ic95_inf'], 2)}–{f(sa['ic95_sup'], 2)})",
                    f"Taxa padronizada {rot_b} (IC95%)": f"{f(sb['taxa'], 2)} ({f(sb['ic95_inf'], 2)}–{f(sb['ic95_sup'], 2)})",
                    "Variação padronizada (%)": round(100 * (rz["razao"] - 1), 1),
                    "Razão padronizada B/A (IC95%)": f"{f(rz['razao'], 3)} ({f(rz['ic'][0], 3)}–{f(rz['ic'][1], 3)})",
                    "p": E.fmt_p(rz["p"]),
                    "_rz": rz, "_sa": sa, "_sb": sb})
    return out


comp = comparar(B, ROT_B)
comp_sens = comparar(B_SENS, "2022–2024")
tabelas["2 Comparação períodos"] = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in comp])
tabelas["3 Sensibilidade sem 20-21"] = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in comp_sens])

# ------------------------------------------------------------------ 3. taxas por faixa etária
linhas = []
for gr, faixas in GRANDES.items():
    for sexo in ("Total", "Masculino", "Feminino"):
        d = sub_sexo(df, sexo)
        d = d[d["faixa5"].isin(faixas)]
        ka, kb = int(d["ano"].isin(A).sum()), int(d["ano"].isin(B).sum())
        pa = float(pop_idade(A, sexo)[faixas].sum())
        pb = float(pop_idade(B, sexo)[faixas].sum())
        c = E.comparar_taxas(ka, pa, kb, pb)
        linhas.append({"Faixa etária": gr, "Sexo": sexo, f"Óbitos {ROT_A}": ka, f"Óbitos {ROT_B}": kb,
                       f"Taxa {ROT_A}": round(c["tA"] * 1e5, 2), f"Taxa {ROT_B}": round(c["tB"] * 1e5, 2),
                       "Variação (%)": round(c["var_pct"], 1),
                       "Razão B/A (IC95%)": f"{f(c['razao'], 3)} ({f(c['razao_ic'][0], 3)}–{f(c['razao_ic'][1], 3)})",
                       "p": E.fmt_p(c["p"])})
tabelas["4 Taxas por idade"] = pd.DataFrame(linhas)

# ------------------------------------------------------------------ 4. tendência (Prais-Winsten sobre taxa padronizada)
linhas = []
for sexo in ("Total", "Masculino", "Feminino"):
    s = anual[anual["Sexo"] == sexo]
    for rot, anos in (("2015–2024", range(2015, 2025)), (ROT_A, A), (ROT_B, B)):
        ss = s[s["Ano"].isin(list(anos))]
        r = E.prais_winsten(ss["Ano"], ss["Taxa padronizada"])
        if r:
            linhas.append({"Sexo": sexo, "Período": rot, "VPA (%)": round(r["vpa"], 2),
                           "IC95%": f"{f(r['ic95_inf'], 2)} a {f(r['ic95_sup'], 2)}", "p": E.fmt_p(r["p"]),
                           "Tendência": r["tendencia"], "Durbin-Watson": round(r["durbin_watson"], 2)})
tabelas["5 Tendência Prais-Winsten"] = pd.DataFrame(linhas)

# ------------------------------------------------------------------ 5. série temporal interrompida (mensal)
m = df.groupby(["ano", "mes_obito"]).size().reindex(
    pd.MultiIndex.from_product([range(2015, 2025), range(1, 13)], names=["ano", "mes_obito"]), fill_value=0
).reset_index(name="obitos")
inicio = int((m["ano"] >= 2020).idxmax())
its = E.serie_interrompida(m["ano"], m["obitos"], inicio, periodo_sazonal=m["mes_obito"], maxlags=12)
media_pre = m.loc[: inicio - 1, "obitos"].mean()
c = its["coef"]
tabelas["6 Série interrompida"] = pd.DataFrame([{
    "Modelo": "Óbitos mensais, 2015–2024; interrupção em jan/2020; ajuste sazonal; Newey-West (12 lags)",
    "Média mensal pré": round(media_pre, 1),
    "Tendência pré (óbitos/mês)": f"{f(c['tempo']['b'], 3)} (p={E.fmt_p(c['tempo']['p'])})",
    "Mudança de nível (IC95%)": f"{f(c['nivel_pos']['b'], 1)} ({f(c['nivel_pos']['ic'][0], 1)} a {f(c['nivel_pos']['ic'][1], 1)})",
    "p nível": E.fmt_p(c["nivel_pos"]["p"]),
    "Mudança de tendência por mês (IC95%)": f"{f(c['tendencia_pos']['b'], 3)} ({f(c['tendencia_pos']['ic'][0], 3)} a {f(c['tendencia_pos']['ic'][1], 3)})",
    "p tendência": E.fmt_p(c["tendencia_pos"]["p"]), "R²": round(its["r2"], 3)}])
m["ajustado"], m["contrafactual"] = its["ajustado"], its["contrafactual"]

# ------------------------------------------------------------------ 6. perfil dos óbitos (Tabela 1)
t1 = E.tabela1(df, "periodo", ["sexo", "raca_cor", "faixa_etaria", "escolaridade", "estado_civil",
                               "local_ocorrencia"], ["idade_anos"], excluir_ignorados=True)
tabelas["7 Perfil (Tabela 1)"] = t1

# ------------------------------------------------------------------ 7. causas específicas
desc = cid10_descricoes(CACHE)
ct = pd.crosstab(df["causa_basica_cat3"], df["periodo"])
p_ct = E._teste_categorico(ct)
causas = ct.reset_index().rename(columns={"causa_basica_cat3": "CID"})
causas["Descrição"] = causas["CID"].map(lambda x: desc.get(x, ""))
for per in (ROT_A, ROT_B):
    causas[f"% {per}"] = (100 * causas[per] / causas[per].sum()).round(1)
causas["p (qui-quadrado)"] = [E.fmt_p(p_ct[0])] + [""] * (len(causas) - 1)
tabelas["8 Causas J40-J44"] = causas

# ------------------------------------------------------------------ figuras
def cfg(ch):
    return ch.configure_axis(gridColor="#e1e0d9", domainColor="#c3c2b7", labelColor="#52514e", titleColor="#52514e",
                             labelFontSize=12, titleFontSize=12).configure_view(strokeWidth=0).configure_legend(
        orient="top", labelColor="#52514e", titleColor="#52514e").properties(background="#ffffff")


g = anual.copy()
g["Ano"] = g["Ano"].astype(str)
esc = alt.Scale(domain=list(COR_SEXO), range=list(COR_SEXO.values()))
banda = alt.Chart(g).mark_area(opacity=0.15).encode(x=alt.X("Ano:O", axis=alt.Axis(labelAngle=0), title=None),
                                                     y="pad_inf:Q", y2="pad_sup:Q", color=alt.Color("Sexo:N", scale=esc))
linha = alt.Chart(g).mark_line(strokeWidth=2).encode(
    x="Ano:O", y=alt.Y("Taxa padronizada:Q", title="Óbitos por 100 mil hab. (padronizada por idade)",
                       scale=alt.Scale(zero=True)), color=alt.Color("Sexo:N", scale=esc, title=None))
pts = alt.Chart(g).mark_point(filled=True, size=64, stroke="#ffffff", strokeWidth=2).encode(
    x="Ano:O", y="Taxa padronizada:Q", color=alt.Color("Sexo:N", scale=esc))
corte = alt.Chart(pd.DataFrame({"Ano": ["2020"]})).mark_rule(strokeDash=[4, 4], color=CINZA).encode(x="Ano:O")
cfg((banda + linha + pts + corte).properties(width=620, height=320, title="Figura 1 – Mortalidade por DPOC, RJ, 2015–2024")
    ).save(os.path.join(SAIDA, "fig1_taxa_padronizada.png"), scale_factor=2)

m["data"] = pd.to_datetime(dict(year=m["ano"], month=m["mes_obito"], day=1))
m["segmento"] = np.where(m.index >= inicio, "pós", "pré")
base = alt.Chart(m)
obs = base.mark_point(size=30, filled=True, color=CINZA, opacity=0.8).encode(
    x=alt.X("data:T", title=None), y=alt.Y("obitos:Q", title="Óbitos por DPOC por mês", scale=alt.Scale(zero=False)))
aj = base.mark_line(strokeWidth=2, color=AZUL).encode(x="data:T", y="ajustado:Q", detail="segmento:N")
cf = base.transform_filter("datum.segmento == 'pós'").mark_line(strokeWidth=2, strokeDash=[6, 4], color=LARANJA).encode(
    x="data:T", y="contrafactual:Q")
cfg((obs + aj + cf).properties(width=620, height=300,
                               title="Figura 2 – Série temporal interrompida (jan/2020): observado, ajustado e contrafactual")
    ).save(os.path.join(SAIDA, "fig2_serie_interrompida.png"), scale_factor=2)

ti = tabelas["4 Taxas por idade"]
ti = ti[ti["Sexo"] == "Total"].melt(id_vars=["Faixa etária"], value_vars=[f"Taxa {ROT_A}", f"Taxa {ROT_B}"],
                                    var_name="Período", value_name="Taxa")
ti["Período"] = ti["Período"].str.replace("Taxa ", "")
cfg(alt.Chart(ti).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
    x=alt.X("Faixa etária:N", title=None, axis=alt.Axis(labelAngle=0)), xOffset="Período:N",
    y=alt.Y("Taxa:Q", title="Óbitos por 100 mil hab."),
    color=alt.Color("Período:N", scale=alt.Scale(range=[CINZA, AZUL]), title=None)
).properties(width=620, height=300, title="Figura 3 – Taxa de mortalidade por DPOC por faixa etária e período")
).save(os.path.join(SAIDA, "fig3_taxa_idade.png"), scale_factor=2)

lo = df[df["local_ocorrencia"].notna() & (df["local_ocorrencia"] != "Ignorado")]
lo = lo.groupby(["periodo", "local_ocorrencia"]).size().reset_index(name="n")
lo["%"] = 100 * lo["n"] / lo.groupby("periodo")["n"].transform("sum")
cfg(alt.Chart(lo).mark_bar(cornerRadiusEnd=4, height={"band": 0.8}).encode(
    y=alt.Y("local_ocorrencia:N", sort="-x", title=None), yOffset="periodo:N",
    x=alt.X("%:Q", title="% dos óbitos"), color=alt.Color("periodo:N", scale=alt.Scale(range=[CINZA, AZUL]), title=None)
).properties(width=560, height=260, title="Figura 4 – Local de ocorrência dos óbitos por DPOC, por período")
).save(os.path.join(SAIDA, "fig4_local_obito.png"), scale_factor=2)

# ------------------------------------------------------------------ Excel e resumo
xlsx = os.path.join(SAIDA, "DPOC_RJ_resultados.xlsx")
with pd.ExcelWriter(xlsx) as xw:
    pd.DataFrame({"Item": ["Fonte", "População", "Padronização", "Métodos"], "Valor": [
        "SIM/DATASUS – óbitos de residentes no RJ, causa básica J40–J44, 2015–2024 (dados finais)",
        "IBGE: Projeções da População, Revisão 2024 (por sexo e faixa quinquenal; compatível com o Censo 2022)",
        "Método direto, população-padrão mundial da OMS (Ahmad et al., 2001); IC95% gama de Fay & Feuer",
        E.TEXTO_METODOS_PERIODOS]}).to_excel(xw, sheet_name="Notas", index=False)
    for nome, t in tabelas.items():
        t.to_excel(xw, sheet_name=nome[:31], index=False)

tot_c = comp[0]
masc, fem = comp[1], comp[2]
s_tot = comp_sens[0]
pw = tabelas["5 Tendência Prais-Winsten"]
pw_tot = pw[(pw["Sexo"] == "Total")].set_index("Período")
loc_tab = lo.pivot(index="local_ocorrencia", columns="periodo", values="%").round(1)
idade_t = tabelas["4 Taxas por idade"]
idade_t = idade_t[idade_t["Sexo"] == "Total"].set_index("Faixa etária")

res = f"""# Mortalidade por DPOC no Rio de Janeiro: 2015–2019 × 2020–2024

Fonte: SIM/DATASUS (dados finais), óbitos de residentes no estado do RJ com causa básica J40–J44.
Total: **{f(len(df), 0)} óbitos** ({f(tot_c['Óbitos 2015–2019'], 0)} em 2015–2019 e {f(tot_c['Óbitos 2020–2024'], 0)} em 2020–2024).

## Principais resultados

- **Taxa padronizada por idade** (por 100 mil hab., padrão OMS): {tot_c['Taxa padronizada 2015–2019 (IC95%)']} em 2015–2019 → {tot_c['Taxa padronizada 2020–2024 (IC95%)']} em 2020–2024; variação de **{f(tot_c['Variação padronizada (%)'])}%**, razão {tot_c['Razão padronizada B/A (IC95%)']}, p={tot_c['p']}.
- Taxa **bruta**: {f(tot_c['Taxa bruta 2015–2019'], 2)} → {f(tot_c['Taxa bruta 2020–2024'], 2)} (razão {tot_c['Razão bruta B/A (IC95%)']}). A diferença entre a variação bruta e a padronizada reflete o envelhecimento da população.
- **Homens**: {masc['Taxa padronizada 2015–2019 (IC95%)']} → {masc['Taxa padronizada 2020–2024 (IC95%)']} ({f(masc['Variação padronizada (%)'])}%; razão {masc['Razão padronizada B/A (IC95%)']}). **Mulheres**: {fem['Taxa padronizada 2015–2019 (IC95%)']} → {fem['Taxa padronizada 2020–2024 (IC95%)']} ({f(fem['Variação padronizada (%)'])}%; razão {fem['Razão padronizada B/A (IC95%)']}).
- **Sensibilidade** (excluindo 2020–2021, anos agudos da COVID-19): 2022–2024 vs 2015–2019 = {f(s_tot['Variação padronizada (%)'])}% (razão {s_tot['Razão padronizada B/A (IC95%)']}).
- **Tendência (Prais-Winsten, taxa padronizada)**: 2015–2024 VPA {f(pw_tot.loc['2015–2024', 'VPA (%)'], 2)}% ({pw_tot.loc['2015–2024', 'IC95%']}; {pw_tot.loc['2015–2024', 'Tendência'].lower()}); 2015–2019 VPA {f(pw_tot.loc[ROT_A, 'VPA (%)'], 2)}% ({pw_tot.loc[ROT_A, 'Tendência'].lower()}); 2020–2024 VPA {f(pw_tot.loc[ROT_B, 'VPA (%)'], 2)}% ({pw_tot.loc[ROT_B, 'Tendência'].lower()}).
- **Série temporal interrompida** (óbitos mensais, jan/2020): mudança imediata de nível de {f(c['nivel_pos']['b'], 1)} óbitos/mês (IC95% {f(c['nivel_pos']['ic'][0], 1)} a {f(c['nivel_pos']['ic'][1], 1)}; p={E.fmt_p(c['nivel_pos']['p'])}) sobre média pré de {f(media_pre, 1)}/mês; mudança de tendência de {f(c['tendencia_pos']['b'], 3)} óbitos/mês por mês (p={E.fmt_p(c['tendencia_pos']['p'])}).
- **Por idade** (taxa bruta específica, total): 40–59: {idade_t.loc['40–59', 'Variação (%)']}%; 60–69: {idade_t.loc['60–69', 'Variação (%)']}%; 70–79: {idade_t.loc['70–79', 'Variação (%)']}%; 80+: {idade_t.loc['80+', 'Variação (%)']}%.
- **Local do óbito** (% hospital → domicílio): hospital {loc_tab.loc['Hospital', ROT_A] if 'Hospital' in loc_tab.index else '–'}% → {loc_tab.loc['Hospital', ROT_B] if 'Hospital' in loc_tab.index else '–'}%; domicílio {loc_tab.loc['Domicílio', ROT_A] if 'Domicílio' in loc_tab.index else '–'}% → {loc_tab.loc['Domicílio', ROT_B] if 'Domicílio' in loc_tab.index else '–'}%.

## Arquivos

- `DPOC_RJ_resultados.xlsx` – todas as tabelas (série anual, comparação, sensibilidade, idade, tendência, série interrompida, Tabela 1, causas)
- `fig1_taxa_padronizada.png`, `fig2_serie_interrompida.png`, `fig3_taxa_idade.png`, `fig4_local_obito.png`

## Métodos (sugestão)

Estudo ecológico de séries temporais com óbitos de residentes no estado do Rio de Janeiro cuja causa básica foi DPOC
(CID-10 J40–J44), registrados no SIM/DATASUS entre 2015 e 2024. Foram calculadas taxas brutas e padronizadas por idade
(método direto, população-padrão mundial da OMS), com denominadores das Projeções da População do IBGE
(revisão 2024, compatível com o Censo 2022). Os períodos 2015–2019 e 2020–2024 foram
comparados pela razão de taxas padronizadas (IC95% log-normal). A tendência foi avaliada por regressão de Prais-Winsten
(variação percentual anual) e o efeito do início da pandemia por série temporal interrompida mensal (regressão
segmentada com ajuste sazonal e erros de Newey-West). Análise de sensibilidade excluiu 2020–2021. O perfil dos óbitos
foi comparado pelo teste qui-quadrado.

## Limitações a discutir

- Óbitos de pacientes com DPOC atribuídos à COVID-19 como causa básica em 2020–2022 podem reduzir artificialmente a mortalidade por DPOC (competição de causas).
- Denominadores populacionais são projeções (IBGE, revisão 2024), não contagens anuais.
- Qualidade da declaração de óbito e causas mal definidas (R00–R99) podem variar no tempo.
"""
with open(os.path.join(SAIDA, "RESULTADOS.md"), "w", encoding="utf-8") as fh:
    fh.write(res)
print(res)
