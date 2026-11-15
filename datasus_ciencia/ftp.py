"""Acesso ao FTP público do DATASUS: listagem (com cache), localização e download de arquivos."""

import ftplib
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone

from .catalogo import FTP_HOST, SISTEMAS

CACHE_LISTAGEM_HORAS = 24


class ClienteFTP:
    def __init__(self, pasta_cache, tentativas=4, log=print):
        self.pasta_cache = pasta_cache
        self.tentativas = tentativas
        self.log = log
        self._ftp = None
        os.makedirs(pasta_cache, exist_ok=True)

    # ---------------- conexão ----------------
    def _conectar(self):
        if self._ftp is not None:
            try:
                self._ftp.voidcmd("NOOP")
                return self._ftp
            except Exception:
                self._ftp = None
        ftp = ftplib.FTP(FTP_HOST, timeout=120, encoding="latin-1")
        ftp.login()
        self._ftp = ftp
        return ftp

    def _com_retentativa(self, func):
        ultimo = None
        for i in range(self.tentativas):
            try:
                return func(self._conectar())
            except (ftplib.error_temp, ftplib.error_reply, OSError, EOFError) as e:
                ultimo = e
                self._ftp = None
                espera = 3 * (i + 1)
                self.log(f"  ! falha no FTP ({e}); nova tentativa em {espera}s...")
                time.sleep(espera)
        raise RuntimeError(f"Não foi possível acessar o FTP do DATASUS: {ultimo}")

    def fechar(self):
        if self._ftp is not None:
            try:
                self._ftp.quit()
            except Exception:
                pass
            self._ftp = None

    # ---------------- listagem ----------------
    def listar(self, diretorio, usar_cache=True):
        chave = re.sub(r"[^A-Za-z0-9]+", "_", diretorio).strip("_")
        arq = os.path.join(self.pasta_cache, f"lista_{chave}.json")
        if usar_cache and os.path.exists(arq):
            idade_h = (time.time() - os.path.getmtime(arq)) / 3600
            if idade_h < CACHE_LISTAGEM_HORAS:
                with open(arq, encoding="utf-8") as fh:
                    return json.load(fh)

        def _ls(ftp):
            ftp.cwd(diretorio)
            return ftp.nlst()

        try:
            nomes = self._com_retentativa(_ls)
        except RuntimeError:
            raise
        except ftplib.error_perm:
            nomes = []
        with open(arq, "w", encoding="utf-8") as fh:
            json.dump(nomes, fh)
        return nomes

    def listar_tamanhos(self, diretorio):
        """{nome: tamanho em bytes} via LIST (com cache de 24 h)."""
        chave = re.sub(r"[^A-Za-z0-9]+", "_", diretorio).strip("_")
        arq = os.path.join(self.pasta_cache, f"tam_{chave}.json")
        if os.path.exists(arq) and (time.time() - os.path.getmtime(arq)) / 3600 < CACHE_LISTAGEM_HORAS:
            with open(arq, encoding="utf-8") as fh:
                return json.load(fh)

        def _list(ftp):
            ftp.cwd(diretorio)
            linhas = []
            ftp.retrlines("LIST", linhas.append)
            return linhas

        out = {}
        for ln in self._com_retentativa(_list):
            t = ln.split()
            if len(t) < 4:
                continue
            try:
                tam = int(t[4]) if t[0][0] in "-dl" else int(t[2])
            except (ValueError, IndexError):
                continue
            out[t[-1]] = tam
        with open(arq, "w", encoding="utf-8") as fh:
            json.dump(out, fh)
        return out

    def tamanho(self, diretorio, nome):
        def _sz(ftp):
            ftp.cwd(diretorio)
            ftp.voidcmd("TYPE I")
            return ftp.size(nome)
        try:
            return self._com_retentativa(_sz)
        except Exception:
            return None

    # ---------------- download ----------------
    def baixar(self, diretorio, nome, destino):
        """Baixa o arquivo para `destino` (com cache: não baixa de novo se já existe com mesmo tamanho)."""
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        esperado = self.tamanho(diretorio, nome)
        if os.path.exists(destino) and (esperado is None or os.path.getsize(destino) == esperado):
            return {"baixado_agora": False, "tamanho_bytes": os.path.getsize(destino)}

        parcial = destino + ".part"

        def _get(ftp):
            ftp.cwd(diretorio)
            with open(parcial, "wb") as fh:
                ftp.retrbinary(f"RETR {nome}", fh.write, blocksize=1 << 16)
            return True

        mb = f"{esperado / 1e6:.1f} MB" if esperado else "tamanho desconhecido"
        self.log(f"  ↓ baixando {nome} ({mb})")
        self._com_retentativa(_get)
        if esperado is not None and os.path.getsize(parcial) != esperado:
            raise RuntimeError(f"Download incompleto de {nome}")
        os.replace(parcial, destino)
        return {"baixado_agora": True, "tamanho_bytes": os.path.getsize(destino)}


