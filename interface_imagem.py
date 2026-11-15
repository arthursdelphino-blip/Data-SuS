"""Download de gráficos, mapas e tabelas da interface como imagem (PNG 300 dpi / SVG), prontos para publicação,
com personalização de título, legenda, fonte, eixos, tamanho, letra e cores.

Os gráficos da tela usam o tema escuro; na exportação recebem o tema claro de publicação: fundo branco, tinta escura
e os passos "light" da mesma paleta categórica (skill dataviz, references/palette.md). O sequencial dos mapas é
invertido (claro = pouco, escuro = muito), como manda a convenção em fundo claro. A personalização vale só para a
imagem baixada; a tela não muda.

Uso: `iniciar_figuras(pagina, fonte_padrao)` no início da página; `mostrar_grafico(st, chart, "serie_anual")` e
`mostrar_tabela(st, df, "tabela_1", hide_index=True, ...)` no lugar de `st.altair_chart`/`st.dataframe`;
`botao_zip(container, pagina, nome)` monta o ZIP com tudo. A conversão só roda quando o usuário clica em baixar
(data= callable) ou abre a janela "Personalizar". As escolhas ficam em `st.session_state["_perso_<pagina>_<nome>"]`
(dicionário alterado no lugar, para os downloads já montados verem as mudanças sem rerun da página).
"""

import html
import io
import json
import re
import textwrap
import unicodedata
import zipfile
from copy import deepcopy
from functools import lru_cache
from types import SimpleNamespace

import numpy as np
import pandas as pd
import streamlit as st

# ------------------------------------------------------------------ tema claro de publicação
FUNDO_ESCURO = "#0b1a2e"
ESCURO_PARA_CLARO = {  # passo dark → passo light da paleta categórica validada
    "#3987e5": "#2a78d6", "#d95926": "#eb6834", "#199e70": "#1baf7a", "#c98500": "#eda100",
    "#d55181": "#e87ba4", "#0ca30c": "#008300", "#9085e9": "#6250d6", "#e66767": "#e34948",
    FUNDO_ESCURO: "#ffffff",
}
SERIES_CLARO = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SEQ_ESCURO = ["#184f95", "#1c5cab", "#2a78d6", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"]
SEQ_CLARO = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#2a78d6", "#1c5cab", "#184f95"]
# escala de cinza (impressão): só as 3 primeiras séries ficam bem distintas; o sequencial vai do claro ao escuro
SERIES_CINZA = ["#262626", "#8c8c8c", "#c8c8c8", "#555555", "#a8a8a8", "#000000", "#707070", "#dddddd"]
SEQ_CINZA = ["#ededed", "#d0d0d0", "#ababab", "#878787", "#636363", "#404040", "#1f1f1f"]
CLARO_PARA_CINZA = dict(zip(SERIES_CLARO, SERIES_CINZA))
TINTA, TINTA_2, MUDO, GRADE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
FONTE = "Arial"
LETRA = {"P": 9, "M": 11, "G": 13}  # pt (corpo dos rótulos)
ROT_LETRA = {"P": "Pequena (9 pt)", "M": "Média (11 pt)", "G": "Grande (13 pt)"}
CM_PX = 72 / 2.54  # o Vega desenha a 72 px/pol; o PNG sai a 300 ppi
TAMANHOS = {"Página inteira (17 cm)": (17.0, None), "1 coluna (8,5 cm)": (8.5, None),
            "Slide 16:9 (25 × 14 cm)": (25.0, 14.0), "Personalizado": None}
POS_LEGENDA = {"Automática": None, "Em cima": "top", "À direita": "right", "Embaixo": "bottom", "Sem legenda": "none"}
LOCALE_NUM = {"decimal": ",", "thousands": ".", "grouping": [3], "currency": ["R$ ", ""]}
LOCALE_DATA = {  # d3-time-format pt-BR (eixos de datas: "jul", "2021"...)
    "dateTime": "%A, %e de %B de %Y. %X", "date": "%d/%m/%Y", "time": "%H:%M:%S", "periods": ["AM", "PM"],
    "days": ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"],
    "shortDays": ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"],
    "months": ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
               "novembro", "dezembro"],
    "shortMonths": ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
}


def _config(letra="M", cinza=False):
    b = LETRA.get(letra, 11)
    cor = (SERIES_CINZA if cinza else SERIES_CLARO)
    return {
        "background": "#ffffff",
        "font": FONTE,
        "axis": {"gridColor": GRADE, "domainColor": MUDO, "tickColor": MUDO, "labelColor": TINTA_2,
                 "titleColor": TINTA, "labelFont": FONTE, "titleFont": FONTE, "labelFontSize": b,
                 "titleFontSize": b + 1},
        "axisX": {"labelOverlap": "greedy"},  # figura estreita: esconde rótulos que colidiriam
        "legend": {"labelColor": TINTA_2, "titleColor": TINTA, "labelFont": FONTE, "titleFont": FONTE,
                   "labelFontSize": b, "titleFontSize": b + 1, "symbolOpacity": 1},
        "title": {"color": TINTA, "font": FONTE, "fontSize": b + 3, "subtitleFont": FONTE, "subtitleFontSize": b,
                  "subtitleColor": TINTA_2, "anchor": "start", "offset": 10},
        "header": {"labelColor": TINTA_2, "titleColor": TINTA, "labelFont": FONTE, "titleFont": FONTE,
                   "labelFontSize": b, "titleFontSize": b + 1},
        "text": {"color": TINTA_2, "font": FONTE, "fontSize": b},
        "range": {"category": list(cor)},
        **{m: {"color": cor[0]} for m in ("mark", "bar", "line", "point", "area")},
    }


