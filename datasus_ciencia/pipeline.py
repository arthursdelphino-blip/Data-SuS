"""Fluxo completo de busca → leitura → filtros → tratamento → produtos. Usado pela CLI e pela interface."""

import json
import os
import re

from . import __version__
from .catalogo import SISTEMAS, UFS
from .ftp import ClienteFTP, agora_iso, localizar_arquivos, md5
from .leitura import harmonizar, ler_dbc
from .saida import salvar
from .tratamento import Municipios, expandir_cids, filtrar, filtros_previos, tratar

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PASTA_DADOS = os.path.join(RAIZ, "dados")
PASTA_CACHE = os.path.join(PASTA_DADOS, ".cache")
PASTA_PROCESSADOS = os.path.join(PASTA_DADOS, "processados")


class ErroPedido(Exception):
    """Pedido inválido ou sem dados correspondentes."""


def nome_automatico(sistema, tipo, ufs, anos, cids=None, procedimentos=None):
    partes = [sistema.replace("-", "")]
    if tipo:
        partes.append(tipo)
    partes.append("-".join(ufs) if ufs and len(ufs) <= 4 else ("BR" if not ufs or len(ufs) == 27 else f"{len(ufs)}UFs"))
    partes.append(f"{anos[0]}-{anos[-1]}" if len(anos) > 1 else str(anos[0]))
    if cids:
        partes.append("cid" + "_".join(cids)[:30])
    if procedimentos:
        partes.append("proc" + "_".join(procedimentos)[:34])
    return re.sub(r"[^A-Za-z0-9_\-]", "", "_".join(partes))


def montar_comando(sistema, tipo, ufs, anos, meses, cids, ufs_res, municipios, colunas, formatos,
                   nome, somente_finais, sem_derivadas, procedimentos=None, modo_leve=False):
    def faixa(v):
        v = sorted(v)
        return f"{v[0]}-{v[-1]}" if len(v) > 1 and v == list(range(v[0], v[-1] + 1)) else ",".join(map(str, v))
    c = ["datasus", "baixar", sistema]
    if ufs:
        c += ["--uf", *ufs]
    c += ["--anos", faixa(anos)]
    if meses and SISTEMAS[sistema]["periodicidade"] == "mensal" and meses != list(range(1, 13)):
        c += ["--meses", faixa(meses)]
    if tipo:
        c += ["--tipo", tipo]
    if cids:
        c += ["--cid", *cids]
    if procedimentos:
        c += ["--proc", *procedimentos]
    if modo_leve:
        c.append("--leve")
    if ufs_res:
        c += ["--uf-residencia", *ufs_res]
    if municipios:
        c += ["--municipio", *municipios]
    if colunas:
        c += ["--colunas", *colunas]
    c += ["--formato", *formatos]
    if nome:
        c += ["--nome", nome]
    if somente_finais:
        c.append("--somente-finais")
    if sem_derivadas:
        c.append("--sem-derivadas")
    return " ".join(c)


def _arq_campos(sistema, tipo):
    return os.path.join(PASTA_CACHE, f"campos_{sistema}_{tipo or ''}.json")


def campos_em_cache(sistema, tipo):
    p = _arq_campos(sistema, tipo)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)["campos"]
    return None


def campos_disponiveis(sistema, tipo=None, log=print):
    """Lista as variáveis originais do sistema lendo o cabeçalho do menor arquivo recente no FTP."""
    from .ftp import periodos_disponiveis
    import pyreaddbc
    import tempfile
    from dbfread import DBF

    fonte = SISTEMAS[sistema]
    tipo = (tipo or fonte["tipo_padrao"] or "").upper() or None
    em_cache = campos_em_cache(sistema, tipo)
    if em_cache:
        return em_cache
    cli = ClienteFTP(PASTA_CACHE, log=log)
    try:
        itens = [i for i in periodos_disponiveis(cli, sistema, tipo) if i[0] == "final"]
        if not itens:
            raise ErroPedido("Nenhum arquivo encontrado para este sistema/tipo.")
        ano_max = max(i[2] for i in itens)
        recentes = [i for i in itens if i[2] >= ano_max - 1]
        d = fonte["final"][0].replace("{tipo}", tipo or "")
        tam = cli.listar_tamanhos(d)
        nome = min(recentes, key=lambda i: tam.get(i[4], 10 ** 12))[4]
        destino = os.path.join(PASTA_DADOS, "brutos", sistema, nome.upper().replace(".DBC", ".dbc"))
        cli.baixar(d, nome, destino)
    finally:
        cli.fechar()
    with tempfile.TemporaryDirectory() as tmp:
        dbf = os.path.join(tmp, "a.dbf")
        pyreaddbc.dbc2dbf(destino, dbf)
        campos = list(DBF(dbf, load=False, encoding="latin-1").field_names)
    with open(_arq_campos(sistema, tipo), "w", encoding="utf-8") as fh:
        json.dump({"campos": campos, "arquivo_referencia": nome}, fh)
    return campos


