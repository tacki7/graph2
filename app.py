import os
import io
import zipfile
import datetime
from collections import defaultdict
import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

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

# ── [1] ファイルアップロード ──────────────────────────────────────────────────
st.header("1. ファイルアップロード")
uploaded_files = st.file_uploader(
    "CSV / bz2 / ZIP を選択（複数可）",
    type=["csv", "bz2", "zip"],
    accept_multiple_files=True,
)
st.caption("対応形式: .csv / .csv.bz2 などの bz2 圧縮 / .zip（ZIP内のCSVを自動展開）")

if not uploaded_files:
    st.info("ファイルをアップロードしてください。")
    st.stop()

@st.cache_data(show_spinner="ファイルを読み込み中...")
def _load_file(raw: bytes, name: str) -> list:
    fname_lower = name.lower()
    result = []
    if fname_lower.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            csv_names = [n for n in zf.namelist()
                         if n.lower().endswith(".csv") and not n.startswith("__MACOSX")]
            for inner in csv_names:
                with zf.open(inner) as csv_file:
                    df_tmp = pd.read_csv(csv_file)
                    label = inner if len(csv_names) == 1 else f"{name}/{inner}"
                    df_tmp["source_file"] = label
                    result.append(df_tmp)
    elif fname_lower.endswith(".bz2"):
        df_tmp = pd.read_csv(io.BytesIO(raw), compression="bz2")
        df_tmp["source_file"] = name
        result.append(df_tmp)
    else:
        df_tmp = pd.read_csv(io.BytesIO(raw))
        df_tmp["source_file"] = name
        result.append(df_tmp)
    return result

# ── [2] 前処理 ────────────────────────────────────────────────────────────────
dfs = []
for f in uploaded_files:
    try:
        loaded = _load_file(f.read(), f.name)
        if not loaded:
            st.warning(f"{f.name}: ZIP内にCSVが見つかりませんでした。")
        dfs.extend(loaded)
    except Exception as e:
        st.error(f"{f.name} の読み込みに失敗しました: {e}")

if not dfs:
    st.warning("読み込めたCSVがありません。ファイルを確認してください。")
    st.stop()

df_all = pd.concat(dfs, ignore_index=True)

st.header("2. 前処理設定")

col_options = [c for c in df_all.columns if c != "source_file"]
numeric_cols = df_all.select_dtypes(include="number").columns.tolist()

# プレフィックス検出（例: "1std_sales" → prefix="1std", base="sales"）
_prefix_base: dict[str, list[str]] = defaultdict(list)  # base -> [prefix, ...]
for col in numeric_cols:
    if "_" in col:
        prefix, base = col.split("_", 1)
        _prefix_base[base].append(prefix)

all_prefixes = sorted({p for ps in _prefix_base.values() for p in ps})
base_numeric_cols = sorted(_prefix_base.keys())
has_prefixes = bool(all_prefixes) and bool(base_numeric_cols)

# プレフィックス付きカラムの全ベース名（数値以外も含む）
_prefixed_col_set = {f"{p}_{b}" for p in all_prefixes for col in [f"{p}_{b}" for b in base_numeric_cols] for b in base_numeric_cols if col in df_all.columns}
_prefixed_col_set = {col for col in df_all.columns if any(col.startswith(f"{p}_") for p in all_prefixes)}
_non_prefixed_cols = [c for c in col_options if c not in _prefixed_col_set]
_all_base_names = sorted({col[len(p)+1:] for col in _prefixed_col_set for p in all_prefixes if col.startswith(f"{p}_")})

sort_col = st.selectbox("ソートするカラム", options=col_options)
ascending = st.radio("ソート順", ["昇順", "降順"], horizontal=True) == "昇順"

df_sorted = df_all.sort_values(by=sort_col, ascending=ascending).reset_index(drop=True)

