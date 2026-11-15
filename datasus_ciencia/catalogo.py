"""Catálogo dos sistemas do DATASUS disponíveis no FTP público.

Cada fonte descreve: diretório(s) no FTP, padrão de nome de arquivo e periodicidade.
Padrões aceitam os marcadores {tipo}, {uf}, {aaaa}, {aa}, {mm}.
"""

FTP_HOST = "ftp.datasus.gov.br"
BASE = "/dissemin/publicos"

UFS = {
    "AC": "12", "AL": "27", "AP": "16", "AM": "13", "BA": "29", "CE": "23",
    "DF": "53", "ES": "32", "GO": "52", "MA": "21", "MT": "51", "MS": "50",
    "MG": "31", "PA": "15", "PB": "25", "PR": "41", "PE": "26", "PI": "22",
    "RJ": "33", "RN": "24", "RS": "43", "RO": "11", "RR": "14", "SC": "42",
    "SP": "35", "SE": "28", "TO": "17",
}
UF_POR_CODIGO = {v: k for k, v in UFS.items()}
REGIOES = {"1": "Norte", "2": "Nordeste", "3": "Sudeste", "4": "Sul", "5": "Centro-Oeste"}


def _f(nome, descricao, final, prelim, padrao, periodicidade, por_uf=True, tipos=None, tipo_padrao=None):
    return {
        "nome": nome, "descricao": descricao, "final": final, "prelim": prelim,
        "padrao": padrao, "periodicidade": periodicidade, "por_uf": por_uf,
        "tipos": tipos or {}, "tipo_padrao": tipo_padrao,
    }