def _cor(s, cinza):
    s2 = ESCURO_PARA_CLARO.get(s.lower(), s)
    return CLARO_PARA_CINZA.get(s2.lower(), s2) if cinza else s2


def _claro(obj, cinza=False):
    """Troca as cores do tema escuro pelas do claro (ou cinza) em todo o spec (recursivo)."""
    if isinstance(obj, dict):
        return {k: _claro(v, cinza) for k, v in obj.items()}
    if isinstance(obj, list):
        baixo = [str(x).lower() for x in obj]
        if baixo in (SEQ_ESCURO, SEQ_CLARO):
            return list(SEQ_CINZA if cinza else SEQ_CLARO)
        return [_claro(v, cinza) for v in obj]
    if isinstance(obj, str) and obj.startswith("#"):
        return _cor(obj, cinza)
    return obj


def _mesclar(base, novo):
    for k, v in novo.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _mesclar(base[k], v)
        else:
            base[k] = v
    return base


def _larguras_fixas(spec, largura):
    """`width: container` (ou ausente) não existe fora do navegador: fixa a largura em px (gráficos compostos)."""
    if not isinstance(spec, dict):
        return
    compostos = [k for k in ("hconcat", "vconcat", "concat") if k in spec]
    if compostos:
        for k in compostos:
            n = len(spec[k]) if k == "hconcat" else 1
            for sub in spec[k]:
                _larguras_fixas(sub, max(200, largura // max(n, 1)))
        return
    if "facet" in spec or "repeat" in spec:
        return
    if spec.get("width") in (None, "container"):
        spec["width"] = largura


def _encodings(spec):
    if not isinstance(spec, dict):
        return
    if isinstance(spec.get("encoding"), dict):
        yield spec["encoding"]
    for k in ("layer", "hconcat", "vconcat", "concat"):
        for sub in spec.get(k) or []:
            yield from _encodings(sub)
    if isinstance(spec.get("spec"), dict):
        yield from _encodings(spec["spec"])


def _tem_campo(e):
    return isinstance(e, dict) and any(k in e for k in ("field", "aggregate", "datum"))


def spec_publicacao(chart, opcoes=None):
    """Spec Vega-Lite do gráfico com o tema claro de publicação, tamanho em cm e as personalizações de `opcoes`
    (titulo_final, subtitulo, eixo_x, eixo_y, legenda_cores, titulo_legenda, largura_cm, altura_cm, letra, cinza).
    Legenda da figura e fonte entram depois, no rodapé (`exportar_grafico`)."""
    o = opcoes or {}
    cinza = bool(o.get("cinza"))
    spec = _claro(chart.to_dict(), cinza)
    spec.pop("autosize", None)
    composto = any(k in spec for k in ("hconcat", "vconcat", "concat", "facet", "repeat"))
    mapa = '"geoshape"' in json.dumps({k: spec.get(k) for k in ("mark", "layer")})
    larg = round(float(o.get("largura_cm") or 17.0) * CM_PX)
    if composto:
        _larguras_fixas(spec, larg)
    else:  # largura total exata (eixos e legenda incluídos)
        spec["width"] = larg
        spec["autosize"] = {"type": "fit-x", "contains": "padding"}
        if o.get("altura_cm"):
            spec["height"] = round(float(o["altura_cm"]) * CM_PX)
            spec["autosize"]["type"] = "fit"
        elif mapa:
            spec["height"] = round(larg * 0.8)
            spec["autosize"]["type"] = "fit"
        elif isinstance(spec.get("height"), (int, float)):
            # altura acompanha a largura (17 cm → ~290 px); barras com altura por categoria (step) ficam como estão
            spec["height"] = max(150, min(int(spec["height"]), round(larg * 0.6)))

    for enc in _encodings(spec):
        for eixo in ("x", "y"):
            novo = (o.get(f"eixo_{eixo}") or "").strip()
            if novo and _tem_campo(enc.get(eixo)):
                enc[eixo]["title"] = novo
        if (o.get("titulo_legenda") or "").strip() and _tem_campo(enc.get("color")):
            enc["color"]["title"] = o["titulo_legenda"].strip()

    cfg = _config(o.get("letra", "M"), cinza)
    pos = o.get("legenda_cores")
    if pos == "none":
        cfg["legend"]["disable"] = True
    elif pos:
        cfg["legend"]["orient"] = pos
    spec["config"] = _mesclar(spec.get("config", {}), cfg)

    tit, sub = (o.get("titulo_final") or "").strip(), (o.get("subtitulo") or "").strip()
    if tit or sub:
        # o Vega não quebra título: quebra aqui pela largura (≈ 0,55 × corpo por caractere)
        b = LETRA.get(o.get("letra", "M"), 11)
        larg_px = larg if not composto else larg

        def linhas(t, corpo):
            return textwrap.wrap(t, max(20, int(larg_px / (0.55 * corpo)))) or [t]
        t_txt = linhas(tit or sub, b + 3)
        spec["title"] = {"text": t_txt if len(t_txt) > 1 else t_txt[0]}
        if tit and sub:
            s_txt = linhas(sub, b)
            spec["title"]["subtitle"] = s_txt if len(s_txt) > 1 else s_txt[0]
    spec["background"] = "#ffffff"
    spec["padding"] = 12
    return spec


@lru_cache(maxsize=64)
def _converter(spec_json, formato):
    import vl_convert as vlc
    if formato == "png":
        # ppi=300 amplia 300/72 (≈4,2×): 17 cm → 482 px no Vega → 2.008 px no PNG, fontes no tamanho em pt
        return vlc.vegalite_to_png(spec_json, scale=1, ppi=300, format_locale=LOCALE_NUM,
                                   time_format_locale=LOCALE_DATA)
    return vlc.vegalite_to_svg(spec_json, format_locale=LOCALE_NUM, time_format_locale=LOCALE_DATA).encode("utf-8")


# ------------------------------------------------------------------ rodapé (legenda da figura e fonte)
def _linhas_rodape(o):
    o = o or {}
    linhas = [l.strip() for l in (o.get("legenda") or "").splitlines() if l.strip()]
    if (o.get("fonte") or "").strip():
        linhas.append(o["fonte"].strip())
    return linhas


def _quebrar_px(texto, fonte, largura, medir):
    palavras, linhas, atual = texto.split(), [], ""
    for p in palavras:
        teste = f"{atual} {p}".strip()
        if atual and medir.textlength(teste, font=fonte) > largura:
            linhas.append(atual)
            atual = p
        else:
            atual = teste
    return linhas + ([atual] if atual else [])


def _png_com_rodape(png, linhas, pt):
    from PIL import Image, ImageDraw
    im = Image.open(io.BytesIO(png)).convert("RGB")
    esc = 300 / 72
    fs = round(pt * esc)
    f = _fonte(fs)
    margem = round(12 * esc)
    medir = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    q = [t for l in linhas for t in _quebrar_px(l, f, im.width - 2 * margem, medir)]
    alt = round(fs * 1.35)
    topo = im.height - margem // 2
    novo = Image.new("RGB", (im.width, topo + len(q) * alt + margem), "white")
    novo.paste(im, (0, 0))
    dr = ImageDraw.Draw(novo)
    for i, t in enumerate(q):
        dr.text((margem, topo + i * alt), t, font=f, fill=TINTA_2)
    buf = io.BytesIO()
    novo.save(buf, format="PNG", dpi=(300, 300))
    return buf.getvalue()


def _svg_com_rodape(svg, linhas, pt):
    from PIL import Image, ImageDraw
    txt = svg.decode("utf-8")
    m = re.search(r"<svg\b[^>]*>", txt)
    if not m:
        return svg
    raiz = m.group(0)
    w = float(re.search(r'\bwidth="([\d.]+)', raiz).group(1))
    h = float(re.search(r'\bheight="([\d.]+)', raiz).group(1))
    f = _fonte(pt)
    medir = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    q = [t for l in linhas for t in _quebrar_px(l, f, w - 24, medir)]
    alt = pt * 1.35
    topo = h - 6
    novo_h = topo + len(q) * alt + 12
    raiz2 = re.sub(r'\bheight="[\d.]+"', f'height="{novo_h:.0f}"', raiz)
    raiz2 = re.sub(r'viewBox="([\d.\-]+) ([\d.\-]+) ([\d.]+) ([\d.]+)"',
                   lambda mm: f'viewBox="{mm.group(1)} {mm.group(2)} {mm.group(3)} {novo_h:.0f}"', raiz2)
    textos = "".join(
        f'<text x="12" y="{topo + (i + 0.8) * alt:.1f}" font-family="{FONTE}, Helvetica, sans-serif" '
        f'font-size="{pt}" fill="{TINTA_2}">{html.escape(t)}</text>' for i, t in enumerate(q))
    fundo = f'<rect x="0" y="{h:.0f}" width="{w:.0f}" height="{novo_h - h:.0f}" fill="#ffffff"/>'
    txt = txt.replace(raiz, raiz2, 1)
    i = txt.rfind("</svg>")
    return (txt[:i] + f'<g class="rodape">{fundo}{textos}</g>' + txt[i:]).encode("utf-8")


def exportar_grafico(chart, formato="png", opcoes=None):
    """Bytes da imagem (png 300 dpi ou svg) de um gráfico Altair, no tema claro e com as personalizações."""
    bruto = _converter(json.dumps(spec_publicacao(chart, opcoes), ensure_ascii=False, sort_keys=True), formato)
    linhas = _linhas_rodape(opcoes)
    if not linhas:
        return bruto
    pt = LETRA.get((opcoes or {}).get("letra", "M"), 11) - 1
    return _png_com_rodape(bruto, linhas, pt) if formato == "png" else _svg_com_rodape(bruto, linhas, pt)


# ------------------------------------------------------------------ tabela → PNG
def _num(v, casas=None):
    if v is None or v is pd.NA or v is pd.NaT or (isinstance(v, (float, np.floating)) and np.isnan(v)):
        return "–"
    if isinstance(v, (bool, np.bool_)):
        return "Sim" if v else "Não"
    if isinstance(v, (int, np.integer)):
        return f"{int(v):,}".replace(",", ".")
    if isinstance(v, (float, np.floating)):
        v = float(v)
        if casas is None:
            casas = 0 if v.is_integer() else _casas([v])
        s = f"{v:,.{casas}f}"
        return s.replace(",", "X").replace(".", ",").replace("X", ".")
    if isinstance(v, pd.Timestamp):
        return v.strftime("%d/%m/%Y")
    return str(v)


def _casas(valores):
    """Casas decimais comuns a uma coluna: o necessário para mostrar os valores (até 2 se houver valores ≥ 1;
    até 4 se todos forem < 1, ex.: p-valores), para a coluna ficar alinhada ("8,0" e "8,5", não "8" e "8,5")."""
    v = np.asarray([x for x in valores if x is not None and np.isfinite(x)], dtype=float)
    if not len(v) or np.all(np.mod(v, 1) == 0):
        return 0
    teto = 2 if np.nanmax(np.abs(v)) >= 1 else 4
    for c in range(1, teto + 1):
        if np.allclose(np.round(v, c), np.round(v, teto)):
            return c
    return teto


ROT_TABELA = {"n": "n", "ano": "Ano", "pct": "%", "taxa": "Taxa", "ic95_inf": "IC95% inf", "ic95_sup": "IC95% sup",
              "populacao": "População", "numerador": "Numerador", "denominador": "Denominador",
              "categoria": "Categoria", "grupo": "Grupo", "eventos": "Eventos"}


def _cabecalho(c):
    """Nome técnico (snake_case) → rótulo do dicionário; os demais ficam como estão."""
    c = str(c)
    if c in ROT_TABELA:
        return ROT_TABELA[c]
    if re.fullmatch(r"[a-z][a-z0-9_]*", c):
        try:
            from datasus_ciencia.saida import _rotulo
            r = _rotulo(c)
        except Exception:
            r = ""
        if r and not r.startswith("Variável original"):
            return re.sub(r"\s*\(decodificad[ao]\)", "", r)
    return c


def _fonte(tam, negrito=False):
    from PIL import ImageFont
    for nome in (("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf") if negrito else
                 ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf")):
        for pasta in ("C:/Windows/Fonts/", ""):
            try:
                return ImageFont.truetype(pasta + nome, tam)
            except OSError:
                continue
    return ImageFont.load_default(tam)


MAX_LINHAS_TABELA = 60
TAM_TABELA = {"P": 34, "M": 40, "G": 48}  # px a 300 dpi (≈ 8 / 9,6 / 11,5 pt)


def tabela_png(df, titulo=None, incluir_indice=False, max_linhas=MAX_LINHAS_TABELA, opcoes=None):
    """Tabela no estilo de artigo (linhas horizontais no cabeçalho e no fim), PNG 300 dpi. `opcoes`: titulo_final,
    colunas (lista a incluir), renomear {coluna: nome}, casas ("auto" ou int), letra, legenda, fonte."""
    from PIL import Image, ImageDraw
    o = opcoes or {}
    if "titulo_final" in o:  # opcoes_efetivas já resolveu o título (inclusive o padrão da página)
        titulo = o["titulo_final"]
    d = df.reset_index() if incluir_indice else df
    if o.get("colunas"):
        cols = [c for c in o["colunas"] if c in d.columns]
        if cols:
            d = d[cols]
    d = d.head(max_linhas)
    renomear = o.get("renomear") or {}
    cab = [str(renomear.get(str(c)) or _cabecalho(c)) for c in d.columns]
    numericas = [pd.api.types.is_numeric_dtype(d[c]) and not pd.api.types.is_bool_dtype(d[c]) for c in d.columns]
    fixa = o.get("casas")
    fixa = None if fixa in (None, "auto", "Automático") else int(fixa)
    casas = [(fixa if fixa is not None else _casas(pd.to_numeric(d.iloc[:, j], errors="coerce").dropna().astype(float)))
             if numericas[j] and pd.api.types.is_float_dtype(d.iloc[:, j]) else None for j in range(len(cab))]
    # anos (coluna "ano…") sem separador de milhar: 2020, não 2.020
    anos = [numericas[j] and "ano" in str(c).lower() and
            pd.to_numeric(d.iloc[:, j], errors="coerce").dropna().between(1900, 2100).all()
            for j, c in enumerate(d.columns)]
    linhas = [[str(int(v)) if anos[j] and pd.notna(v) else _num(v, casas[j]) for j, v in enumerate(reg)]
              for reg in d.itertuples(index=False, name=None)]

    def quebrar(t, largura=40):
        return textwrap.wrap(t, largura) or [""]

    cab_q = [quebrar(c, 24) for c in cab]
    lin_q = [[quebrar(t) for t in reg] for reg in linhas]

    tam = TAM_TABELA.get(o.get("letra", "M"), 40)
    pad_x, pad_y = round(tam * 0.9), round(tam * 0.4)
    f, fb, fr = _fonte(tam), _fonte(tam, negrito=True), _fonte(round(tam * 0.85))
    alt_linha = int(tam * 1.3)
    alt_rod = int(tam * 0.85 * 1.35)
    medir = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    def larg(t, fonte):
        return medir.textlength(t, font=fonte)

    larguras = []
    for j in range(len(cab)):
        w = max(larg(t, fb) for t in cab_q[j])
        for reg in lin_q:
            w = max(w, max(larg(t, f) for t in reg[j]))
        larguras.append(int(w) + 2 * pad_x)
    margem = 48
    w_tab = sum(larguras)
    rodape = _linhas_rodape(o)
    w_texto = max(w_tab, 1600 if (rodape or titulo) else 0)  # título/rodapé longos não espremem numa tabela estreita
    tit_q = [t for l in (titulo or "").splitlines() if l.strip() for t in _quebrar_px(l, fb, w_texto, medir)]
    rod_q = [t for l in rodape for t in _quebrar_px(l, fr, w_texto, medir)]
    w_total = max(w_tab, min(w_texto, max([larg(t, fb) for t in tit_q] + [larg(t, fr) for t in rod_q] + [0])))
    w_total = int(w_total) + 2 * margem
    h_cab = max(len(c) for c in cab_q) * alt_linha + 2 * pad_y
    h_lin = [max(len(t) for t in reg) * alt_linha + 2 * pad_y for reg in lin_q]
    h_tit = (len(tit_q) * alt_linha + pad_y) if tit_q else 0
    h_rod = (pad_y + len(rod_q) * alt_rod) if rod_q else 0
    h_total = margem + h_tit + h_cab + sum(h_lin) + h_rod + margem
    img = Image.new("RGB", (max(w_total, 300), h_total), "white")
    dr = ImageDraw.Draw(img)
    x_fim = margem + w_tab
    y = margem
    for t in tit_q:
        dr.text((margem, y), t, font=fb, fill=TINTA)
        y += alt_linha
    if tit_q:
        y += pad_y
    esp = 4
    dr.line([(margem, y), (x_fim, y)], fill=TINTA, width=esp)

    def celula(x, y, w, textos, fonte, direita, cor):
        for k, t in enumerate(textos):
            tx = x + w - pad_x - larg(t, fonte) if direita else x + pad_x
            dr.text((tx, y + pad_y + k * alt_linha), t, font=fonte, fill=cor)

    x = margem
    for j, w in enumerate(larguras):
        celula(x, y, w, cab_q[j], fb, numericas[j], TINTA)
        x += w
    y += h_cab
    dr.line([(margem, y), (x_fim, y)], fill=TINTA, width=2)
    for reg, h in zip(lin_q, h_lin):
        x = margem
        for j, w in enumerate(larguras):
            celula(x, y, w, reg[j], f, numericas[j], TINTA_2 if not numericas[j] else TINTA)
            x += w
        y += h
    dr.line([(margem, y), (x_fim, y)], fill=TINTA, width=esp)
    y += pad_y
    for t in rod_q:
        dr.text((margem, y), t, font=fr, fill=TINTA_2)
        y += alt_rod
    buf = io.BytesIO()
    img.save(buf, format="PNG", dpi=(300, 300))
    return buf.getvalue()


# ------------------------------------------------------------------ fonte dos dados
def _periodo(anos):
    anos = sorted({int(a) for a in anos or [] if pd.notna(a)})
    if not anos:
        return ""
    return str(anos[0]) if len(anos) == 1 else f"{anos[0]}–{anos[-1]}"


def fonte_dados(sistemas, ufs=None, anos=None, acesso=None, extra=None):
    """Texto padrão da fonte, ex.: "Fonte: Ministério da Saúde/DATASUS – Sistema de Informações sobre Mortalidade
    (SIM); RJ, 2020–2024. Acesso em 14/11/2026." `sistemas`: nomes; `acesso`: data ISO; `extra`: frase final."""
    sist = [s for s in dict.fromkeys(sistemas or []) if s]
    nomes = " e ".join([", ".join(sist[:-1]), sist[-1]] if len(sist) > 1 else sist)
    if isinstance(ufs, str):
        ufs = [u.strip() for u in ufs.split(",") if u.strip()]
    ufs = sorted(set(ufs or []))
    local = "Brasil" if len(ufs) >= 27 else ", ".join(ufs)
    recorte = "; ".join(p for p in (", ".join(p for p in (local, _periodo(anos)) if p),) if p)
    txt = "Fonte: Ministério da Saúde/DATASUS" + (f" – {nomes}" if nomes else "") + (f"; {recorte}" if recorte else "")
    txt += "."
    if acesso:
        a = str(acesso)[:10].split("-")
        if len(a) == 3:
            txt += f" Acesso em {a[2]}/{a[1]}/{a[0]}."
    if extra:
        txt += " " + extra.strip()
    return txt


def fonte_de_meta(meta, ufs=None, anos=None, extra=None):
    meta = meta or {}
    return fonte_dados([meta.get("sistema_nome") or meta.get("sistema")],
                       meta.get("ufs") if ufs is None else ufs,
                       meta.get("anos") if anos is None else anos, meta.get("data_acesso"), extra)


# ------------------------------------------------------------------ registro das figuras da página
def _slug(nome):
    s = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()[:60] or "figura"


def _legivel(nome):
    return str(nome).replace("_", " ").strip().capitalize()


def iniciar_figuras(pagina, fonte_padrao=""):
    """Zera a lista de figuras/tabelas da página (chamar uma vez por execução, no início) e define a fonte padrão."""
    st.session_state[f"_figuras_{pagina}"] = []
    st.session_state["_figuras_pagina"] = pagina
    definir_fonte(fonte_padrao, escopo=pagina)


def definir_fonte(fonte_padrao, escopo=None):
    """Fonte padrão das próximas figuras/tabelas (ex.: uma por base em "Minhas bases"). Se o usuário editou a fonte
    ("usar em todas"), a edição vale enquanto a fonte padrão do escopo não mudar (outra base, outro recorte)."""
    pagina = st.session_state.get("_figuras_pagina", "geral")
    chave = f"_fonte_{pagina}_{escopo or pagina}"
    h = st.session_state.setdefault(chave, {"padrao": fonte_padrao or "", "editada": None})
    if h["padrao"] != (fonte_padrao or ""):
        h["padrao"], h["editada"] = fonte_padrao or "", None
    st.session_state["_fonte_atual"] = chave


def _fonte_texto(holder):
    return holder["editada"] if holder.get("editada") is not None else holder.get("padrao", "")


def _registrar(tipo, nome, obj):
    pagina = st.session_state.get("_figuras_pagina")
    if pagina is None:
        iniciar_figuras("geral")
        pagina = "geral"
    lista = st.session_state.setdefault(f"_figuras_{pagina}", [])
    if "_fonte_atual" not in st.session_state:
        definir_fonte("", escopo=pagina)
    holder = st.session_state[st.session_state["_fonte_atual"]]
    opts = st.session_state.setdefault(f"_perso_{pagina}_{tipo}_{_slug(nome)}", {})
    n = sum(1 for r in lista if r.tipo == tipo) + 1
    reg = SimpleNamespace(tipo=tipo, nome=nome, obj=obj, n=n, opts=opts, holder=holder,
                          key=f"img_{pagina}_{len(lista) + 1}")
    lista.append(reg)
    return reg


def opcoes_efetivas(reg):
    """Opções salvas + fonte da página + título numerado ("Figura 3 – ..."). Não usa session_state (roda nos
    downloads, em outra thread)."""
    o = dict(reg.opts)
    if o.get("fonte") is None:
        o["fonte"] = _fonte_texto(reg.holder)
    t = o.get("titulo")
    if t is None and reg.tipo == "tabela":  # título que a página já dá à tabela (ex.: indicador e unidade)
        t = reg.obj[1]
    t = (t or "").strip()
    if o.get("numerar"):
        rot = f"{'Figura' if reg.tipo == 'figura' else 'Tabela'} {reg.n}"
        t = f"{rot} – {t}" if t else rot
    o["titulo_final"] = t
    return o


def _personalizado(reg):
    o = reg.opts
    return any(o.get(k) for k in ("titulo", "subtitulo", "legenda", "numerar", "eixo_x", "eixo_y", "titulo_legenda",
                                  "legenda_cores", "cinza", "colunas", "renomear")) or \
        o.get("fonte") is not None or o.get("letra", "M") != "M" or o.get("casas", "auto") != "auto" or \
        o.get("largura_cm", 17.0) != 17.0 or reg.holder.get("editada") is not None


# ------------------------------------------------------------------ janelas "Personalizar"
def _campos_texto(reg, k, rotulo_tipo):
    """Título, numeração, legenda e fonte (comuns a gráfico e tabela). Atualiza reg.opts no lugar."""
    o = reg.opts
    a, b = st.columns([3, 1], vertical_alignment="bottom")
    padrao = (reg.obj[1] or "") if reg.tipo == "tabela" else ""
    o["titulo"] = a.text_input("Título", o.get("titulo", padrao), key=k + "tit",
                               placeholder=f"Ex.: Taxa de mortalidade por sexo, Rio de Janeiro, 2020–2024")
    o["numerar"] = b.checkbox(f"Numerar ({rotulo_tipo} {reg.n})", o.get("numerar", False), key=k + "num")
    if reg.tipo == "figura":
        o["subtitulo"] = st.text_input("Subtítulo", o.get("subtitulo", ""), key=k + "sub")
    o["legenda"] = st.text_area(f"Legenda / nota (abaixo {'do gráfico' if reg.tipo == 'figura' else 'da tabela'})",
                                o.get("legenda", ""), key=k + "leg", height=80,
                                placeholder="Ex.: Faixa sombreada = IC95% exato de Poisson. Uma linha por nota.")
    atual = o["fonte"] if o.get("fonte") is not None else _fonte_texto(reg.holder)
    fonte = st.text_area("Fonte", atual, key=k + "fon", height=68,
                         help="Pré-preenchida com o sistema, o local, o período e a data de acesso. Apague para "
                              "não mostrar.")
    todas = st.checkbox("Usar esta fonte em todas as figuras e tabelas desta página", value=o.get("fonte") is None,
                        key=k + "fon_todas")
    if todas:
        reg.holder["editada"] = None if fonte == reg.holder.get("padrao", "") else fonte
        o["fonte"] = None
    else:
        o["fonte"] = fonte


def _restaurar(reg, k):
    if st.button("↺ Restaurar padrão", key=k + "rest", type="tertiary"):
        reg.opts.clear()
        for chave in [c for c in st.session_state if str(c).startswith(k)]:
            del st.session_state[chave]
        st.rerun(scope="fragment")


@st.dialog("Personalizar figura", width="large")
def _dialogo_grafico(reg):
    o, k = reg.opts, reg.key + "_d_"
    st.caption(f"Figura {reg.n} · {_legivel(reg.nome)}. Muda só a imagem baixada (e o ZIP); a tela continua igual.")
    _campos_texto(reg, k, "Figura")
    with st.expander("Eixos e legenda das cores", expanded=bool(o.get("eixo_x") or o.get("eixo_y") or
                                                                o.get("legenda_cores") or o.get("titulo_legenda"))):
        a, b = st.columns(2)
        o["eixo_x"] = a.text_input("Título do eixo X", o.get("eixo_x", ""), key=k + "ex", placeholder="(manter)")
        o["eixo_y"] = b.text_input("Título do eixo Y", o.get("eixo_y", ""), key=k + "ey", placeholder="(manter)")
        a, b = st.columns(2)
        pos_atual = next((r for r, v in POS_LEGENDA.items() if v == o.get("legenda_cores")), "Automática")
        o["legenda_cores"] = POS_LEGENDA[a.selectbox("Legenda das cores", list(POS_LEGENDA),
                                                     index=list(POS_LEGENDA).index(pos_atual), key=k + "pos")]
        o["titulo_legenda"] = b.text_input("Título da legenda das cores", o.get("titulo_legenda", ""),
                                           key=k + "tleg", placeholder="(manter)")
    with st.expander("Tamanho, letra e cores", expanded=False):
        a, b, c = st.columns(3)
        tam_atual = o.get("tamanho", "Página inteira (17 cm)")
        tam = a.selectbox("Tamanho", list(TAMANHOS), index=list(TAMANHOS).index(tam_atual), key=k + "tam")
        o["tamanho"] = tam
        if TAMANHOS[tam] is None:
            o["largura_cm"] = b.number_input("Largura (cm)", 5.0, 40.0, float(o.get("largura_cm") or 17.0), 0.5,
                                             key=k + "lcm")
            alt = c.number_input("Altura (cm; 0 = automática)", 0.0, 30.0, float(o.get("altura_cm") or 0.0), 0.5,
                                 key=k + "acm")
            o["altura_cm"] = alt or None
        else:
            o["largura_cm"], o["altura_cm"] = TAMANHOS[tam]
        a, b = st.columns(2)
        o["letra"] = a.radio("Tamanho da letra", list(LETRA), index=list(LETRA).index(o.get("letra", "M")),
                             format_func=ROT_LETRA.get, horizontal=True, key=k + "let")
        o["cinza"] = b.toggle("Escala de cinza (impressão)", o.get("cinza", False), key=k + "cin",
                              help="Bem legível com até 3 séries; acima disso, prefira cores.")
    efet = opcoes_efetivas(reg)
    st.markdown("**Prévia**")
    try:
        with st.spinner("Gerando a prévia..."):
            png = exportar_grafico(reg.obj, "png", efet)
        st.image(png, width="stretch")
    except Exception as e:
        png = None
        st.error(f"Não foi possível gerar a imagem: {e}")
    arq = _slug(reg.nome)
    a, b, c = st.columns([1, 1, 1], vertical_alignment="center")
    if png is not None:
        a.download_button("⬇️ PNG (300 dpi)", png, file_name=f"{arq}.png", mime="image/png", type="primary",
                          key=k + "dpng", on_click="ignore", width="stretch")
    b.download_button("⬇️ SVG (editável)", lambda: exportar_grafico(reg.obj, "svg", efet), file_name=f"{arq}.svg",
                      mime="image/svg+xml", key=k + "dsvg", on_click="ignore", width="stretch")
    with c:
        _restaurar(reg, k)
    st.caption("As escolhas ficam salvas: o botão “Baixar imagem” e o ZIP do Relatório já saem personalizados.")


@st.dialog("Personalizar tabela", width="large")
def _dialogo_tabela(reg):
    o, k = reg.opts, reg.key + "_d_"
    df, titulo, indice = reg.obj
    base = df.reset_index() if indice else df
    st.caption(f"Tabela {reg.n} · {_legivel(reg.nome)}. Muda só a imagem baixada (e o ZIP); a tela continua igual.")
    _campos_texto(reg, k, "Tabela")
    with st.expander("Colunas", expanded=bool(o.get("colunas") or o.get("renomear"))):
        todas = [str(c) for c in base.columns]
        sel = st.multiselect("Colunas na imagem (na ordem escolhida)", todas,
                             default=[c for c in (o.get("colunas") or todas) if c in todas], key=k + "cols")
        o["colunas"] = sel if sel and sel != todas else None
        ren = o.get("renomear") or {}
        tab = pd.DataFrame({"Coluna": sel or todas,
                            "Nome na imagem": [ren.get(c) or _cabecalho(c) for c in (sel or todas)]})
        ed = st.data_editor(tab, hide_index=True, disabled=["Coluna"], key=k + "ren", width="stretch")
        o["renomear"] = {c: n for c, n in zip(ed["Coluna"], ed["Nome na imagem"])
                         if isinstance(n, str) and n.strip() and n != _cabecalho(c)} or None
    with st.expander("Números e letra", expanded=False):
        a, b = st.columns(2)
        ops = ["auto", 0, 1, 2, 3]
        o["casas"] = a.selectbox("Casas decimais", ops, index=ops.index(o.get("casas", "auto")),
                                 format_func=lambda v: "Automático (por coluna)" if v == "auto" else str(v),
                                 key=k + "cas")
        o["letra"] = b.radio("Tamanho da letra", list(LETRA), index=list(LETRA).index(o.get("letra", "M")),
                             format_func=ROT_LETRA.get, horizontal=True, key=k + "let")
    efet = opcoes_efetivas(reg)
    st.markdown("**Prévia**")
    try:
        png = tabela_png(df, titulo, indice, opcoes=efet)
        st.image(png, width="stretch")
    except Exception as e:
        png = None
        st.error(f"Não foi possível gerar a imagem: {e}")
    if len(df) > MAX_LINHAS_TABELA:
        st.caption(f"A imagem mostra as primeiras {MAX_LINHAS_TABELA} linhas; a tabela completa está no Excel/CSV.")
    a, b = st.columns(2, vertical_alignment="center")
    if png is not None:
        a.download_button("⬇️ PNG (300 dpi)", png, file_name=f"{_slug(reg.nome)}.png", mime="image/png",
                          type="primary", key=k + "dpng", on_click="ignore", width="stretch")
    with b:
        _restaurar(reg, k)
    st.caption("As escolhas ficam salvas: o botão “Baixar tabela” e o ZIP do Relatório já saem personalizados.")


# ------------------------------------------------------------------ componentes da interface
def mostrar_grafico(container, chart, nome, width="stretch", **kwargs):
    """Exibe o gráfico (ou mapa) e, abaixo, "Baixar imagem" (PNG 300 dpi/SVG) e "Personalizar"."""
    container.altair_chart(chart, width=width, **kwargs)
    reg = _registrar("figura", nome, chart)
    arq = _slug(nome)
    linha = container.container(horizontal=True, gap="small", vertical_alignment="center")
    with linha.popover("🖼️ Baixar imagem", key=f"{reg.key}_pop"):
        st.download_button("PNG (300 dpi)", lambda: exportar_grafico(chart, "png", opcoes_efetivas(reg)),
                           file_name=f"{arq}.png", mime="image/png", key=f"{reg.key}_png", on_click="ignore",
                           width="stretch")
        st.download_button("SVG (editável)", lambda: exportar_grafico(chart, "svg", opcoes_efetivas(reg)),
                           file_name=f"{arq}.svg", mime="image/svg+xml", key=f"{reg.key}_svg", on_click="ignore",
                           width="stretch")
        st.caption("Fundo branco, com a fonte dos dados. Título, legenda, eixos e tamanho: 🎨 Personalizar."
                   + (" **Com as suas personalizações.**" if _personalizado(reg) else ""))
    if linha.button("🎨 Personalizar", key=f"{reg.key}_perso", type="tertiary",
                    help="Título, legenda, fonte, eixos, tamanho, letra e cores da imagem baixada"):
        _dialogo_grafico(reg)


def mostrar_tabela(container, df, nome, titulo=None, **kwargs):
    """Exibe a tabela (st.dataframe com os mesmos argumentos) e, abaixo, "Baixar tabela (PNG)" e "Personalizar"."""
    container.dataframe(df, **kwargs)
    if not isinstance(df, pd.DataFrame):  # Styler (ou outro objeto) → os dados por trás
        df = getattr(df, "data", None)
        if not isinstance(df, pd.DataFrame):
            return
    if df is None or len(df) == 0:
        return
    indice = not kwargs.get("hide_index") and not isinstance(df.index, pd.RangeIndex)
    reg = _registrar("tabela", nome, (df, titulo, indice))
    rot = "🖼️ Baixar tabela (PNG)"
    if len(df) > MAX_LINHAS_TABELA:
        rot = f"🖼️ Baixar primeiras {MAX_LINHAS_TABELA} linhas (PNG)"
    linha = container.container(horizontal=True, gap="small", vertical_alignment="center")
    linha.download_button(rot, lambda: tabela_png(df, titulo, indice, opcoes=opcoes_efetivas(reg)),
                          file_name=f"{_slug(nome)}.png", mime="image/png", key=reg.key, on_click="ignore",
                          type="tertiary")
    if linha.button("🎨 Personalizar", key=f"{reg.key}_perso", type="tertiary",
                    help="Título, legenda, fonte, colunas, casas decimais e letra da imagem baixada"):
        _dialogo_tabela(reg)


def zip_figuras(itens):
    """ZIP com as figuras (PNG e SVG) e tabelas (PNG) registradas, numeradas na ordem da tela, com as
    personalizações salvas."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for reg in itens:
            try:
                o = opcoes_efetivas(reg)
                if reg.tipo == "figura":
                    base = f"Figura_{reg.n:02d}_{_slug(reg.nome)}"
                    z.writestr(base + ".png", exportar_grafico(reg.obj, "png", o))
                    z.writestr(base + ".svg", exportar_grafico(reg.obj, "svg", o))
                else:
                    df, titulo, indice = reg.obj
                    z.writestr(f"Tabela_{reg.n:02d}_{_slug(reg.nome)}.png", tabela_png(df, titulo, indice, opcoes=o))
            except Exception as e:  # uma figura com problema não impede as demais
                z.writestr(f"ERRO_{_slug(reg.nome)}.txt", f"{type(e).__name__}: {e}")
    return buf.getvalue()


def botao_zip(container, pagina, nome_arquivo):
    # a lista é capturada agora (a geração roda em outra thread, sem session_state); itens exibidos depois do
    # botão na mesma execução também entram, porque é o mesmo objeto
    itens = st.session_state.get(f"_figuras_{pagina}", [])
    if not itens:
        return
    container.download_button("🖼️ Baixar todas as figuras e tabelas (ZIP)", lambda: zip_figuras(list(itens)),
                              file_name=f"{_slug(nome_arquivo)}.zip", mime="application/zip",
                              key=f"zip_{pagina}", on_click="ignore",
                              help="PNG 300 dpi e SVG de cada gráfico/mapa e PNG de cada tabela exibidos nesta "
                                   "página, com título, legenda e fonte personalizados.")
