"""Geração dos produtos para pesquisa: base analítica, dicionário, tabela descritiva, metadados e citação."""

import json
import os
from datetime import date

import pandas as pd

from .catalogo import SISTEMAS

ROTULOS = {
    # derivadas comuns
    "sexo": "Sexo (decodificado)", "raca_cor": "Raça/cor (decodificada)",
    "idade_anos": "Idade em anos (decodificada; frações para menores de 1 ano)",
    "faixa_etaria": "Faixa etária (anos)", "cid10_capitulo": "Capítulo da CID-10 (algarismo romano)",
    "cid10_capitulo_nome": "Nome do capítulo da CID-10",
    # SIM
    "data_obito": "Data do óbito", "ano_obito": "Ano do óbito", "mes_obito": "Mês do óbito",
    "data_nascimento": "Data de nascimento", "obito_infantil": "Óbito em menor de 1 ano",
    "estado_civil": "Estado civil", "escolaridade": "Escolaridade (anos de estudo)",
    "local_ocorrencia": "Local de ocorrência do óbito", "circunstancia_obito": "Circunstância do óbito (causas externas)",
    "causa_basica": "Causa básica do óbito (CID-10)", "causa_basica_cat3": "Causa básica – categoria CID-10 (3 caracteres)",
    # SINASC
    "ano_nascimento": "Ano do nascimento", "mes_nascimento": "Mês do nascimento", "raca_cor_mae": "Raça/cor da mãe",
    "idade_mae": "Idade da mãe (anos; valores <8 ou >65 tratados como faltantes)", "faixa_etaria_mae": "Faixa etária da mãe",
    "escolaridade_mae": "Escolaridade da mãe", "estado_civil_mae": "Estado civil da mãe", "tipo_parto": "Tipo de parto",
    "tipo_gravidez": "Tipo de gravidez", "gestacao_semanas_cat": "Duração da gestação (categorias)",
    "consultas_prenatal": "Número de consultas de pré-natal", "semanas_gestacao": "Semanas de gestação (20–45)",
    "prematuro": "Prematuridade (<37 semanas)", "peso_g": "Peso ao nascer em gramas (200–7000)",
    "baixo_peso": "Baixo peso ao nascer (<2500 g)", "apgar1": "Apgar no 1º minuto", "apgar5": "Apgar no 5º minuto",
    "anomalia_congenita": "Presença de anomalia congênita",
    "peso_nascer_cat": "Peso ao nascer (faixas do TabNet)",
    "apgar1_cat": "Apgar no 1º minuto (faixas)", "apgar5_cat": "Apgar no 5º minuto (faixas)",
    "grupo_robson": "Grupo de Robson", "adequacao_prenatal": "Adequação quantitativa do pré-natal (Kotelchuck)",
    "raca_cor_mae": "Raça/cor da mãe", "estado_civil_mae": "Estado civil da mãe",
    # SINAN
    "classificacao_final": "Classificação final", "criterio_confirmacao": "Critério de confirmação",
    "hospitalizacao": "Hospitalização", "caso_autoctone": "Caso autóctone do município de residência",
    "forma_clinica_tb": "Forma clínica (tuberculose)", "tipo_entrada_tb": "Tipo de entrada (tuberculose)",
    "encerramento_tb": "Situação de encerramento (tuberculose)", "hiv_tb": "Teste de HIV (tuberculose)",
    "classificacao_operacional": "Classificação operacional (hanseníase)",
    "forma_clinica_hans": "Forma clínica (hanseníase)", "mun_notificacao_nome": "Município de notificação",
    # territórios do TabNet
    "regiao_saude": "Região de Saúde (CIR)", "macrorregiao_saude": "Macrorregião de Saúde",
    "microrregiao_ibge": "Microrregião IBGE", "regiao_metropolitana": "Região Metropolitana/RIDE",
    # SIM – óbitos fetais, infantis e maternos
    "tipo_obito": "Tipo de óbito (fetal / não fetal)", "faixa_etaria_infantil": "Idade no óbito infantil (dias)",
    "componente_infantil": "Componente da mortalidade infantil (neonatal precoce/tardio, pós-neonatal)",
    "obito_relacao_parto": "Óbito em relação ao parto (antes/durante/depois)", "obito_investigado": "Óbito investigado",
    "filhos_vivos": "Nº de filhos vivos da mãe", "filhos_mortos": "Nº de perdas fetais/abortos da mãe",
    "obito_na_gravidez": "Óbito de mulher durante a gravidez", "obito_no_puerperio": "Óbito de mulher no puerpério",
    "momento_obito_materno": "Momento do óbito materno",
    # SIH
    "data_internacao": "Data de internação", "data_saida": "Data de saída", "ano_internacao": "Ano de internação",
    "mes_internacao": "Mês de internação", "competencia": "Competência (AAAA-MM)", "carater_internacao": "Caráter da internação",
    "obito_hospitalar": "Óbito durante a internação", "permanencia_dias": "Dias de permanência",
    "valor_total_rs": "Valor total da AIH (R$)", "diag_principal": "Diagnóstico principal (CID-10)",
    "diag_principal_cat3": "Diagnóstico principal – categoria CID-10 (3 caracteres)",
    # SINAN
    "data_notificacao": "Data de notificação", "ano_notificacao": "Ano de notificação",
    "data_diagnostico": "Data do diagnóstico", "ano_diagnostico": "Ano do diagnóstico (usado pelo TabNet)",
    "mes_diagnostico": "Mês do diagnóstico",
    "semana_epi_notificacao": "Semana epidemiológica da notificação", "data_primeiros_sintomas": "Data dos primeiros sintomas",
    "evolucao": "Evolução do caso",
    # SIA
    "valor_aprovado_rs": "Valor aprovado (R$)",
    "ano_processamento": "Ano de processamento (competência da AIH/APAC – equivale ao 'Ano processamento' do TabNet)",
    "mes_processamento": "Mês de processamento (competência)",
    "procedimento": "Procedimento realizado (código SIGTAP)", "procedimento_nome": "Procedimento realizado (SIGTAP)",
    # controle
    "_arquivo_origem": "Arquivo .dbc de origem no FTP do DATASUS", "_status_dado": "Situação do dado (final/preliminar)",
}
ROTULOS_ORIGINAIS = {
    "CAUSABAS": "Causa básica (CID-10)", "CODMUNRES": "Município de residência (IBGE 6 dígitos)",
    "CODMUNOCOR": "Município de ocorrência", "DTOBITO": "Data do óbito (ddmmaaaa)", "IDADE": "Idade codificada",
    "SEXO": "Sexo (código)", "RACACOR": "Raça/cor (código)", "DTNASC": "Data de nascimento",
    "PESO": "Peso ao nascer (g)", "SEMAGESTAC": "Semanas de gestação", "IDADEMAE": "Idade da mãe",
    "DIAG_PRINC": "Diagnóstico principal", "MUNIC_RES": "Município de residência", "VAL_TOT": "Valor total",
    "DT_INTER": "Data de internação (aaaammdd)", "MORTE": "Óbito (1=sim)", "N_AIH": "Número da AIH",
    "ID_AGRAVO": "Agravo (CID-10)", "DT_NOTIFIC": "Data de notificação", "ID_MN_RESI": "Município de residência",
    "NU_IDADE_N": "Idade codificada", "CS_SEXO": "Sexo", "CS_RACA": "Raça/cor", "CNES": "Código CNES do estabelecimento",
    # SIM
    "TIPOBITO": "Tipo de óbito (1 fetal, 2 não fetal)", "HORAOBITO": "Hora do óbito", "NATURAL": "Naturalidade",
    "ESTCIV": "Estado civil", "ESC": "Escolaridade (anos de estudo)", "ESC2010": "Escolaridade (versão 2010)",
    "OCUP": "Ocupação (CBO)", "LOCOCOR": "Local de ocorrência", "CODESTAB": "Estabelecimento (CNES)",
    "ASSISTMED": "Recebeu assistência médica", "NECROPSIA": "Necropsia", "LINHAA": "Causa – linha A",
    "LINHAB": "Causa – linha B", "LINHAC": "Causa – linha C", "LINHAD": "Causa – linha D",
    "LINHAII": "Causas contribuintes (parte II)", "CIRCOBITO": "Circunstância (causas externas)",
    "ACIDTRAB": "Acidente de trabalho", "FONTE": "Fonte da informação", "ATESTANTE": "Atestante",
    "OBITOGRAV": "Óbito na gravidez", "OBITOPUERP": "Óbito no puerpério", "TPMORTEOCO": "Momento do óbito materno",
    "DTATESTADO": "Data do atestado", "DTINVESTIG": "Data da investigação", "DTCADASTRO": "Data de cadastro",
    "CAUSABAS_O": "Causa básica original", "ORIGEM": "Origem do registro",
    # SINASC
    "CODMUNNASC": "Município de nascimento", "LOCNASC": "Local de nascimento", "ESTCIVMAE": "Estado civil da mãe",
    "ESCMAE": "Escolaridade da mãe", "CODOCUPMAE": "Ocupação da mãe", "QTDFILVIVO": "Filhos vivos",
    "QTDFILMORT": "Filhos mortos", "GESTACAO": "Duração da gestação (categorias)", "GRAVIDEZ": "Tipo de gravidez",
    "PARTO": "Tipo de parto", "CONSULTAS": "Consultas de pré-natal (categorias)", "HORANASC": "Hora do nascimento",
    "APGAR1": "Apgar 1º minuto", "APGAR5": "Apgar 5º minuto", "IDANOMAL": "Anomalia congênita",
    "CODANOMAL": "Código da anomalia (CID-10)", "RACACORMAE": "Raça/cor da mãe", "QTDGESTANT": "Gestações anteriores",
    "QTDPARTNOR": "Partos vaginais anteriores", "QTDPARTCES": "Cesáreas anteriores", "IDADEPAI": "Idade do pai",
    "CONSPRENAT": "Nº de consultas de pré-natal", "MESPRENAT": "Mês de início do pré-natal",
    "TPAPRESENT": "Apresentação do RN", "STTRABPART": "Trabalho de parto induzido", "STCESPARTO": "Cesárea antes do trabalho de parto",
    "TPNASCASSI": "Nascimento assistido por", "TPROBSON": "Grupo de Robson", "KOTELCHUCK": "Índice de Kotelchuck",
    "PARIDADE": "Paridade", "DTNASCMAE": "Data de nascimento da mãe", "DTULTMENST": "Data da última menstruação",
    # SIH
    "ANO_CMPT": "Ano de competência", "MES_CMPT": "Mês de competência", "ESPEC": "Especialidade do leito",
    "CGC_HOSP": "CNPJ do hospital", "CEP": "CEP de residência", "NASC": "Data de nascimento",
    "UTI_MES_TO": "Dias de UTI no mês", "MARCA_UTI": "Tipo de UTI", "QT_DIARIAS": "Quantidade de diárias",
    "PROC_SOLIC": "Procedimento solicitado", "PROC_REA": "Procedimento realizado", "VAL_SH": "Valor serviços hospitalares",
    "VAL_SP": "Valor serviços profissionais", "VAL_UTI": "Valor de UTI", "US_TOT": "Valor total em US$",
    "DT_SAIDA": "Data de saída", "DIAG_SECUN": "Diagnóstico secundário", "COBRANCA": "Motivo de saída/permanência",
    "NAT_JUR": "Natureza jurídica", "GESTAO": "Tipo de gestão", "MUNIC_MOV": "Município do estabelecimento",
    "COD_IDADE": "Unidade da idade", "DIAS_PERM": "Dias de permanência", "NACIONAL": "Nacionalidade",
    "CAR_INT": "Caráter da internação", "RACA_COR": "Raça/cor", "INSTRU": "Grau de instrução",
    "CID_ASSO": "CID associado", "CID_MORTE": "CID da morte", "UF_ZI": "Gestor (UF/município)",
    # SINAN
    "TP_NOT": "Tipo de notificação", "NU_ANO": "Ano da notificação", "SG_UF_NOT": "UF de notificação",
    "ID_MUNICIP": "Município de notificação", "ID_UNIDADE": "Unidade notificadora", "DT_SIN_PRI": "Data dos primeiros sintomas",
    "SEM_NOT": "Semana epidemiológica da notificação", "SEM_PRI": "Semana dos primeiros sintomas",
    "ANO_NASC": "Ano de nascimento", "CS_GESTANT": "Gestante", "CS_ESCOL_N": "Escolaridade", "SG_UF": "UF de residência",
    "ID_OCUPA_N": "Ocupação", "CLASSI_FIN": "Classificação final", "CRITERIO": "Critério de confirmação",
    "EVOLUCAO": "Evolução do caso", "DT_OBITO": "Data do óbito", "DT_ENCERRA": "Data de encerramento",
    "HOSPITALIZ": "Hospitalização", "DT_INTERNA": "Data de internação",
    # SIA / CNES
    "PA_CMP": "Competência", "PA_PROC_ID": "Procedimento", "PA_CIDPRI": "CID principal", "PA_SEXO": "Sexo",
    "PA_IDADE": "Idade", "PA_RACACOR": "Raça/cor", "PA_MUNPCN": "Município de residência", "PA_UFMUN": "Município do estabelecimento",
    "PA_QTDAPR": "Quantidade aprovada", "PA_VALAPR": "Valor aprovado", "PA_CBOCOD": "CBO do profissional",
    "CODUFMUN": "Município do estabelecimento", "TP_UNID": "Tipo de unidade", "VINC_SUS": "Vínculo com o SUS",
    "TPGESTAO": "Tipo de gestão", "NIV_HIER": "Nível de hierarquia", "QTLEITP1": "Leitos (tipo 1)",
}


