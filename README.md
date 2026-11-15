# Data-SUS (`datasus_ciencia`)

**Dos microdados do SUS ao trabalho científico, sem precisar programar.** Baixe, trate e analise dados do SIM, SINASC, SIH, SIA, SINAN e CNES numa interface no navegador, com indicadores conferidos com o TabNet, estatística pronta e rascunho de resumo para congresso.

Programa gratuito e de código aberto (licença [AGPL‑3.0](#licença)) para **buscar microdados do DATASUS** (FTP público do Ministério da Saúde) e **organizá-los para produção científica**: base analítica tratada, dicionário de variáveis, tabela descritiva, metadados de reprodutibilidade, citação da fonte e texto de Métodos.

## Interface interativa (recomendado)

Dê **dois cliques em `interface.bat`**. A interface abre no navegador (http://localhost:8501), com quatro abas:

- **Nova busca**: escolha o sistema, as UFs (há atalho por região), o período e os formatos. Depois clique em *Buscar e organizar dados*. Nos filtros avançados, CID-10, municípios e variáveis são **menus suspensos com busca**. A CID-10 traz grupos prontos (suicídio, homicídio, AVC, IAM, COVID-19...), capítulos e todas as categorias. As variáveis aparecem com descrição; a lista é lida uma vez do FTP pelo botão *Carregar lista de variáveis*.
- **Minhas bases**: todas as bases já geradas, cada uma com dados, tabela descritiva com gráfico, agregações (por ano, UF, sexo...) com gráfico e CSV, dicionário, citação/Métodos e arquivos para baixar.
- **Disponibilidade**: quais anos e meses existem no FTP, separando os finais dos preliminares.
- **Ajuda**: exemplos e cuidados.

Para encerrar, feche a janela preta do `interface.bat`.

### Página Análise (menu lateral → 📈 Análise)

Escolha a base e as características na barra lateral: **período, sexo, raça/cor, faixa etária, região, UF, município, CID-10** e outros filtros. Também dá para escolher uma variável em **Comparar grupos por**. A página gera:

| Aba | Conteúdo |
|---|---|
| Panorama | Série anual (contagem ou **taxa por 100 mil hab.** com IC95% de Poisson) e sazonalidade mensal |
| Perfil | Pirâmide etária, distribuição de cada característica, resumo das variáveis numéricas |
| Geografia | **Mapa coroplético** por município (até 3 UFs) ou por UF, com ranking de taxas e IC95% |
| Causas | Principais causas (CID-10, com descrição oficial) e distribuição por capítulo |
| Tabela 1 | Comparação entre grupos com qui-quadrado/Fisher, Mann-Whitney/Kruskal-Wallis e V de Cramér |
| Tendência | **Regressão de Prais-Winsten**: variação percentual anual (VPA), IC95% e classificação (para contagem, taxa ou proporção/letalidade) |
| Períodos | **Comparação pré × pós** (ex.: pandemia): razão B/A com IC95%, diferença em p.p., qui-quadrado/Fisher ou binomial; **série temporal interrompida** mensal ou anual (mudança de nível e de tendência, Newey-West, ajuste sazonal), com gráfico do contrafactual |
| Regressão | **Regressão logística**: OR bruto e ajustado (IC95%), gráfico de floresta e escolha da categoria de referência |
| Relatório | Excel com todas as tabelas, mais o parágrafo de métodos estatísticos pronto para o artigo. **Resumo para congresso**: lista de achados ranqueados por relevância estatística (significância, tamanho de efeito, magnitude); você marca os que quer e o programa monta um resumo estruturado (250–300 palavras), editável e para baixar (.txt/.md). Gratuito e offline |

Indicadores no seletor **Medir** (barra lateral), além de número de registros e proporção de um desfecho:
- **Letalidade** (SINAN): % de casos com óbito pelo agravo (na tuberculose, óbito por TB no encerramento); denominador = todos os notificados, só confirmados ou só casos com desfecho informado.
- **Mortalidade proporcional** (SIM): % dos óbitos por uma causa escolhida. Para o total de óbitos, baixe o SIM sem filtro de CID.

Filtros como no TabNet (cada um só aparece se a base tiver mais de uma opção para ele):
- **Região de Saúde (CIR), Macrorregião de Saúde, Microrregião IBGE e Região Metropolitana/RIDE** do município de residência (tabelas oficiais do TabNet; as taxas continuam disponíveis).
- **Idade (anos)** mínima e máxima e **faixas etárias do TabNet** (OPS, ampla, menores de 1 ano: 0–6, 7–27 e 28–364 dias).
- **Grupos da CID-10** no seletor de CID, **excluir causas mal definidas (R00–R99)** e **listas de causas do TabNet** no SIM: Lista de Mortalidade CID-10 (geral e infância) e causas evitáveis (0–4 e 5–74 anos).
- **Outros filtros** com várias variáveis ao mesmo tempo, incluindo, no SINASC, Apgar (faixas), Grupo de Robson e adequação do pré-natal; no SINAN, município de notificação, classificação final, critério de confirmação, hospitalização, caso autóctone e variáveis próprias da tuberculose e da hanseníase.

Na barra lateral também é possível escolher:
- **Excluir 'Ignorado' / 'Sem informação' em**: remove da análise os registros sem informação nas variáveis escolhidas (o % de ignorados aparece ao lado de cada uma). Com esse filtro as taxas populacionais ficam desativadas, porque o denominador incluiria essas pessoas.
- **Ano de referência**: no SIH/SIA, *ano de processamento* (competência, igual ao "Ano processamento" do TabNet) ou *ano de internação*.
- **Indicador**: número de registros ou **proporção de um desfecho**, como a **letalidade hospitalar** (% de internações com óbito), % de prematuros, ou % de uma categoria (ex.: % de transplantes com doador falecido).

Observações:
- As taxas usam a **população do TabNet** (Demográficas e Socioeconômicas → População residente: estudo de estimativas do MS/SVSA por município, idade e sexo, consistente com o Censo 2022). O programa lê do FTP do DATASUS (`IBGE/POPSVS`), guarda em cache e, se o FTP falhar, usa o IBGE como alternativa.
- Com filtros de **sexo, faixa etária, município, UF ou região**, o denominador é a população do mesmo subgrupo. Com **CID**, a taxa é por causa e usa a população total. Raça/cor e outros filtros não têm população no TabNet, então as taxas ficam desativadas.
- O seletor **"Padronizar por idade (OMS)"** gera taxas padronizadas (método direto, IC de Fay-Feuer) no Panorama, na Tendência e nos Períodos.
- A análise de tendência precisa de pelo menos 4 anos. Baixe séries longas (ex.: 2010–2023).
- Com bases grandes, até diferenças pequenas ficam significativas. Interprete o p-valor junto com o tamanho de efeito (V de Cramér, OR).
- No **resumo para congresso**, a Introdução e as implicações da Conclusão ficam marcadas com `[completar: ...]`. Para um texto mais fluido usando sua assinatura do Claude (sem API), clique em **Preparar para o Claude**, peça no Claude Code *"Monta o resumo para congresso da base &lt;nome&gt;"* e depois clique em **Carregar resumo do Claude**. Confira os números antes de submeter.

### Página Indicadores (menu lateral → 🧮 Indicadores)

Indicadores prontos (definições do MS/RIPSA) que juntam bases já baixadas, com IC95% exato de Poisson, série anual, tendência (Prais-Winsten), desagregação por UF ou município e Excel:

| Indicador | Numerador ÷ denominador |
|---|---|
| Mortalidade infantil, neonatal (precoce e tardia) e pós-neonatal | óbitos do SIM ÷ nascidos vivos do SINASC (por 1.000) |
| Mortalidade fetal e perinatal | óbitos fetais (SIM-NAC DOFET) [+ 0–6 dias] ÷ (nascidos vivos + óbitos fetais) (por 1.000) |
| Razão de mortalidade materna | óbitos maternos (O00–O95, O98–O99, A34, F53, M83.0) ÷ nascidos vivos (por 100 mil) |
| Letalidade SIM ÷ SIH | óbitos pela causa (SIM) ÷ internações pela mesma causa (SIH) × 100 – aproximado |
| Mortalidade prematura por DCNT (ODS 3.4) | óbitos de 30–69 anos por doenças cardiovasculares, câncer, diabetes e respiratórias crônicas ÷ população de 30–69 anos (por 100 mil; bruta e padronizada) |
| Razão de mortalidade por sexo | taxa masculina ÷ taxa feminina (bruta ou padronizada) |
| Taxa de incidência / detecção (SINAN) | casos de residentes ÷ população (por 100 mil); na tuberculose, só casos novos; opção de excluir descartados |
| Taxa de mortalidade (SIM) | óbitos ÷ população (por 100 mil), geral ou por causa |
| Taxa de internação (SIH) | internações ÷ população (por 10 mil), geral ou por causa |

Em todos os indicadores há a **tabela ano a ano** e a opção **Agrupar anos** (biênios, triênios, quadriênios, quinquênios), que soma numeradores e denominadores de cada bloco – útil com poucos eventos por ano. Você escolhe só a base do **numerador**; o **denominador é automático**, sempre com as mesmas UFs e anos do numerador. Se o SINASC (ou o SIH, na letalidade) desses anos ainda não estiver baixado, aparece o botão **Baixar … do DATASUS** com exatamente as UFs e anos que faltam (SINASC: segundos por ano; SIH: ~1 min por arquivo mensal, só com as causas escolhidas); a base fica guardada para as próximas vezes. Até baixar, o indicador usa só os anos que existem nas duas bases.

Nas três taxas por população dá para filtrar **sexo** e **idade** (a população do denominador é recortada igual) e ver a **taxa padronizada por idade** (OMS).

Só aparecem os indicadores cujo numerador você já baixou; o denominador vem sozinho. Se o DATASUS não tiver algum ano do denominador, ele sai também do numerador (os dois ficam sempre no mesmo período). Os cálculos são diretos (sem o fator de correção de sub-registro que o MS aplica em algumas UFs).

## Linha de comando

Abra o PowerShell nesta pasta e use `.\datasus.bat` (ou simplesmente peça ao Claude em linguagem natural, ex.: *"baixe os óbitos por infarto em MG de 2018 a 2022"*).

```bash
.\datasus.bat sistemas
```

```bash
.\datasus.bat listar SIM --uf SP
```

```bash
.\datasus.bat baixar SIM --uf SP RJ --anos 2019-2022
```

### Exemplos

| Objetivo | Comando |
|---|---|
| Óbitos em SP, 2018–2022 | `.\datasus.bat baixar SIM --uf SP --anos 2018-2022` |
| Óbitos por IAM (I21–I22) no Brasil | `.\datasus.bat baixar SIM --uf TODAS --anos 2022 --cid I21 I22` |
| Nascidos vivos no Nordeste | `.\datasus.bat baixar SINASC --uf BA PE CE --anos 2023` |
| Internações por AVC em MG, 1º semestre | `.\datasus.bat baixar SIH --uf MG --anos 2024 --meses 1-6 --cid I60 I61 I63 I64` |
| IAM no RJ por ano de processamento (letalidade) | `.\datasus.bat baixar SIH --uf RJ --anos 2014-2025 --cid I21 I22 --leve` |
| Transplantes renais no Brasil (procedimento SIGTAP) | `.\datasus.bat baixar SIH --uf TODAS --anos 2016-2025 --proc 0505020092 0505020106 --leve --sem-brutos` |
| Dengue em residentes de PE | `.\datasus.bat baixar SINAN --tipo DENG --anos 2024 --uf PE` |
| Estabelecimentos de saúde | `.\datasus.bat baixar CNES --tipo ST --uf RS --anos 2025 --meses 12` |
| Exportar também para Stata e Excel | acrescente `--formato parquet csv dta xlsx` |
| Contagens agregadas (estudos ecológicos) | `.\datasus.bat agregar SIM_SP_2018-2022 --por ano_obito mun_residencia_nome sexo` |

### Opções de `baixar`

- `--uf` UF(s) do arquivo (`SP RJ`, `TODAS`, `BR`). Em SINAN (arquivo nacional) vira filtro por UF de residência.
- `--anos` `2022`, `2018-2022` ou `2015,2020`; `--meses` para SIH/SIA/CNES (padrão: 1-12).
- `--tipo` tipo de arquivo (SIH: RD; SIA: PA, AQ, AR...; CNES: ST, LT, PF...; SINAN: DENG, TUBE, HANS...).
- `--cid` filtra por prefixo da CID-10 (causa básica no SIM, diagnóstico principal no SIH).
- `--uf-residencia`, `--municipio` (código IBGE) filtram por residência.
- `--proc` filtra SIH/SIA por **procedimento SIGTAP** (código ou prefixo: `0505020092` = transplante de rim com doador falecido; `050502` = todos os transplantes de órgãos). Na interface há um menu com os nomes.
- `--leve` lê só as variáveis essenciais (recomendado para o Brasil inteiro); `--sem-brutos` apaga os `.dbc` depois de ler.
- A interface mostra **quantos GB serão baixados** e o tempo estimado antes de começar.
- `--colunas` lê apenas as variáveis originais indicadas (economiza memória em bases grandes).
- `--somente-finais` ignora dados preliminares (por padrão, anos ainda não fechados vêm da pasta PRELIM e são sinalizados).
- `--nome` nome da pasta de saída; `--sem-derivadas` mantém só as variáveis originais.

## O que é gerado

Em `dados/processados/<nome>/`:

| Arquivo | Conteúdo |
|---|---|
| `<nome>.parquet` / `.csv` / `.dta` / `.xlsx` | Base analítica: variáveis **originais em MAIÚSCULAS** intactas + **derivadas em minúsculas** (sexo, raça/cor, idade em anos, faixa etária, datas, capítulo CID-10, nome/UF/região do município IBGE, prematuridade, baixo peso, óbito hospitalar, valores em R$...) |
| `dicionario_variaveis.csv` | Descrição, origem, tipo, % de faltantes, nº de categorias e exemplos de cada variável |
| `tabela_descritiva.xlsx` | Frequências (n, %) e medidas-resumo (média, DP, mediana, IIQ) – base para a Tabela 1 |
| `metadados.json` | URL de cada arquivo, tamanho, hash MD5, data de acesso, status final/preliminar, filtros e comando usado |
| `LEIA-ME.md` | Citação ABNT e Vancouver, texto para Métodos (PT/EN), nota ética (Res. CNS 510/2016) e cuidados metodológicos |

Os `.dbc` originais ficam em `dados/brutos/` (cache: não são baixados de novo).

## Leitura em R / Stata / Python

```r
df <- arrow::read_parquet("dados/processados/SIM_SP_2018-2022/SIM_SP_2018-2022.parquet")
```

```python
import pandas as pd; df = pd.read_parquet("dados/processados/SIM_SP_2018-2022/SIM_SP_2018-2022.parquet")
```

## Observações

- Desempenho: ~1 min por arquivo grande (ex.: SIH SP de um mês, ~220 mil AIH). Bases nacionais de vários anos podem levar bastante tempo e memória; use `--cid`, `--colunas` ou divida por período.
- O FTP do DATASUS às vezes fica instável; o programa tenta novamente automaticamente.
- As decodificações seguem os dicionários oficiais; confira sempre as variáveis originais para usos específicos.

## Exemplo de análise

[`analises/dpoc_rj_2015-2024.py`](analises/dpoc_rj_2015-2024.py) mostra uma análise completa feita com o programa: mortalidade por DPOC (J40–J44) no Rio de Janeiro, 2015–2019 × 2020–2024, com taxas padronizadas, tabelas e figuras. Primeiro baixe a base (`.\datasus.bat baixar SIM --uf RJ --anos 2015-2024 --cid J40 J41 J42 J43 J44 --nome DPOC_RJ_2015-2024`) e depois rode `.\.venv\Scripts\python.exe analises\dpoc_rj_2015-2024.py`.

## Instalação passo a passo (Windows)

Você só faz isto uma vez por computador.

1. **Instale o Python 3.12**: baixe em <https://www.python.org/downloads/> e, na primeira tela do instalador, **marque "Add python.exe to PATH"** antes de clicar em *Install Now*.
2. **Baixe o programa**: em <https://github.com/arthursdelphino-blip/Data-SuS>, clique no botão verde **Code → Download ZIP** e extraia o ZIP, por exemplo, na Área de Trabalho.
3. **Abra o PowerShell na pasta**: abra a pasta extraída, clique na barra de endereço do Explorador de Arquivos, digite `powershell` e aperte Enter.
4. **Crie o ambiente do programa** (leva alguns minutos):

```bash
python -m venv .venv
```

```bash
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

5. **Abra a interface**: dê dois cliques em `interface.bat`. O navegador abre sozinho em http://localhost:8501.

Os dados baixados ficam na pasta `dados/` do seu computador. Precisa de internet para acessar o FTP do DATASUS; o restante funciona offline.

## Fonte dos dados

Todos os dados vêm do **DATASUS / Ministério da Saúde** (FTP público `ftp.datasus.gov.br`) e, como alternativa para população, do IBGE. Este programa é independente: **não é oficial nem tem vínculo com o Ministério da Saúde**. Cite sempre a fonte original (o `LEIA-ME.md` de cada base já traz a citação pronta).

## Como citar

> DELPHINO, Arthur. Data-SUS: programa para obtenção e análise de microdados do DATASUS para pesquisa científica [software]. 2026. Disponível em: https://github.com/arthursdelphino-blip/Data-SuS. Acesso em: [data].

## Suporte, cursos e análises sob encomenda

Desenvolvido por **Arthur Delphino**, estudante de Medicina da Universidade Federal Fluminense (UFF).

Precisa de ajuda para usar o programa, de um curso ou de uma análise pronta para o seu trabalho? Entre em contato: **arthursildelphino@gmail.com**.

## Aviso

O programa é oferecido **sem nenhuma garantia**. Decodificações e cálculos seguem os dicionários e as definições oficiais e foram conferidos com o TabNet em vários indicadores. Ainda assim, **confira os resultados** antes de publicar; a responsabilidade pelas conclusões é do pesquisador.

## Licença

Distribuído sob a **GNU Affero General Public License v3.0** (arquivo [LICENSE](LICENSE)). Em linguagem simples:

- você pode **usar, estudar, modificar e redistribuir** o programa, inclusive para fins comerciais;
- se distribuir uma versão modificada, **ou oferecê-la para outras pessoas usarem por um site**, precisa disponibilizar o código-fonte dela com a mesma licença;
- não há garantia.

A licença acompanha a do leitor de arquivos `.dbc` usado pelo programa (pyreaddbc, AGPL‑3.0).
