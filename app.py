import os
import io
import zipfile
from collections import defaultdict
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.font_manager as _fm
_fm.fontManager.addfont(r"C:\Windows\Fonts\msgothic.ttc")
matplotlib.rcParams["font.family"] = "MS Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
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

_prefix_base: dict[str, list[str]] = defaultdict(list)
for col in numeric_cols:
    if "_" in col:
        prefix, base = col.split("_", 1)
        _prefix_base[base].append(prefix)

all_prefixes = sorted({p for ps in _prefix_base.values() for p in ps})
base_numeric_cols = sorted(_prefix_base.keys())
has_prefixes = bool(all_prefixes) and bool(base_numeric_cols)

_prefixed_col_set = {col for col in df_all.columns if any(col.startswith(f"{p}_") for p in all_prefixes)}
_non_prefixed_cols = [c for c in col_options if c not in _prefixed_col_set]
_all_base_names = sorted({col[len(p)+1:] for col in _prefixed_col_set for p in all_prefixes if col.startswith(f"{p}_")})

sort_col = st.selectbox("ソートするカラム", options=col_options)
ascending = st.radio("ソート順", ["昇順", "降順"], horizontal=True) == "昇順"

df_sorted = df_all.sort_values(by=sort_col, ascending=ascending).reset_index(drop=True)

# ── フィルタ ──────────────────────────────────────────────────────────────────
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

# ── [3] 統計特徴量分析（Matplotlib） ─────────────────────────────────────────
st.header("3. 中間処理")

_MPLLS = {"solid": "-", "dash": "--", "dot": ":", "dashdot": "-."}
_MPL_COLORS = plt.rcParams["axes.prop_cycle"].by_key()["color"]

