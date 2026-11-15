"""Análises estatísticas para dados do DATASUS.

- Tabela 1 comparativa (qui-quadrado/Fisher; Mann-Whitney/Kruskal-Wallis; V de Cramér)
- Taxas brutas com IC95% exato de Poisson
- Tendência temporal por regressão de Prais-Winsten (variação percentual anual – VPA)
- Regressão logística (OR bruto e ajustado com IC95%)
"""

import warnings

import numpy as np
import pandas as pd
from scipy import stats

AUSENTES = {"Ignorado", "Sem informação", "<NA>", "nan", "None"}


ORDENS = [
    ["<1", "1-4", "5-9", "10-14", "15-19", "20-29", "30-39", "40-49", "50-59", "60-69", "70-79", "80+"],
    ["<15", "15-19", "20-34", "35+"],
    ["Nenhuma", "1 a 3 anos", "4 a 7 anos", "8 a 11 anos", "12 anos ou mais"],
    ["Nenhuma", "1 a 3", "4 a 6", "7 ou mais"],
    ["Menos de 22 semanas", "22 a 27 semanas", "28 a 31 semanas", "32 a 36 semanas", "37 a 41 semanas",
     "42 semanas ou mais"],
    ["10 a 14 anos", "15 a 19 anos", "20 a 24 anos", "25 a 29 anos", "30 a 34 anos", "35 a 39 anos",
     "40 a 44 anos", "45 anos ou mais"],
    ["Menos de 500 g", "500 a 999 g", "1.000 a 1.499 g", "1.500 a 2.499 g", "2.500 a 2.999 g", "3.000 a 3.999 g",
     "4.000 g e mais"],
    ["0 a 6 dias", "7 a 27 dias", "28 a 364 dias"],
    ["Neonatal precoce", "Neonatal tardio", "Pós-neonatal"],
    ["Antes do parto", "Durante o parto", "Depois do parto"],
]


def ordenar_categorias(valores, contagens=None):
    """Ordem natural para variáveis ordinais conhecidas (faixa etária, escolaridade...), senão por frequência."""
    vals = [v for v in valores if v is not None]
    for ordem in ORDENS:
        if vals and all(v in ordem or v in AUSENTES for v in vals):
            return [o for o in ordem if o in vals] + [v for v in vals if v in AUSENTES]
    if all(str(v).lstrip("-").isdigit() for v in vals):
        return sorted(vals, key=lambda v: int(v))
    if contagens is not None:
        conj = set(vals)
        return [v for v in contagens.sort_values(ascending=False).index if v in conj]
    return vals


def fmt_p(p):
    if p is None or (isinstance(p, float) and np.isnan(p)):
        return "–"
    if p < 0.001:
        return "<0,001"
    return f"{p:.3f}".replace(".", ",")