def descricao_campo(c):
    """Rótulo para menus: 'CAMPO – descrição' quando conhecida."""
    d = ROTULOS_ORIGINAIS.get(c.upper())
    return f"{c} – {d}" if d else c
CATEGORICAS_RESUMO = ["sexo", "raca_cor", "faixa_etaria", "estado_civil", "escolaridade", "local_ocorrencia",
                      "circunstancia_obito", "cid10_capitulo_nome", "faixa_etaria_mae", "escolaridade_mae",
                      "tipo_parto", "tipo_gravidez", "gestacao_semanas_cat", "consultas_prenatal", "prematuro",
                      "baixo_peso", "carater_internacao", "obito_hospitalar", "procedimento_nome",
                      "tipo_obito", "componente_infantil", "faixa_etaria_infantil", "peso_nascer_cat",
                      "obito_relacao_parto", "obito_investigado", "momento_obito_materno", "evolucao", "mun_residencia_regiao",
                      "mun_residencia_uf", "_status_dado"]
NUMERICAS_RESUMO = ["idade_anos", "idade_mae", "peso_g", "semanas_gestacao", "apgar5", "permanencia_dias",
                    "valor_total_rs", "valor_aprovado_rs"]


def _rotulo(c):
    if c in ROTULOS:
        return ROTULOS[c]
    if c in ROTULOS_ORIGINAIS:
        return ROTULOS_ORIGINAIS[c] + " [original]"
    for pref, nome in (("mun_residencia", "residência"), ("mun_ocorrencia", "ocorrência"),
                       ("mun_nascimento", "nascimento"), ("mun_internacao", "internação"),
                       ("mun_notificacao", "notificação"), ("mun_estabelecimento", "estabelecimento"),
                       ("mun_atendimento", "atendimento")):
        if c.startswith(pref + "_"):
            suf = c[len(pref) + 1:]
            return {"cod_ibge6": f"Município de {nome} – código IBGE (6 díg.)",
                    "cod_ibge7": f"Município de {nome} – código IBGE (7 díg.)",
                    "nome": f"Município de {nome} – nome (IBGE)", "uf": f"UF de {nome}",
                    "regiao": f"Região de {nome}"}.get(suf, c)
    return "Variável original do DATASUS – ver dicionário oficial" if c.isupper() else ""


