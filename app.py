"""DB-OPTIMA AI - Streamlit entrypoint.  Run:  streamlit run app.py"""
import streamlit as st

st.set_page_config(page_title="DB-OPTIMA AI", page_icon="🧭", layout="wide", initial_sidebar_state="expanded")

from dboptima.ui import CSS, sidebar  # noqa: E402

st.markdown(CSS, unsafe_allow_html=True)
sidebar()

pages = [
    st.Page("views/executive_dashboard.py", title="Executive Dashboard", icon="📊", default=True),
    st.Page("views/estate_licence.py", title="Estate & Licence Intelligence", icon="🗄️"),
    st.Page("views/modernization_tco.py", title="Modernization & TCO", icon="🚀"),
    st.Page("views/ai_reports.py", title="AI Assistant & Reports", icon="🤖"),
]
st.navigation(pages).run()