def md5(caminho):
    h = hashlib.md5()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def agora_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------------- resolução de arquivos ----------------
def _regex_nome(padrao, tipo, uf, ano, mes):
    aaaa = f"{ano:04d}"
    rx = re.escape(padrao)
    rx = rx.replace(r"\{tipo\}", re.escape(tipo or ""))
    rx = rx.replace(r"\{uf\}", re.escape(uf or ""))
    rx = rx.replace(r"\{aaaa\}", aaaa).replace(r"\{aa\}", aaaa[2:])
    rx = rx.replace(r"\{mm\}", f"{mes:02d}" if mes else "")
    # arquivos SIA grandes vêm divididos em partes a, b, c...
    return re.compile(rf"^{rx}[a-z]?\.dbc$", re.IGNORECASE)


def localizar_arquivos(cliente, sistema, tipo, ufs, anos, meses, incluir_preliminares=True):
    """Retorna lista de dicts {diretorio, nome, uf, ano, mes, status, url} e lista de ausentes."""
    fonte = SISTEMAS[sistema]
    encontrados, ausentes = [], []
    grupos = [("final", fonte["final"])]
    if incluir_preliminares and fonte["prelim"]:
        grupos.append(("preliminar", fonte["prelim"]))

    listas = {}

    def lista(d):
        if d not in listas:
            listas[d] = cliente.listar(d)
        return listas[d]

    ufs_iter = ufs if fonte["por_uf"] else [None]
    meses_iter = meses if fonte["periodicidade"] == "mensal" else [None]
    for uf in ufs_iter:
        for ano in anos:
            for mes in meses_iter:
                rx = _regex_nome(fonte["padrao"], tipo, uf, ano, mes)
                achou = False
                for status, dirs in grupos:
                    for d in dirs:
                        d = d.replace("{tipo}", tipo or "")
                        nomes = sorted(n for n in lista(d) if rx.match(n))
                        for n in nomes:
                            encontrados.append({
                                "diretorio": d, "nome": n, "uf": uf, "ano": ano, "mes": mes,
                                "status": status, "url": f"ftp://{FTP_HOST}{d}/{n}",
                            })
                        if nomes:
                            achou = True
                            break
                    if achou:
                        break
                if not achou:
                    rot = f"{tipo or ''} {uf or 'BR'} {ano}" + (f"/{mes:02d}" if mes else "")
                    ausentes.append(rot.strip())
    return encontrados, ausentes


def periodos_disponiveis(cliente, sistema, tipo=None, uf=None):
    """Lista os períodos disponíveis (para o comando `listar`)."""
    fonte = SISTEMAS[sistema]
    rx = re.escape(fonte["padrao"])
    rx = rx.replace(r"\{tipo\}", re.escape(tipo or ""))
    rx = rx.replace(r"\{uf\}", r"(?P<uf>[A-Z]{2})")
    rx = rx.replace(r"\{aaaa\}", r"(?P<ano>\d{4})").replace(r"\{aa\}", r"(?P<aa>\d{2})")
    rx = rx.replace(r"\{mm\}", r"(?P<mes>\d{2})")
    rx = re.compile(rf"^{rx}[A-Z]?\.DBC$", re.IGNORECASE)
    saida = []
    for status, dirs in (("final", fonte["final"]), ("preliminar", fonte["prelim"])):
        for d in dirs:
            d = d.replace("{tipo}", tipo or "")
            for n in cliente.listar(d):
                m = rx.match(n)
                if not m:
                    continue
                g = m.groupdict()
                arq_uf = (g.get("uf") or "BR").upper()
                if uf and fonte["por_uf"] and arq_uf != uf.upper():
                    continue
                ano = int(g["ano"]) if g.get("ano") else 2000 + int(g["aa"]) if int(g["aa"]) < 80 else 1900 + int(g["aa"])
                saida.append((status, arq_uf, ano, int(g["mes"]) if g.get("mes") else None, n))
    return saida
