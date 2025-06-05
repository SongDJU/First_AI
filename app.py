"""
식단 계획 웹 앱

이 Streamlit 앱은 meal_ai.py의 기능을 웹 인터페이스로 제공합니다.
주요 기능:
1. 주간 식단 계획 생성 및 다운로드
2. 메뉴 데이터베이스 관리
3. 영양소 기준치 설정
"""

import streamlit as st
import pandas as pd
import meal_ai
from datetime import datetime
import os
from openai import OpenAI
from openai import APIError, AuthenticationError
from dotenv import load_dotenv
import config

# Streamlit 설정 초기화
config.init_page_config()

# .env 파일 로드
load_dotenv()


# API 키 확인
def check_api_key():
    """OpenAI API 키가 유효한지 확인"""
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            st.sidebar.error("⚠️ API 키가 설정되지 않았습니다!")
            return False

        # API 키 형식 확인
        if not (api_key.startswith("sk-") or api_key.startswith("sk-proj-")):
            st.sidebar.error(
                "⚠️ API 키 형식이 올바르지 않습니다! (sk- 또는 sk-proj-로 시작해야 합니다)"
            )
            return False

        # OpenAI 클라이언트 초기화
        client = OpenAI(api_key=api_key)

        # 간단한 API 호출 테스트
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",  # 더 가벼운 모델로 테스트
            messages=[{"role": "user", "content": "테스트"}],
            max_tokens=5,
        )
        return True
    except AuthenticationError as e:
        st.sidebar.error(f"⚠️ API 키 인증 오류: {str(e)}")
        return False
    except APIError as e:
        st.sidebar.error(f"⚠️ API 오류: {str(e)}")
        return False
    except Exception as e:
        st.sidebar.error(f"⚠️ 예상치 못한 오류: {str(e)}")
        return False


# 사이드바 - API 키 상태 표시
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    st.sidebar.error("⚠️ OpenAI API 키가 설정되지 않았습니다!")
else:
    # API 키 일부만 표시 (보안)
    masked_key = api_key[:8] + "..." + api_key[-4:]
    st.sidebar.info(f"현재 설정된 API 키: {masked_key}")

    if check_api_key():
        st.sidebar.success("✅ OpenAI API 키가 정상적으로 설정되었습니다!")
    else:
        st.sidebar.error("⚠️ OpenAI API 키가 유효하지 않습니다!")

# 사이드바 - 페이지 선택
page = st.sidebar.selectbox(
    "페이지 선택", ["홈 / 식단 계획", "메뉴 DB", "설정", "메뉴판 분석"]
)

# 데이터베이스 초기화
if not os.path.exists("meal.db"):
    meal_ai.init_db()

# 홈 / 식단 계획 페이지
if page == "홈 / 식단 계획":
    st.title("🍱 주간 식단 계획")

    # API 키가 없거나 유효하지 않은 경우 경고 표시
    if not api_key or not check_api_key():
        st.warning(
            """
        ⚠️ OpenAI API 키가 설정되지 않았거나 유효하지 않습니다.
        
        다음 단계를 따라 API 키를 설정해주세요:
        1. [OpenAI API 키 발급 페이지](https://platform.openai.com/api-keys)에서 키를 발급받습니다.
        2. 터미널에서 다음 명령어를 실행합니다:
           ```bash
           # Windows
           set OPENAI_API_KEY=your-api-key-here
           
           # Linux/Mac
           export OPENAI_API_KEY=your-api-key-here
           ```
        3. 앱을 다시 시작합니다.
        """
        )

    st.markdown(
        """
    ### 📝 주간 식단 계획 가이드
    
    주간 식단 계획을 생성할 수 있습니다. 아래 버튼을 클릭하세요:
    
    - **주간 5일 식단표 생성**: 월요일부터 금요일까지의 식단표를 생성합니다.
    
    각 식단은 잡곡밥, 국/수프, 메인, 사이드 메뉴로 구성됩니다.
    """
    )

    if st.button("주간 5일 식단표 생성", type="primary", use_container_width=True):
        try:
            with st.spinner("식단표를 생성하는 중..."):
                plan = meal_ai.make_plan("점심")

            st.success("✅ 식단표가 생성되었습니다!")
            st.dataframe(plan, use_container_width=True)

            filename = f"meal_plan_lunch_{datetime.now().strftime('%Y%m%d')}.xlsx"
            file_path = meal_ai.export_plan(plan, filename)
            with open(file_path, "rb") as f:
                st.download_button(
                    "📥 Excel 다운로드",
                    f,
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="lunch_excel",
                )
        except Exception as e:
            st.error(f"❌ 계획 생성 중 오류가 발생했습니다: {str(e)}")

