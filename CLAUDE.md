# Data-SUS

Programa `datasus_ciencia` para baixar e organizar microdados do DATASUS para pesquisa científica. Detalhes em README.md.

## Quando o usuário pedir dados do DATASUS

Traduza o pedido em linguagem natural para o comando e execute no PowerShell a partir desta pasta:

```
.\datasus.bat baixar <SISTEMA> --uf <UFs> --anos <AAAA[-AAAA]> [--meses 1-12] [--tipo X] [--cid PREFIXOS] [--formato parquet csv dta xlsx]
```

- Sistemas: SIM (óbitos), SIM-NAC (DOFET/DOEXT/DOINF/DOMAT nacionais), SINASC (nascidos vivos), SIH (internações, tipo RD), SIA (ambulatorial, tipo PA etc.), SINAN (agravos; `--tipo` obrigatório, ex.: DENG, TUBE, HANS, VIOL), CNES (tipo ST, LT, PF...). `.\datasus.bat sistemas` lista tudo.
- Antes de baixar períodos incertos, rode `.\datasus.bat listar <SISTEMA> --uf <UF>` para ver o que existe (finais e preliminares).
- Pedidos por procedimento (SIH/SIA): `--proc <código SIGTAP ou prefixo>`; nomes em `datasus_ciencia/referencias.py::sigtap` (cache `dados/.cache/sigtap.json`).
- Brasil inteiro no SIH (~1 GB/ano de RD): use `--leve` e filtros; rode em background. O leitor rápido (`leitura.ler_dbf_rapido`) aplica filtros por prefixo antes de decodificar.
- Pedidos por doença: converta para prefixos CID-10 (`--cid I21 I22`). Faixas como X60–X84 devem ser listadas como prefixos (`X6 X7 X80 X81 X82 X83 X84`).
- Bases grandes (Brasil inteiro, SIH/SIA de muitos meses): rode em background e avise o usuário do tempo (~1 min por arquivo grande); sugira `--cid`/`--colunas`.
- Ao final, mostre ao usuário a pasta em `dados/processados/<nome>/`, nº de registros, dados preliminares e períodos ausentes (estão no `LEIA-ME.md` e `metadados.json`).
- Análises complementares: `.\datasus.bat agregar <pasta> --por <variáveis>`; ou leia o `.parquet` com `.\.venv\Scripts\python.exe`.

## Interface

