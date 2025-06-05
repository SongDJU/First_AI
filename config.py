"""
Streamlit 앱 설정 파일
"""

import streamlit as st


def init_page_config():
    """Streamlit 페이지 설정을 초기화합니다."""
    st.set_page_config(
        page_title="식단 계획 AI",
        page_icon="🍱",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={"Get help": None, "Report a bug": None, "About": None},
    )

    # deploy 버튼 제거
    st.markdown(
        """
        <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            .stDeployButton {display: none;}
        </style>
    """,
        unsafe_allow_html=True,
    )