def _mpl_color(i):
    return _MPL_COLORS[i % len(_MPL_COLORS)]

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
        _n_cols_an = len(an_target)
        _src_list = sorted(df_sorted["source_file"].unique()) if _has_src else [None]
        _n_files = len(_src_list)

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

        # ヒストグラム（3列グリッド）
        if an_hist:
            st.subheader("ヒストグラム")
            _hcols = st.columns(min(3, _n_cols_an))
            for _i, _c in enumerate(an_target):
                with _hcols[_i % 3]:
                    _fig, _ax = plt.subplots(figsize=(5, 3.5))
                    for _si, _src in enumerate(_src_list):
                        _d = df_sorted[df_sorted["source_file"] == _src][_c].dropna() if _has_src else df_sorted[_c].dropna()
                        _lbl = _src if _has_src else _c
                        _col = _mpl_color(_si)
                        if an_hist_hollow:
                            _ax.hist(_d, bins=30, label=_lbl, histtype="step",
                                     color=_col, linewidth=1.5, alpha=0.9)
                        else:
                            _ax.hist(_d, bins=30, label=_lbl, color=_col, alpha=0.6)
                    _ax.set_title(_c, fontsize=9)
                    _ax.set_xlabel(_c, fontsize=8)
                    _ax.set_ylabel("度数", fontsize=8)
                    if _n_files > 1:
                        _ax.legend(fontsize=7)
                    _fig.tight_layout()
                    st.pyplot(_fig, use_container_width=True)
                    plt.close(_fig)

        # 箱ひげ図
        if an_box:
            st.subheader("箱ひげ図")
            _fig, _ax = plt.subplots(figsize=(max(6, _n_cols_an * 1.5 * _n_files), 5))
            _positions = np.arange(_n_cols_an)
            _width = 0.8 / max(_n_files, 1)
            for _si, _src in enumerate(_src_list):
                _data = [df_sorted[df_sorted["source_file"] == _src][_c].dropna().values
                         if _has_src else df_sorted[_c].dropna().values
                         for _c in an_target]
                _pos = _positions + (_si - (_n_files - 1) / 2) * _width
                _bp = _ax.boxplot(_data, positions=_pos, widths=_width * 0.9,
                                  patch_artist=True, medianprops=dict(color="black"))
                _col = _mpl_color(_si)
                for _patch in _bp["boxes"]:
                    _patch.set_facecolor(_col)
                    _patch.set_alpha(0.6)
            _ax.set_xticks(_positions)
            _ax.set_xticklabels(an_target, rotation=30, ha="right", fontsize=8)
            if _n_files > 1:
                _handles = [plt.Rectangle((0,0),1,1, color=_mpl_color(_si), alpha=0.6) for _si in range(_n_files)]
                _ax.legend(_handles, _src_list, fontsize=7)
            _fig.tight_layout()
            st.pyplot(_fig, use_container_width=True)
            plt.close(_fig)

        # バイオリン図
        if an_violin:
            st.subheader("バイオリン図")
            _fig, _ax = plt.subplots(figsize=(max(6, _n_cols_an * 1.5 * _n_files), 5))
            _positions = np.arange(_n_cols_an)
            _width = 0.8 / max(_n_files, 1)
            for _si, _src in enumerate(_src_list):
                _data = [df_sorted[df_sorted["source_file"] == _src][_c].dropna().values
                         if _has_src else df_sorted[_c].dropna().values
                         for _c in an_target]
                _data = [d for d in _data if len(d) >= 2]
                if not _data:
                    continue
                _pos = _positions[:len(_data)] + (_si - (_n_files - 1) / 2) * _width
                _vp = _ax.violinplot(_data, positions=_pos, widths=_width * 0.9, showmedians=True)
                _col = _mpl_color(_si)
                for _pc in _vp["bodies"]:
                    _pc.set_facecolor(_col)
                    _pc.set_alpha(0.5)
            _ax.set_xticks(_positions)
            _ax.set_xticklabels(an_target, rotation=30, ha="right", fontsize=8)
            _fig.tight_layout()
            st.pyplot(_fig, use_container_width=True)
            plt.close(_fig)

        # 相関行列
        if an_corr:
            st.subheader("相関行列")
            _corr = df_sorted[an_target].corr().round(3)
            _side = max(5, _n_cols_an * 0.8)
            _fig, _ax = plt.subplots(figsize=(_side, _side))
            _im = _ax.imshow(_corr.values, vmin=-1, vmax=1, cmap="RdBu_r", aspect="auto")
            _ax.set_xticks(range(_n_cols_an))
            _ax.set_yticks(range(_n_cols_an))
            _ax.set_xticklabels(_corr.columns, rotation=45, ha="right", fontsize=8)
            _ax.set_yticklabels(_corr.index, fontsize=8)
            for _r in range(_n_cols_an):
                for _cc in range(_n_cols_an):
                    _ax.text(_cc, _r, f"{_corr.values[_r, _cc]:.2f}",
                             ha="center", va="center", fontsize=7)
            plt.colorbar(_im, ax=_ax, shrink=0.8)
            _ax.set_title("相関行列（Pearson）", fontsize=10)
            _fig.tight_layout()
            st.pyplot(_fig, use_container_width=True)
            plt.close(_fig)

        # 散布図行列
        if an_scatter:
            st.subheader("散布図行列")
            df_scat = df_sorted
            if len(df_scat) > an_scatter_maxrows:
                df_scat = df_scat.sample(an_scatter_maxrows, random_state=42).reset_index(drop=True)
                st.caption(f"描画負荷軽減のため {an_scatter_maxrows:,} 行にサンプリングしました（元: {len(df_sorted):,} 行）")
            _side2 = max(4, _n_cols_an * 2)
            _fig, _axes = plt.subplots(_n_cols_an, _n_cols_an, figsize=(_side2, _side2))
            if _n_cols_an == 1:
                _axes = np.array([[_axes]])
            for _r in range(_n_cols_an):
                for _cc in range(_n_cols_an):
                    _ax2 = _axes[_r][_cc]
                    if _r == _cc:
                        _ax2.set_visible(False)
                        continue
                    for _si, _src in enumerate(_src_list):
                        _df2 = df_scat[df_scat["source_file"] == _src] if _has_src else df_scat
                        _xd2 = _df2[an_target[_cc]].values
                        _yd2 = _df2[an_target[_r]].values
                        _col = _mpl_color(_si)
                        if an_scatter_hollow:
                            _ax2.scatter(_xd2, _yd2, s=4, facecolors="none",
                                         edgecolors=_col, linewidths=an_scatter_bw, alpha=0.5)
                        else:
                            _ax2.scatter(_xd2, _yd2, s=4, color=_col,
                                         linewidths=an_scatter_bw, alpha=0.5)
                    if _r == _n_cols_an - 1:
                        _ax2.set_xlabel(an_target[_cc], fontsize=7)
                    if _cc == 0:
                        _ax2.set_ylabel(an_target[_r], fontsize=7)
                    _ax2.tick_params(labelsize=6)
            _fig.tight_layout()
            st.pyplot(_fig, use_container_width=True)
            plt.close(_fig)

        # ローリング統計
        if an_rolling:
            st.subheader(f"ローリング統計（ウィンドウ: {roll_window}）")
            _rcols = st.columns(min(2, _n_cols_an))
            for _i, _c in enumerate(an_target):
                with _rcols[_i % 2]:
                    _fig, _ax = plt.subplots(figsize=(7, 3.5))
                    for _si, _src in enumerate(_src_list):
                        _df_r = df_sorted[df_sorted["source_file"] == _src].copy() if _has_src else df_sorted.copy()
                        _xr = np.arange(len(_df_r))
                        _col = _mpl_color(_si)
                        _lbl = _src if _has_src else _c
                        _ax.plot(_xr, _df_r[_c].values, color=_col, alpha=0.3, linewidth=0.8, label=f"{_lbl} 元")
                        _ax.plot(_xr, _df_r[_c].rolling(roll_window, min_periods=1).mean().values,
                                 color=_col, linewidth=1.5, label=f"{_lbl} 平均")
                        _ax.plot(_xr, _df_r[_c].rolling(roll_window, min_periods=1).std().values,
                                 color=_col, linewidth=1.0, linestyle="--", label=f"{_lbl} STD")
                    _ax.set_title(f"{_c} ローリング統計", fontsize=9)
                    _ax.set_xlabel("行インデックス", fontsize=8)
                    _ax.legend(fontsize=7)
                    _fig.tight_layout()
                    st.pyplot(_fig, use_container_width=True)
                    plt.close(_fig)

        # 外れ値分析
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

            _ocols = st.columns(min(3, _n_cols_an))
            for _i, _c in enumerate(an_target):
                with _ocols[_i % 3]:
                    _q1, _q3 = df_sorted[_c].quantile(0.25), df_sorted[_c].quantile(0.75)
                    _iqr = _q3 - _q1
                    _lo2, _hi2 = _q1 - 1.5 * _iqr, _q3 + 1.5 * _iqr
                    _df_o = df_sorted[_c].reset_index(drop=True)
                    _is_out = (_df_o < _lo2) | (_df_o > _hi2)
                    _fig, _ax = plt.subplots(figsize=(5, 3.5))
                    _ax.scatter(_df_o.index[~_is_out], _df_o[~_is_out], s=3, color="steelblue", alpha=0.5, label="正常")
                    _ax.scatter(_df_o.index[_is_out],  _df_o[_is_out],  s=6, color="red",       alpha=0.8, label="外れ値")
                    _ax.set_title(_c, fontsize=9)
                    _ax.set_xlabel("行インデックス", fontsize=8)
                    _ax.legend(fontsize=7)
                    _fig.tight_layout()
                    st.pyplot(_fig, use_container_width=True)
                    plt.close(_fig)