SISTEMAS = {
    "SIM": _f(
        "Sistema de Informações sobre Mortalidade (SIM)",
        "Declarações de óbito por local de residência (CID-10, 1996+).",
        [f"{BASE}/SIM/CID10/DORES"], [f"{BASE}/SIM/PRELIM/DORES"],
        "DO{uf}{aaaa}", "anual",
    ),
    "SIM-NAC": _f(
        "Sistema de Informações sobre Mortalidade (SIM) – arquivos nacionais",
        "Óbitos fetais (DOFET), por causas externas (DOEXT), infantis (DOINF) e maternos (DOMAT) – Brasil.",
        [f"{BASE}/SIM/CID10/DOFET"], [f"{BASE}/SIM/PRELIM/DOFET"],
        "{tipo}{aa}", "anual", por_uf=False,
        tipos={"DOFET": "Óbitos fetais", "DOEXT": "Óbitos por causas externas",
               "DOINF": "Óbitos infantis", "DOMAT": "Óbitos maternos"},
        tipo_padrao="DOFET",
    ),
    "SINASC": _f(
        "Sistema de Informações sobre Nascidos Vivos (SINASC)",
        "Declarações de nascido vivo por local de residência da mãe (1996+).",
        [f"{BASE}/SINASC/1996_/Dados/DNRES"], [f"{BASE}/SINASC/PRELIM/DNRES"],
        "DN{uf}{aaaa}", "anual",
    ),
    "SIH": _f(
        "Sistema de Informações Hospitalares do SUS (SIH/SUS)",
        "Autorizações de Internação Hospitalar (AIH) por competência (2008+).",
        [f"{BASE}/SIHSUS/200801_/Dados"], [],
        "{tipo}{uf}{aa}{mm}", "mensal",
        tipos={"RD": "AIH reduzida (padrão para pesquisa)", "RJ": "AIH rejeitada",
               "ER": "AIH rejeitada com erro", "SP": "Serviços profissionais",
               "CH": "Cadastro hospitalar", "CM": "Cadastro de leitos/UTI"},
        tipo_padrao="RD",
    ),
    "SIA": _f(
        "Sistema de Informações Ambulatoriais do SUS (SIA/SUS)",
        "Produção ambulatorial por competência (2008+). Arquivos grandes podem vir divididos (a, b, c...).",
        [f"{BASE}/SIASUS/200801_/Dados"], [],
        "{tipo}{uf}{aa}{mm}", "mensal",
        tipos={"PA": "Produção ambulatorial", "BI": "Boletim de produção individualizado",
               "AM": "APAC medicamentos", "AQ": "APAC quimioterapia", "AR": "APAC radioterapia",
               "AD": "APAC laudos diversos", "AN": "APAC nefrologia", "ACF": "APAC confecção de fístula",
               "AB": "APAC cirurgia bariátrica", "ATD": "APAC tratamento dialítico",
               "PS": "RAAS psicossocial", "SAD": "RAAS atenção domiciliar"},
        tipo_padrao="PA",
    ),
    "SINAN": _f(
        "Sistema de Informação de Agravos de Notificação (SINAN)",
        "Notificações por agravo. Arquivos nacionais (BR); filtro por UF é aplicado após o download.",
        [f"{BASE}/SINAN/DADOS/FINAIS"], [f"{BASE}/SINAN/DADOS/PRELIM"],
        "{tipo}BR{aa}", "anual", por_uf=False,
        tipos={
            "ACBI": "Acidente de trabalho com material biológico", "ACGR": "Acidente de trabalho grave",
            "ANIM": "Acidente por animais peçonhentos", "ANTR": "Atendimento antirrábico",
            "BOTU": "Botulismo", "CANC": "Câncer relacionado ao trabalho", "CHAG": "Doença de Chagas aguda",
            "CHIK": "Chikungunya", "COLE": "Cólera", "COQU": "Coqueluche", "DENG": "Dengue",
            "DERM": "Dermatoses ocupacionais", "DIFT": "Difteria", "ESPO": "Esporotricose",
            "ESQU": "Esquistossomose", "FMAC": "Febre maculosa", "FTIF": "Febre tifoide",
            "HANS": "Hanseníase", "HANT": "Hantavirose", "IEXO": "Intoxicação exógena",
            "LEIV": "Leishmaniose visceral", "LEPT": "Leptospirose", "LER": "LER/DORT", "LERD": "LER/DORT",
            "LTAN": "Leishmaniose tegumentar americana", "MALA": "Malária", "MENI": "Meningite",
            "MENT": "Transtornos mentais relacionados ao trabalho", "NTRA": "Notificação de tracoma",
            "PAIR": "Perda auditiva induzida por ruído", "PEST": "Peste", "PFAN": "Paralisia flácida aguda",
            "PNEU": "Pneumoconioses", "RAIV": "Raiva humana", "ROTA": "Rotavírus",
            "SDTA": "Surto de doenças transmitidas por alimentos", "TETA": "Tétano acidental",
            "TETN": "Tétano neonatal", "TOXC": "Toxoplasmose congênita", "TOXG": "Toxoplasmose gestacional",
            "TRAC": "Tracoma", "TUBE": "Tuberculose", "VIOL": "Violência interpessoal/autoprovocada",
            "ZIKA": "Zika", "SIFA": "Sífilis adquirida", "SIFC": "Sífilis congênita", "SIFG": "Sífilis em gestante",
            "AIDA": "AIDS adulto", "AIDC": "AIDS criança", "HEPA": "Hepatites virais",
            "VARC": "Varicela", "EXAN": "Doenças exantemáticas", "FAMA": "Febre amarela",
        },
        tipo_padrao=None,
    ),
    "CNES": _f(
        "Cadastro Nacional de Estabelecimentos de Saúde (CNES)",
        "Cadastro mensal de estabelecimentos, leitos, profissionais e equipamentos (2005+).",
        [f"{BASE}/CNES/200508_/Dados/{{tipo}}"], [],
        "{tipo}{uf}{aa}{mm}", "mensal",
        tipos={"ST": "Estabelecimentos", "LT": "Leitos", "PF": "Profissionais", "EQ": "Equipamentos",
               "SR": "Serviços especializados", "HB": "Habilitações", "EP": "Equipes",
               "RC": "Regras contratuais", "IN": "Incentivos", "EE": "Estabelecimentos de ensino",
               "EF": "Estabelecimentos filantrópicos", "GM": "Gestão e metas", "DC": "Dados complementares"},
        tipo_padrao="ST",
    ),
}

ALIASES = {
    "OBITOS": "SIM", "MORTALIDADE": "SIM", "NASCIDOS": "SINASC", "NASCIMENTOS": "SINASC",
    "INTERNACOES": "SIH", "SIHSUS": "SIH", "SIASUS": "SIA", "AMBULATORIAL": "SIA",
    "ESTABELECIMENTOS": "CNES", "AGRAVOS": "SINAN",
}


def resolver_sistema(nome: str) -> str:
    n = nome.strip().upper()
    n = ALIASES.get(n, n)
    if n not in SISTEMAS:
        raise ValueError(f"Sistema desconhecido: {nome}. Opções: {', '.join(SISTEMAS)}")
    return n
