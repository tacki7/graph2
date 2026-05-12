import os
import io
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="CSV 可視化アプリ", layout="wide")
st.title("CSV 可視化アプリ")

# ── サイドバー：プロキシ設定 ──────────────────────────────────────────────────
with st.sidebar:
    st.header("プロキシ設定")
    proxy_url = st.text_input(
        "プロキシURL",
        value=st.session_state.get("proxy_url", ""),
        placeholder="http://proxy.example.com:8080",
    )
    if proxy_url != st.session_state.get("proxy_url", ""):
        st.session_state["proxy_url"] = proxy_url
        if proxy_url:
            os.environ["HTTP_PROXY"] = proxy_url
            os.environ["HTTPS_PROXY"] = proxy_url
        else:
            os.environ.pop("HTTP_PROXY", None)
            os.environ.pop("HTTPS_PROXY", None)

    if proxy_url:
        st.success(f"プロキシ設定中: {proxy_url}")
    else:
        st.info("プロキシなし")

# ── [1] CSVアップロード ───────────────────────────────────────────────────────
st.header("1. CSVアップロード")
uploaded_files = st.file_uploader(
    "CSVファイルを選択（複数可）",
    type="csv",
    accept_multiple_files=True,
)

if not uploaded_files:
    st.info("CSVファイルをアップロードしてください。")
    st.stop()

# ── [2] 前処理 ────────────────────────────────────────────────────────────────
dfs = []
for f in uploaded_files:
    df_tmp = pd.read_csv(io.BytesIO(f.read()))
    df_tmp["source_file"] = f.name
    dfs.append(df_tmp)

df_all = pd.concat(dfs, ignore_index=True)

st.header("2. 前処理設定")

col_options = [c for c in df_all.columns if c != "source_file"]

sort_col = st.selectbox("ソートするカラム", options=col_options)
ascending = st.radio("ソート順", ["昇順", "降順"], horizontal=True) == "昇順"

df_sorted = df_all.sort_values(by=sort_col, ascending=ascending).reset_index(drop=True)

with st.expander("データプレビュー（先頭50行）", expanded=True):
    st.dataframe(df_sorted.head(50), use_container_width=True)

# ── [3] グラフ設定・表示 ──────────────────────────────────────────────────────
st.header("3. グラフ設定")

all_groups = sorted(df_sorted["source_file"].unique().tolist())
selected_groups = st.multiselect(
    "表示するグループ（ファイル）",
    options=all_groups,
    default=all_groups,
)

y_cols = st.multiselect(
    "Y軸カラム（複数選択可）",
    options=col_options,
)

if not selected_groups:
    st.warning("グループを1つ以上選択してください。")
    st.stop()

if not y_cols:
    st.warning("Y軸カラムを1つ以上選択してください。")
    st.stop()

total_graphs = len(selected_groups) * len(y_cols)
if total_graphs > 20:
    st.warning(f"グラフが {total_graphs} 個になります。多い場合は選択を絞ってください。")

# グラフ描画
df_filtered = df_sorted[df_sorted["source_file"].isin(selected_groups)]
groups = df_filtered.groupby("source_file", sort=False)

chart_items = [
    (group_name, y_col)
    for group_name in selected_groups
    for y_col in y_cols
]

cols = st.columns(2)
for idx, (group_name, y_col) in enumerate(chart_items):
    group_df = groups.get_group(group_name).reset_index(drop=True)
    fig = px.line(
        group_df,
        y=y_col,
        title=f"{group_name}  |  {y_col}",
        labels={"index": "行インデックス", y_col: y_col},
    )
    fig.update_layout(margin=dict(t=40, b=20, l=20, r=20))
    cols[idx % 2].plotly_chart(fig, use_container_width=True)