# ── [4] 個別グラフ選択 ───────────────────────────────────────────────────────
st.header("4. 個別グラフ選択")

all_groups = sorted(df_sorted["source_file"].unique().tolist())

if not numeric_cols:
    st.warning("数値カラムが見つかりません。CSVを確認してください。")
    st.stop()

if has_prefixes:
    _y_options = base_numeric_cols
else:
    _y_options = numeric_cols

if has_prefixes:
    _x_options = ["連番（行インデックス）"] + _non_prefixed_cols + _all_base_names
else:
    _x_options = ["連番（行インデックス）"] + col_options

sel_groups = all_groups
df_g_base = df_sorted[df_sorted["source_file"].isin(sel_groups)].copy()
df_g_base["_idx"] = df_g_base.groupby("source_file").cumcount()
detail_n_cols = len(sel_groups)

_tab1, _tab2 = st.tabs(["時系列グラフ", "変数間グラフ"])

# ── タブ1: 時系列グラフ ───────────────────────────────────────────────────────
with _tab1:
    _ca, _cb, _cc, _cd, _ce, _cf, _cg, _ch = st.columns(8)
    with _ca:
        detail_n_rows = int(st.number_input("行数", min_value=1, max_value=20,
                                             value=2, step=1, key="detail_n_rows"))
    with _cb:
        detail_dpi = st.select_slider("DPI", options=[72, 100, 150, 200, 300],
                                       value=100, key="detail_dpi")
    with _cc:
        detail_cell_w = st.number_input("幅(inch)", min_value=2.0, max_value=20.0,
                                         value=5.0, step=0.5, key="detail_cell_w")
    with _cd:
        detail_cell_h = st.number_input("高(inch)", min_value=1.0, max_value=15.0,
                                         value=3.5, step=0.5, key="detail_cell_h")
    with _ce:
        g_thin = int(st.number_input("間引き", min_value=1, max_value=10,
                                      value=1, step=1, key="g_thin"))
    with _cf:
        g_chart = st.selectbox("タイプ", ["折れ線", "散布図", "棒グラフ"], key="g_chart")
    with _cg:
        g_opacity = st.number_input("透明度", min_value=0.1, max_value=1.0,
                                     value=0.7, step=0.1, key="g_opacity")
    with _ch:
        if g_chart == "折れ線":
            g_lw = st.number_input("線幅", min_value=0.1, max_value=10.0,
                                    value=1.0, step=0.1, key="g_lw")
            g_ld = st.selectbox("線種", ["solid", "dash", "dot", "dashdot"], key="g_ld")
            g_hollow = False; g_bw = 2.0
        elif g_chart == "散布図":
            g_hollow = st.checkbox("白抜き", key="g_hollow")
            g_bw = st.number_input("枠線幅", min_value=0.1, max_value=10.0,
                                    value=2.0, step=0.1, key="g_bw")
            g_lw = 1.0; g_ld = "solid"
        else:
            g_lw = 1.0; g_ld = "solid"; g_hollow = False; g_bw = 2.0

    _row_configs = []
    for _ri in range(detail_n_rows):
        with st.expander(f"行 {_ri + 1}", expanded=False):
            _rc1, _rc2, _rc3 = st.columns(3)
            with _rc1:
                _r_ys = st.multiselect(
                    "Y軸", options=_y_options, default=_y_options[:1],
                    key=f"row_y_{_ri}",
                )
            with _rc2:
                if has_prefixes:
                    _r_pfx = st.multiselect(
                        "プレフィックス", options=all_prefixes, default=all_prefixes,
                        key=f"row_pfx_{_ri}",
                    )
                else:
                    _r_pfx = []
                    st.empty()
            with _rc3:
                _r_x_sel = st.selectbox("X軸", options=_x_options, key=f"row_x_{_ri}")
                _r_x_col = "_idx" if _r_x_sel == "連番（行インデックス）" else _r_x_sel
                _r_x_label = "行インデックス" if _r_x_col == "_idx" else _r_x_col
        _row_configs.append({
            "y_labels": _r_ys, "prefixes": _r_pfx,
            "x_col": _r_x_col, "x_label": _r_x_label,
        })

    _active_rows = [(ri, rc) for ri, rc in enumerate(_row_configs) if rc["y_labels"]]

    if _active_rows:
        _d_nrows = len(_active_rows)
        _d_fw = detail_cell_w * detail_n_cols
        _d_fh = detail_cell_h * _d_nrows
        _d_fig, _d_axes = plt.subplots(_d_nrows, detail_n_cols,
                                        figsize=(_d_fw, _d_fh), dpi=detail_dpi,
                                        squeeze=False)

        def _fill_grid(axes, thin):
            _sampled = False
            for _ri2, (_orig_ri, _row_cfg) in enumerate(_active_rows):
                _dyls = _row_cfg["y_labels"]
                _dpfx = _row_cfg["prefixes"]
                _r_xc = _row_cfg["x_col"]
                _r_xl = _row_cfg["x_label"]
                for _ci, _dgrp in enumerate(sel_groups):
                    _dax = axes[_ri2][_ci]
                    if _ri2 == 0:
                        _dax.set_title(_dgrp, fontsize=8)
                    if _ci == 0:
                        _dax.set_ylabel(", ".join(_dyls), fontsize=8)
                    if _ri2 == _d_nrows - 1:
                        _dax.set_xlabel(_r_xl, fontsize=8)
                    _dax.tick_params(labelsize=7)
                    _df_d = df_g_base[df_g_base["source_file"] == _dgrp].copy()
                    _color_idx = 0
                    for _dyl in _dyls:
                        if has_prefixes:
                            for _dp in _dpfx:
                                _dyc = f"{_dp}_{_dyl}"
                                if _dyc not in _df_d.columns:
                                    continue
                                _dxd = _df_d["_idx"].values if _r_xc == "_idx" else _df_d[_r_xc].values
                                _dyd = _df_d[_dyc].values
                                if thin > 1:
                                    _dxd = _dxd[::thin]; _dyd = _dyd[::thin]; _sampled = True
                                _dc = _mpl_color(_color_idx); _color_idx += 1
                                _lbl = f"{_dyl}/{_dp}" if len(_dyls) > 1 else _dp
                                if g_chart == "折れ線":
                                    _dax.plot(_dxd, _dyd, label=_lbl, color=_dc, alpha=g_opacity,
                                              linewidth=g_lw, linestyle=_MPLLS.get(g_ld, "-"))
                                elif g_chart == "散布図":
                                    _dax.scatter(_dxd, _dyd, label=_lbl,
                                                 facecolors="none" if g_hollow else _dc,
                                                 edgecolors=_dc, linewidths=g_bw, alpha=g_opacity, s=6)
                                else:
                                    _dax.bar(_dxd, _dyd, label=_lbl, color=_dc, alpha=g_opacity)
                        else:
                            if _dyl not in _df_d.columns:
                                continue
                            _dxd = _df_d["_idx"].values if _r_xc == "_idx" else _df_d[_r_xc].values
                            _dyd = _df_d[_dyl].values
                            if thin > 1:
                                _dxd = _dxd[::thin]; _dyd = _dyd[::thin]; _sampled = True
                            _dc = _mpl_color(_color_idx); _color_idx += 1
                            if g_chart == "折れ線":
                                _dax.plot(_dxd, _dyd, label=_dyl, color=_dc, alpha=g_opacity,
                                          linewidth=g_lw, linestyle=_MPLLS.get(g_ld, "-"))
                            elif g_chart == "散布図":
                                _dax.scatter(_dxd, _dyd, label=_dyl,
                                             facecolors="none" if g_hollow else _dc,
                                             edgecolors=_dc, linewidths=g_bw, alpha=g_opacity, s=6)
                            else:
                                _dax.bar(_dxd, _dyd, label=_dyl, color=_dc, alpha=g_opacity)
                    if _color_idx <= 10:
                        _dax.legend(fontsize=6)
            return _sampled

        _d_sampled = _fill_grid(_d_axes, g_thin)
        if _d_sampled:
            st.caption("描画点数が多いため間引きました（ダウンロードは全点）")
        _d_fig.tight_layout()
        st.pyplot(_d_fig, use_container_width=True)
        plt.close(_d_fig)

        _dl_fig, _dl_axes = plt.subplots(_d_nrows, detail_n_cols,
                                         figsize=(_d_fw, _d_fh), dpi=detail_dpi,
                                         squeeze=False)
        _fill_grid(_dl_axes, 1)
        _dl_fig.tight_layout()
        _dl_buf = io.BytesIO()
        _dl_fig.savefig(_dl_buf, format="png", dpi=detail_dpi, bbox_inches="tight")
        _dl_buf.seek(0)
        st.download_button(
            "PNG ダウンロード",
            data=_dl_buf,
            file_name="detail_graph.png",
            mime="image/png",
            key="dl_detail_all",
        )
        plt.close(_dl_fig)