`app.py` (Streamlit, st.navigation) aberta por `interface.bat`; para pré-visualizar, use `.claude/launch.json` ("interface", porta 8501).
- `paginas/busca.py` – busca/minhas bases/disponibilidade; `paginas/analise.py` → `interface_analise.py` (filtros, gráficos Altair, estatística).
- Memória (PCs de 8 GB): nenhuma página lê a base inteira. "Minhas bases" lê prévia/esquema e, no agregado, só as colunas escolhidas; a Análise lê `_colunas_analise` (derivadas + originais de CID/`variaveis_extras`, sem municípios que não são de residência) em `st.cache_resource` (não altere `df0`; sem filtro, `df` é cópia rasa) e monta o CSV filtrado sob demanda (`_csv_selecao`, com todas as variáveis, lendo o parquet em lotes).
- Página Indicadores: `paginas/indicadores.py` → `interface_indicadores.py`; lógica em `datasus_ciencia/indicadores.py` (`INDICADORES`, `selecionar_numerador`, `contar`, `combinar` com IC Poisson, DCNT padronizada, razão por sexo). Junta bases (SIM ÷ SINASC, SIM ÷ SIH, SIM ÷ população). Não há seletor de denominador: `_cobertura` acha as bases locais que cobrem (UF, ano) do numerador e o botão "Baixar … do DATASUS" chama `_baixar`, que baixa só o que falta via `pipeline.executar` (SIH com os CIDs da causa, `--leve`); numerador e denominador sempre no mesmo período. Bases do numerador filtradas por `indicadores.serve_numerador` (`NUM_TIPOS`: DOFET só na fetal/perinatal; o SIM por UF não tem óbitos fetais); na perinatal o denominador usa as UFs comuns às bases fetal e não fetal. `_juntar` remove repetição por `_arquivo_origem` (nunca por colunas: apagaria nascimentos distintos). Letalidade do SINAN e mortalidade proporcional ficam no seletor "Medir" da Análise. A página lê só as colunas de `interface_indicadores.COLUNAS` (bases inteiras estouram a memória em PCs de 8 GB); idade em dias = `indicadores.idade_dias` (arredonda; `idade_anos` tem 3 casas). Conferido com o TabNet: NV, óbitos infantis por faixa, maternos e óbitos por IAM idênticos; internações SIH ~0,4% abaixo (residentes internados em outras UFs).
- SINAN: o TabNet conta casos pelo **ano de diagnóstico** (`tratamento.diagnostico` → `ano_diagnostico`, de DT_DIAG), padrão na Análise quando ≥90% preenchido; os arquivos SIxxBRaa são por ano de notificação, então diagnósticos antes do 1º ano baixado ficam incompletos (o período da Análise começa no 1º ano da base). Conferido: sífilis em gestante RJ 2009–2025 idêntica ao TabNet. No SIM, variáveis restritas a parte dos óbitos (tipo de parto, circunstância, maternas) são descritas só no seu universo (`tratamento.universo`).
- "Comparar grupos por" é montado por base: lista prioritária + toda variável derivada categórica com 2–30 níveis em `df0` (cada agravo mostra só os seus marcadores). Variáveis com muitos níveis (`GRUPOS_ESCOLHA`: territórios de `T.TERRITORIOS`, `municipio_residencia`, `municipio_prenatal`, `mun_notificacao_nome`): o usuário escolhe até 8; os demais ficam vazios na coluna do grupo em `df` (fora da comparação, mas no Total). Só os territoriais (`GRUPOS_TERRIT`) têm taxa: `pop_base` ganha a mesma coluna por cod6. Preparo do grupo em `preparar_comparacao`.
- SIFG (sífilis em gestante): `tratamento.EXTRAS_DECOD` decodifica os marcadores do TabNet (trimestre, UF do pré-natal, classificação clínica, testes não treponêmico/treponêmico, esquema de tratamento, parceiro); o município do pré-natal (`municipio_prenatal`, "Nome – UF") é montado em `_carregar` a partir de PRE_MUNIRE.
- `datasus_ciencia/tabnet.py` – tabelas .CNV do TabNet do FTP (`SIHSUS/200801_/Auxiliar/TAB_SIH.zip`, `SIM/CID10/TAB/OBITOS_CID10_TAB.zip`, cache em `dados/.cache/tabnet`): territórios por município (CIR, macro, micro, RM) e listas de causas (`classificar`). Filtros da barra lateral só aparecem com ≥2 opções na base; `tratamento.variaveis_extras` decodifica Robson, Kotelchuck, Apgar e campos do SINAN (também aplicada ao carregar bases antigas).
- `datasus_ciencia/resumo.py` – resumo para congresso (aba Relatório), por regras e sem API: `extrair_achados` (um extrator por tabela de `relatorio`, relevância alta/média/baixa) → `montar_resumo` (IMRD 250–300 palavras); `salvar_contexto`/`ler_resumo_claude` fazem a ponte com o pedido no chat (abaixo).

## Quando o usuário pedir o resumo para congresso de uma base