# 메뉴 DB 페이지
elif page == "메뉴 DB":
    st.title("🍽️ 메뉴 데이터베이스")
    tabs = st.tabs(["메뉴 추가", "메뉴 관리"])

    # 메뉴 추가 탭
    with tabs[0]:
        st.subheader("메뉴 추가")
        st.markdown("여러 메뉴를 한 번에 추가하려면 쉼표(,)로 구분하여 입력하세요.")

        # 텍스트 입력으로 메뉴 추가
        menu_input = st.text_area("메뉴 입력", height=100)
        if st.button("메뉴 추가", key="add_menu_btn"):
            if menu_input:
                menu_list = [
                    menu.strip() for menu in menu_input.split(",") if menu.strip()
                ]
                if menu_list:
                    try:
                        with st.spinner("메뉴를 추가하는 중..."):
                            meal_ai.bulk_add(menu_list)
                        st.success("✅ 메뉴가 성공적으로 추가되었습니다!")
                    except Exception as e:
                        st.error(f"❌ 메뉴 추가 중 오류가 발생했습니다: {str(e)}")

        # 엑셀 파일 업로드로 메뉴 추가
        st.markdown("---")
        st.markdown("### 엑셀 파일로 메뉴 추가")
        st.markdown(
            """
            엑셀 파일을 업로드하여 여러 메뉴를 한 번에 추가할 수 있습니다.
            
            **파일 형식:**
            - 첫 번째 열의 제목은 반드시 '메뉴'여야 합니다.
            - 각 행에 하나의 메뉴를 입력합니다.
            
            **주의사항:**
            - 파일은 반드시 .xlsx 또는 .xls 형식이어야 합니다.
            - 중복된 메뉴는 자동으로 건너뜁니다.
            - 메뉴 이름은 정확히 입력해야 합니다.
            """
        )

        uploaded_file = st.file_uploader(
            "엑셀 파일 업로드", type=["xlsx", "xls"], key="menu_uploader"
        )

        if uploaded_file is not None:
            try:
                df = pd.read_excel(uploaded_file)
                if "메뉴" not in df.columns:
                    st.error("❌ 엑셀 파일의 첫 번째 열 제목이 '메뉴'여야 합니다.")
                else:
                    menu_list = df["메뉴"].dropna().tolist()
                    if menu_list:
                        st.write("추가할 메뉴 목록:")
                        st.write(menu_list)
                        if st.button("메뉴 일괄 추가", key="bulk_add_btn"):
                            try:
                                with st.spinner("메뉴를 추가하는 중..."):
                                    meal_ai.bulk_add(menu_list)
                                st.success("✅ 메뉴가 성공적으로 추가되었습니다!")
                            except Exception as e:
                                st.error(
                                    f"❌ 메뉴 추가 중 오류가 발생했습니다: {str(e)}"
                                )
            except Exception as e:
                st.error(f"❌ 파일 처리 중 오류가 발생했습니다: {str(e)}")

    # 메뉴 관리 탭
    with tabs[1]:
        st.subheader("메뉴 관리 및 영양소/카테고리 수정")
        menus = meal_ai.get_all_menus()
        if not menus.empty:
            # 카테고리 목록 추출
            category_options = menus["category"].dropna().unique().tolist()
            # 표 기반 편집
            edited_df = st.data_editor(
                menus,
                column_config={
                    "category": st.column_config.SelectboxColumn(
                        "카테고리", options=category_options + ["기타"], required=True
                    ),
                    "calories": st.column_config.NumberColumn(
                        "칼로리", min_value=0, step=0.1
                    ),
                    "protein": st.column_config.NumberColumn(
                        "단백질", min_value=0, step=0.1
                    ),
                    "fat": st.column_config.NumberColumn("지방", min_value=0, step=0.1),
                    "carbs": st.column_config.NumberColumn(
                        "탄수화물", min_value=0, step=0.1
                    ),
                    "sodium": st.column_config.NumberColumn(
                        "나트륨", min_value=0, step=0.1
                    ),
                },
                disabled=["name"],
                use_container_width=True,
                num_rows="dynamic",
                key="menu_edit_table",
            )
            if st.button("수정사항 저장", key="save_menu_edits"):
                # 변경된 행만 찾아서 업데이트
                for idx, row in edited_df.iterrows():
                    orig_row = menus.loc[idx]
                    # name은 고유키
                    menu_name = orig_row["name"]
                    nutrition = {
                        "칼로리": row["calories"],
                        "단백질": row["protein"],
                        "지방": row["fat"],
                        "탄수화물": row["carbs"],
                        "나트륨": row["sodium"],
                    }
                    # 카테고리도 수정
                    if row["category"] != orig_row["category"]:
                        meal_ai.update_menu_category(menu_name, row["category"])
                    # 영양소 수정
                    meal_ai.update_menu_nutrition(menu_name, nutrition)
                st.success("수정사항이 저장되었습니다.")
        else:
            st.info("등록된 메뉴가 없습니다.")