def _num_br(x, casas=1):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    return f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ================================================================== Tabela 1
def tabela1(df, grupo, categoricas, numericas, excluir_ignorados=True, universos=None):
    """Tabela descritiva estratificada por `grupo` com testes de hipótese.

    `universos`: {variável: máscara booleana alinhada a `df`} – a variável só é descrita/testada nos registros a que
    se aplica (ex.: tipo de parto só nos óbitos fetais e de menores de 1 ano).

    Categóricas: n (%) por coluna; qui-quadrado de Pearson (ou exato de Fisher em tabelas 2x2 com
    frequência esperada < 5); tamanho de efeito V de Cramér.
    Numéricas: mediana (P25–P75) e média (DP); Mann-Whitney (2 grupos) ou Kruskal-Wallis (>2).
    """
    d = df.copy()
    d[grupo] = d[grupo].astype("string")
    if excluir_ignorados:
        d = d[~d[grupo].isin(AUSENTES) & d[grupo].notna()]
    vc = d[grupo].value_counts()
    niveis = ordenar_categorias(list(vc.index), vc)
    linhas = []
    cab_n = {g: int((d[grupo] == g).sum()) for g in niveis}
    linhas.append({"Variável": "n", "Categoria": "", **{f"{g} (n={_num_br(cab_n[g], 0)})": _num_br(cab_n[g], 0) for g in niveis},
                   f"Total (n={_num_br(len(d), 0)})": _num_br(len(d), 0), "p-valor": "", "Teste": "", "Efeito": ""})
    col = lambda g: f"{g} (n={_num_br(cab_n[g], 0)})"
    col_t = f"Total (n={_num_br(len(d), 0)})"

    for v in categoricas:
        if v == grupo or v not in d:
            continue
        x = d[v].astype("string").fillna("Sem informação")
        if excluir_ignorados:
            mask = ~x.isin(AUSENTES)
        else:
            mask = pd.Series(True, index=x.index)
        if universos and v in universos:
            mask &= universos[v].reindex(x.index, fill_value=False)
        ct = pd.crosstab(x[mask], d.loc[mask, grupo])
        ct = ct.reindex(columns=niveis, fill_value=0)
        if ct.shape[0] < 2 or ct.shape[1] < 2:
            continue
        p, teste, efeito = _teste_categorico(ct)
        tot_col = ct.sum(axis=0)
        primeira = True
        for cat in ordenar_categorias(list(ct.index), ct.sum(axis=1)):
            linha = {"Variável": v if primeira else "", "Categoria": cat}
            for g in niveis:
                n = ct.loc[cat, g]
                linha[col(g)] = f"{_num_br(n, 0)} ({_num_br(100 * n / tot_col[g] if tot_col[g] else np.nan)})"
            nt = ct.loc[cat].sum()
            linha[col_t] = f"{_num_br(nt, 0)} ({_num_br(100 * nt / ct.values.sum())})"
            linha["p-valor"] = fmt_p(p) if primeira else ""
            linha["Teste"] = teste if primeira else ""
            linha["Efeito"] = efeito if primeira else ""
            linhas.append(linha)
            primeira = False

    for v in numericas:
        if v not in d:
            continue
        x = pd.to_numeric(d[v], errors="coerce").astype(float)
        amostras = [x[d[grupo] == g].dropna() for g in niveis]
        if sum(len(a) > 0 for a in amostras) < 2:
            continue
        validas = [a for a in amostras if len(a) > 0]
        if len(validas) == 2:
            p = stats.mannwhitneyu(*validas, alternative="two-sided").pvalue
            teste = "Mann-Whitney"
        else:
            p = stats.kruskal(*validas).pvalue
            teste = "Kruskal-Wallis"
        for rot, f in (("Mediana (P25–P75)", lambda a: f"{_num_br(a.median())} ({_num_br(a.quantile(.25))}–{_num_br(a.quantile(.75))})"),
                       ("Média (DP)", lambda a: f"{_num_br(a.mean())} ({_num_br(a.std())})")):
            linha = {"Variável": v if rot.startswith("Mediana") else "", "Categoria": rot}
            for g, a in zip(niveis, amostras):
                linha[col(g)] = f(a) if len(a) else "–"
            linha[col_t] = f(x.dropna())
            linha["p-valor"] = fmt_p(p) if rot.startswith("Mediana") else ""
            linha["Teste"] = teste if rot.startswith("Mediana") else ""
            linha["Efeito"] = ""
            linhas.append(linha)
    return pd.DataFrame(linhas)


def _teste_categorico(ct):
    # linhas/colunas zeradas (ex.: grupo em que a variável é toda "Ignorado") tornam o esperado 0 e o teste inválido
    ct = ct.loc[ct.sum(axis=1) > 0, ct.sum(axis=0) > 0]
    obs = ct.values
    if obs.shape[0] < 2 or obs.shape[1] < 2:
        return np.nan, "Não aplicável (sem variação)", ""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        chi2, p, dof, esperado = stats.chi2_contingency(obs, correction=False)
    n = obs.sum()
    v = np.sqrt(chi2 / (n * (min(obs.shape) - 1))) if n else np.nan
    if obs.shape == (2, 2) and (esperado < 5).any():
        p = stats.fisher_exact(obs).pvalue
        return p, "Exato de Fisher", f"V={_num_br(v, 2)}"
    teste = "Qui-quadrado" + (" (esperado<5 em células)" if (esperado < 5).mean() > 0.2 else "")
    return p, teste, f"V={_num_br(v, 2)}"


# ================================================================== taxas
def ic_poisson(k, alpha=0.05):
    k = np.asarray(k, dtype=float)
    inf = np.where(k > 0, stats.chi2.ppf(alpha / 2, 2 * k) / 2, 0.0)
    sup = stats.chi2.ppf(1 - alpha / 2, 2 * (k + 1)) / 2
    return inf, sup