def dicionario(df):
    linhas = []
    for c in df.columns:
        s = df[c]
        n_val = int(s.notna().sum())
        ex = s.dropna().astype(str).value_counts().head(3).index.tolist()
        linhas.append({
            "variavel": c, "descricao": _rotulo(c),
            "origem": "original DATASUS" if c.isupper() else ("controle" if c.startswith("_") else "derivada"),
            "tipo": str(s.dtype), "n_validos": n_val, "n_faltantes": int(len(s) - n_val),
            "pct_faltantes": round(100 * (len(s) - n_val) / len(s), 2) if len(s) else None,
            "n_distintos": int(s.nunique(dropna=True)), "exemplos": " | ".join(ex),
        })
    return pd.DataFrame(linhas)


def tabela_descritiva(df, sistema=None):
    """Frequências e medidas-resumo. Variáveis que só se aplicam a parte dos registros (ex.: tipo de parto no SIM,
    só para óbitos fetais e de <1 ano) são descritas nesse universo, indicado na coluna `universo`."""
    from .tratamento import universo
    cat, num = [], []
    for c in CATEGORICAS_RESUMO:
        if c in df:
            u = universo(df, c, sistema)
            s = df[c] if u is None else df.loc[u[0], c]
            if not len(s):
                continue
            vc = s.astype("string").fillna("Sem informação").value_counts()
            for k, v in vc.items():
                cat.append({"variavel": c, "descricao": _rotulo(c), "universo": u[1] if u else "todos os registros",
                            "categoria": k, "n": int(v), "pct": round(100 * v / len(s), 2)})
    for c in NUMERICAS_RESUMO:
        if c in df:
            s = pd.to_numeric(df[c], errors="coerce").dropna().astype(float)
            if len(s):
                num.append({"variavel": c, "descricao": _rotulo(c), "n_validos": len(s),
                            "media": round(s.mean(), 3), "desvio_padrao": round(s.std(), 3),
                            "mediana": round(s.median(), 3), "p25": round(s.quantile(.25), 3),
                            "p75": round(s.quantile(.75), 3), "minimo": round(s.min(), 3), "maximo": round(s.max(), 3)})
    return pd.DataFrame(cat), pd.DataFrame(num)