1. Leia `dados/processados/<base>/resumo_congresso/contexto.md` (gerado pelo botão "Preparar para o Claude"). Se não existir, peça para clicar no botão na aba Relatório.
2. Redija em português científico um resumo IMRD com 250–300 palavras no total, uma linha por seção, exatamente com os rótulos `Introdução:`, `Objetivo:`, `Métodos:`, `Resultados:`, `Conclusão:`.
3. Resultados: só os achados marcados pelo autor, com os números copiados das tabelas (vírgula decimal). Não invente números, comparações nem dados da literatura. Métodos: só as técnicas que correspondem aos achados. Introdução: use o contexto do autor; sem ele, uma frase genérica terminando em `[completar]`. Conclusão sem extrapolar causalidade.
4. Salve em `dados/processados/<base>/resumo_congresso/resumo_claude.md` (as cinco linhas e, ao final, `Palavras: N`), mostre o texto no chat e diga para clicar em "Carregar resumo do Claude" na interface.
- `datasus_ciencia/estatistica.py` – Tabela 1, taxas (IC Poisson), Prais-Winsten, regressão logística, texto de métodos.
- `datasus_ciencia/referencias.py` – população do TabNet (`populacao_svs`: FTP `IBGE/POPSVS`, município×sexo×idade 0–80+, cache parquet em `dados/.cache/popsvs`; IBGE/SIDRA só como alternativa), CID-10 (FTP SIM/TABELAS), SIGTAP, malhas IBGE (rebobinadas p/ Vega). Padronização: `FAIXAS_5_80`/`PADRAO_OMS_80` + `estatistica.padronizacao_direta`.
- CLI e interface compartilham `datasus_ciencia/pipeline.py::executar` — mudanças no fluxo vão lá.
- Imagens: `interface_imagem.py` – use `mostrar_grafico(container, chart, nome)` / `mostrar_tabela(container, df, nome, **kwargs_dataframe)` no lugar de `altair_chart`/`dataframe` (botão PNG 300 dpi/SVG via `vl_convert`, tabela PNG via Pillow, gerados só no clique). Na exportação, `spec_publicacao` troca o tema escuro pelo claro (passos light da paleta, sequencial invertido, datas pt-BR, largura fixa 640 px). `iniciar_figuras(pagina, fonte_padrao)` + `botao_zip` montam o ZIP (Relatório e Indicadores). Prévia de dados e dicionário ficam sem imagem. "🎨 Personalizar" (`st.dialog`) grava as opções em `session_state["_perso_<pagina>_<tipo>_<nome>"]`, um dicionário alterado no lugar porque os downloads rodam em outra thread sem `session_state`. `opcoes_efetivas(reg)` resolve título numerado e fonte. A fonte padrão vem de `fonte_de_meta`/`fonte_dados`; `definir_fonte(texto, escopo)` define uma fonte por base ou indicador. Legenda e fonte entram como rodapé desenhado depois do Vega (`_png_com_rodape`/`_svg_com_rodape`). O título é quebrado em linhas pela largura.
- Paleta dos gráficos: categórica validada (skill dataviz); Masculino/Feminino com cores fixas, Ignorado/Outros cinza, no máx. 8 séries.
- Temas: `.streamlit/config.toml` tem `[theme.dark]` (azul-marinho original, Inter) e `[theme.light]` (papel #F5F6F1, primária #3A3F9A, Archivo); troca no menu ⋮ (`toolbarMode = "viewer"`). Os links de fonte só carregam na seção `[theme]`; os temas citam a fonte pelo nome. Gráficos da tela pegam as cores de `interface_analise.paleta()` (lê `st.context.theme.type`); não use cores fixas nos gráficos. A exportação sai igual nos dois temas.
- Testes da interface: `streamlit.testing.v1.AppTest` com `PYTHONUTF8=1` (no Windows, sem isso os acentos se corrompem no harness).

## Código

- `datasus_ciencia/catalogo.py` – sistemas, diretórios FTP e padrões de nome
- `ftp.py` – listagem com cache (24 h), download com retentativa e verificação de tamanho
- `leitura.py` – .dbc → DataFrame (pyreaddbc + dbfread)
- `tratamento.py` – decodificações e variáveis derivadas (originais em MAIÚSCULAS nunca são alteradas)
- `saida.py` – base, dicionário, tabela descritiva, metadados, LEIA-ME com citação
- Python 3.12 em `.venv` (pandas 3: textos usam dtype `str`/`string`)