def taxas(contagens, populacao, multiplicador=100_000):
    """contagens e populacao alinhadas → DataFrame com taxa e IC95% exato de Poisson."""
    k = np.asarray(contagens, dtype=float)
    pop = np.asarray(populacao, dtype=float)
    inf, sup = ic_poisson(k)
    with np.errstate(divide="ignore", invalid="ignore"):
        return pd.DataFrame({"taxa": k / pop * multiplicador, "ic95_inf": inf / pop * multiplicador,
                             "ic95_sup": sup / pop * multiplicador})


# ================================================================== padronização direta por idade
def padronizacao_direta(obitos, populacao, pesos, multiplicador=100_000):
    """Taxa padronizada por idade (método direto) com IC95% gama de Fay & Feuer (1997).
    obitos, populacao, pesos: arrays alinhados por faixa etária."""
    d = np.asarray(obitos, dtype=float)
    n = np.asarray(populacao, dtype=float)
    w = np.asarray(pesos, dtype=float)
    w = w / w.sum()
    ok = n > 0
    d, n, w = d[ok], n[ok], w[ok] / w[ok].sum()
    y = np.sum(w * d / n)
    v = np.sum(w ** 2 * d / n ** 2)
    wm = np.max(w / n)
    if v > 0:
        inf = v / (2 * y) * stats.chi2.ppf(0.025, 2 * y ** 2 / v)
    else:
        inf = 0.0
    sup = (v + wm ** 2) / (2 * (y + wm)) * stats.chi2.ppf(0.975, 2 * (y + wm) ** 2 / (v + wm ** 2))
    return {"taxa": y * multiplicador, "ic95_inf": inf * multiplicador, "ic95_sup": sup * multiplicador,
            "var": v * multiplicador ** 2}


def razao_padronizada(a, b):
    """Razão B/A de taxas padronizadas com IC95% (log-normal)."""
    rr = b["taxa"] / a["taxa"]
    se = np.sqrt(a["var"] / a["taxa"] ** 2 + b["var"] / b["taxa"] ** 2)
    z = np.log(rr) / se
    return {"razao": rr, "ic": (rr * np.exp(-1.96 * se), rr * np.exp(1.96 * se)), "p": 2 * stats.norm.sf(abs(z))}


# ================================================================== proporções e comparação de períodos
def ic_wilson(k, n, z=1.959964):
    """IC95% de Wilson para proporção (retorna em %)."""
    k = np.asarray(k, dtype=float)
    n = np.asarray(n, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        p = k / n
        den = 1 + z ** 2 / n
        centro = (p + z ** 2 / (2 * n)) / den
        meia = z * np.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2)) / den
    return 100 * (centro - meia), 100 * (centro + meia)


def comparar_proporcoes(kA, nA, kB, nB):
    """Proporções (%) em A e B, razão B/A com IC95% (log), diferença em pontos percentuais e p."""
    pA, pB = (kA / nA if nA else np.nan), (kB / nB if nB else np.nan)
    iA, sA = ic_wilson(kA, nA)
    iB, sB = ic_wilson(kB, nB)
    if kA > 0 and kB > 0:
        rr = pB / pA
        se = np.sqrt(1 / kB - 1 / nB + 1 / kA - 1 / nA)
        rr_i, rr_s = np.exp(np.log(rr) - 1.96 * se), np.exp(np.log(rr) + 1.96 * se)
    else:
        rr = rr_i = rr_s = np.nan
    tab = np.array([[kA, nA - kA], [kB, nB - kB]])
    if (tab.sum(axis=0) == 0).any() or (tab.sum(axis=1) == 0).any():
        # sem eventos (ou só eventos) nos dois períodos: proporções idênticas, não há o que testar
        return {"pA": 100 * pA, "icA": (float(iA), float(sA)), "pB": 100 * pB, "icB": (float(iB), float(sB)),
                "razao": rr, "razao_ic": (rr_i, rr_s), "dif_pp": 100 * (pB - pA), "p": np.nan,
                "teste": "Não aplicável (sem variação)"}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        chi2, p, _, esp = stats.chi2_contingency(tab, correction=False)
    teste = "Qui-quadrado"
    if (esp < 5).any():
        p = stats.fisher_exact(tab).pvalue
        teste = "Exato de Fisher"
    return {"pA": 100 * pA, "icA": (float(iA), float(sA)), "pB": 100 * pB, "icB": (float(iB), float(sB)),
            "razao": rr, "razao_ic": (rr_i, rr_s), "dif_pp": 100 * (pB - pA), "p": p, "teste": teste}