COLUNAS_ESSENCIAIS = {
    "SIM": ["DTOBITO", "DTNASC", "IDADE", "SEXO", "RACACOR", "ESTCIV", "ESC", "LOCOCOR", "CODMUNRES",
            "CODMUNOCOR", "CAUSABAS", "CIRCOBITO", "OBITOGRAV", "OBITOPUERP"],
    "SINASC": ["DTNASC", "SEXO", "RACACOR", "RACACORMAE", "IDADEMAE", "ESCMAE", "ESTCIVMAE", "PARTO", "GRAVIDEZ",
               "GESTACAO", "SEMAGESTAC", "CONSULTAS", "PESO", "APGAR1", "APGAR5", "IDANOMAL", "CODMUNRES",
               "CODMUNNASC", "TPROBSON"],
    "SIH": ["ANO_CMPT", "MES_CMPT", "N_AIH", "IDENT", "DT_INTER", "DT_SAIDA", "NASC", "SEXO", "RACA_COR", "IDADE",
            "COD_IDADE", "DIAG_PRINC", "DIAG_SECUN", "PROC_REA", "PROC_SOLIC", "CAR_INT", "MUNIC_RES", "MUNIC_MOV",
            "CNES", "MORTE", "DIAS_PERM", "UTI_MES_TO", "VAL_TOT", "ESPEC", "COBRANCA"],
    "SIA": ["PA_CMP", "PA_PROC_ID", "PA_CIDPRI", "PA_SEXO", "PA_IDADE", "PA_RACACOR", "PA_MUNPCN", "PA_UFMUN",
            "PA_CODUNI", "PA_QTDAPR", "PA_VALAPR"],
    "SINAN": ["DT_NOTIFIC", "SEM_NOT", "NU_ANO", "ID_AGRAVO", "DT_SIN_PRI", "NU_IDADE_N", "CS_SEXO", "CS_RACA",
              "CS_GESTANT", "CS_ESCOL_N", "ID_MUNICIP", "ID_MN_RESI", "CLASSI_FIN", "CRITERIO", "EVOLUCAO",
              "DT_OBITO", "HOSPITALIZ"],
}
COLUNAS_ESSENCIAIS["SIM-NAC"] = COLUNAS_ESSENCIAIS["SIM"]


