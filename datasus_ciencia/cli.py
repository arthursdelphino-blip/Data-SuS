"""Interface de linha de comando.

Exemplos:
  datasus sistemas
  datasus listar SIM --uf SP
  datasus baixar SIM --uf SP RJ --anos 2019-2022
  datasus baixar SIH --uf MG --anos 2023 --meses 1-6 --cid I21 I22
  datasus baixar SINAN --tipo DENG --anos 2024 --uf-residencia PE
  datasus agregar dados/processados/<pasta> --por ano_obito mun_residencia_uf sexo
"""

import argparse
import os
import shlex
import sys
from collections import defaultdict

import pandas as pd

from . import __version__
from .catalogo import SISTEMAS, UFS, resolver_sistema
from .ftp import ClienteFTP, periodos_disponiveis
from .pipeline import PASTA_DADOS, RAIZ, ErroPedido, executar


def _intervalo(valores, minimo=None, maximo=None):
    out = []
    for v in valores or []:
        for parte in str(v).split(","):
            parte = parte.strip()
            if not parte:
                continue
            if "-" in parte:
                a, b = parte.split("-", 1)
                out += list(range(int(a), int(b) + 1))
            else:
                out.append(int(parte))
    out = sorted(set(out))
    for x in out:
        if (minimo is not None and x < minimo) or (maximo is not None and x > maximo):
            raise ValueError(f"Valor fora do intervalo: {x}")
    return out


def _ufs(lista):
    if not lista:
        return []
    ufs = []
    for u in lista:
        for p in u.split(","):
            p = p.strip().upper()
            if not p:
                continue
            if p in ("TODAS", "TODOS", "ALL"):
                ufs += list(UFS)
            elif p == "BR" or p in UFS:
                ufs.append(p)
            else:
                raise ValueError(f"UF inválida: {p}")
    return list(dict.fromkeys(ufs))


# ------------------------------------------------------------------ comandos
def cmd_sistemas(_args):
    for k, f in SISTEMAS.items():
        print(f"\n{k:8s} {f['nome']}\n         {f['descricao']}\n         periodicidade: {f['periodicidade']}"
              f"{'' if f['por_uf'] else ' | arquivos nacionais'}")
        if f["tipos"]:
            tipos = ", ".join(f"{t} ({d})" for t, d in f["tipos"].items())
            print(f"         tipos (--tipo): {tipos}" + (f"  [padrão: {f['tipo_padrao']}]" if f["tipo_padrao"] else ""))


def cmd_listar(args):
    sistema = resolver_sistema(args.sistema)
    fonte = SISTEMAS[sistema]
    tipo = (args.tipo or fonte["tipo_padrao"] or "").upper() or None
    if fonte["tipos"] and not tipo:
        sys.exit(f"Informe --tipo para {sistema}. Opções: {', '.join(fonte['tipos'])}")
    cli = ClienteFTP(os.path.join(PASTA_DADOS, ".cache"))
    try:
        itens = periodos_disponiveis(cli, sistema, tipo, (args.uf or None))
    finally:
        cli.fechar()
    if not itens:
        print("Nenhum arquivo encontrado.")
        return
    agrup = defaultdict(set)
    for status, uf, ano, mes, _ in itens:
        agrup[(status, uf)].add((ano, mes))
    print(f"{fonte['nome']}" + (f" – tipo {tipo}" if tipo else ""))
    for (status, uf), per in sorted(agrup.items()):
        anos = sorted({a for a, _ in per})
        meses_ult = sorted(m for a, m in per if a == anos[-1] and m)
        extra = f" (último ano até mês {meses_ult[-1]:02d})" if meses_ult else ""
        print(f"  {status:10s} {uf}: {anos[0]}–{anos[-1]} ({len(anos)} anos){extra}")


def cmd_baixar(args):
    sistema = resolver_sistema(args.sistema)
    try:
        pasta, meta = executar(
            sistema, _intervalo(args.anos, 1979, 2100), ufs=_ufs(args.uf), tipo=args.tipo,
            meses=_intervalo(args.meses, 1, 12), cids=args.cid, ufs_residencia=_ufs(args.uf_residencia),
            municipios=args.municipio, colunas=args.colunas, formatos=args.formato, nome=args.nome,
            somente_finais=args.somente_finais, sem_derivadas=args.sem_derivadas,
            procedimentos=args.proc, modo_leve=args.leve, guardar_brutos=not args.sem_brutos,
            comando="datasus " + " ".join(shlex.quote(x) for x in sys.argv[1:]))
    except ErroPedido as e:
        sys.exit(f"Erro: {e}  (use `datasus listar {sistema}` para ver o que existe)")
    print("\nPronto! Produtos gerados:")
    for p in meta["produtos"]:
        print(f"  - {os.path.relpath(os.path.join(pasta, p), RAIZ)}")


