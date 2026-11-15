"""DATASUS para Pesquisa – aplicação interativa (Streamlit). Abra com interface.bat."""

import streamlit as st

st.set_page_config(page_title="DATASUS para Pesquisa", page_icon="📊", layout="wide")

paginas = st.navigation([
    st.Page("paginas/busca.py", title="Buscar dados", icon="🔎", default=True),
    st.Page("paginas/analise.py", title="Análise", icon="📈", url_path="analise"),
    st.Page("paginas/indicadores.py", title="Indicadores", icon="🧮", url_path="indicadores"),
])
paginas.run()