# ── タブ2: 変数間グラフ ───────────────────────────────────────────────────────
with _tab2:
    _va, _vb, _vc, _vd, _ve, _vf = st.columns(6)
    with _va:
        vg_dpi = st.select_slider("DPI", options=[72, 100, 150, 200, 300],
                                   value=100, key="vg_dpi")
    with _vb:
        vg_cell_w = st.number_input("幅(inch)", min_value=2.0, max_value=20.0,
                                     value=5.0, step=0.5, key="vg_cell_w")
    with _vc:
        vg_cell_h = st.number_input("高(inch)", min_value=1.0, max_value=15.0,
                                     value=3.5, step=0.5, key="vg_cell_h")
    with _vd:
        vg_chart = st.selectbox("タイプ", ["散布図", "折れ線"], key="vg_chart")
    with _ve:
        vg_opacity = st.number_input("透明度", min_value=0.1, max_value=1.0,
                                     value=0.7, step=0.1, key="vg_opacity")
    with _vf:
        if vg_chart == "折れ線":
            vg_lw = st.number_input("線幅", min_value=0.1, max_value=10.0,
                                     value=1.0, step=0.1, key="vg_lw")
            vg_ld = st.selectbox("線種", ["solid", "dash", "dot", "dashdot"], key="vg_ld")
            vg_hollow = False; vg_bw = 2.0
        else:
            vg_hollow = st.checkbox("白抜き", key="vg_hollow")
            vg_bw = st.number_input("枠線幅", min_value=0.1, max_value=10.0,
                                     value=2.0, step=0.1, key="vg_bw")
            vg_lw = 1.0; vg_ld = "solid"

    _vsel1, _vsel2 = st.columns(2)
    with _vsel1:
        if has_prefixes:
            _vg_x_opts = _non_prefixed_cols + _all_base_names
        else:
            _vg_x_opts = [c for c in col_options if c in numeric_cols]
        vg_x_sel = st.selectbox("X軸変数", options=_vg_x_opts if _vg_x_opts else col_options,
                                 key="vg_x")
    with _vsel2:
        vg_ys = st.multiselect("Y軸変数", options=_y_options,
                                default=_y_options[:1], key="vg_ys")

    if has_prefixes:
        vg_pfx = st.multiselect("プレフィックス", options=all_prefixes,
                                 default=all_prefixes, key="vg_pfx")
    else:
        vg_pfx = []

    if vg_ys:
        _vg_n_rows = len(vg_ys)
        _vg_fw = vg_cell_w * detail_n_cols
        _vg_fh = vg_cell_h * _vg_n_rows

        def _render_vg(axes):
            for _ri, _vy in enumerate(vg_ys):
                for _ci, _grp in enumerate(sel_groups):
                    _ax = axes[_ri][_ci]
                    if _ri == 0:
                        _ax.set_title(_grp, fontsize=8)
                    if _ci == 0:
                        _ax.set_ylabel(_vy, fontsize=8)
                    if _ri == _vg_n_rows - 1:
                        _ax.set_xlabel(vg_x_sel, fontsize=8)
                    _ax.tick_params(labelsize=7)
                    _df_v = df_g_base[df_g_base["source_file"] == _grp]
                    if vg_x_sel not in _df_v.columns:
                        continue
                    _xd = _df_v[vg_x_sel].values
                    _color_idx = 0
                    if has_prefixes:
                        for _vp in vg_pfx:
                            _vyc = f"{_vp}_{_vy}"
                            if _vyc not in _df_v.columns:
                                continue
                            _yd = _df_v[_vyc].values
                            _dc = _mpl_color(_color_idx); _color_idx += 1
                            if vg_chart == "折れ線":
                                _ax.plot(_xd, _yd, label=_vp, color=_dc, alpha=vg_opacity,
                                         linewidth=vg_lw, linestyle=_MPLLS.get(vg_ld, "-"))
                            else:
                                _ax.scatter(_xd, _yd, label=_vp,
                                            facecolors="none" if vg_hollow else _dc,
                                            edgecolors=_dc, linewidths=vg_bw, alpha=vg_opacity, s=6)
                    else:
                        if _vy in _df_v.columns:
                            _yd = _df_v[_vy].values
                            _dc = _mpl_color(0)
                            if vg_chart == "折れ線":
                                _ax.plot(_xd, _yd, color=_dc, alpha=vg_opacity,
                                         linewidth=vg_lw, linestyle=_MPLLS.get(vg_ld, "-"))
                            else:
                                _ax.scatter(_xd, _yd,
                                            facecolors="none" if vg_hollow else _dc,
                                            edgecolors=_dc, linewidths=vg_bw, alpha=vg_opacity, s=6)
                    if _color_idx > 0 and _color_idx <= 10:
                        _ax.legend(fontsize=6)

        _vg_fig, _vg_axes = plt.subplots(_vg_n_rows, detail_n_cols,
                                          figsize=(_vg_fw, _vg_fh), dpi=vg_dpi,
                                          squeeze=False)
        _render_vg(_vg_axes)
        _vg_fig.tight_layout()
        st.pyplot(_vg_fig, use_container_width=True)
        plt.close(_vg_fig)

        _vg_dl_fig, _vg_dl_axes = plt.subplots(_vg_n_rows, detail_n_cols,
                                                figsize=(_vg_fw, _vg_fh), dpi=vg_dpi,
                                                squeeze=False)
        _render_vg(_vg_dl_axes)
        _vg_dl_fig.tight_layout()
        _vg_buf = io.BytesIO()
        _vg_dl_fig.savefig(_vg_buf, format="png", dpi=vg_dpi, bbox_inches="tight")
        _vg_buf.seek(0)
        st.download_button(
            "PNG ダウンロード",
            data=_vg_buf,
            file_name="var_graph.png",
            mime="image/png",
            key="dl_vg",
        )
        plt.close(_vg_dl_fig)