# ── フィルタ（行ドロップ）────────────────────────────────────────────────────
st.subheader("行フィルタ（条件に一致する行をドロップ）")
n_filters = int(st.number_input("フィルタ条件数", min_value=0, max_value=20, value=0, step=1))
_op_categories = {
    "比較":       [">", ">=", "<", "<=", "==", "!="],
    "diff":       [">", ">=", "<", "<=", "==", "!="],
    "abs(diff)":  [">", ">=", "<", "<=", "==", "!="],
    "統計":       ["== max", "== min", "> mean", "< mean"],
    "文字列":     ["含む", "含まない"],
    "欠損値":     ["NaN", "非NaN"],
}
_no_val_cats = {"統計", "欠損値"}

df_filtered_pre = df_sorted.copy()
for fi in range(n_filters):
    fc1, fc2, fc3, fc4 = st.columns([3, 2, 2, 3])
    with fc1:
        f_col = st.selectbox("カラム", options=col_options, key=f"fc_{fi}")
    with fc2:
        f_cat = st.selectbox("演算種別", options=list(_op_categories.keys()), key=f"fcat_{fi}")
    with fc3:
        f_sym = st.selectbox("演算子", options=_op_categories[f_cat], key=f"fo_{fi}")
    with fc4:
        f_val_str = st.text_input("値", key=f"fv_{fi}", disabled=f_cat in _no_val_cats)

    try:
        col_series = df_filtered_pre[f_col]
        if f_cat == "欠損値":
            mask = col_series.isna() if f_sym == "NaN" else col_series.notna()
        elif f_cat == "統計":
            stat_map = {
                "== max": col_series == col_series.max(),
                "== min": col_series == col_series.min(),
                "> mean": col_series > col_series.mean(),
                "< mean": col_series < col_series.mean(),
            }
            mask = stat_map[f_sym]
        elif f_cat == "文字列":
            base = col_series.astype(str).str.contains(f_val_str, na=False)
            mask = base if f_sym == "含む" else ~base
        else:
            f_val = pd.to_numeric(f_val_str, errors="coerce")
            if pd.isna(f_val):
                continue
            if f_cat == "diff":
                d = col_series.diff()
            elif f_cat == "abs(diff)":
                d = col_series.diff().abs()
            else:
                d = col_series
            cmp = {">": d > f_val, ">=": d >= f_val, "<": d < f_val,
                   "<=": d <= f_val, "==": d == f_val, "!=": d != f_val}
            mask = cmp[f_sym]
        df_filtered_pre = df_filtered_pre[~mask].reset_index(drop=True)
    except Exception:
        pass

if n_filters > 0:
    st.caption(f"フィルタ適用後: {len(df_filtered_pre):,} 行（{len(df_sorted) - len(df_filtered_pre):,} 行ドロップ）")

df_sorted = df_filtered_pre

with st.expander("データプレビュー（先頭50行）", expanded=True):
    st.dataframe(df_sorted.head(50), use_container_width=True)

def _img_cfg(w, h, scale=2):
    return {"toImageButtonOptions": {"format": "png", "width": int(w), "height": int(h), "scale": scale}}

# ── [3] 中間処理：統計特徴量分析 ─────────────────────────────────────────────
st.header("3. 中間処理")