def _para_parquet(df):
    out = df.copy()
    for c in out.columns:
        if out[c].dtype == object:
            out[c] = out[c].astype("string")
    return out


def salvar(df, pasta, nome_base, formatos, metadados, log=print):
    os.makedirs(pasta, exist_ok=True)
    arquivos = []
    df_out = _para_parquet(df)
    if "parquet" in formatos:
        p = os.path.join(pasta, f"{nome_base}.parquet")
        df_out.to_parquet(p, index=False)
        arquivos.append(p)
    if "csv" in formatos:
        p = os.path.join(pasta, f"{nome_base}.csv")
        df_out.to_csv(p, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
        arquivos.append(p)
    if "xlsx" in formatos:
        if len(df_out) > 1_000_000:
            log("  ! base com mais de 1 milhão de linhas: Excel não suporta; pulando .xlsx (use parquet/csv).")
        else:
            p = os.path.join(pasta, f"{nome_base}.xlsx")
            df_out.to_excel(p, index=False)
            arquivos.append(p)
    if "dta" in formatos:
        p = os.path.join(pasta, f"{nome_base}.dta")
        try:
            d = df_out.copy()
            for c in d.columns:
                if pd.api.types.is_bool_dtype(d[c]) or str(d[c].dtype) == "boolean":
                    d[c] = d[c].astype("Float64")
                elif str(d[c].dtype) == "string":
                    d[c] = d[c].fillna("").astype(object)
                elif str(d[c].dtype) in ("Int64", "Float64"):
                    d[c] = d[c].astype(float)
            d.to_stata(p, write_index=False, version=118,
                       variable_labels={c: _rotulo(c)[:80] for c in d.columns})
            arquivos.append(p)
        except Exception as e:
            log(f"  ! não foi possível gravar .dta: {e}")

    dic = dicionario(df)
    cat, num = tabela_descritiva(df, metadados.get("sistema"))
    p_dic = os.path.join(pasta, "dicionario_variaveis.csv")
    dic.to_csv(p_dic, index=False, encoding="utf-8-sig")
    p_desc = os.path.join(pasta, "tabela_descritiva.xlsx")
    with pd.ExcelWriter(p_desc) as xw:
        (cat if len(cat) else pd.DataFrame({"aviso": ["sem variáveis categóricas derivadas"]})).to_excel(
            xw, sheet_name="categoricas", index=False)
        (num if len(num) else pd.DataFrame({"aviso": ["sem variáveis numéricas derivadas"]})).to_excel(
            xw, sheet_name="numericas", index=False)
        dic.to_excel(xw, sheet_name="dicionario", index=False)
    arquivos += [p_dic, p_desc]

    metadados["produtos"] = [os.path.basename(a) for a in arquivos] + ["metadados.json", "LEIA-ME.md"]
    with open(os.path.join(pasta, "metadados.json"), "w", encoding="utf-8") as fh:
        json.dump(metadados, fh, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(pasta, "LEIA-ME.md"), "w", encoding="utf-8") as fh:
        fh.write(leia_me(metadados))
    return arquivos


def _milhar(n):
    return f"{n:,}".replace(",", ".")


MESES_ABNT = ["jan.", "fev.", "mar.", "abr.", "maio", "jun.", "jul.", "ago.", "set.", "out.", "nov.", "dez."]


def leia_me(m):
    fonte = SISTEMAS[m["sistema"]]
    hoje = date.fromisoformat(m["data_acesso"][:10])
    acesso_abnt = f"{hoje.day} {MESES_ABNT[hoje.month - 1]} {hoje.year}"
    acesso_vanc = hoje.strftime("%Y %b %d")
    dirs = sorted({a["url"].rsplit("/", 1)[0] for a in m["arquivos"]})
    periodo = f"{min(m['anos'])}–{max(m['anos'])}" if len(m["anos"]) > 1 else str(m["anos"][0])
    prelim = [a["nome"] for a in m["arquivos"] if a["status"] == "preliminar"]
    abrangencia = ", ".join(m["ufs"]) if m.get("ufs") else "Brasil"
    filtros = []
    if m.get("cids"):
        filtros.append(f"CID-10 iniciando por {', '.join(m['cids'])}")
    if m.get("procedimentos"):
        nomes = m.get("procedimentos_nomes") or {}
        filtros.append("procedimento(s) SIGTAP " + "; ".join(
            f"{p}" + (f" ({nomes[p]})" if nomes.get(p) else "") for p in m["procedimentos"]))
    if m.get("ufs_residencia"):
        filtros.append(f"residência em {', '.join(m['ufs_residencia'])}")
    filtro_txt = ("; filtros aplicados: " + "; ".join(filtros)) if filtros else ""
    tipo_txt = f" (arquivos {m['tipo']})" if m.get("tipo") else ""

    linhas = [
        f"# {fonte['nome']} – {abrangencia}, {periodo}",
        "",
        f"Gerado em {m['data_acesso']} pelo programa datasus_ciencia v{m['versao_programa']}.",
        "",
        "## Conteúdo",
        "",
        f"- Registros: **{_milhar(m['n_registros'])}**",
        f"- Variáveis: {m['n_variaveis']} (originais em MAIÚSCULAS; derivadas em minúsculas)",
        f"- Arquivos de origem: {len(m['arquivos'])} (lista completa, tamanhos e hash MD5 em `metadados.json`)",
        "- `dicionario_variaveis.csv`: descrição, tipo e completude de cada variável",
        "- `tabela_descritiva.xlsx`: frequências e medidas-resumo (base para a Tabela 1)",
        "",
    ]
    if prelim:
        linhas += ["> **Atenção:** parte dos dados é **preliminar** e pode mudar até o fechamento oficial: "
                   + ", ".join(prelim), ""]
    if m.get("ausentes"):
        linhas += ["> Períodos não encontrados no FTP: " + ", ".join(m["ausentes"]), ""]
    linhas += [
        "## Como citar a fonte",
        "",
        "**ABNT (NBR 6023):**",
        "",
        f"BRASIL. Ministério da Saúde. Departamento de Informação e Informática do SUS (DATASUS). "
        f"**{fonte['nome']}**. Brasília, DF: Ministério da Saúde, {hoje.year}. "
        f"Disponível em: {dirs[0] if dirs else 'ftp://ftp.datasus.gov.br/dissemin/publicos'}. "
        f"Acesso em: {acesso_abnt}.",
        "",
        "**Vancouver:**",
        "",
        f"Ministério da Saúde (BR), Departamento de Informação e Informática do SUS. {fonte['nome']} [Internet]. "
        f"Brasília: Ministério da Saúde; {hoje.year} [citado {acesso_vanc}]. "
        f"Disponível em: {dirs[0] if dirs else 'ftp://ftp.datasus.gov.br/dissemin/publicos'}",
        "",
        "## Texto sugerido para a seção de Métodos",
        "",
        f"Foram utilizados microdados do {fonte['nome']}{tipo_txt}, referentes a {abrangencia}, no período "
        f"de {periodo}, obtidos do repositório público de transferência de arquivos do Departamento de "
        f"Informação e Informática do SUS (DATASUS) em {hoje.strftime('%d/%m/%Y')}{filtro_txt}. Os arquivos no "
        f"formato DBC foram descomprimidos e processados em Python (pyreaddbc, dbfread e pandas); as variáveis "
        f"codificadas foram decodificadas conforme os dicionários oficiais do DATASUS, a idade foi convertida para "
        f"anos, e os códigos de município foram compatibilizados com a malha do IBGE. Ao todo, "
        f"{_milhar(m['n_registros'])} registros foram incluídos"
        + (f"; os dados de {', '.join(sorted({str(a['ano']) for a in m['arquivos'] if a['status'] == 'preliminar'}))} "
           "são preliminares." if prelim else "."),
        "",
        "*Methods (English):* Individual-level data from the Brazilian "
        f"{fonte['nome']} for {abrangencia}, {periodo}, were obtained from the public file repository of the "
        f"Brazilian Ministry of Health's Department of Informatics (DATASUS) on {hoje.isoformat()}. DBC files were "
        "decompressed and processed in Python (pyreaddbc, dbfread, pandas); coded variables were decoded "
        "according to official DATASUS data dictionaries.",
        "",
        "## População (se calcular taxas)",
        "",
        "Use como denominador a base de população do TabNet, a mesma usada pela página Análise:",
        "",
        f"BRASIL. Ministério da Saúde. Secretaria de Vigilância em Saúde e Ambiente. **Estudo de Estimativas "
        f"Populacionais por Município, Idade e Sexo 2000–2025 – Brasil**. Brasília, DF: Ministério da Saúde. "
        f"Disponível em: ftp://ftp.datasus.gov.br/dissemin/publicos/IBGE/POPSVS (TabNet: Demográficas e "
        f"Socioeconômicas → População residente). Acesso em: {acesso_abnt}.",
        "",
        "## Aspectos éticos",
        "",
        "Dados secundários, públicos e sem identificação nominal. Pesquisas que utilizam exclusivamente "
        "informações de acesso/domínio público podem ser dispensadas de apreciação pelo sistema CEP/CONEP "
        "(Resolução CNS nº 510/2016, art. 1º, parágrafo único). Confirme a exigência com o CEP da sua instituição "
        "e com as normas da revista.",
        "",
        "## Cuidados metodológicos",
        "",
        "- Variáveis com muitos faltantes ou 'Ignorado' devem ser relatadas (ver `pct_faltantes` no dicionário).",
        "- A codificação de algumas variáveis mudou ao longo dos anos (ex.: escolaridade, versão da DN/DO); "
        "compare períodos com cautela.",
        "- Para taxas, use denominadores populacionais compatíveis (IBGE/estimativas do DATASUS).",
        "- SIH: cada registro é uma AIH (internação), não um indivíduo; reinternações geram registros distintos.",
        "- SINAN: avalie a classificação final (`CLASSI_FIN`) e remova duplicidades quando aplicável.",
        "",
        "## Reprodutibilidade",
        "",
        "Comando utilizado:",
        "",
        "```",
        m["comando"],
        "```",
        "",
    ]
    return "\n".join(linhas)