def comparar_taxas(kA, expA, kB, expB):
    """Razão de taxas B/A (exposição = pessoas-ano ou nº de anos) com IC95% e teste binomial condicional."""
    tA, tB = kA / expA, kB / expB
    if kA > 0 and kB > 0:
        rr = tB / tA
        se = np.sqrt(1 / kA + 1 / kB)
        ic = (np.exp(np.log(rr) - 1.96 * se), np.exp(np.log(rr) + 1.96 * se))
    else:
        rr, ic = np.nan, (np.nan, np.nan)
    p = stats.binomtest(int(kB), int(kA + kB), expB / (expA + expB)).pvalue if (kA + kB) > 0 else np.nan
    return {"tA": tA, "tB": tB, "razao": rr, "razao_ic": ic, "var_pct": 100 * (tB / tA - 1) if tA else np.nan, "p": p}


def serie_interrompida(tempo, y, inicio_pos, periodo_sazonal=None, maxlags=None):
    """Série temporal interrompida por regressão segmentada:
        y = b0 + b1·t + b2·pós + b3·(t − t0)·pós [+ dummies de mês] + e
    com erros-padrão robustos de Newey-West (HAC). `tempo` ordenado; `inicio_pos` = 1º índice do período pós.
    Retorna coeficientes (IC95%, p), valores ajustados e contrafactual (tendência pré projetada)."""
    import statsmodels.api as sm

    y = np.asarray(y, dtype=float)
    n = len(y)
    t = np.arange(1, n + 1, dtype=float)
    pos = (np.arange(n) >= inicio_pos).astype(float)
    t_pos = np.where(pos == 1, t - (inicio_pos + 1), 0.0)  # 0 no 1º ponto pós → b2 = mudança imediata de nível
    X = pd.DataFrame({"const": 1.0, "tempo": t, "nivel_pos": pos, "tendencia_pos": t_pos})
    if periodo_sazonal is not None:
        dm = pd.get_dummies(pd.Series(periodo_sazonal).astype(int), prefix="mes", drop_first=True, dtype=float)
        X = pd.concat([X, dm.reset_index(drop=True)], axis=1)
    ok = np.isfinite(y)
    if ok.sum() < 8 or pos[ok].sum() < 3 or (1 - pos[ok]).sum() < 3:
        return None
    lags = maxlags if maxlags is not None else max(1, int(round(4 * (ok.sum() / 100) ** (2 / 9))))
    mod = sm.OLS(y[ok], X[ok]).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    ci = mod.conf_int()
    coef = {}
    for k in ("const", "tempo", "nivel_pos", "tendencia_pos"):
        coef[k] = {"b": mod.params[k], "ic": (ci.loc[k, 0], ci.loc[k, 1]), "p": mod.pvalues[k]}
    ajust = mod.predict(X)
    Xc = X.copy()
    Xc["nivel_pos"] = 0.0
    Xc["tendencia_pos"] = 0.0
    contraf = mod.predict(Xc)
    return {"coef": coef, "ajustado": np.asarray(ajust), "contrafactual": np.asarray(contraf),
            "r2": mod.rsquared, "n": int(ok.sum()), "lags": lags, "durbin_watson": float(
                np.sum(np.diff(mod.resid) ** 2) / np.sum(mod.resid ** 2))}