# 설정 페이지
elif page == "설정":
    st.title("⚙️ 설정")

    st.subheader("영양소 기준치 (RDI)")

    # 현재 설정값 로드
    rdi = meal_ai.DEFAULT_RDI.copy()
    tolerance = meal_ai.DEFAULT_TOLERANCE

    # 영양소별 설정
    cols = st.columns(2)
    for i, (nutrient, value) in enumerate(rdi.items()):
        with cols[i % 2]:
            rdi[nutrient] = st.number_input(
                f"{nutrient} (기본값: {value})", value=value, min_value=0
            )

    # 허용 오차 설정
    tolerance = st.slider(
        "허용 오차 (%)", min_value=0, max_value=50, value=tolerance, step=1
    )

    if st.button("설정 저장", type="primary"):
        # TODO: 설정값을 파일이나 DB에 저장하는 기능 구현
        st.success("설정이 저장되었습니다!")

# 메뉴판 분석 페이지
elif page == "메뉴판 분석":
    st.title("📊 메뉴판 분석")

    st.markdown(
        """
    ### 📝 메뉴판 분석 가이드
    
    기존 식단표를 업로드하여 영양 정보를 분석할 수 있습니다.
    
    **파일 형식:**
    - Excel 파일 (.xlsx, .xls)
    - **시트명:** '점심' 또는 '저녁'
    - **행:** 잡곡밥, 국/수프, 메인, 사이드1, 사이드2, 기타(선택)
    - **열:** 월, 화, 수, 목, 금
    - 각 셀에는 해당 요일의 메뉴명이 들어가야 합니다.
    
    **주의사항:**
    - 메뉴 이름은 데이터베이스에 등록된 이름과 정확히 일치해야 합니다
    - 빈 셀은 자동으로 제외됩니다
    - 메뉴구분(국/수프, 메인, 사이드 등)은 없어도 무방합니다
    """
    )

    uploaded_file = st.file_uploader(
        "식단표 엑셀 파일을 업로드하세요",
        type=["xlsx", "xls"],
        help="'점심' 또는 '저녁' 시트가 포함된 엑셀 파일을 선택해주세요",
    )

    if uploaded_file is not None:
        try:
            xl = pd.ExcelFile(uploaded_file)
            sheet_name = None
            for s in xl.sheet_names:
                if s.strip() in ["점심", "저녁"]:
                    sheet_name = s
                    break
            if not sheet_name:
                st.error("'점심' 또는 '저녁' 시트가 없습니다.")
            else:
                df = xl.parse(sheet_name, index_col=0)
                df.index = df.index.str.strip()
                df.columns = df.columns.str.strip()
                row_order = ["잡곡밥", "국/수프", "메인", "사이드1", "사이드2", "기타"]
                exist_rows = [r for r in row_order if r in df.index]
                df = df.loc[exist_rows]
                df_t = df.T.reset_index().rename(columns={"index": "요일"})
                df_t = df_t[df_t["요일"].isin(["월", "화", "수", "목", "금"])]
                st.subheader("업로드된 데이터 미리보기")
                st.dataframe(df_t)

                if st.button("영양 정보 분석", key="analyze_nutrition"):
                    with st.spinner("영양 정보를 분석하는 중..."):
                        try:
                            nutrition_df = meal_ai.analyze_menu_plan(df_t)
                            st.success("영양 정보 분석이 완료되었습니다!")
                            st.dataframe(nutrition_df)

                            filename = f"nutrition_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                            file_path = meal_ai.export_plan(df_t, filename)
                            with open(file_path, "rb") as f:
                                st.download_button(
                                    label="분석 결과 다운로드",
                                    data=f,
                                    file_name=filename,
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                )
                        except Exception as e:
                            st.error(f"영양 정보 분석 중 오류가 발생했습니다: {str(e)}")
        except Exception as e:
            st.error(f"파일 처리 중 오류가 발생했습니다: {str(e)}")
