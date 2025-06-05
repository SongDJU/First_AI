"""
식단 계획 및 영양 분석을 위한 AI 기반 시스템

이 모듈은 다음과 같은 기능을 제공합니다:
1. 메뉴 항목과 영양 정보를 SQLite DB에 저장
2. OpenAI GPT-4를 사용하여 새로운 메뉴 항목 분류
3. 주간 식단 계획 생성 (월-금, 1개의 수프, 1개의 메인, 2개의 사이드, 선택적 추가 메뉴)
4. 계획과 상세 영양 정보를 Excel 파일로 내보내기
"""

import sqlite3
import pandas as pd
from openai import OpenAI
from openai import APIError, AuthenticationError
import os
from typing import List, Dict, Any
import json
from datetime import datetime
from dotenv import load_dotenv
import streamlit as st
import random

# .env 파일 로드
load_dotenv()

# OpenAI API 키 설정
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY 환경 변수가 설정되지 않았습니다.")

# OpenAI 클라이언트 초기화
client = OpenAI(api_key=api_key)  # API 키를 직접 전달

# 기본 영양소 기준치 (RDI)
DEFAULT_RDI = {
    "칼로리": 2000,
    "단백질": 50,
    "지방": 65,
    "탄수화물": 300,
    "나트륨": 2300,
    "당류": 50,
}

# 허용 오차 범위 (%)
DEFAULT_TOLERANCE = 10


def init_db():
    """데이터베이스 초기화 및 테이블 생성"""
    conn = sqlite3.connect("meal.db")
    c = conn.cursor()

    # 메뉴 테이블 생성
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS menus (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            calories INTEGER,
            protein REAL,
            fat REAL,
            carbs REAL,
            sodium INTEGER,
            sugar REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    conn.commit()
    conn.close()


def classify_menu(menu_name: str) -> Dict[str, Any]:
    """OpenAI API를 사용하여 메뉴를 분류하고 영양 정보를 추출합니다."""
    try:
        # API 호출
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """다음 메뉴를 분석하여 JSON 형식으로 분류해주세요.
                    응답은 반드시 다음 형식의 JSON이어야 합니다:
                    {
                        "category": "수프/메인/사이드",
                        "nutrition": {
                            "칼로리": 숫자,
                            "단백질": 숫자,
                            "지방": 숫자,
                            "탄수화물": 숫자,
                            "나트륨": 숫자
                        }
                    }
                    숫자는 모두 정수로 표현해주세요.""",
                },
                {"role": "user", "content": menu_name},
            ],
            temperature=0.3,
            max_tokens=500,
        )

        # 응답에서 JSON 추출
        content = response.choices[0].message.content.strip()

        # JSON 문자열에서 실제 JSON 부분만 추출
        try:
            # JSON 형식이 아닌 경우를 처리
            if not content.startswith("{"):
                content = content[content.find("{") : content.rfind("}") + 1]

            result = json.loads(content)

            # 필수 필드 확인
            if "category" not in result or "nutrition" not in result:
                raise ValueError("응답에 필수 필드가 없습니다.")

            # 영양소 정보 확인
            required_nutrients = ["칼로리", "단백질", "지방", "탄수화물", "나트륨"]
            for nutrient in required_nutrients:
                if nutrient not in result["nutrition"]:
                    raise ValueError(f"응답에 {nutrient} 정보가 없습니다.")

            return result

        except json.JSONDecodeError as e:
            st.error(f"JSON 파싱 오류: {str(e)}")
            st.error(f"원본 응답: {content}")
            raise ValueError("API 응답을 JSON으로 파싱할 수 없습니다.")

    except Exception as e:
        st.error(f"메뉴 분류 중 오류 발생: {str(e)}")
        raise