# ================================================================== tendência
def prais_winsten(anos, valores, max_iter=50):
    """Regressão de Prais-Winsten de log10(valor) sobre o ano (Antunes & Cardoso, 2015).

    Retorna dict com VPA (variação percentual anual), IC95%, p, rho, Durbin-Watson e classificação
    (crescente / decrescente / estacionária).
    """
    x = np.asarray(anos, dtype=float)
    y = np.asarray(valores, dtype=float)
    ok = np.isfinite(y) & (y > 0)
    x, y = x[ok], np.log10(y[ok])
    n = len(x)
    if n < 4:
        return None
    X = np.column_stack([np.ones(n), x - x.mean()])
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    rho = 0.0
    for _ in range(max_iter):
        e = y - X @ beta
        rho_novo = np.sum(e[1:] * e[:-1]) / np.sum(e[:-1] ** 2) if np.sum(e[:-1] ** 2) > 0 else 0.0
        rho_novo = float(np.clip(rho_novo, -0.99, 0.99))
        fator = np.sqrt(1 - rho_novo ** 2)
        ys = np.r_[fator * y[0], y[1:] - rho_novo * y[:-1]]
        Xs = np.vstack([fator * X[0], X[1:] - rho_novo * X[:-1]])
        beta = np.linalg.lstsq(Xs, ys, rcond=None)[0]
        if abs(rho_novo - rho) < 1e-8:
            rho = rho_novo
            break
        rho = rho_novo
    res = ys - Xs @ beta
    gl = n - 2
    s2 = np.sum(res ** 2) / gl
    cov = s2 * np.linalg.inv(Xs.T @ Xs)
    b, se = beta[1], np.sqrt(cov[1, 1])
    t = stats.t.ppf(0.975, gl)
    p = 2 * stats.t.sf(abs(b / se), gl) if se > 0 else 0.0
    dw = np.sum(np.diff(res) ** 2) / np.sum(res ** 2) if np.sum(res ** 2) > 0 else np.nan
    vpa = (10 ** b - 1) * 100
    inf, sup = (10 ** (b - t * se) - 1) * 100, (10 ** (b + t * se) - 1) * 100
    classe = "Estacionária" if p >= 0.05 else ("Crescente" if b > 0 else "Decrescente")
    return {"n_pontos": n, "vpa": vpa, "ic95_inf": inf, "ic95_sup": sup, "p": p, "beta": b,
            "rho": rho, "durbin_watson": dw, "tendencia": classe}


# ================================================================== regressão logística
def regressao_logistica(df, desfecho, covariaveis, excluir_ignorados=True, max_n=400_000, referencias=None):
    """Regressão logística: OR bruto (um modelo por covariável) e ajustado (todas juntas).

    `desfecho` deve ser uma Série booleana alinhada a `df`. Categoria de referência = `referencias[c]`
    se informada, senão a mais frequente.
    """
    referencias = referencias or {}
    import statsmodels.api as sm

    d = df[covariaveis].copy()
    d["_y"] = desfecho.astype("Float64")
    for c in covariaveis:
        d[c] = d[c].astype("string")
        if excluir_ignorados:
            d.loc[d[c].isin(AUSENTES), c] = pd.NA
    d = d.dropna()
    if len(d) > max_n:
        d = d.sample(max_n, random_state=42)
    n_eventos = int(d["_y"].sum())
    if len(d) < 30 or n_eventos < 5 or n_eventos == len(d):
        raise ValueError("Dados insuficientes para o modelo (poucos registros ou eventos).")
    y = d["_y"].astype(float)

    omitidas = set()

    def matriz(cols):
        partes, refs = [], {}
        for c in cols:
            freq = d[c].value_counts()
            freq = freq[freq >= 1]
            ref = referencias.get(c) if referencias.get(c) in freq.index else freq.index[0]
            refs[c] = ref
            dm = pd.get_dummies(d[c], prefix=c, prefix_sep="=", dtype=float)
            dm = dm.drop(columns=[f"{c}={ref}"])
            # remove categorias sem variação no desfecho (separação perfeita)
            for k in list(dm.columns):
                sub = y[dm[k] == 1]
                if len(sub) < 5 or sub.nunique() < 2:
                    dm = dm.drop(columns=[k])
                    omitidas.add(k)
            partes.append(dm)
        X = pd.concat(partes, axis=1) if partes else pd.DataFrame(index=d.index)
        return sm.add_constant(X, has_constant="add"), refs

    def ajustar(X):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return sm.Logit(y, X).fit(disp=0, maxiter=200)

    linhas = []
    Xa, refs = matriz(covariaveis)
    mod_aj = ajustar(Xa)
    ci_aj = mod_aj.conf_int()
    for c in covariaveis:
        Xb, _ = matriz([c])
        mod_b = ajustar(Xb)
        ci_b = mod_b.conf_int()
        linhas.append({"Variável": c, "Categoria": f"{refs[c]} (ref.)", "n": int((d[c] == refs[c]).sum()),
                       "Eventos (%)": _pct_evento(d, c, refs[c]),
                       "OR bruto (IC95%)": "1", "p bruto": "", "OR ajustado (IC95%)": "1", "p ajustado": "",
                       "_or": 1.0, "_inf": 1.0, "_sup": 1.0})
        chaves = [k for k in Xb.columns if k.startswith(f"{c}=")]
        ordem = ordenar_categorias([k.split("=", 1)[1] for k in chaves], d[c].value_counts())
        for k in [f"{c}={o}" for o in ordem]:
            cat = k.split("=", 1)[1]
            orb = np.exp(mod_b.params[k]); ib, sb = np.exp(ci_b.loc[k])
            if k in mod_aj.params:
                ora = np.exp(mod_aj.params[k]); ia, sa = np.exp(ci_aj.loc[k]); pa = mod_aj.pvalues[k]
                txt_a = f"{_num_br(ora, 2)} ({_num_br(ia, 2)}–{_num_br(sa, 2)})"
            else:
                ora = ia = sa = np.nan; pa = np.nan; txt_a = "–"
            linhas.append({"Variável": "", "Categoria": cat, "n": int((d[c] == cat).sum()),
                           "Eventos (%)": _pct_evento(d, c, cat),
                           "OR bruto (IC95%)": f"{_num_br(orb, 2)} ({_num_br(ib, 2)}–{_num_br(sb, 2)})",
                           "p bruto": fmt_p(mod_b.pvalues[k]), "OR ajustado (IC95%)": txt_a,
                           "p ajustado": fmt_p(pa), "_or": ora, "_inf": ia, "_sup": sa, "_var": c})
    resumo = {"n": len(d), "eventos": n_eventos, "pseudo_r2": mod_aj.prsquared, "aic": mod_aj.aic,
              "amostrado": len(df) > max_n, "omitidas": sorted(omitidas)}
    return pd.DataFrame(linhas), resumo


