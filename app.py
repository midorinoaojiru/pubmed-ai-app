import streamlit as st
import google.generativeai as genai
from Bio import Entrez
import xml.etree.ElementTree as ET
import time

# --- 1. 設定エリア ---
# StreamlitのSecrets機能（後述）から読み込む
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
NCBI_API_KEY = st.secrets.get("NCBI_API_KEY", "") # 無くても動くようにgetを使用
ENTREZ_EMAIL = st.secrets["ENTREZ_EMAIL"] 
Entrez.email = ENTREZ_EMAIL
Entrez.api_key = NCBI_API_KEY

genai.configure(api_key=GEMINI_API_KEY)
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]
model = genai.GenerativeModel('gemini-3.1-flash-lite', safety_settings=safety_settings)

# --- 2. 論文検索関数（タイトル取得を強化） ---
def search_pmc(query, max_results=10):
    try:
        # IDを検索
        handle = Entrez.esearch(db="pmc", term=query, retmax=max_results, sort="relevance")
        record = Entrez.read(handle)
        ids = record.get("IdList", [])
        
        if not ids:
            return []

        # タイトル等の概要を取得
        handle = Entrez.esummary(db="pmc", id=",".join(ids))
        summaries = Entrez.read(handle)
        
        results = []
        for doc in summaries:
            # docは辞書形式。キーの大文字小文字や存在を確認しながら取得
            pmcid = doc.get("Id", "不明")
            # PMCではタイトルは "Title" というキーに入っていることが一般的
            title = doc.get("Title", f"PMC ID: {pmcid} (タイトル取得不可)")
            
            results.append({
                "id": str(pmcid),
                "title": str(title)
            })
        return results
    except Exception as e:
        st.error(f"検索中にエラーが発生しました: {e}")
        return []

# --- 3. セクション抽出関数 ---
def fetch_sections(pmc_id):
    try:
        handle = Entrez.efetch(db="pmc", id=pmc_id, rettype="xml", retmode="text")
        root = ET.fromstring(handle.read())
        sections = {"Abstract": "", "Discussion": "", "Conclusion": ""}
        
        abstract_node = root.find(".//abstract")
        if abstract_node is not None:
            sections["Abstract"] = "".join(abstract_node.itertext())

        for sec in root.findall(".//body/sec"):
            title_node = sec.find("title")
            if title_node is not None and title_node.text:
                t = title_node.text.lower()
                content = "".join(sec.itertext())
                if any(k in t for k in ["discussion", "考察"]):
                    sections["Discussion"] += content
                elif any(k in t for k in ["conclusion", "結論", "summary", "concluding"]):
                    sections["Conclusion"] += content
        return sections
    except Exception:
        return None

# --- 4. Streamlit UI ---
st.set_page_config(page_title="論文解析ツール", layout="wide")
st.title("🧬 PMC 論文解析アシスタント")

# セッション状態の初期化
if "results" not in st.session_state:
    st.session_state.results = []
if "analysis_storage" not in st.session_state:
    st.session_state.analysis_storage = {} # 解析結果を貯める辞書

# サイドバーに設定
with st.sidebar:
    st.header("設定")
    if st.button("キャッシュをクリアして再起動"):
        st.session_state.results = []
        st.rerun()

query = st.text_input("検索キーワード（英語推奨）", "")

if st.button("論文を検索"):
    with st.spinner("タイトルを取得中..."):
        # 検索結果（タイトル付き）を保存
        st.session_state.results = search_pmc(query, max_results=10)
        st.session_state.analysis_storage = {} # 新しい検索のときは前回の解析結果をクリア
        if not st.session_state.results:
            st.warning("論文が見つかりませんでした。")
        else:
            st.success(f"{len(st.session_state.results)}件の論文が見つかりました。")

# 結果の表示
for paper in st.session_state.results:
    # データの型をチェックして安全に取得
    if isinstance(paper, dict):
        pmc_id = paper.get("id", "不明")
        title = paper.get("title", "タイトルなし")
    else:
        # 万が一古いデータ（文字列）が残っていた場合
        pmc_id = str(paper)
        title = f"PMC ID: {pmc_id} (再度検索してください)"

    with st.container():
        st.divider()
        col1, col2 = st.columns([4, 1])
        col1.markdown(f"📄 **{title}**")
        col1.caption(f"PMC ID: {pmc_id}")
        
# --- 解析ボタン ---
        if col2.button(f"解析する", key=f"btn_{pmc_id}"):
            with st.spinner("AI解析中..."):
                data = fetch_sections(pmc_id)
                if data:
                    # テキストの準備
                    target_text = ""
                    if data.get("Discussion") or data.get("Conclusion"):
                        target_text = f"Discussion: {data['Discussion']}\nConclusion: {data['Conclusion']}"
                    elif data.get("Abstract"):
                        target_text = f"Abstract: {data['Abstract']}"

                    if target_text.strip():
                        # --- try-exceptブロックの開始 ---
                        try:
                            prompt = f"以下の論文内容を要約してください。\n\n{target_text[:4000]}"
                            response = model.generate_content(prompt)
                            # 解析結果をセッションに保存
                            st.session_state.analysis_storage[pmc_id] = response.text
                        except Exception as e:
                            st.error(f"解析エラーが発生しました: {e}")
                        # --- try-exceptブロックの終了 ---
                    else:
                        st.warning("要約できるテキストが見つかりませんでした。")
                else:
                    st.error("論文データを取得できませんでした。")

        # --- 解析済み結果の表示（ボタンの外側！） ---
        if pmc_id in st.session_state.analysis_storage:
            st.info(f"**【解析結果】**\n\n{st.session_state.analysis_storage[pmc_id]}")