def cmd_agregar(args):
    pasta = args.pasta
    if not os.path.isdir(pasta):
        alt = os.path.join(PASTA_DADOS, "processados", pasta)
        if os.path.isdir(alt):
            pasta = alt
        else:
            sys.exit(f"Pasta não encontrada: {args.pasta}")
    pq = [f for f in os.listdir(pasta) if f.endswith(".parquet") and not f.startswith("agregado")]
    if not pq:
        sys.exit("Nenhum .parquet encontrado na pasta (gere com `datasus baixar ... --formato parquet`).")
    df = pd.read_parquet(os.path.join(pasta, pq[0]))
    faltam = [c for c in args.por if c not in df.columns]
    if faltam:
        sys.exit(f"Variáveis inexistentes: {faltam}. Veja dicionario_variaveis.csv.")
    ag = df.groupby(args.por, dropna=False, observed=True).size().reset_index(name="n")
    if args.soma:
        s = df.groupby(args.por, dropna=False, observed=True)[args.soma].sum(numeric_only=True).reset_index()
        ag = ag.merge(s, on=args.por, how="left")
    nome = "agregado_" + "_".join(args.por)
    ag.to_csv(os.path.join(pasta, nome + ".csv"), index=False, encoding="utf-8-sig")
    ag.to_parquet(os.path.join(pasta, nome + ".parquet"), index=False)
    print(ag.head(30).to_string(index=False))
    print(f"\n{len(ag)} linhas salvas em {os.path.join(pasta, nome)}.csv / .parquet")


# ------------------------------------------------------------------ parser
def main(argv=None):
    p = argparse.ArgumentParser(prog="datasus", description="Busca e organiza microdados do DATASUS para pesquisa científica.")
    p.add_argument("--versao", action="version", version=f"datasus_ciencia {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sistemas", help="Lista os sistemas e tipos de arquivo disponíveis").set_defaults(f=cmd_sistemas)

    pl = sub.add_parser("listar", help="Mostra os períodos disponíveis no FTP")
    pl.add_argument("sistema")
    pl.add_argument("--tipo")
    pl.add_argument("--uf")
    pl.set_defaults(f=cmd_listar)

    pb = sub.add_parser("baixar", help="Baixa, trata e organiza os dados")
    pb.add_argument("sistema", help="SIM, SIM-NAC, SINASC, SIH, SIA, SINAN, CNES")
    pb.add_argument("--uf", nargs="+", help="UF(s) do arquivo: SP RJ ... | TODAS | BR")
    pb.add_argument("--anos", nargs="+", required=True, help="ex.: 2022 | 2018-2022 | 2015,2020")
    pb.add_argument("--meses", nargs="+", help="para sistemas mensais (SIH, SIA, CNES); ex.: 1-6")
    pb.add_argument("--tipo", help="tipo de arquivo (RD, PA, ST, DENG, ...). Veja `datasus sistemas`")
    pb.add_argument("--cid", nargs="+", help="filtra por CID-10 (prefixo): I21 I22 | C50 | X60-X84 não suportado, liste os prefixos")
    pb.add_argument("--proc", nargs="+", help="SIH/SIA: procedimento SIGTAP (código ou prefixo), ex.: 0505020092 0505020106 | 050502")
    pb.add_argument("--leve", action="store_true", help="lê só as variáveis essenciais (recomendado para o Brasil inteiro)")
    pb.add_argument("--sem-brutos", action="store_true", help="apaga cada .dbc após a leitura (economiza disco)")
    pb.add_argument("--uf-residencia", nargs="+", help="mantém só residentes nessas UFs")
    pb.add_argument("--municipio", nargs="+", help="mantém só residentes nesses municípios (código IBGE 6 ou 7 dígitos)")
    pb.add_argument("--colunas", nargs="+", help="lê só estas variáveis originais (economiza memória)")
    pb.add_argument("--formato", nargs="+", default=["parquet", "csv"], choices=["parquet", "csv", "xlsx", "dta"])
    pb.add_argument("--nome", help="nome da pasta de saída (padrão: automático)")
    pb.add_argument("--somente-finais", action="store_true", help="não usa dados preliminares")
    pb.add_argument("--sem-derivadas", action="store_true", help="mantém apenas variáveis originais")
    pb.set_defaults(f=cmd_baixar)

    pa = sub.add_parser("agregar", help="Contagens agregadas a partir de uma base já processada")
    pa.add_argument("pasta", help="pasta em dados/processados (nome ou caminho)")
    pa.add_argument("--por", nargs="+", required=True, help="variáveis de agrupamento")
    pa.add_argument("--soma", nargs="+", help="variáveis numéricas a somar (ex.: valor_total_rs)")
    pa.set_defaults(f=cmd_agregar)

    args = p.parse_args(argv)
    try:
        args.f(args)
    except ValueError as e:
        sys.exit(f"Erro: {e}")


if __name__ == "__main__":
    main()