def add_menu(menu_info: Dict[str, Any]) -> None:
    """메뉴 항목을 DB에 추가"""
    conn = get_db_connection()
    try:
        # 메뉴 정보 추출
        name = menu_info.get("name", "")
        category = menu_info.get("category", "")
        nutrition = menu_info.get("nutrition", {})

        # 영양 정보 추출
        calories = nutrition.get("칼로리", 0)
        protein = nutrition.get("단백질", 0)
        fat = nutrition.get("지방", 0)
        carbs = nutrition.get("탄수화물", 0)
        sodium = nutrition.get("나트륨", 0)

        # DB에 저장
        conn.execute(
            """
            INSERT INTO menus (name, category, calories, protein, fat, carbs, sodium)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (name, category, calories, protein, fat, carbs, sodium),
        )
        conn.commit()
    finally:
        conn.close()


def bulk_add(menu_names: List[str]) -> None:
    """여러 메뉴 항목을 일괄 추가"""
    for name in menu_names:
        menu_info = classify_menu(name)
        menu_info["name"] = name  # 메뉴 이름 추가
        add_menu(menu_info)


def get_all_menus() -> pd.DataFrame:
    """모든 메뉴 항목을 DataFrame으로 반환"""
    conn = sqlite3.connect("meal.db")
    df = pd.read_sql_query("SELECT * FROM menus", conn)
    conn.close()
    return df


def make_plan(meal_type: str = "점심") -> pd.DataFrame:
    """
    주간 식단 계획 생성

    Args:
        meal_type: 식사 유형 ("점심" 또는 "점심저녁")

    Returns:
        생성된 식단 계획 DataFrame (컬럼명: 잡곡밥, 국/수프, 메인, 사이드1, 사이드2, 기타)
    """
    menus = get_all_menus()
    plan = []
    used_menus = set()  # 이미 사용된 메뉴를 추적

    # 월-금 각 요일별로
    for day in ["월", "화", "수", "목", "금"]:
        day_plan = {
            "요일": day,
        }

        # 식단
        available_soup = menus[
            (menus["category"] == "수프") & (~menus["name"].isin(used_menus))
        ]
        available_main = menus[
            (menus["category"] == "메인") & (~menus["name"].isin(used_menus))
        ]
        available_side = menus[
            (menus["category"] == "사이드") & (~menus["name"].isin(used_menus))
        ]
        available_etc = menus[
            (~menus["category"].isin(["수프", "메인", "사이드"]))
            & (~menus["name"].isin(used_menus))
        ]

        # 메뉴가 부족한 경우 사용된 메뉴 재사용
        if available_soup.empty:
            available_soup = menus[menus["category"] == "수프"]
        if available_main.empty:
            available_main = menus[menus["category"] == "메인"]
        if available_side.empty:
            available_side = menus[menus["category"] == "사이드"]
        if available_etc.empty:
            available_etc = menus[~menus["category"].isin(["수프", "메인", "사이드"])]

        soup_menu = available_soup.sample(1)
        main_menu = available_main.sample(1)
        side_menu1 = available_side.sample(1)
        side_menu2 = available_side[
            available_side["name"] != side_menu1.iloc[0]["name"]
        ].sample(1)

        # 잡곡밥은 반드시 포함
        rice_menu = menus[menus["name"] == "잡곡밥"]
        if rice_menu.empty:
            rice_menu = pd.DataFrame([{"name": "잡곡밥", "category": "기타"}])

        # 20% 확률로 기타 메뉴 추가
        etc_menu_name = ""
        if not available_etc.empty and random.random() < 0.2:
            etc_menu = available_etc.sample(1)
            etc_menu_name = etc_menu.iloc[0]["name"]
            used_menus.add(etc_menu_name)

        # 선택된 메뉴를 사용된 메뉴 목록에 추가
        used_menus.update(
            [
                soup_menu.iloc[0]["name"] if not soup_menu.empty else "",
                main_menu.iloc[0]["name"] if not main_menu.empty else "",
                side_menu1.iloc[0]["name"] if not side_menu1.empty else "",
                side_menu2.iloc[0]["name"] if not side_menu2.empty else "",
                "잡곡밥",
            ]
        )

        day_plan.update(
            {
                "잡곡밥": "잡곡밥",
                "국/수프": soup_menu.iloc[0]["name"] if not soup_menu.empty else "",
                "메인": main_menu.iloc[0]["name"] if not main_menu.empty else "",
                "사이드1": side_menu1.iloc[0]["name"] if not side_menu1.empty else "",
                "사이드2": side_menu2.iloc[0]["name"] if not side_menu2.empty else "",
                "기타": etc_menu_name,
            }
        )

        plan.append(day_plan)

    return pd.DataFrame(plan)


def export_plan(plan_df: pd.DataFrame, filename: str) -> str:
    """
    식단 계획을 엑셀 파일로 내보냅니다.
    요일이 열, 메뉴구분(잡곡밥, 국/수프, 메인, 사이드1, 사이드2, 기타)이 행이 되도록 변환해서 저장합니다.
    값이 없더라도 반드시 행이 보이도록 합니다.
    영양 정보 시트와 일일 영양소 합계 시트도 함께 생성합니다.

    Args:
        plan_df: 내보낼 식단 계획 DataFrame
        filename: 저장할 파일 이름

    Returns:
        저장된 파일의 경로
    """
    export_dir = "exports"
    if not os.path.exists(export_dir):
        os.makedirs(export_dir)
    file_path = os.path.join(export_dir, filename)

    days = ["월", "화", "수", "목", "금"]
    row_order = ["잡곡밥", "국/수프", "메인", "사이드1", "사이드2", "기타"]

    with pd.ExcelWriter(file_path, engine="xlsxwriter") as writer:
        # 점심/저녁 시트 구분
        if "점심" in filename or ("저녁" not in filename and "점심" not in filename):
            # 점심 시트
            plan_dict = {}
            for row_name in row_order:
                plan_dict[row_name] = []
                for day in days:
                    if row_name in plan_df.columns:
                        val = plan_df.loc[plan_df["요일"] == day, row_name]
                        plan_dict[row_name].append(
                            val.values[0] if not val.empty else ""
                        )
                    else:
                        plan_dict[row_name].append("")
            plan_out_df = pd.DataFrame(plan_dict, index=days).T
            plan_out_df.columns = days
            plan_out_df.to_excel(writer, sheet_name="점심", index=True, header=True)
        if "저녁" in filename:
            # 저녁 시트 (동일 구조, 필요시 확장)
            plan_dict = {}
            for row_name in row_order:
                plan_dict[row_name] = []
                for day in days:
                    if row_name in plan_df.columns:
                        val = plan_df.loc[plan_df["요일"] == day, row_name]
                        plan_dict[row_name].append(
                            val.values[0] if not val.empty else ""
                        )
                    else:
                        plan_dict[row_name].append("")
            plan_out_df = pd.DataFrame(plan_dict, index=days).T
            plan_out_df.columns = days
            plan_out_df.to_excel(writer, sheet_name="저녁", index=True, header=True)

        # 영양 정보 시트 및 일일 영양소 합계 시트 복구
        nutrition_df = analyze_menu_plan(plan_df)
        nutrition_df.to_excel(writer, sheet_name="영양 정보", index=False)

        if not nutrition_df.empty:
            daily_totals = (
                nutrition_df.groupby("요일")
                .agg(
                    {
                        "칼로리": "sum",
                        "단백질": "sum",
                        "지방": "sum",
                        "탄수화물": "sum",
                        "나트륨": "sum",
                    }
                )
                .reset_index()
            )
            daily_totals.to_excel(writer, sheet_name="일일 영양소 합계", index=False)

    return file_path


def check_api_key() -> bool:
    """OpenAI API 키의 유효성을 검사합니다."""
    try:
        # API 키가 설정되어 있는지 확인
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            st.error("⚠️ API 키가 설정되지 않았습니다!")
            return False

        # API 키 형식 확인
        if not (api_key.startswith("sk-") or api_key.startswith("sk-proj-")):
            st.error("⚠️ API 키 형식이 올바르지 않습니다!")
            return False

        # API 키로 간단한 요청 테스트
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=5,
        )
        return True
    except AuthenticationError as e:
        st.error(f"⚠️ API 키 인증 오류: {str(e)}")
        return False
    except APIError as e:
        st.error(f"⚠️ API 오류: {str(e)}")
        return False
    except Exception as e:
        st.error(f"⚠️ 예상치 못한 오류: {str(e)}")
        return False


def delete_menu(menu_name: str) -> None:
    """메뉴 항목을 DB에서 삭제"""
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM menus WHERE name = ?", (menu_name,))
        conn.commit()
    finally:
        conn.close()


def delete_menus(menu_names: List[str]) -> None:
    """여러 메뉴 항목을 일괄 삭제"""
    for name in menu_names:
        delete_menu(name)


def get_db_connection():
    """데이터베이스 연결을 반환"""
    return sqlite3.connect("meal.db")


def analyze_menu_plan(plan_df: pd.DataFrame) -> pd.DataFrame:
    """
    식단 계획의 영양 정보를 분석합니다.
    데이터베이스에 없는 메뉴는 자동으로 추가합니다.

    Args:
        plan_df: 분석할 식단 계획 DataFrame (컬럼명: 잡곡밥, 국/수프, 메인, 사이드1, 사이드2, 기타)

    Returns:
        영양 정보가 포함된 DataFrame
    """
    menus = get_all_menus()
    nutrition_data = []
    existing_menus = set(menus["name"].tolist())

    meal_types = ["국/수프", "메인", "사이드1", "사이드2", "기타"]

    for _, row in plan_df.iterrows():
        for meal_type in meal_types:
            if (
                meal_type in plan_df.columns
                and pd.notna(row[meal_type])
                and str(row[meal_type]).strip() != ""
            ):
                menu_name = str(row[meal_type]).strip()
                if menu_name not in existing_menus:
                    try:
                        menu_info = classify_menu(menu_name)
                        menu_info["name"] = menu_name
                        add_menu(menu_info)
                        existing_menus.add(menu_name)
                        menus = get_all_menus()  # 메뉴 목록 새로고침
                    except Exception as e:
                        st.error(f"❌ {menu_name} 메뉴 추가 중 오류 발생: {str(e)}")
                        continue
                menu_info = menus[menus["name"] == menu_name]
                if not menu_info.empty:
                    nutrition_data.append(
                        {
                            "요일": row["요일"],
                            "구분": meal_type,
                            "메뉴": menu_name,
                            "칼로리": menu_info.iloc[0]["calories"],
                            "단백질": menu_info.iloc[0]["protein"],
                            "지방": menu_info.iloc[0]["fat"],
                            "탄수화물": menu_info.iloc[0]["carbs"],
                            "나트륨": menu_info.iloc[0]["sodium"],
                        }
                    )

    nutrition_df = pd.DataFrame(nutrition_data)
    day_order = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4}
    nutrition_df["요일_순서"] = nutrition_df["요일"].map(day_order)
    nutrition_df = nutrition_df.sort_values(["요일_순서", "구분"])
    nutrition_df = nutrition_df.drop("요일_순서", axis=1)
    return nutrition_df


def calculate_nutrition(plan_df: pd.DataFrame) -> Dict[str, float]:
    """
    식단 계획의 영양소 합계 계산

    Args:
        plan_df: 식단 계획 DataFrame

    Returns:
        영양소 합계 딕셔너리
    """
    menus = get_all_menus()
    total = {nutrient: 0.0 for nutrient in DEFAULT_RDI.keys()}

    for _, row in plan_df.iterrows():
        # 메뉴 영양소 계산 (점심 또는 저녁 시트)
        for meal_type in ["국/수프", "메인", "사이드1", "사이드2", "기타"]:
            if meal_type in row and row[meal_type]:
                menu_name = row[meal_type]
                menu_info = menus[menus["name"] == menu_name]
                if not menu_info.empty:
                    menu_info = menu_info.iloc[0]
                    total["칼로리"] += menu_info["calories"]
                    total["단백질"] += menu_info["protein"]
                    total["지방"] += menu_info["fat"]
                    total["탄수화물"] += menu_info["carbs"]
                    total["나트륨"] += menu_info["sodium"]

    return total


def update_menu_nutrition(menu_name: str, nutrition: Dict[str, float]) -> None:
    """
    메뉴의 영양소 정보를 업데이트합니다.

    Args:
        menu_name: 수정할 메뉴 이름
        nutrition: 새로운 영양소 정보 딕셔너리
    """
    conn = get_db_connection()
    try:
        # 영양소 정보 업데이트
        conn.execute(
            """
            UPDATE menus 
            SET calories = ?, protein = ?, fat = ?, carbs = ?, sodium = ?
            WHERE name = ?
            """,
            (
                nutrition.get("칼로리", 0),
                nutrition.get("단백질", 0),
                nutrition.get("지방", 0),
                nutrition.get("탄수화물", 0),
                nutrition.get("나트륨", 0),
                menu_name,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def update_menu_category(menu_name: str, category: str) -> None:
    """
    메뉴의 카테고리를 수정합니다.
    Args:
        menu_name: 수정할 메뉴 이름
        category: 새로운 카테고리
    """
    with sqlite3.connect("meal.db") as conn:
        conn.execute(
            """
            UPDATE menus
            SET category = ?
            WHERE name = ?
            """,
            (category, menu_name),
        )
        conn.commit()


if __name__ == "__main__":
    # 데이터베이스 초기화
    init_db()

    # 예시 메뉴 추가
    sample_menus = [
        "미역국",
        "된장국",
        "순두부찌개",
        "불고기",
        "제육볶음",
        "닭갈비",
        "김치찌개",
        "비빔밥",
        "샐러드",
        "김치",
        "멸치볶음",
        "시금치나물",
        "계란말이",
        "두부조림",
    ]

    bulk_add(sample_menus)

    # 주간 식단 계획 생성 및 내보내기 (점심만)
    plan = make_plan()
    filename = f"meal_plan_lunch_{datetime.now().strftime('%Y%m%d')}.xlsx"
    file_path = export_plan(plan, filename)
    with open(file_path, "rb") as f:
        st.download_button(
            "📥 Excel 다운로드",
            f,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="lunch_excel",
        )

    # 메뉴판 분석 결과 다운로드 (점심/저녁 시트 구조 자동 인식)
    st.markdown(
        """
    ### 📝 메뉴판 분석 가이드

    - 업로드 파일은 반드시 아래와 같은 구조여야 합니다.
    - **시트명:** '점심' 또는 '저녁'
    - **행:** 잡곡밥, 국/수프, 메인, 사이드1, 사이드2, 기타(선택)
    - **열:** 월, 화, 수, 목, 금
    - 각 셀에는 해당 요일의 메뉴명이 들어가야 합니다.
    - '요일' 컬럼만 필수, 나머지 메뉴구분(국/수프, 메인 등)은 없어도 무방합니다.
    """
    )

    uploaded_file = st.file_uploader(
        "'점심' 또는 '저녁' 시트 엑셀 업로드", type=["xlsx", "xls"]
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
                df_t = df.T.reset_index().rename(columns={"index": "요일"})
                if "요일" not in df_t.columns:
                    st.error("엑셀 파일에 '요일' 컬럼이 없습니다.")
                else:
                    df_t = df_t[df_t["요일"].isin(["월", "화", "수", "목", "금"])]
                    st.dataframe(df_t)
                    if st.button("영양 정보 분석"):
                        with st.spinner("영양 정보를 분석하는 중..."):
                            nutrition_df = analyze_menu_plan(df_t)
                            st.success("영양 정보 분석이 완료되었습니다!")
                            st.dataframe(nutrition_df)
                            filename = f"nutrition_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                            file_path = export_plan(df_t, filename)
                            with open(file_path, "rb") as f:
                                st.download_button(
                                    label="분석 결과 다운로드",
                                    data=f,
                                    file_name=filename,
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                )
        except Exception as e:
            st.error(f"파일 처리 중 오류가 발생했습니다: {str(e)}")