def _pct_evento(d, c, cat):
    s = d.loc[d[c] == cat, "_y"]
    return f"{_num_br(int(s.sum()), 0)} ({_num_br(100 * s.mean())})" if len(s) else "–"


TEXTO_METODOS = (
    "As variáveis categóricas foram descritas por frequências absolutas e relativas e comparadas pelo teste "
    "qui-quadrado de Pearson (ou exato de Fisher quando a frequência esperada foi inferior a cinco em tabelas 2×2), "
    "com o V de Cramér como medida de tamanho de efeito. As variáveis numéricas foram descritas por mediana e "
    "intervalo interquartil e comparadas pelos testes de Mann-Whitney ou Kruskal-Wallis. As taxas brutas foram "
    "calculadas com denominadores do Estudo de Estimativas Populacionais por Município, Idade e Sexo do Ministério "
    "da Saúde (SVSA), disponibilizado no TabNet/DATASUS, com intervalos de confiança de 95% exatos de Poisson; "
    "quando indicado, as taxas foram padronizadas por idade pelo método direto (população-padrão mundial da OMS), "
    "com IC95% gama de Fay-Feuer. A "
    "tendência temporal foi analisada por regressão linear generalizada de Prais-Winsten sobre o logaritmo das "
    "taxas (ou contagens), estimando-se a variação percentual anual (VPA) e seu IC95%; a tendência foi "
    "classificada como crescente, decrescente ou estacionária (p≥0,05). Associações com desfechos binários foram "
    "estimadas por regressão logística, com razões de chances (OR) brutas e ajustadas e IC95%. Adotou-se nível de "
    "significância de 5%. As análises foram realizadas em Python (pandas, SciPy e statsmodels)."
)

TEXTO_METODOS_PERIODOS = (
    "A letalidade hospitalar foi calculada como a proporção de internações com óbito (×100), com IC95% de Wilson; "
    "a letalidade dos agravos notificados, como a proporção de casos com óbito pelo agravo; e a mortalidade "
    "proporcional, como a proporção dos óbitos atribuída à causa estudada. "
    "Os períodos foram comparados pela razão de proporções (ou razão de taxas para contagens e taxas), com IC95% "
    "pelo método logarítmico e teste qui-quadrado (exato de Fisher quando indicado) ou binomial condicional. O efeito "
    "da interrupção foi avaliado por série temporal interrompida (regressão segmentada), estimando-se a mudança "
    "imediata de nível e a mudança de tendência após o início do período pós, com erros-padrão robustos de "
    "Newey-West para autocorrelação e heterocedasticidade e, nas séries mensais, ajuste para sazonalidade."
)