with st.expander("統計特徴量の分析", expanded=False):
    _a1, _a2, _a3 = st.columns(3)
    with _a1:
        an_stats          = st.checkbox("基本統計量",         value=True, key="an_stats")
        an_hist           = st.checkbox("ヒストグラム",       value=True, key="an_hist")
        an_hist_hollow    = st.checkbox("　└ 輪郭のみ",                    key="an_hist_hollow")
        an_box            = st.checkbox("箱ひげ図",           value=True, key="an_box")
    with _a2:
        an_violin  = st.checkbox("バイオリン図",               key="an_violin")
        an_corr    = st.checkbox("相関行列",       value=True, key="an_corr")
        an_scatter = st.checkbox("散布図行列",                 key="an_scatter")
        an_scatter_hollow = st.checkbox("　└ 白抜き",                     key="an_scatter_hollow")
        an_scatter_bw     = st.number_input("　└ 枠線の太さ", min_value=0.5, max_value=10.0, value=1.5, step=0.5, key="an_scatter_bw")
        an_scatter_maxrows = int(st.number_input("　└ 最大行数", min_value=500, max_value=50000, value=5000, step=500, key="an_scatter_maxrows"))
        st.caption("散布図行列は列数²に比例して重くなります")
    with _a3:
        an_rolling = st.checkbox("ローリング統計",             key="an_rolling")
        an_outlier = st.checkbox("外れ値分析（IQR）",         key="an_outlier")
        an_skew    = st.checkbox("歪度・尖度",                 key="an_skew")

    if an_rolling:
        roll_window = int(st.number_input("ローリングウィンドウ幅", 2, 500, 20, key="roll_w"))

    an_target = st.multiselect(
        "分析対象カラム（数値）",
        options=numeric_cols,
        default=numeric_cols[:min(6, len(numeric_cols))],
        key="an_target",
    )

    if st.button("統計特徴量を分析・表示", key="run_analysis"):
        st.session_state["_analysis_done"] = True

    if st.session_state.get("_analysis_done") and an_target:
        _has_src = "source_file" in df_sorted.columns
        _id_vars = ["source_file"] if _has_src else []
        _n_cols = len(an_target)
        _n_files = df_sorted["source_file"].nunique() if _has_src else 1
        _n_rows = len(df_sorted)

        # 基本統計量
        if an_stats:
            st.subheader("基本統計量")
            st.dataframe(df_sorted[an_target].describe().T.round(4), use_container_width=True)

        # 歪度・尖度
        if an_skew:
            st.subheader("歪度・尖度")
            st.dataframe(pd.DataFrame({
                "歪度": df_sorted[an_target].skew(),
                "尖度": df_sorted[an_target].kurtosis(),
            }).round(4), use_container_width=True)

        # ヒストグラム（3列グリッド、列ごとに独立）
        if an_hist:
            st.subheader("ヒストグラム")
            _hcols = st.columns(min(3, _n_cols))
            _hist_w = max(700, 150 * _n_files + 400)
            _hist_h = max(400, 300 + _n_files * 20)
            _default_colors = px.colors.qualitative.Plotly
            for _i, _c in enumerate(an_target):
                with _hcols[_i % 3]:
                    fig = px.histogram(df_sorted, x=_c,
                                       color="source_file" if _has_src else None,
                                       barmode="overlay", opacity=0.7, title=_c)
                    if an_hist_hollow:
                        for _ti, _tr in enumerate(fig.data):
                            _col = _tr.marker.color or _default_colors[_ti % len(_default_colors)]
                            _tr.marker.update(color="rgba(0,0,0,0)",
                                              line=dict(color=_col, width=2))
                        fig.update_traces(opacity=1.0)
                    fig.update_layout(margin=dict(t=40, b=20, l=20, r=20))
                    st.plotly_chart(fig, width='stretch', key=f"hist_{_c}",
                                    config=_img_cfg(_hist_w, _hist_h))

        # 箱ひげ図（全列を1グラフに）
        if an_box:
            st.subheader("箱ひげ図")
            _melt = df_sorted[_id_vars + an_target].melt(
                id_vars=_id_vars, value_vars=an_target, var_name="カラム", value_name="値")
            fig = px.box(_melt, x="カラム", y="値",
                         color="source_file" if _has_src else None, title="箱ひげ図")
            _box_w = max(900, _n_cols * (60 * _n_files + 50) + 250)
            st.plotly_chart(fig, width='stretch', key="box_plot",
                            config=_img_cfg(_box_w, 600))

        # バイオリン図
        if an_violin:
            st.subheader("バイオリン図")
            _melt = df_sorted[_id_vars + an_target].melt(
                id_vars=_id_vars, value_vars=an_target, var_name="カラム", value_name="値")
            fig = px.violin(_melt, x="カラム", y="値",
                            color="source_file" if _has_src else None,
                            box=True, title="バイオリン図")
            _vio_w = max(900, _n_cols * (70 * _n_files + 50) + 250)
            st.plotly_chart(fig, width='stretch', key="violin_plot",
                            config=_img_cfg(_vio_w, 650))

        # 相関行列（正方形、列数に比例）
        if an_corr:
            st.subheader("相関行列")
            corr = df_sorted[an_target].corr().round(3)
            fig = px.imshow(corr, text_auto=True, aspect="auto",
                            color_continuous_scale="RdBu_r", zmin=-1, zmax=1,
                            title="相関行列（Pearson）")
            _corr_side = max(600, _n_cols * 100 + 200)
            st.plotly_chart(fig, width='stretch', key="corr_matrix",
                            config=_img_cfg(_corr_side, _corr_side))

        # 散布図行列（n×n パネル）
        if an_scatter:
            st.subheader("散布図行列")
            df_scat = df_sorted
            if len(df_scat) > an_scatter_maxrows:
                df_scat = df_scat.sample(an_scatter_maxrows, random_state=42).reset_index(drop=True)
                st.caption(f"描画負荷軽減のため {an_scatter_maxrows:,} 行にサンプリングしました（元: {len(df_sorted):,} 行）")
            fig = px.scatter_matrix(df_scat, dimensions=an_target,
                                    color="source_file" if _has_src else None,
                                    opacity=0.4, title="散布図行列")
            if an_scatter_hollow:
                fig.update_traces(diagonal_visible=False,
                                  marker=dict(symbol="circle-open", line=dict(width=an_scatter_bw)))
            else:
                fig.update_traces(diagonal_visible=False,
                                  marker=dict(line=dict(width=an_scatter_bw)))
            _scat_side = max(900, _n_cols * 220)
            st.plotly_chart(fig, width='stretch', key="scatter_matrix",
                            config=_img_cfg(_scat_side, _scat_side))

        # ローリング統計（2列グリッド、系列数に応じて幅調整）
        if an_rolling:
            st.subheader(f"ローリング統計（ウィンドウ: {roll_window}）")
            _rcols = st.columns(min(2, _n_cols))
            _n_roll_series = _n_files * 3  # 元・平均・STD × ファイル数
            _roll_w = max(1000, 200 + _n_roll_series * 60 + min(_n_rows, 2000) // 10)
            _roll_h = max(450, 350 + _n_roll_series * 15)
            for _i, _c in enumerate(an_target):
                with _rcols[_i % 2]:
                    df_r = df_sorted[[_c] + _id_vars].copy()
                    df_r["_ridx"] = df_r.groupby("source_file").cumcount() if _has_src else range(len(df_r))
                    if _has_src:
                        df_r["ローリング平均"] = df_r.groupby("source_file")[_c].transform(
                            lambda x: x.rolling(roll_window, min_periods=1).mean())
                        df_r["ローリングSTD"] = df_r.groupby("source_file")[_c].transform(
                            lambda x: x.rolling(roll_window, min_periods=1).std())
                    else:
                        df_r["ローリング平均"] = df_r[_c].rolling(roll_window, min_periods=1).mean()
                        df_r["ローリングSTD"] = df_r[_c].rolling(roll_window, min_periods=1).std()
                    _melt_r = df_r.melt(id_vars=["_ridx"] + _id_vars,
                                        value_vars=[_c, "ローリング平均", "ローリングSTD"],
                                        var_name="系列", value_name="値")
                    fig = px.line(_melt_r, x="_ridx", y="値",
                                  color="系列", line_dash="source_file" if _has_src else None,
                                  title=f"{_c} ローリング統計",
                                  labels={"_ridx": "行インデックス"})
                    fig.update_traces(opacity=0.8)
                    fig.update_layout(margin=dict(t=40, b=20, l=20, r=20))
                    st.plotly_chart(fig, width='stretch', key=f"rolling_{_c}",
                                    config=_img_cfg(_roll_w, _roll_h))

        # 外れ値分析（3列グリッド、データ点数に応じてスケール）
        if an_outlier:
            st.subheader("外れ値分析（IQR法）")
            _outlier_rows = []
            for _c in an_target:
                _q1, _q3 = df_sorted[_c].quantile(0.25), df_sorted[_c].quantile(0.75)
                _iqr = _q3 - _q1
                _lo, _hi = _q1 - 1.5 * _iqr, _q3 + 1.5 * _iqr
                _n = int(((df_sorted[_c] < _lo) | (df_sorted[_c] > _hi)).sum())
                _outlier_rows.append({"カラム": _c, "下限": round(_lo, 3), "上限": round(_hi, 3),
                                      "外れ値数": _n, "外れ値率(%)": round(_n / len(df_sorted) * 100, 2)})
            st.dataframe(pd.DataFrame(_outlier_rows), use_container_width=True)

            _ocols = st.columns(min(3, _n_cols))
            _out_scale = 3 if _n_rows > 5000 else 2
            _out_w = max(800, 400 + min(_n_rows, 5000) // 10)
            for _i, _c in enumerate(an_target):
                with _ocols[_i % 3]:
                    _q1, _q3 = df_sorted[_c].quantile(0.25), df_sorted[_c].quantile(0.75)
                    _iqr = _q3 - _q1
                    _df_o = df_sorted[[_c] + _id_vars].copy()
                    _df_o["判定"] = ((_df_o[_c] < _q1 - 1.5*_iqr) | (_df_o[_c] > _q3 + 1.5*_iqr)).map(
                        {True: "外れ値", False: "正常"})
                    _df_o["_idx"] = range(len(_df_o))
                    fig = px.scatter(_df_o, x="_idx", y=_c, color="判定",
                                     color_discrete_map={"外れ値": "red", "正常": "steelblue"},
                                     title=_c, opacity=0.5,
                                     labels={"_idx": "行インデックス"})
                    fig.update_layout(margin=dict(t=40, b=20, l=20, r=20))
                    st.plotly_chart(fig, width='stretch', key=f"outlier_{_c}",
                                    config=_img_cfg(_out_w, 500, scale=_out_scale))

# ── [4] グラフ設定・表示 ──────────────────────────────────────────────────────
st.header("4. グラフ設定")

all_groups = sorted(df_sorted["source_file"].unique().tolist())

if not numeric_cols:
    st.warning("数値カラムが見つかりません。CSVを確認してください。")
    st.stop()

n_graphs = int(st.number_input("グラフ数", min_value=1, max_value=max(20, len(numeric_cols)), value=1, step=1))
n_cols = st.radio("1行あたりの列数", [1, 2, 3, 4], index=1, horizontal=True)
max_pts_per_trace = int(st.number_input(
    "トレースあたりの最大描画点数（超過時は等間隔間引き）",
    min_value=1000, max_value=200000, value=50000, step=1000, key="max_pts_per_trace",
))
st.caption("💡 描画点数の目安: 〜5万点=快適 / 5〜20万点=やや重い / 20万点超=クラッシュ注意。散布図は自動でWebGL描画に切り替わります。")

st.divider()
show_vline_all = st.checkbox("縦線を表示（行インデックス軸のグラフ全体に反映）", key="show_vline_all")
if show_vline_all:
    _vc1, _vc2, _vc3 = st.columns([3, 1, 1])
    with _vc1:
        _vline_max = int(df_sorted.groupby("source_file").size().min()) - 1
        vline_pos_all = st.slider("縦線の位置（行インデックス）", 0, max(_vline_max, 1),
                                  _vline_max // 2, key="vline_pos_all")
        st.caption("グラフ上で縦線をドラッグして移動できます")
    with _vc2:
        vline_color_all = st.selectbox("縦線の色", ["red","blue","green","orange","purple","gray"], key="vline_color_all")
    with _vc3:
        vline_dash_all = st.selectbox("縦線スタイル", ["dash","solid","dot","dashdot"], key="vline_dash_all")
else:
    vline_pos_all = 0
    vline_color_all = "red"
    vline_dash_all = "dash"

for row_start in range(0, n_graphs, n_cols):
    cols = st.columns(n_cols)
    for j in range(n_cols):
        graph_idx = row_start + j
        if graph_idx >= n_graphs:
            break
        with cols[j]:
            # グループ選択（グラフごと）
            sel_groups = st.multiselect(
                f"グラフ {graph_idx + 1} のグループ",
                options=all_groups,
                default=all_groups,
                key=f"groups_{graph_idx}",
            )
            if not sel_groups:
                st.warning("グループを1つ以上選択してください。")
                continue

            # Y軸・プレフィックス
            if has_prefixes:
                base_col = st.selectbox(
                    f"グラフ {graph_idx + 1} のY軸",
                    options=base_numeric_cols,
                    index=min(graph_idx, len(base_numeric_cols) - 1),
                    key=f"base_col_{graph_idx}",
                )
                sel_prefixes = st.multiselect(
                    f"グラフ {graph_idx + 1} のプレフィックス",
                    options=all_prefixes,
                    default=all_prefixes,
                    key=f"prefixes_{graph_idx}",
                )
            else:
                base_col = st.selectbox(
                    f"グラフ {graph_idx + 1} のY軸",
                    options=numeric_cols,
                    index=min(graph_idx, len(numeric_cols) - 1),
                    key=f"y_col_{graph_idx}",
                )

            # X軸選択
            if has_prefixes:
                _x_options = ["連番（行インデックス）"] + _non_prefixed_cols + _all_base_names
            else:
                _x_options = ["連番（行インデックス）"] + col_options
            _x_sel = st.selectbox(
                f"グラフ {graph_idx + 1} のX軸",
                options=_x_options,
                key=f"x_col_{graph_idx}",
            )
            x_col = "_idx" if _x_sel == "連番（行インデックス）" else _x_sel
            x_is_prefixed_base = has_prefixes and x_col != "_idx" and x_col in _all_base_names

            with st.expander("スタイル設定"):
                chart_type = st.selectbox(
                    "グラフタイプ",
                    ["折れ線", "散布図", "棒グラフ"],
                    key=f"chart_type_{graph_idx}",
                )
                opacity = st.number_input("透明度", min_value=0.1, max_value=1.0, value=0.7, step=0.1, key=f"op_{graph_idx}")
                if chart_type == "折れ線":
                    line_width = st.number_input("線の太さ", min_value=0.1, max_value=10.0, value=1.0, step=0.1, key=f"lw_{graph_idx}")
                    line_dash = st.selectbox(
                        "線スタイル",
                        ["solid", "dash", "dot", "dashdot"],
                        key=f"ld_{graph_idx}",
                    )
                elif chart_type == "散布図":
                    hollow = st.checkbox("白抜き", key=f"hollow_{graph_idx}")
                    border_width = st.number_input("枠線の太さ", min_value=0.1, max_value=10.0, value=2.0, step=0.1, key=f"bw_{graph_idx}")

            # データ準備（グラフごとにフィルタ）
            df_g = df_sorted[df_sorted["source_file"].isin(sel_groups)].copy()
            df_g["_idx"] = df_g.groupby("source_file").cumcount()

            if has_prefixes:
                if x_is_prefixed_base:
                    # X・Y 両方に同じプレフィックスを適用してプレフィックスごとに結合
                    parts = []
                    for p in sel_prefixes:
                        yc = f"{p}_{base_col}"
                        xc = f"{p}_{x_col}" if f"{p}_{x_col}" in df_g.columns else x_col
                        if yc not in df_g.columns:
                            continue
                        tmp = df_g[["source_file", xc, yc]].copy()
                        tmp.rename(columns={xc: "__x__", yc: base_col}, inplace=True)
                        tmp["凡例"] = tmp["source_file"] + " / " + p
                        parts.append(tmp)
                    if not parts:
                        st.warning("プレフィックスを1つ以上選択してください。")
                        continue
                    plot_df = pd.concat(parts, ignore_index=True)
                    x_for_plot = "__x__"
                else:
                    y_cols = [f"{p}_{base_col}" for p in sel_prefixes if f"{p}_{base_col}" in df_g.columns]
                    if not y_cols:
                        st.warning("プレフィックスを1つ以上選択してください。")
                        continue
                    id_vars = ["_idx", "source_file"] if x_col == "_idx" else list(dict.fromkeys([x_col, "_idx", "source_file"]))
                    plot_df = (
                        df_g[id_vars + y_cols]
                        .melt(id_vars=id_vars, value_vars=y_cols, var_name="prefix_col", value_name=base_col)
                    )
                    plot_df["凡例"] = plot_df["source_file"] + " / " + plot_df["prefix_col"].str.split("_").str[0]
                    x_for_plot = x_col
                color_col, y_axis, title = "凡例", base_col, base_col
                labels = {"_idx": "行インデックス"}
            else:
                plot_df = df_g.copy()
                x_for_plot = x_col
                color_col, y_axis, title = "source_file", base_col, base_col
                labels = {"_idx": "行インデックス", base_col: base_col, "source_file": "ファイル"}

            x_label = "行インデックス" if x_col == "_idx" else x_col
            labels[x_for_plot] = x_label

            # X軸が時間型かどうかを検出して変換
            _x_is_datetime = False
            if x_for_plot in plot_df.columns and x_for_plot != "_idx":
                _col_dtype = plot_df[x_for_plot].dtype
                if pd.api.types.is_datetime64_any_dtype(_col_dtype):
                    _x_is_datetime = True
                elif _col_dtype == object:
                    _parsed = pd.to_datetime(plot_df[x_for_plot], errors="coerce")
                    if _parsed.notna().mean() >= 0.9:
                        plot_df = plot_df.copy()
                        plot_df[x_for_plot] = _parsed
                        _x_is_datetime = True

            # 間引き（トレースごとに max_pts_per_trace を上限に等間隔サンプリング）
            _sampled = False
            if color_col in plot_df.columns:
                _parts = []
                for _grp, _gdf in plot_df.groupby(color_col, sort=False):
                    if len(_gdf) > max_pts_per_trace:
                        _step = len(_gdf) // max_pts_per_trace + 1
                        _gdf = _gdf.iloc[::_step]
                        _sampled = True
                    _parts.append(_gdf)
                plot_df = pd.concat(_parts, ignore_index=True)
            elif len(plot_df) > max_pts_per_trace:
                _step = len(plot_df) // max_pts_per_trace + 1
                plot_df = plot_df.iloc[::_step].reset_index(drop=True)
                _sampled = True
            if _sampled:
                st.caption(f"描画点数が多いため間引きました（表示: {len(plot_df):,} 点）")

            # WebGL 切り替え（散布図 & 総点数 > 10000）
            _use_webgl = chart_type == "散布図" and len(plot_df) > 10000


            # グラフ描画
            common = dict(data_frame=plot_df, x=x_for_plot, y=y_axis, color=color_col, title=title, labels=labels)
            if chart_type == "折れ線":
                fig = px.line(**common)
                fig.update_traces(line=dict(width=line_width, dash=line_dash), opacity=opacity)
            elif chart_type == "散布図":
                fig = px.scatter(**common, render_mode="webgl" if _use_webgl else "auto")
                marker_symbol = "circle-open" if hollow else "circle"
                fig.update_traces(marker=dict(symbol=marker_symbol, line=dict(width=border_width)), opacity=opacity)
            else:
                fig = px.bar(**common)
                fig.update_traces(opacity=opacity)

            # 縦線を描画（行インデックス軸のみ・グラフ上でドラッグ移動可）
            if show_vline_all and x_col == "_idx":
                _vx = vline_pos_all
                fig.add_shape(
                    type="line",
                    x0=_vx, x1=_vx,
                    y0=0, y1=1, yref="paper",
                    line=dict(color=vline_color_all, width=2, dash=vline_dash_all),
                )
                # 縦線位置のY値をアノテーション表示
                _y_items = []
                if color_col in plot_df.columns:
                    for _gn, _gdf in plot_df.groupby(color_col, sort=False):
                        if "_idx" in _gdf.columns and len(_gdf) > 0:
                            _lbl = (_gdf["_idx"] - _vx).abs().idxmin()
                            _yv = _gdf.loc[_lbl, y_axis]
                            if pd.notna(_yv):
                                _y_items.append(f"{_gn}: {_yv:.2f}")
                if _y_items:
                    fig.add_annotation(
                        x=_vx, y=1, yref="paper",
                        text="<br>".join(_y_items),
                        showarrow=False, xanchor="left", align="left",
                        font=dict(size=10, color=vline_color_all),
                        bgcolor="rgba(255,255,255,0.85)",
                        bordercolor=vline_color_all, borderwidth=1,
                    )

            # スパイクライン（ホバー追従型クロスヘア）
            if x_for_plot != "_idx":
                fig.update_xaxes(showspikes=True, spikemode="across+toaxis",
                                  spikesnap="cursor", spikecolor="#888888",
                                  spikethickness=1, spikedash="solid")
                fig.update_yaxes(showspikes=True, spikecolor="#cccccc",
                                  spikethickness=1, spikedash="dot")
                fig.update_layout(hovermode="x unified")

            fig.update_layout(margin=dict(t=40, b=20, l=20, r=20))
            _n_traces = len(sel_prefixes) * len(sel_groups) if has_prefixes else len(sel_groups)
            _n_pts = len(plot_df)
            _mg_w = max(1200, 400 + _n_traces * 40 + min(_n_pts // _n_traces if _n_traces else _n_pts, 2000) // 8)
            _mg_h = max(500, 400 + _n_traces * 10)
            _mg_scale = 3 if _n_pts > 10000 else 2
            _chart_cfg = _img_cfg(_mg_w, _mg_h, scale=_mg_scale)
            if show_vline_all and x_col == "_idx":
                _chart_cfg["edits"] = {"shapePosition": True}
            st.plotly_chart(fig, width='stretch', key=f"main_graph_{graph_idx}",
                            config=_chart_cfg)

# 縦線の位置をすべてのグラフで同時同期（クライアントサイドJS）
if show_vline_all:
    components.html("""
<script>
(function(){
  var doc = window.parent.document;
  var Plotly = window.parent.Plotly;
  var syncing = false;  // 無限ループ防止フラグ

  function syncVlines(srcDiv, newX) {
    if (syncing) return;
    syncing = true;
    try {
      doc.querySelectorAll('.js-plotly-plot').forEach(function(div) {
        if (div === srcDiv) return;
        if (!div.layout || !div.layout.shapes) return;
        var upd = {};
        div.layout.shapes.forEach(function(s, i) {
          if (s.type === 'line' && s.yref === 'paper') {
            upd['shapes[' + i + '].x0'] = newX;
            upd['shapes[' + i + '].x1'] = newX;
          }
        });
        if (Object.keys(upd).length) Plotly.relayout(div, upd);
      });
    } finally {
      syncing = false;
    }
  }

  function attach() {
    doc.querySelectorAll('.js-plotly-plot').forEach(function(div) {
      if (div._vls) return;
      div._vls = true;
      div.on('plotly_relayout', function(ed) {
        if (syncing) return;
        var k = Object.keys(ed).find(function(k) {
          return k.indexOf('shapes[') === 0 && k.slice(-3) === '.x0';
        });
        if (k != null) syncVlines(div, ed[k]);
      });
    });
  }

  // グラフ描画完了後に複数回アタッチ試行（MutationObserverの代替）
  attach();
  setTimeout(attach, 600);
  setTimeout(attach, 1500);
})();
</script>
""", height=0)
