"""Resumo para congresso montado por regras, sem custo e offline.

1. `extrair_achados` lê as tabelas agregadas do relatório da análise e gera achados em frases prontas,
   ranqueados por critérios estatísticos (significância, tamanho de efeito, magnitude).
2. O usuário marca os achados; `montar_resumo` monta o resumo IMRD (meta 250–300 palavras).
3. Opcional: `salvar_contexto` grava um arquivo para o usuário pedir um texto mais fluido ao Claude Code
   (assinatura do Claude, sem API); `ler_resumo_claude` traz o texto de volta para a interface.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from datetime import datetime

import pandas as pd

from . import estatistica as E

PALAVRAS_MIN, PALAVRAS_MAX = 250, 300
SECOES = [("introducao", "Introdução"), ("objetivo", "Objetivo"), ("metodos", "Métodos"),
          ("resultados", "Resultados"), ("conclusao", "Conclusão")]
ORDEM_REL = {"alta": 0, "media": 1, "baixa": 2}
PASTA_RESUMO = "resumo_congresso"
COMPLETAR_INTRO = "[completar: relevância do tema e lacuna de conhecimento]"
COMPLETAR_CONCL = "[completar: implicações para os serviços de saúde e a pesquisa]"


# ------------------------------------------------------------------ utilidades
def _n(x, casas=1):
    """Número em formato brasileiro (vírgula decimal, ponto de milhar)."""
    if isinstance(x, str):
        return x
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    return E._num_br(float(x), casas)


def _num(txt):
    """'1.234,5' / '-0,040' / '<0,001' / 12.3 → float (None se não der)."""
    if txt is None:
        return None
    if isinstance(txt, (int, float)):
        return None if (isinstance(txt, float) and math.isnan(txt)) else float(txt)
    s = str(txt).strip().replace("−", "-")
    m = re.search(r"-?[\d.]*\d(?:,\d+)?", s)
    if not m:
        return None
    v = m.group(0)
    v = v.replace(".", "").replace(",", ".") if "," in v or re.fullmatch(r"-?\d{1,3}(\.\d{3})+", v) else v
    try:
        return float(v)
    except ValueError:
        return None


def _p(txt):
    """p-valor em texto ('<0,001', '0,050') → float."""
    if txt is None or str(txt).strip() in ("", "–"):
        return None
    s = str(txt)
    return 0.0005 if "<" in s else _num(s)


def _ic(txt):
    """'0,688 (0,667–0,710)' ou '-8,65 a -2,85' → (est, inf, sup) com None onde faltar."""
    nums = [float(x.replace(".", "").replace(",", ".")) if "," in x else float(x)
            for x in re.findall(r"-?\d[\d.]*(?:,\d+)?", str(txt).replace("−", "-"))]
    if len(nums) >= 3:
        return nums[0], nums[1], nums[2]
    if len(nums) == 2:
        return None, nums[0], nums[1]
    return (nums[0] if nums else None), None, None


def _limpar_rotulo(v):
    return re.sub(r"\s*\((decodificad[ao]|derivad[ao])[^)]*\)", "", str(v)).strip()


def _slug(*partes):
    return re.sub(r"[^a-z0-9]+", "_", "_".join(str(p) for p in partes).lower()).strip("_")[:60]


def _achado(id_, texto, relevancia, pontos, motivo, metodo, secao="Resultados", tipo=""):
    return {"id": id_, "texto": texto, "relevancia": relevancia, "pontos": float(pontos or 0),
            "motivo": motivo, "metodo": metodo, "secao": secao, "tipo": tipo}


UF_LOCAL = {"AC": "no Acre", "AL": "em Alagoas", "AP": "no Amapá", "AM": "no Amazonas", "BA": "na Bahia",
            "CE": "no Ceará", "DF": "no Distrito Federal", "ES": "no Espírito Santo", "GO": "em Goiás",
            "MA": "no Maranhão", "MT": "em Mato Grosso", "MS": "em Mato Grosso do Sul", "MG": "em Minas Gerais",
            "PA": "no Pará", "PB": "na Paraíba", "PR": "no Paraná", "PE": "em Pernambuco", "PI": "no Piauí",
            "RJ": "no Rio de Janeiro", "RN": "no Rio Grande do Norte", "RS": "no Rio Grande do Sul",
            "RO": "em Rondônia", "RR": "em Roraima", "SC": "em Santa Catarina", "SP": "em São Paulo",
            "SE": "em Sergipe", "TO": "no Tocantins"}
ROT_VAR = {"raca_cor": "raça/cor", "faixa_etaria": "faixa etária", "estado_civil": "estado civil",
           "circunstancia_obito": "circunstância do óbito", "local_ocorrencia": "local de ocorrência",
           "cid10_capitulo_nome": "capítulo da CID-10", "carater_internacao": "caráter da internação",
           "consultas_prenatal": "consultas de pré-natal", "tipo_parto": "tipo de parto"}
FEMININOS = {"internações"}


def _local(ctx):
    ufs = list(ctx.get("ufs") or [])
    if not ufs or len(ufs) >= 27:
        return "no Brasil"
    if len(ufs) == 1:
        return UF_LOCAL.get(ufs[0], f"em {ufs[0]}")
    return "nas UFs " + ", ".join(ufs[:-1]) + " e " + ufs[-1]


def _filtro(ctx):
    """' (CID-10 I21, I22; sexo: Feminino)' – recorte da base + filtros da análise."""
    partes = [ctx.get("recorte") or "", ctx.get("filtros") if ctx.get("filtros") not in (None, "nenhum") else ""]
    partes = [p for p in partes if p]
    return f" ({'; '.join(partes)})" if partes else ""


def _sig(p, tend=None):
    """Significativo: p<0,05 (ou p=0,050 já classificado como tendência pela tabela)."""
    if tend and tend not in ("estacionária", ""):
        return True
    return p is not None and p < 0.05


def _artigo_evento(evento):
    return {"óbitos": "dos óbitos", "internações": "das internações", "nascidos vivos": "dos nascidos vivos",
            "casos": "dos casos", "procedimentos": "dos procedimentos",
            "estabelecimentos": "dos estabelecimentos"}.get(evento, f"dos {evento}")


def _nome_indicador(ctx):
    ind = ctx.get("indicador") or ""
    nome = ind.split(" (")[0].strip()
    return nome[:1].lower() + nome[1:] if nome else ""


def _medida(ctx, medida_col=""):
    """(nome da medida com artigo, sufixo de unidade) a partir do rótulo 'Medida' das tabelas."""
    m = str(medida_col)
    if ctx.get("indicador") and ("%" in m or m == _nome_indicador(ctx) or "(" in m):
        return f"a {_nome_indicador(ctx)}", "%"
    if m.startswith("taxa") or "taxa" in m.lower():
        pad = " padronizada por idade" if "padronizada" in m.lower() else ""
        por = m.split("/", 1)[1] if "/" in m else (ctx.get("taxa") or "")
        return f"a taxa{pad} de {ctx.get('evento', 'eventos')}", f" por {por}" if por else ""
    return f"o número de {ctx.get('evento', 'registros')}", ""


def assinatura(texto: str) -> str:
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()[:12]


def contar_palavras(texto: str) -> int:
    return len(re.findall(r"\S+", texto or ""))


# ------------------------------------------------------------------ extratores (um por tabela)
def _x_volume(ctx, rel):
    per = ctx.get("periodo")
    ev = ctx.get("evento", "registros")
    filtro = _filtro(ctx)
    txt = f"Foram {'analisadas' if ev in FEMININOS else 'analisados'} {ctx.get('n')} {ev}{filtro} {_local(ctx)}" + \
          (f", entre {per.replace('–', ' e ')}." if per else ".")
    return [_achado("volume", txt, "alta", 1000, "contexto do estudo (sempre recomendado)", "base", tipo="volume")]


def _x_tendencia(ctx, rel):
    t = rel.get("Tendência (Prais-Winsten)")
    out = []
    if t is None:
        return out
    for _, r in t.iterrows():
        vpa, p = _num(r.get("VPA (%)")), _p(r.get("p"))
        if vpa is None:
            continue
        nome, un = _medida(ctx, r.get("Medida", ""))
        a0, a1 = str(r.get("Anos", "")).split("–") if "–" in str(r.get("Anos", "")) else ("", "")
        grupo = str(r.get("Grupo", "Total"))
        pre = "" if grupo == "Total" else f"{grupo}: "
        _, i1, i2 = _ic(r.get("IC95%", ""))
        tend = str(r.get("Tendência", "")).lower()
        txt = f"{pre}{nome if pre else nome[:1].upper() + nome[1:]}"
        un_v = "%" if un == "%" else ""
        txt += (f" passou de {_n(_num(r.get('Inicial')), 2)}{un_v} em {a0} para {_n(_num(r.get('Final')), 2)}"
                f"{un_v if un == '%' else un} em {a1} (VPA = {_n(vpa, 2)}%; IC95%: {_n(i1, 2)} a {_n(i2, 2)}; "
                f"tendência {tend}).")
        if _sig(p, tend) and abs(vpa) >= 1:
            rel_, mot = "alta", f"tendência significativa (p {E.fmt_p(p)}) e VPA de {_n(vpa, 2)}%/ano"
        elif _sig(p, tend):
            rel_, mot = "media", f"p {E.fmt_p(p)}, mas VPA pequeno ({_n(vpa, 2)}%/ano)"
        else:
            rel_, mot = "baixa", f"tendência estacionária (p {E.fmt_p(p) if p is not None else '–'})"
        out.append(_achado(_slug("tend", grupo), txt, rel_, 500 + abs(vpa) * 10 - (grupo != "Total") * 5, mot,
                           "prais", tipo="tendencia"))
    return out


def _x_serie(ctx, rel):
    if "Tendência (Prais-Winsten)" in rel:
        return []
    s = rel.get("Série anual")
    if s is None or "ano" not in s or len(s) < 2:
        return []
    col = next((c for c in ("taxa", "pct", "n") if c in s), None)
    extras = [c for c in s.columns if c not in ("ano", "n", "eventos", "pct", "taxa", "populacao",
                                                "ic95_inf", "ic95_sup")]
    if col is None or extras:
        return []
    s = s.sort_values("ano")
    v0, v1 = float(s[col].iloc[0]), float(s[col].iloc[-1])
    if not v0:
        return []
    var = 100 * (v1 / v0 - 1)
    nome, un = _medida(ctx, {"taxa": "taxa", "pct": "%"}.get(col, ""))
    un_v = "%" if col == "pct" else ""
    txt = (f"{nome[:1].upper() + nome[1:]} passou de {_n(v0, 2 if col != 'n' else 0)}{un_v} em {int(s['ano'].iloc[0])} "
           f"para {_n(v1, 2 if col != 'n' else 0)}{un_v} em {int(s['ano'].iloc[-1])}"
           f"{un if col == 'taxa' else ''} (variação de {_n(var)}%).")
    return [_achado("serie_anual", txt, "media", 300 + abs(var), "variação entre o primeiro e o último ano "
                    "(sem teste de tendência)", "taxa" if col == "taxa" else "descritiva", tipo="serie")]


def _x_periodos(ctx, rel):
    t = rel.get("Comparação de períodos")
    out = []
    if t is None or "Razão B/A (IC95%)" not in t:
        return out
    cols = list(t.columns)
    per_a = next((re.search(r" A \((.+?)\)", c).group(1) for c in cols if re.search(r" A \((.+?)\)", c)), "A")
    per_b = next((re.search(r" B \((.+?)\)", c).group(1) for c in cols if re.search(r" B \((.+?)\)", c)), "B")
    excl = ("n ", "eventos ", "Total ")
    col_a = next((c for c in cols if f"A ({per_a})" in c and not c.startswith(excl)), None)
    col_b = next((c for c in cols if f"B ({per_b})" in c and not c.startswith(excl)), None)
    col_var = next((c for c in cols if c.startswith("Variação")), None)
    if not col_a or not col_b:
        return out
    if col_a.startswith("%"):
        nome, un = f"a {_nome_indicador(ctx) or 'proporção'}", "%"
    elif "taxa" in col_a.lower():
        nome, un = _medida(ctx, col_a.split(" A (")[0])
    else:
        nome, un = f"o número de {ctx.get('evento', 'registros')}", ""
    for _, r in t.iterrows():
        rz, i1, i2 = _ic(r["Razão B/A (IC95%)"])
        p, var = _p(r.get("p")), _num(r.get(col_var)) if col_var else None
        if rz is None:
            continue
        grupo = str(r.get("Grupo", "Total"))
        va = str(r[col_a]).split(" (")[0] if isinstance(r[col_a], str) else _n(r[col_a], 2)
        vb = str(r[col_b]).split(" (")[0] if isinstance(r[col_b], str) else _n(r[col_b], 2)
        un_v = "%" if un == "%" else ""
        pre = "" if grupo == "Total" else f"{grupo}: "
        txt = (f"{pre}{nome[:1].upper() + nome[1:] if not pre else nome} foi de {va}{un_v if un == '%' else un} em "
               f"{per_a} e de {vb}{un_v} em {per_b}"
               f" (razão = {_n(rz, 3)}; IC95%: {_n(i1, 3)}–{_n(i2, 3)}"
               + (f"; variação de {_n(var)}%" if var is not None else "") + f"; p {E.fmt_p(p) if p is not None else '–'}).")
        efeito = abs(var) if var is not None else abs(rz - 1) * 100
        if p is not None and p < 0.05 and efeito >= 10:
            rel_, mot = "alta", f"diferença significativa e relevante ({_n(efeito)}%)"
        elif p is not None and p < 0.05:
            rel_, mot = "media", f"significativa, mas variação pequena ({_n(efeito)}%)"
        else:
            rel_, mot = "baixa", "sem diferença significativa entre os períodos"
        out.append(_achado(_slug("per", grupo), txt, rel_, 450 + efeito - (grupo != "Total") * 5, mot,
                           "comparacao", tipo="comparacao"))
    return out


def _x_its(ctx, rel):
    t = rel.get("Série interrompida")
    out = []
    if t is None:
        return out
    col_niv = next((c for c in t.columns if c.startswith("Mudança de nível")), None)
    col_tend = next((c for c in t.columns if c.startswith("Mudança de tendência")), None)
    if not col_niv or not col_tend:
        return out
    un = re.search(r"por (\w+)", col_tend)
    un = un.group(1) if un else "período"
    un_nivel = " p.p." if ctx.get("indicador") else f" {ctx.get('evento', '')} por {un}"
    for _, r in t.iterrows():
        grupo = str(r.get("Grupo", "Total"))
        en, n1, n2 = _ic(r[col_niv])
        et, t1, t2 = _ic(r[col_tend])
        pn, pt = _p(r.get("p nível")), _p(r.get("p tendência"))
        partes, sig = [], 0
        if pn is not None and pn < 0.05:
            partes.append(f"mudança imediata de nível de {_n(en, 2)}{un_nivel} (IC95%: {_n(n1, 2)} a {_n(n2, 2)}; "
                          f"p {E.fmt_p(pn)})")
            sig += 1
        if pt is not None and pt < 0.05:
            partes.append(f"mudança de tendência de {_n(et, 3)} por {un} (IC95%: {_n(t1, 3)} a {_n(t2, 3)}; "
                          f"p {E.fmt_p(pt)})")
            sig += 1
        pre = "" if grupo == "Total" else f" ({grupo})"
        if partes:
            txt = f"Na série temporal interrompida{pre}, houve " + " e ".join(partes) + " após a interrupção."
            rel_, mot = "alta", "efeito significativo da interrupção"
        else:
            txt = (f"Na série temporal interrompida{pre}, não houve mudança significativa de nível "
                   f"(p {E.fmt_p(pn) if pn is not None else '–'}) nem de tendência (p {E.fmt_p(pt) if pt is not None else '–'}).")
            rel_, mot = "baixa", "sem efeito significativo da interrupção"
        out.append(_achado(_slug("its", grupo), txt, rel_, 440 + sig * 20 - (grupo != "Total") * 5, mot, "its",
                           tipo="its"))
    return out


def _x_logistica(ctx, rel):
    t = rel.get("Regressão logística")
    out = []
    if t is None or "OR ajustado (IC95%)" not in t:
        return out
    var, ref = "", ""
    for _, r in t.iterrows():
        cat = str(r.get("Categoria", ""))
        if str(r.get("Variável", "")).strip():
            var = _limpar_rotulo(r["Variável"])
        if cat.endswith("(ref.)"):
            ref = cat.replace("(ref.)", "").strip()
            continue
        orr, i1, i2 = _ic(r["OR ajustado (IC95%)"])
        p = _p(r.get("p ajustado"))
        if orr is None or p is None or p >= 0.05:
            continue
        txt = (f"{var}: {cat} teve chance {'maior' if orr > 1 else 'menor'} do desfecho que {ref} "
               f"(OR ajustado = {_n(orr, 2)}; IC95%: {_n(i1, 2)}–{_n(i2, 2)}; p {E.fmt_p(p)}).")
        forte = orr >= 1.5 or orr <= 1 / 1.5
        out.append(_achado(_slug("or", var, cat), txt, "alta" if forte else "media",
                           400 + abs(math.log(orr)) * 100, f"OR ajustado {'forte' if forte else 'moderado'} e "
                           f"significativo", "logistica", tipo="logistica"))
    return out


def _x_tabela1(ctx, rel):
    t = rel.get("Tabela 1")
    out = []
    if t is None or "p-valor" not in t:
        return out
    gcols = [c for c in t.columns if re.search(r"\(n=", str(c)) and not str(c).startswith("Total")]
    if len(gcols) < 2:
        return out
    nomes = [re.sub(r"\s*\(n=.*\)$", "", c) for c in gcols]
    blocos, atual = [], None
    for _, r in t.iterrows():
        if str(r.get("Variável", "")) == "n":
            continue
        if str(r.get("Variável", "")).strip():
            atual = {"var": _limpar_rotulo(r["Variável"]), "p": _p(r.get("p-valor")), "teste": r.get("Teste", ""),
                     "efeito": str(r.get("Efeito", "")), "linhas": []}
            blocos.append(atual)
        if atual is not None:
            atual["linhas"].append(r)
    grupo = _limpar_rotulo(ctx.get("grupo") or "grupo")
    for b in blocos:
        p = b["p"]
        v = _num(b["efeito"].replace("V=", "")) if b["efeito"].startswith("V=") else None
        primeira = b["linhas"][0]
        if str(primeira.get("Categoria", "")).startswith("Mediana"):
            vals = [str(primeira[c]).split(" (")[0] for c in gcols]
            comp = " vs ".join(f"{vv} ({nm})" for vv, nm in zip(vals, nomes))
            txt = f"A mediana de {b['var'].lower()} foi {comp} (p {E.fmt_p(p) if p is not None else '–'})."
            rel_ = "media" if p is not None and p < 0.05 else "baixa"
            mot = "diferença significativa entre os grupos" if rel_ == "media" else "sem diferença significativa"
            out.append(_achado(_slug("t1", b["var"]), txt, rel_, 200 + (p is not None and p < 0.05) * 50, mot,
                               "tabela1", tipo="tabela1"))
            continue
        melhor, dif = None, -1
        for r in b["linhas"]:
            pcts = [_num((re.search(r"\(([^)]*)\)", str(r[c])) or [None, None])[1]) for c in gcols]
            if None in pcts:
                continue
            d = max(pcts) - min(pcts)
            if d > dif:
                melhor, dif = (r["Categoria"], pcts), d
        if melhor is None:
            continue
        cat, pcts = melhor
        cat = {"True": "Sim", "False": "Não", "true": "Sim", "false": "Não"}.get(str(cat), cat)
        comp = " vs ".join(f"{_n(pc)}% ({nm})" for pc, nm in zip(pcts, nomes))
        txt = (f"{b['var']} diferiu segundo {grupo.lower()}: {cat} representou {comp} "
               f"(p {E.fmt_p(p) if p is not None else '–'}" + (f"; V de Cramér = {_n(v, 2)}" if v is not None else "") + ").")
        if p is not None and p < 0.05 and v is not None and v >= 0.3:
            rel_, mot = "alta", f"associação significativa com efeito grande (V = {_n(v, 2)})"
        elif p is not None and p < 0.05 and (v is None or v >= 0.1):
            rel_, mot = "media", f"associação significativa com efeito pequeno a moderado (V = {_n(v, 2)})"
        elif p is not None and p < 0.05:
            rel_, mot = "baixa", f"p {E.fmt_p(p)}, mas efeito desprezível (V = {_n(v, 2)}) – típico de amostras grandes"
        else:
            rel_, mot = "baixa", "sem associação significativa"
        out.append(_achado(_slug("t1", b["var"]), txt, rel_, 250 + (v or 0) * 300 + dif, mot, "tabela1",
                           tipo="tabela1"))
    return out


def _x_causas(ctx, rel):
    t = rel.get("Principais causas")
    if t is None or not len(t) or "CID" not in t:
        return []
    top = t.head(3)
    itens = [f"{r['CID']} – {str(r.get('Descrição', '')).strip()} ({_n(_num(r['%']))}%)" for _, r in top.iterrows()]
    lista = ", ".join(itens[:-1]) + (" e " if len(itens) > 1 else "") + itens[-1]
    p1 = _num(top.iloc[0]["%"]) or 0
    txt = f"As principais causas foram {lista}." if len(itens) > 1 else f"A principal causa foi {lista}."
    if p1 >= 90:
        rel_, mot = "baixa", "causa já definida pelo filtro de CID da seleção"
    elif p1 >= 20:
        rel_, mot = "alta", f"uma causa concentra {_n(p1)}% dos registros"
    else:
        rel_, mot = "media", "distribuição de causas (nenhuma concentra ≥20%)"
    return [_achado("causas", txt, rel_, 350 + p1, mot, "descritiva", tipo="causas")]


FRASE_PERFIL = {
    "sexo": "Predominou o sexo {cat_l} ({pct}%).",
    "faixa_etaria": "A faixa etária mais frequente foi a de {cat} anos ({pct}%).",
    "raca_cor": "Predominou a raça/cor {cat_l} ({pct}%).",
    "escolaridade": "A escolaridade mais frequente foi {cat_l} ({pct}%).",
    "estado_civil": "O estado civil mais frequente foi {cat_l} ({pct}%).",
    "local_ocorrencia": "O local de ocorrência mais frequente foi {cat_l} ({pct}%).",
    "carater_internacao": "O caráter de internação mais frequente foi {cat_l} ({pct}%).",
    "tipo_parto": "Predominou o parto {cat_l} ({pct}%).",
    "cid10_capitulo_nome": "O capítulo da CID-10 mais frequente foi {cat_l} ({pct}%).",
    "circunstancia_obito": "Entre as circunstâncias do óbito, a mais frequente foi {cat_l} ({pct}%).",
}
PERFIL_DESTAQUE = {"sexo", "faixa_etaria", "raca_cor"}


def _x_perfil(ctx, rel):
    out = []
    for nome, t in rel.items():
        if not nome.startswith("Perfil – ") or t is None or "categoria" not in t:
            continue
        var = nome.replace("Perfil – ", "")
        validos = t[~t["categoria"].astype(str).isin(list(E.AUSENTES) + ["Sem informação"])]
        if validos.empty or len(t) < 2:
            continue
        r = validos.sort_values("n", ascending=False).iloc[0]
        pct = float(r["%"])
        if pct >= 99.9:
            continue
        cat = str(r["categoria"])
        rot_v = ROT_VAR.get(var, var.replace("_", " "))
        modelo = FRASE_PERFIL.get(var, rot_v[:1].upper() + rot_v[1:] + ": predominou {cat_l} ({pct}%).")
        txt = modelo.format(cat=cat, cat_l=cat.lower(), pct=_n(pct))
        if var in PERFIL_DESTAQUE or pct >= 60:
            rel_, mot = "media", "perfil descritivo principal" if var in PERFIL_DESTAQUE else f"categoria dominante ({_n(pct)}%)"
        else:
            rel_, mot = "baixa", "perfil descritivo secundário"
        out.append(_achado(_slug("perfil", var), txt, rel_, 100 + pct + (var in PERFIL_DESTAQUE) * 100, mot,
                           "descritiva", tipo="perfil"))
    return out


def _x_numericas(ctx, rel):
    t = rel.get("Numéricas")
    out = []
    if t is None or "Mediana" not in t:
        return out
    for _, r in t.iterrows():
        v = str(r["Variável"]).lower()
        md, p25, p75 = (_n(_num(r[c]), 0 if "idade" in v or "dias" in v else 2) for c in ("Mediana", "P25", "P75"))
        if "idade" in v and "mãe" not in v:
            txt, rel_, pts = f"A mediana de idade foi de {md} anos (IIQ: {p25}–{p75}).", "media", 180
        elif "permanência" in v:
            txt, rel_, pts = f"A mediana de permanência foi de {md} dias (IIQ: {p25}–{p75}).", "baixa", 90
        elif "valor" in v:
            txt, rel_, pts = f"O valor mediano foi de R$ {md} (IIQ: {p25}–{p75}).", "baixa", 80
        else:
            nome = _limpar_rotulo(r["Variável"])
            txt, rel_, pts = f"A mediana de {nome.lower()} foi {md} (IIQ: {p25}–{p75}).", "baixa", 70
        out.append(_achado(_slug("num", v[:30]), txt, rel_, pts, "medida descritiva", "descritiva", tipo="numerica"))
    return out


def _x_sazonalidade(ctx, rel):
    t = rel.get("Sazonalidade")
    if t is None or "n" not in t or t["n"].sum() == 0:
        return []
    mx, mn = t.loc[t["n"].idxmax()], t.loc[t["n"].idxmin()]
    if not mn["n"]:
        return []
    razao = mx["n"] / mn["n"]
    txt = (f"O maior número de {ctx.get('evento', 'registros')} ocorreu em {mx['mês']} ({_n(float(mx['%']))}%) e o "
           f"menor em {mn['mês']} ({_n(float(mn['%']))}%).")
    rel_ = "media" if razao >= 1.3 else "baixa"
    return [_achado("sazonalidade", txt, rel_, 60 + razao * 10,
                    f"pico/vale = {_n(razao, 2)}" + (" (sazonalidade marcada)" if razao >= 1.3 else " (pouca variação)"),
                    "descritiva", tipo="sazonalidade")]


def _x_municipios(ctx, rel):
    t = rel.get("Municípios")
    if t is None or len(t) < 2 or "mun_residencia_nome" not in t:
        return []
    if "taxa" in t:
        r = t.sort_values("taxa", ascending=False).iloc[0]
        txt = (f"A maior taxa foi observada em {r['mun_residencia_nome']} ({_n(float(r['taxa']), 2)} por "
               f"{ctx.get('taxa') or 'hab.'}; IC95%: {_n(float(r['ic95_inf']), 2)}–{_n(float(r['ic95_sup']), 2)}).")
    else:
        r = t.sort_values("n", ascending=False).iloc[0]
        tot = t["n"].sum()
        txt = f"{r['mun_residencia_nome']} concentrou {_n(100 * r['n'] / tot)}% dos registros."
    return [_achado("municipios", txt, "baixa", 50, "destaque geográfico (taxas de municípios pequenos são instáveis)",
                    "taxa" if "taxa" in t else "descritiva", tipo="municipios")]


def _x_limitacoes(ctx, rel):
    out = []
    if ctx.get("preliminar"):
        out.append(_achado("lim_preliminar", "Parte dos dados do período mais recente é preliminar e pode ser revisada.",
                           "media", 40, "dados preliminares na seleção", "", secao="Limitações", tipo="limitacao"))
    ign = []
    for nome, t in rel.items():
        if not nome.startswith("Perfil – ") or t is None or "categoria" not in t:
            continue
        pct = t.loc[t["categoria"].astype(str).isin(list(E.AUSENTES) + ["Sem informação"]), "%"].sum()
        if pct >= 10:
            v = nome.replace("Perfil – ", "")
            ign.append((ROT_VAR.get(v, v.replace("_", " ")), pct))
    if ign:
        ign.sort(key=lambda x: -x[1])
        lista = ", ".join(f"{v} ({_n(p)}%)" for v, p in ign[:4])
        out.append(_achado("lim_ignorados", f"Houve proporção elevada de informação ignorada em {lista}.", "media",
                           30 + ign[0][1] / 10, "completude ruim limita a interpretação", "", secao="Limitações",
                           tipo="limitacao"))
    return out


EXTRATORES = [_x_volume, _x_tendencia, _x_serie, _x_periodos, _x_its, _x_logistica, _x_tabela1, _x_causas,
              _x_perfil, _x_numericas, _x_sazonalidade, _x_municipios, _x_limitacoes]


def extrair_achados(ctx: dict, relatorio: dict) -> list[dict]:
    """Achados ranqueados: relevância (alta → baixa), depois magnitude (`pontos`)."""
    achados = []
    for f in EXTRATORES:
        try:
            achados += f(ctx, relatorio)
        except Exception:  # uma tabela com formato inesperado não derruba o resto
            continue
    vistos, unicos = set(), []
    for a in achados:
        if a["id"] not in vistos:
            vistos.add(a["id"])
            unicos.append(a)
    # com linha "Total", os subgrupos da mesma análise ficam no máximo como "média" (resumo mais enxuto)
    for pref in ("tend_", "per_", "its_"):
        if any(a["id"] == pref + "total" for a in unicos):
            for a in unicos:
                if a["id"].startswith(pref) and a["id"] != pref + "total" and a["relevancia"] == "alta":
                    a["relevancia"] = "media"
                    a["motivo"] += " · subgrupo (a linha Total já resume)"
    return sorted(unicos, key=lambda a: (ORDEM_REL[a["relevancia"]], -a["pontos"]))


# ------------------------------------------------------------------ montagem do resumo
FRASES_METODO = {
    "descritiva": "As variáveis foram descritas por frequências absolutas e relativas e por mediana e intervalo "
                  "interquartil (IIQ).",
    "taxa": "As taxas por {taxa} foram calculadas com as estimativas populacionais do MS/SVSA (TabNet), com IC95% "
            "exato de Poisson.",
    "prais": "A tendência temporal foi analisada por regressão de Prais-Winsten, estimando-se a variação percentual "
             "anual (VPA) e seu IC95%.",
    "comparacao": "Os períodos foram comparados pela razão entre as medidas, com IC95% e teste de hipótese.",
    "its": "O efeito da interrupção foi avaliado por série temporal interrompida (regressão segmentada com erros-padrão "
           "de Newey-West).",
    "tabela1": "Os grupos foram comparados pelos testes qui-quadrado (com V de Cramér) e de Mann-Whitney ou "
               "Kruskal-Wallis.",
    "logistica": "Fatores associados foram estimados por regressão logística, com razões de chances (OR) ajustadas e "
                 "IC95%.",
}
ORDEM_METODO = ["descritiva", "taxa", "prais", "comparacao", "its", "tabela1", "logistica"]


def montar_resumo(ctx: dict, achados: list[dict], contexto_usuario: str = "") -> dict:
    """Resumo IMRD (seção → texto) com os achados marcados."""
    metodos = {a["metodo"] for a in achados if a.get("metodo")}
    tipos = {a["tipo"] for a in achados}
    local = _local(ctx)
    per = ctx.get("periodo") or ""
    per_txt = f", {per.replace('–', ' a ')}" if per else ""
    filtro = _filtro(ctx)
    evento_art = _artigo_evento(ctx.get("evento", "registros"))

    # Objetivo
    verbos = []
    if tipos & {"perfil", "causas", "numerica", "tabela1", "sazonalidade", "volume", "municipios"}:
        verbos.append("descrever o perfil")
    if tipos & {"tendencia", "serie", "comparacao", "its"}:
        verbos.append(f"analisar a tendência temporal{' da ' + _nome_indicador(ctx) if ctx.get('indicador') else ''}")
    if "logistica" in tipos:
        verbos.append("identificar fatores associados")
    verbos = verbos or ["descrever o perfil"]
    obj = (", ".join(verbos[:-1]) + " e " + verbos[-1]) if len(verbos) > 1 else verbos[0]
    objetivo = f"{obj[:1].upper() + obj[1:]} {evento_art}{filtro} {local}{per_txt}."

    # Métodos
    serie = bool(tipos & {"tendencia", "serie", "comparacao", "its"})
    desenho = "ecológico de séries temporais" if serie else "transversal descritivo"
    met = [f"Estudo {desenho} com dados secundários do {ctx.get('sistema', 'DATASUS')}, disponibilizados pelo DATASUS."]
    if ctx.get("taxa") and any(a["metodo"] == "taxa" or "por " + str(ctx.get("taxa")) in a["texto"] for a in achados):
        metodos.add("taxa")
    for m in ORDEM_METODO:
        if m in metodos:
            met.append(FRASES_METODO[m].format(taxa=ctx.get("taxa") or "habitantes"))
    if ctx.get("padronizada") and "taxa" in metodos:
        met.append("As taxas foram padronizadas por idade pelo método direto (população-padrão mundial da OMS).")
    if ctx.get("indicador") and serie:
        met.append(f"A {_nome_indicador(ctx)} foi estimada com IC95% de Wilson.")
    if metodos & {"prais", "comparacao", "its", "tabela1", "logistica"}:
        met.append("Adotou-se nível de significância de 5%.")

    # Resultados
    res = [a["texto"] for a in achados if a["secao"] == "Resultados"]
    lim = [a["texto"] for a in achados if a["secao"] == "Limitações"]
    resultados = " ".join(res + lim)

    # Conclusão
    concl = None
    tend = [a for a in achados if a["tipo"] == "tendencia"]
    if tend:
        ts = {re.search(r"tendência (\w+)\)", a["texto"]).group(1) for a in tend if re.search(r"tendência (\w+)\)", a["texto"])}
        nome, _ = _medida(ctx, "%" if ctx.get("indicador") else ("taxa" if ctx.get("taxa") else ""))
        if len(ts) == 1:
            t_ = ts.pop()
            concl = (f"{nome[:1].upper() + nome[1:]} apresentou tendência {t_} {local}{per_txt}"
                     f"{', em todos os grupos analisados' if len(tend) > 1 else ''}.")
        elif ts:
            concl = f"{nome[:1].upper() + nome[1:]} apresentou comportamento distinto entre os grupos analisados."
    if concl is None:
        comp = [a for a in achados if a["tipo"] in ("comparacao", "its")]
        if comp:
            concl = "Houve mudança significativa entre os períodos comparados." if any(
                a["relevancia"] != "baixa" for a in comp) else "Não houve mudança significativa entre os períodos comparados."
        elif "logistica" in tipos:
            concl = "Identificaram-se características associadas ao desfecho, que indicam grupos prioritários para ações."
        else:
            concl = f"Os resultados descrevem o perfil {evento_art} {local}{per_txt} e podem subsidiar o planejamento em saúde."

    return {"introducao": (contexto_usuario or "").strip() or COMPLETAR_INTRO, "objetivo": objetivo,
            "metodos": " ".join(met), "resultados": resultados, "conclusao": f"{concl} {COMPLETAR_CONCL}"}


def texto_final(resumo: dict, titulo: str = "", autores: str = "") -> str:
    partes = [p for p in (titulo.strip(), autores.strip()) if p]
    for chave, rot in SECOES:
        partes.append(f"{rot}: {resumo.get(chave, '').strip()}")
    return "\n\n".join(partes)


# ------------------------------------------------------------------ ponte com o Claude Code (assinatura)
def _tabela_txt(df: pd.DataFrame, max_linhas: int) -> str:
    t = df.drop(columns=[c for c in df.columns if str(c).startswith("_")], errors="ignore")
    extra = ""
    if len(t) > max_linhas:
        extra = f"\n(... {len(t) - max_linhas} linhas omitidas)"
        t = t.head(max_linhas)
    t = t.copy()
    for c in t.columns:
        if pd.api.types.is_float_dtype(t[c]):
            t[c] = t[c].round(2)
    return t.to_csv(index=False, sep="|", lineterminator="\n").strip() + extra


def serializar_contexto(ctx: dict, relatorio: dict, max_linhas: int = 30) -> str:
    """Texto com a descrição da seleção e as tabelas agregadas do relatório."""
    linhas = ["## Seleção analisada"]
    rotulos = {"sistema": "Sistema", "evento": "Unidade", "n": "Registros na seleção", "periodo": "Período",
               "ufs": "UFs", "filtros": "Filtros", "taxa": "Taxas por", "padronizada": "Taxas padronizadas por idade",
               "grupo": "Grupo de comparação", "indicador": "Indicador (proporção)", "preliminar": "Dados preliminares"}
    for chave, rot in rotulos.items():
        v = ctx.get(chave)
        if v not in (None, "", [], False):
            linhas.append(f"- {rot}: {', '.join(map(str, v)) if isinstance(v, (list, tuple)) else v}")
    for nome, tab in relatorio.items():
        if isinstance(tab, pd.DataFrame) and len(tab):
            linhas += ["", f"## Tabela: {nome}", _tabela_txt(tab, max_linhas)]
    return "\n".join(linhas)


def pasta_resumo(pasta_base: str) -> str:
    return os.path.join(pasta_base, PASTA_RESUMO)


def salvar_contexto(pasta_base: str, nome_base: str, ctx: dict, relatorio: dict, marcados: list[dict],
                    resumo_regras: dict | None, titulo: str = "", autores: str = "", contexto_usuario: str = "") -> str:
    """Grava `resumo_congresso/contexto.md` para o usuário pedir o resumo ao Claude Code."""
    pasta = pasta_resumo(pasta_base)
    os.makedirs(pasta, exist_ok=True)
    partes = [f"# Contexto para resumo de congresso – base {nome_base}",
              f"Gerado em {datetime.now():%Y-%m-%d %H:%M} pela interface (aba Relatório).", "",
              "## Pedido do autor",
              f"- Título provisório: {titulo or '(não informado)'}",
              f"- Autores: {autores or '(não informado)'}",
              f"- Contexto/hipótese para a Introdução: {contexto_usuario or '(não informado)'}",
              f"- Formato: IMRD (Introdução, Objetivo, Métodos, Resultados, Conclusão), {PALAVRAS_MIN}–{PALAVRAS_MAX} "
              "palavras no total.", "",
              "## Achados marcados pelo autor (usar somente estes nos Resultados)"]
    partes += [f"- [{a['secao']} · relevância {a['relevancia']}] {a['texto']}" for a in marcados] or ["- (nenhum)"]
    if resumo_regras:
        partes += ["", "## Rascunho montado por regras (pode servir de base)", texto_final(resumo_regras)]
    partes += ["", "## Métodos estatísticos de referência", E.TEXTO_METODOS + " " + E.TEXTO_METODOS_PERIODOS, "",
               serializar_contexto(ctx, relatorio, max_linhas=60)]
    caminho = os.path.join(pasta, "contexto.md")
    with open(caminho, "w", encoding="utf-8") as fh:
        fh.write("\n".join(partes) + "\n")
    return caminho


def ler_resumo_claude(pasta_base: str) -> dict | None:
    """Lê `resumo_congresso/resumo_claude.md` (seções 'Introdução: ...') se for mais novo que o contexto."""
    pasta = pasta_resumo(pasta_base)
    arq, ctx = os.path.join(pasta, "resumo_claude.md"), os.path.join(pasta, "contexto.md")
    if not os.path.exists(arq) or (os.path.exists(ctx) and os.path.getmtime(arq) < os.path.getmtime(ctx)):
        return None
    with open(arq, encoding="utf-8") as fh:
        texto = fh.read()
    rot = "|".join(r for _, r in SECOES)
    partes = re.split(rf"^\**\s*({rot})\s*:?\**\s*:?\s*", texto, flags=re.M)
    achado = {}
    for i in range(1, len(partes) - 1, 2):
        corpo = re.split(r"^\s*(?:---|_Palavras|Palavras:|\(\d+ palavras)", partes[i + 1], flags=re.M)[0]
        achado[partes[i]] = " ".join(corpo.split())
    resumo = {c: achado.get(r, "") for c, r in SECOES}
    return resumo if any(resumo.values()) else None