def executar(sistema, anos, ufs=None, tipo=None, meses=None, cids=None, ufs_residencia=None,
             municipios=None, colunas=None, formatos=("parquet", "csv"), nome=None,
             somente_finais=False, sem_derivadas=False, comando=None, log=print, progresso=None,
             procedimentos=None, modo_leve=False, guardar_brutos=True):
    """Executa o pedido e devolve (pasta_saida, metadados). `progresso(frac, texto)` é opcional.

    procedimentos: prefixos SIGTAP (SIH/SIA), ex.: ['0505020092'] ou ['050502'].
    modo_leve: lê só as variáveis essenciais do sistema (bases grandes, ex.: Brasil inteiro).
    guardar_brutos: se False, apaga cada .dbc após a leitura (economiza disco).
    """
    procedimentos = [re.sub(r"\D", "", p) for p in (procedimentos or []) if re.sub(r"\D", "", p)] or None
    if modo_leve and not colunas:
        colunas = COLUNAS_ESSENCIAIS.get(sistema)
    fonte = SISTEMAS[sistema]
    tipo = (tipo or fonte["tipo_padrao"] or "").upper() or None
    if fonte["tipos"] and not tipo:
        raise ErroPedido(f"Escolha o tipo de arquivo para {sistema}: {', '.join(fonte['tipos'])}")
    anos = sorted(set(anos or []))
    if not anos:
        raise ErroPedido("Informe ao menos um ano.")
    meses = sorted(set(meses or range(1, 13)))
    ufs = list(ufs or [])
    if fonte["por_uf"] and not ufs:
        raise ErroPedido("Escolha ao menos uma UF.")
    ufs_res = list(ufs_residencia or [])
    if not fonte["por_uf"] and ufs and not ufs_res:
        ufs_res = [u for u in ufs if u in UFS]
    cids_pedidos = [c.strip().upper() for c in (cids or []) if c.strip()] or None
    cids = expandir_cids(cids_pedidos) or None
    municipios = [m.strip() for m in (municipios or []) if m.strip()] or None
    col_set = {c.upper() for c in colunas} if colunas else None
    if col_set:
        from .tratamento import COLUNA_CID, COLUNA_MUN_RES, COLUNA_PROC
        col_set |= {c for c in (COLUNA_CID.get(sistema) if cids else None,
                                COLUNA_PROC.get(sistema) if procedimentos else None,
                                COLUNA_MUN_RES.get(sistema) if (municipios or ufs_res) else None) if c}
    formatos = [f.lower() for f in formatos]
    comando = comando or montar_comando(sistema, tipo, ufs, anos, meses, cids_pedidos, ufs_res, municipios,
                                        None if modo_leve else (sorted(col_set) if col_set else None),
                                        formatos, nome, somente_finais, sem_derivadas,
                                        procedimentos=procedimentos, modo_leve=modo_leve)
    prog = progresso or (lambda f, t: None)
    filtros_pre = filtros_previos(sistema, cids=cids, ufs_residencia=ufs_res, municipios=municipios,
                                  procedimentos=procedimentos)
    nomes_proc = None
    if sistema in ("SIH", "SIA"):
        try:
            from .referencias import sigtap
            nomes_proc = sigtap(PASTA_CACHE)["procedimentos"]
        except Exception as e:
            log(f"  ! tabela SIGTAP indisponível ({e}); nomes de procedimentos não serão incluídos.")

    cli = ClienteFTP(PASTA_CACHE, log=log)
    mun = Municipios(PASTA_CACHE, log=log)
    try:
        log(f"Procurando arquivos de {fonte['nome']}...")
        prog(0.02, "Procurando arquivos no FTP do DATASUS...")
        arquivos, ausentes = localizar_arquivos(cli, sistema, tipo, ufs, anos, meses,
                                                incluir_preliminares=not somente_finais)
        if ausentes:
            log(f"  ! não encontrados: {', '.join(ausentes[:20])}{' ...' if len(ausentes) > 20 else ''}")
        if not arquivos:
            raise ErroPedido("Nenhum arquivo correspondente no FTP para esse período/UF.")
        log(f"  {len(arquivos)} arquivo(s) encontrado(s).")

        partes, registro, falhas = [], [], []
        for i, a in enumerate(arquivos, 1):
            prog(0.05 + 0.8 * (i - 1) / len(arquivos), f"Arquivo {i}/{len(arquivos)}: {a['nome']}")
            destino = os.path.join(PASTA_DADOS, "brutos", sistema, a["nome"].upper().replace(".DBC", ".dbc"))
            df = None
            for tentativa in (1, 2):
                try:
                    info = cli.baixar(a["diretorio"], a["nome"], destino)
                    df = ler_dbc(destino, col_set, filtros_pre)
                    break
                except Exception as e:
                    log(f"  ! erro ao ler {a['nome']} ({e}); " + ("baixando de novo..." if tentativa == 1 else "arquivo ignorado."))
                    if os.path.exists(destino):
                        os.remove(destino)
            if df is None:
                falhas.append(a["nome"])
                continue
            n_bruto = df.attrs.get("n_total", len(df))
            df = filtrar(df, sistema, cids=cids, ufs_residencia=ufs_res, municipios=municipios,
                         procedimentos=procedimentos)
            df["_arquivo_origem"] = a["nome"]
            df["_status_dado"] = a["status"]
            partes.append(df)
            registro.append({**a, "tamanho_bytes": info["tamanho_bytes"], "md5": md5(destino),
                             "registros_no_arquivo": n_bruto, "registros_apos_filtros": len(df)})
            log(f"  [{i}/{len(arquivos)}] {a['nome']}" + (" (preliminar)" if a["status"] == "preliminar" else "")
                + (f": {n_bruto:,} → {len(df):,} após filtros".replace(",", ".") if filtros_pre else f": {len(df):,} registros".replace(",", ".")))
            if not guardar_brutos and os.path.exists(destino):
                os.remove(destino)
    finally:
        cli.fechar()
    if falhas:
        ausentes = list(ausentes) + [f"{n} (falha de leitura)" for n in falhas]
    if not partes:
        raise ErroPedido("Nenhum arquivo pôde ser lido.")

    prog(0.88, "Unindo e tratando variáveis...")
    log("Unindo e tratando variáveis...")
    df = harmonizar(partes)
    df = tratar(df, sistema, mun, nomes_proc)
    ctrl = [c for c in df.columns if c.startswith("_")]
    if sem_derivadas:
        df = df[[c for c in df.columns if c.isupper()] + ctrl]
    else:
        df = df[[c for c in df.columns if c not in ctrl] + ctrl]

    nome = nome or nome_automatico(sistema, tipo, ufs or ufs_res, anos, cids_pedidos, procedimentos)
    pasta = os.path.join(PASTA_PROCESSADOS, nome)
    meta = {
        "versao_programa": __version__, "data_acesso": agora_iso(), "sistema": sistema,
        "sistema_nome": fonte["nome"], "tipo": tipo, "ufs": ufs, "anos": anos,
        "meses": meses if fonte["periodicidade"] == "mensal" else None,
        "cids": cids_pedidos, "cids_prefixos_aplicados": cids, "ufs_residencia": ufs_res, "municipios": municipios,
        "procedimentos": procedimentos,
        "procedimentos_nomes": {p: nomes_proc.get(p) for p in procedimentos} if procedimentos and nomes_proc else None,
        "modo_leve": modo_leve,
        "colunas_solicitadas": sorted(col_set) if col_set else None,
        "n_registros": len(df), "n_variaveis": df.shape[1], "ausentes": ausentes,
        "arquivos": registro, "comando": comando,
    }
    prog(0.93, f"Salvando {len(df):,} registros...".replace(",", "."))
    log(f"Salvando {len(df):,} registros em {pasta}".replace(",", "."))
    salvar(df, pasta, nome, formatos, meta, log=log)
    prog(1.0, "Concluído")
    return pasta, meta
