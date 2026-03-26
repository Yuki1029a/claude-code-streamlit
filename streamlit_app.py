"""Claude Code Remote – Streamlit Cloud Frontend

Streamlit Cloud → ngrok → Flask バックエンドへのプロキシUI。
ブラウザからは *.streamlit.app のみアクセスするため、
ngrokドメインがブロックされるネットワークでも利用可能。
"""

import base64
import json
import queue
import re
import threading
import time
from datetime import datetime, timezone, timedelta

# 日本時間 (UTC+9)
JST = timezone(timedelta(hours=9))

import streamlit as st

from backend_client import BackendClient

# ─── ページ設定 ───────────────────────────────────────────
st.set_page_config(
    page_title="CLAUDE TERMINAL v2.0",
    page_icon=">",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── カスタムCSS (Terminal Style) ──────────────────────────────────────────
st.markdown("""
<style>

/* ══════════════════════════════════════════════
   TERMINAL MONOCHROME THEME
   Black background + White text — easy on the eyes
══════════════════════════════════════════════ */

/* メインアプリ背景 */
.stApp {
    background-color: #0a0a0a !important;
    font-family: 'Courier New', 'Consolas', 'Monaco', monospace !important;
    color: #e0e0e0 !important;
}

.main {
    background-color: #0a0a0a !important;
}

/* ヘッダーバー（上部） — 黒に統一、高さ縮小 */
header[data-testid="stHeader"],
.stAppHeader,
header {
    background-color: #0a0a0a !important;
    background: #0a0a0a !important;
    border-bottom: none !important;
    box-shadow: none !important;
}

/* block-container上部の余白を詰める */
.block-container {
    padding-top: 1rem !important;
}

/* デプロイバー */
.stDeployButton,
[data-testid="stStatusWidget"] {
    background-color: transparent !important;
}

/* サイドバー */
section[data-testid="stSidebar"] {
    background-color: #0f0f0f !important;
    border-right: 1px solid #333 !important;
}

section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] h4 {
    color: #d0d0d0 !important;
    font-family: 'Courier New', 'Consolas', 'Monaco', monospace !important;
}

/* タイトル・見出し */
h1, h2, h3, h4, h5, h6 {
    color: #ffffff !important;
    font-family: 'Courier New', 'Consolas', 'Monaco', monospace !important;
}

/* テキスト全般 (span除外: アイコンフォント保護) */
p, label {
    font-family: 'Courier New', 'Consolas', 'Monaco', monospace !important;
}

/* チャットメッセージ */
.stChatMessage {
    background-color: #0a0a0a !important;
    border: none !important;
    border-bottom: 1px solid #1a1a1a !important;
    border-radius: 0 !important;
    padding: 12px 8px !important;
    margin-bottom: 0 !important;
}

.stChatMessage p {
    color: #e0e0e0 !important;
    font-family: 'Courier New', 'Consolas', 'Monaco', monospace !important;
}

/* アバター — 記号をシンプルに表示 */
.stChatMessage [data-testid="stChatMessageAvatarUser"],
.stChatMessage [data-testid="stChatMessageAvatarAssistant"] {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: #666 !important;
    font-family: 'Courier New', monospace !important;
    font-size: 16px !important;
    min-width: 20px !important;
    width: 20px !important;
    height: 20px !important;
}

/* コードブロック */
.stChatMessage pre {
    background: #0a0a0a !important;
    border: 1px solid #333 !important;
    border-radius: 2px !important;
    padding: 12px !important;
    color: #e0e0e0 !important;
    overflow-x: auto;
    overflow-y: auto;
}

.stChatMessage code {
    font-family: 'Courier New', 'Consolas', 'Monaco', monospace !important;
    color: #e0e0e0 !important;
    background: #0a0a0a !important;
}

/* チャット入力欄 — 全て黒、入力枠のみ白 */
.stChatInputContainer,
.stChatInput,
div[data-testid="stChatInput"],
div[data-testid="stBottom"],
div[data-testid="stBottom"] > div,
div[data-testid="stBottom"] > div > div,
div[data-testid="stBottom"] *,
.stBottom,
.stBottom > div {
    background-color: #0a0a0a !important;
    background: #0a0a0a !important;
    border-color: transparent !important;
    box-shadow: none !important;
}

/* 入力エリア上部に白セパレータ線 */
.stChatInputContainer,
div[data-testid="stChatInput"] > div:first-child {
    border-top: 1px solid #555 !important;
    padding-top: 12px !important;
}

/* 入力テキストエリア — ボーダーなし、黒背景 */
.stChatInputContainer textarea,
div[data-testid="stChatInput"] textarea {
    background-color: #0a0a0a !important;
    color: #e0e0e0 !important;
    font-family: 'Courier New', 'Consolas', 'Monaco', monospace !important;
    border: none !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    outline: none !important;
}

/* フォーカス時もボーダーなし */
.stChatInputContainer textarea:focus,
div[data-testid="stChatInput"] textarea:focus {
    border: none !important;
    box-shadow: none !important;
    outline: none !important;
}

/* 送信ボタン */
.stChatInputContainer button,
div[data-testid="stChatInput"] button {
    background-color: #0a0a0a !important;
    background: #0a0a0a !important;
    color: #e0e0e0 !important;
    border: none !important;
    box-shadow: none !important;
}

/* ボタン（全般） */
.stButton > button {
    background-color: #1a1a1a !important;
    color: #e0e0e0 !important;
    border: 1px solid #555 !important;
    border-radius: 3px !important;
    font-family: 'Courier New', 'Consolas', 'Monaco', monospace !important;
    padding: 8px 16px !important;
}

.stButton > button:hover {
    background-color: #333 !important;
    color: #ffffff !important;
    border: 1px solid #888 !important;
}

/* サイドバー内ボタン — 明示的に上書き */
section[data-testid="stSidebar"] .stButton > button {
    background-color: #1a1a1a !important;
    color: #e0e0e0 !important;
    border: 1px solid #555 !important;
    border-radius: 3px !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    min-height: 38px !important;
    cursor: pointer !important;
}

section[data-testid="stSidebar"] .stButton > button:hover {
    background-color: #333 !important;
    color: #fff !important;
    border-color: #888 !important;
}

/* 入力フィールド */
input[type="text"],
input[type="password"],
textarea {
    background-color: #111111 !important;
    color: #e0e0e0 !important;
    border: 1px solid #444 !important;
    font-family: 'Courier New', 'Consolas', 'Monaco', monospace !important;
}

/* 入力コンテナ全体（目アイコン含む） — 背景統一 */
div[data-baseweb="input"],
div[data-baseweb="base-input"] {
    background-color: #111111 !important;
    background: #111111 !important;
    border: 1px solid #444 !important;
    border-radius: 2px !important;
}

div[data-baseweb="input"] > div,
div[data-baseweb="base-input"] > div,
.stTextInput > div,
.stTextInput > div > div {
    background-color: #111111 !important;
    background: #111111 !important;
    border: none !important;
}

div[data-baseweb="input"] button,
div[data-baseweb="base-input"] button {
    background-color: #111111 !important;
    background: #111111 !important;
    color: #e0e0e0 !important;
    border: none !important;
}

/* 内側inputのボーダーを消す（外枠に任せる） */
div[data-baseweb="input"] input,
div[data-baseweb="base-input"] input {
    border: none !important;
    background: transparent !important;
}

/* セレクトボックス */
div[data-baseweb="select"] {
    background-color: #111111 !important;
    border: 1px solid #444 !important;
}

div[data-baseweb="select"] * {
    background-color: #111111 !important;
    color: #e0e0e0 !important;
    font-family: 'Courier New', 'Consolas', 'Monaco', monospace !important;
}

/* エキスパンダー */
.streamlit-expanderHeader {
    background-color: #111111 !important;
    color: #e0e0e0 !important;
    border: 1px solid #333 !important;
    font-family: 'Courier New', 'Consolas', 'Monaco', monospace !important;
}

/* コスト表示 */
.cost-info {
    font-size: 11px;
    color: #888 !important;
    text-align: center;
    margin: 4px 0;
}

/* エラーメッセージ */
.error-msg {
    color: #ff6b6b !important;
    background: rgba(255,0,0,0.08) !important;
    border: 1px solid #ff6b6b !important;
    border-radius: 2px !important;
    padding: 8px;
    margin: 4px 0;
}

/* ステータスバッジ */
.status-running  { color: #ffcc00 !important; }
.status-completed{ color: #88ff88 !important; }
.status-error    { color: #ff6b6b !important; }
.status-cancelled{ color: #666 !important; }

/* ツールカード左ボーダー */
.tool-expander {
    border-left: 3px solid #555 !important;
    padding-left: 8px;
    margin: 4px 0;
}

/* テキストエリア */
.stTextArea textarea {
    background-color: #111111 !important;
    color: #e0e0e0 !important;
    border: 1px solid #444 !important;
    font-family: 'Courier New', 'Consolas', 'Monaco', monospace !important;
}

/* 画像 */
.stImage img {
    border: 1px solid #333 !important;
}

/* divider */
hr {
    border-color: #333 !important;
    opacity: 0.5 !important;
}

/* キャプション */
.stCaption {
    color: #888 !important;
}

/* ══════════════════════════════════════════════
   MOBILE  (≤768px)
══════════════════════════════════════════════ */
@media (max-width: 768px) {
    .block-container {
        padding: 0.5rem 0.4rem 7rem !important;
        max-width: 100% !important;
    }

    .stButton > button {
        min-height: 48px !important;
        font-size: 15px !important;
        padding: 6px 14px !important;
    }

    input[type="text"],
    input[type="password"],
    textarea { font-size: 16px !important; }

    .stChatInputContainer textarea {
        font-size: 16px !important;
        min-height: 48px !important;
    }

    .stChatMessage {
        padding: 6px 8px !important;
        margin-bottom: 0 !important;
    }

    .stChatMessage pre {
        font-size: 12px !important;
        max-height: 180px !important;
    }

    .stImage img {
        max-height: 55vh !important;
        object-fit: contain !important;
    }
}

/* ══════════════════════════════════════════════
   DESKTOP  (>768px)
══════════════════════════════════════════════ */
@media (min-width: 769px) {
    .stChatMessage pre  { max-height: 450px; }
    .stChatMessage code { font-size: 13px; }
}

</style>
""", unsafe_allow_html=True)


# ─── セッションステート初期化 ─────────────────────────────
def init_state():
    """初回のみ実行"""
    defaults = {
        "client": None,
        "connected": False,
        "messages": [],          # [{role, content, tool_blocks, cost_info}]
        "directories": {},       # {group: [dirs]}
        "flat_dirs": [],         # [dir_path, ...]
        "selected_dir": None,
        "session_id": None,
        "sessions": [],          # [session_id, ...]
        "current_job_id": None,
        "is_streaming": False,
        "cancel_requested": False,
        "job_history": [],
        "selected_model": "claude-sonnet-4-6",  # デフォルトモデル
        "screenshot_bytes": None,               # 最新スクリーンショット
        "pc_sessions": [],                      # PCのClaude履歴セッション一覧
        "pc_sessions_loaded": False,            # 一覧取得済みフラグ
        "session_dirs": {},                     # {session_id: cwd} セッション→ディレクトリ対応
        "recovery_checked": False,              # ジョブ復帰チェック済みフラグ
        "active_job_cwd": None,                 # ジョブ再開時の作業ディレクトリ（Noneなら新規）
        "notify_completion": None,               # 完了通知用（テキストプレビュー or None）
        "history_offset": 0,                        # 履歴ページネーション: 読み込み済みオフセット
        "history_has_more": False,                   # まだ古い履歴があるか
        "history_total_lines": 0,                    # セッション総行数
        "pending_images": [],                        # 送信待ち画像 [{data, media_type, name}]
        "new_session_requested": False,              # 新規セッション要求フラグ（process_eventsの復元防止）
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# ─── is_streaming スタック検出 ─────────────────────────────
# ストリーミング中にワーカースレッドが存在しない場合のみチェック
# （非ブロッキングリランでは毎回API呼び出ししないよう、ワーカーの有無で判断）
if st.session_state.is_streaming and not hasattr(st.session_state, "_stream_queue"):
    _stale_job_id = st.session_state.current_job_id
    _job_still_running = False
    if _stale_job_id and st.session_state.client:
        try:
            _jdata = st.session_state.client.poll_job_events(_stale_job_id, offset=0)
            _job_still_running = (_jdata.get("status") == "running")
        except Exception:
            pass
    if not _job_still_running:
        st.session_state.is_streaming = False
        st.session_state.cancel_requested = False

# ─── モバイル自動検出 ──────────────────────────────────────
# 初回アクセス時のみJSで画面幅を検出し ?dv=m|d をURLに付与してリロード
# 2回目以降はURLパラメータから読み取るだけでリロードなし
st.markdown("""
<script>
(function(){
  try {
    if(location.search.indexOf('dv=')<0){
      var sep = location.search ? '&' : '?';
      location.replace(
        location.pathname + location.search + sep +
        'dv=' + (window.innerWidth <= 768 ? 'm' : 'd')
      );
    }
  } catch(e){}
})();
</script>
""", unsafe_allow_html=True)

IS_MOBILE = st.query_params.get("dv", "d") == "m"


# ─── ヘルパー関数 ──────────────────────────────────────────

IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico"}


def extract_file_path(tool_input_str: str) -> str | None:
    """ツール入力JSONからファイルパスを抽出"""
    try:
        obj = json.loads(tool_input_str)
        for key in ("file_path", "path", "command"):
            if key in obj:
                val = obj[key]
                if isinstance(val, str) and ("\\" in val or "/" in val):
                    return val
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def is_image_path(path: str) -> bool:
    """画像ファイルかどうか判定"""
    if not path:
        return False
    lower = path.lower()
    return any(lower.endswith(ext) for ext in IMG_EXTS)


def format_timestamp(ts: float) -> str:
    """UnixタイムスタンプをJST HH:MM形式に変換"""
    return datetime.fromtimestamp(ts, tz=JST).strftime("%H:%M")


def add_session(sid: str):
    """セッションIDをリストに追加（重複なし）"""
    if sid and sid not in st.session_state.sessions:
        st.session_state.sessions.append(sid)


def parse_tool_input_display(raw: str) -> str:
    """ツール入力を読みやすく整形"""
    try:
        obj = json.loads(raw)
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return raw


def get_path_basename(path: str) -> str:
    """パスからファイル名のみ取得"""
    return path.replace("\\", "/").rstrip("/").split("/")[-1]


# ─── ネイティブJSONLパーサー（~/.claude/projects/ 用）──────────
# stream-jsonとは別形式: user.content=str, assistant.content=[{type,text}]

def process_native_events(events: list) -> list:
    """~/.claude/projects/ のネイティブJSONL形式 → メッセージリストに変換

    ネイティブ形式の特徴:
      - type="user":      message.content = "ユーザーの入力テキスト"（文字列）
                          または [{"type":"tool_result", ...}]（配列）
      - type="assistant": message.content = [{"type":"text","text":"..."},
                                             {"type":"tool_use","name":"...","input":{}}]
      - type="queue-operation": 無視
    """
    messages = []
    pending_tool_results = {}  # tool_use_id → result str

    for ev in events:
        etype = ev.get("type", "")
        sid = ev.get("sessionId")
        if sid:
            add_session(sid)

        if etype == "user":
            msg = ev.get("message", {})
            content = msg.get("content", "")

            if isinstance(content, str) and content.strip():
                # 通常のユーザーテキスト入力
                messages.append({
                    "role": "user",
                    "content": content,
                    "tool_blocks": [],
                    "cost_info": None,
                })
            elif isinstance(content, list):
                # tool_result配列 → 直前のassistantのtool_blocksに結果を紐付け
                for block in content:
                    if block.get("type") == "tool_result":
                        tool_id = block.get("tool_use_id", "")
                        result_content = block.get("content", "")
                        if isinstance(result_content, list):
                            result_content = "\n".join(
                                item.get("text", "") for item in result_content
                                if isinstance(item, dict)
                            )
                        pending_tool_results[tool_id] = result_content

        elif etype == "assistant":
            msg = ev.get("message", {})
            content = msg.get("content", [])
            text = ""
            tool_blocks = []

            if isinstance(content, list):
                for block in content:
                    btype = block.get("type", "")
                    if btype == "text":
                        text += block.get("text", "")
                    elif btype == "tool_use":
                        tool_id = block.get("id", "")
                        tool_blocks.append({
                            "name": block.get("name", "tool"),
                            "id": tool_id,
                            "input_str": json.dumps(
                                block.get("input", {}),
                                ensure_ascii=False
                            ),
                            "result": pending_tool_results.pop(tool_id, ""),
                        })

            if text or tool_blocks:
                messages.append({
                    "role": "assistant",
                    "content": text,
                    "tool_blocks": tool_blocks,
                    "cost_info": None,
                })

    # 未消化のtool_resultsは末尾のassistantブロックに付加（稀なケース）
    if pending_tool_results and messages:
        last = messages[-1]
        if last["role"] == "assistant":
            for tid, result in pending_tool_results.items():
                last["tool_blocks"].append({
                    "name": "tool",
                    "id": tid,
                    "input_str": "",
                    "result": result,
                })

    return messages


# ─── ストリーミング処理 ────────────────────────────────────

def _poll_fallback(client: BackendClient, job_id: str,
                   event_queue: queue.Queue, stop_event: threading.Event,
                   offset: int):
    """SSE切断後のフォールバック: ポーリングで残りのイベントを取得"""
    while not stop_event.is_set():
        try:
            result = client.poll_job_events(job_id, offset=offset)
            events = result.get("events", [])
            for ev in events:
                event_queue.put(ev)
                offset += 1
            status = result.get("status", "")
            if status in ("completed", "error", "cancelled"):
                event_queue.put(None)
                return
            time.sleep(1.5)
        except Exception:
            time.sleep(3)
    event_queue.put(None)


def stream_worker(client: BackendClient, job_id: str,
                  event_queue: queue.Queue, stop_event: threading.Event):
    """バックグラウンドスレッド: SSEイベントを受信してキューに入れる。
    SSE切断時は自動的にポーリングにフォールバックする。"""
    received = 0
    sse_done = False
    try:
        for event in client.stream_job(job_id):
            if stop_event.is_set():
                return
            event_queue.put(event)
            received += 1
            # doneイベントを受信したら正常完了
            if event.get("type") == "done":
                sse_done = True
        if sse_done:
            event_queue.put(None)
        else:
            # SSEストリームが途中で切れた → ポーリングで残りを取得
            _poll_fallback(client, job_id, event_queue, stop_event, offset=received)
    except Exception:
        # SSE接続エラー → ポーリングにフォールバック
        _poll_fallback(client, job_id, event_queue, stop_event, offset=received)


def process_events(events: list) -> list:
    """生イベントリストをメッセージ構造に変換する。

    Returns:
        [{"role": "assistant"/"user"/"system",
          "content": str,
          "tool_blocks": [...],
          "cost_info": str | None}]
    """
    messages = []
    current_text = ""
    current_tools = []
    pending_tool = None  # {name, id, input_str}
    has_deltas = False  # stream_eventテキストデルタを受信したか

    for ev in events:
        etype = ev.get("type", "")

        # ── system init ──
        if etype == "system" and ev.get("subtype") == "init":
            sid = ev.get("session_id")
            if sid:
                add_session(sid)
                st.session_state.session_id = sid
                init_cwd = ev.get("cwd")
                if init_cwd:
                    st.session_state.session_dirs[sid] = init_cwd

        # ── assistant (完成メッセージ) ──
        # デルタで既にテキストを受信している場合はスキップ（重複防止）
        elif etype == "assistant":
            if not has_deltas:
                # ポーリングフォールバック時のみテキストを取得
                msg = ev.get("message", {})
                for block in msg.get("content", []):
                    if block.get("type") == "text":
                        current_text += block.get("text", "")

        # ── user = tool_result ──
        elif etype == "user":
            msg = ev.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") == "tool_result":
                    content = block.get("content", "")
                    if isinstance(content, list):
                        content = "\n".join(
                            item.get("text", "") for item in content
                            if isinstance(item, dict)
                        )
                    # pending_toolがあれば結果を追加
                    if pending_tool:
                        pending_tool["result"] = content
                        current_tools.append(pending_tool)
                        pending_tool = None
                    else:
                        current_tools.append({
                            "name": "tool",
                            "id": "",
                            "input_str": "",
                            "result": content,
                        })

        # ── stream_event (リアルタイム) ──
        elif etype == "stream_event":
            inner = ev.get("event", {})
            inner_type = inner.get("type", "")

            if inner_type == "content_block_start":
                cb = inner.get("content_block", {})
                if cb.get("type") == "tool_use":
                    # 前のツールがあればフラッシュ
                    if pending_tool:
                        current_tools.append(pending_tool)
                    pending_tool = {
                        "name": cb.get("name", "tool"),
                        "id": cb.get("id", ""),
                        "input_str": "",
                        "result": "",
                    }
                elif cb.get("type") == "text":
                    pass  # テキストブロック開始

            elif inner_type == "content_block_delta":
                delta = inner.get("delta", {})
                if delta.get("type") == "text_delta":
                    current_text += delta.get("text", "")
                    has_deltas = True
                elif delta.get("type") == "input_json_delta":
                    if pending_tool:
                        pending_tool["input_str"] += delta.get("partial_json", "")

        # ── result (コスト情報) ──
        elif etype == "result":
            sid = ev.get("session_id")
            if sid:
                add_session(sid)
                st.session_state.session_id = sid

            cost = ev.get("cost_usd")
            usage = ev.get("usage", {})
            cost_parts = []
            if cost is not None:
                cost_parts.append(f"${cost:.4f}")
            if usage.get("input_tokens"):
                cost_parts.append(f"in:{usage['input_tokens']}")
            if usage.get("output_tokens"):
                cost_parts.append(f"out:{usage['output_tokens']}")

            # 残りのツールをフラッシュ
            if pending_tool:
                current_tools.append(pending_tool)
                pending_tool = None

            # メッセージとして格納
            if current_text or current_tools:
                messages.append({
                    "role": "assistant",
                    "content": current_text,
                    "tool_blocks": current_tools[:],
                    "cost_info": (" | ".join(cost_parts) + (f" | sid:{sid[:8]}" if sid else "")) if cost_parts else (f"sid:{sid[:8]}" if sid else None),
                })
                current_text = ""
                current_tools = []
                has_deltas = False

        # ── error / stderr ──
        elif etype in ("error", "stderr"):
            text = ev.get("text", "")
            if text:
                messages.append({
                    "role": "system",
                    "content": f"[!] {text}",
                    "tool_blocks": [],
                    "cost_info": None,
                })

        # ── done ──
        elif etype == "done":
            # 残りのバッファをフラッシュ
            if pending_tool:
                current_tools.append(pending_tool)
                pending_tool = None
            if current_text or current_tools:
                messages.append({
                    "role": "assistant",
                    "content": current_text,
                    "tool_blocks": current_tools[:],
                    "cost_info": None,
                })

    # 最後のバッファ（doneが来なかった場合）
    if pending_tool:
        current_tools.append(pending_tool)
    if current_text or current_tools:
        messages.append({
            "role": "assistant",
            "content": current_text,
            "tool_blocks": current_tools[:],
            "cost_info": None,
        })

    return messages


# ─── サイドバー ────────────────────────────────────────────

with st.sidebar:

    # ── ヘッダー ──
    if IS_MOBILE:
        # モバイル: コンパクトヘッダー
        st.markdown("### CLAUDE TERMINAL v2.0")
    else:
        st.title("CLAUDE TERMINAL v2.0")
        st.caption("█ SYSTEM READY █")
        st.divider()

    # ── 接続設定 ──
    st.subheader("接続設定" if IS_MOBILE else "接続設定")

    ngrok_url = st.text_input(
        "ngrok URL",
        placeholder="https://xxxx.ngrok-free.app",
        help="Flask バックエンドの ngrok URL",
        label_visibility="collapsed" if IS_MOBILE else "visible",
    )
    if IS_MOBILE:
        st.caption("ngrok URL")

    # AUTH_TOKEN: secretsから取得、なければ手動入力
    default_token = ""
    try:
        default_token = st.secrets.get("AUTH_TOKEN", "")
    except Exception:
        pass

    auth_token = st.text_input(
        "Auth Token",
        value=default_token,
        type="password",
        help="Flask バックエンドの認証トークン",
        label_visibility="collapsed" if IS_MOBILE else "visible",
    )
    if IS_MOBILE:
        st.caption("Auth Token")

    col1, col2 = st.columns(2)
    with col1:
        connect_label = ("接続" if IS_MOBILE else "接続") if not st.session_state.connected else ("再接続" if IS_MOBILE else "再接続")
        connect_btn = st.button(connect_label, use_container_width=True)
    with col2:
        disconnect_label = "切断" if IS_MOBILE else "切断"
        disconnect_btn = st.button(
            disconnect_label,
            disabled=not st.session_state.connected,
            use_container_width=True,
        )

    # 接続処理
    if connect_btn:
        if not ngrok_url:
            st.error("ngrok URLを入力してください")
        elif not auth_token:
            st.error("Auth Tokenを入力してください")
        else:
            if not re.match(r"https?://.*\.(ngrok-free\.app|ngrok\.io|ngrok\.app)", ngrok_url):
                st.warning("ngrokドメイン以外のURLです")

            with st.spinner("接続中..."):
                client = BackendClient(ngrok_url)
                ok, msg = client.login(auth_token)
                if ok:
                    st.session_state.client = client
                    st.session_state.connected = True
                    try:
                        dirs = client.get_directories()
                        st.session_state.directories = dirs
                        flat = []
                        for group_dirs in dirs.values():
                            flat.extend(group_dirs)
                        st.session_state.flat_dirs = flat
                        if flat and not st.session_state.selected_dir:
                            st.session_state.selected_dir = flat[0]
                    except Exception:
                        pass
                    try:
                        jobs = client.list_jobs()
                        st.session_state.job_history = jobs
                        for job in jobs:
                            sid = job.get("session_id_out")
                            if sid:
                                add_session(sid)
                        # ジョブ復帰チェックをリセット
                        st.session_state.recovery_checked = False
                    except Exception:
                        pass
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    # 切断処理
    if disconnect_btn:
        st.session_state.client = None
        st.session_state.connected = False
        st.session_state.messages = []
        st.session_state.directories = {}
        st.session_state.flat_dirs = []
        st.session_state.session_id = None
        st.session_state.sessions = []
        st.session_state.job_history = []
        st.rerun()

    # 接続状態バッジ
    if st.session_state.connected:
        st.success("接続中")
    else:
        st.info("未接続")

    st.divider()

    # ════════════════════════════════════════════
    # 接続後のUI（モバイル / デスクトップで分岐）
    # ════════════════════════════════════════════

    if st.session_state.connected:

        MODEL_OPTIONS = {
            "claude-opus-4-6":   "Opus 4.6",
            "claude-sonnet-4-6": "Sonnet 4.6",
            "claude-sonnet-4-5": "Sonnet 4.5",
            "claude-opus-4-5":   "Opus 4.5",
            "claude-haiku-4-5":  "Haiku 4.5",
            "claude-opus-4":     "Opus 4",
            "claude-sonnet-4":   "Sonnet 4",
        }

        if IS_MOBILE:
            # ─────────────────────────────────────
            # モバイルサイドバー
            # 情報密度を下げ、タップしやすさを優先
            # ─────────────────────────────────────

            # モデル + ディレクトリ を横並びキャプション付きで表示
            st.markdown("**モデル**")
            selected_model = st.selectbox(
                "Model",
                options=list(MODEL_OPTIONS.keys()),
                format_func=lambda x: MODEL_OPTIONS.get(x, x),
                index=list(MODEL_OPTIONS.keys()).index(
                    st.session_state.selected_model
                ) if st.session_state.selected_model in MODEL_OPTIONS else 0,
                label_visibility="collapsed",
            )
            st.session_state.selected_model = selected_model

            # ── 新規セッション / セッション状態 ──
            _has_active_session = bool(st.session_state.active_job_cwd or st.session_state.session_id)
            if _has_active_session:
                _active_cwd = st.session_state.active_job_cwd or st.session_state.selected_dir
                _active_label = get_path_basename(_active_cwd) if _active_cwd else "不明"
                _sid_short = st.session_state.session_id[:8] if st.session_state.session_id else "---"
                st.caption(f"セッション中: {_active_label} | `{_sid_short}`")
                if st.button("新規セッション", use_container_width=True, key="mob_new_session"):
                    # ストリーミング中ならワーカースレッドを停止
                    if st.session_state.is_streaming:
                        _old_stop = st.session_state.get("_stream_stop")
                        if _old_stop:
                            _old_stop.set()
                        for _k in ("_stream_queue", "_stream_stop", "_stream_text",
                                    "_stream_tools", "_stream_pending_tool",
                                    "_stream_all_events", "_stream_errors",
                                    "_stream_cost_info", "_stream_done"):
                            st.session_state.pop(_k, None)
                        st.session_state.is_streaming = False
                        st.session_state.cancel_requested = False
                    st.session_state.active_job_cwd = None
                    st.session_state.session_id = None
                    st.session_state.messages = []
                    st.session_state.current_job_id = None
                    st.session_state.screenshot_bytes = None
                    st.session_state.history_offset = 0
                    st.session_state.history_has_more = False
                    st.session_state.new_session_requested = True
                    st.rerun()
            else:
                # 新規セッション: フォルダ選択可能
                if st.session_state.flat_dirs:
                    st.markdown("**作業フォルダ**")
                    dir_options = st.session_state.flat_dirs
                    dir_labels = {}
                    for group_name, group_dirs in st.session_state.directories.items():
                        group_base = get_path_basename(group_name)
                        for d in group_dirs:
                            dir_labels[d] = f"{group_base}/{get_path_basename(d)}"
                    selected = st.selectbox(
                        "CWD",
                        options=dir_options,
                        format_func=lambda x: dir_labels.get(x, get_path_basename(x)),
                        index=dir_options.index(st.session_state.selected_dir)
                        if st.session_state.selected_dir in dir_options else 0,
                        label_visibility="collapsed",
                    )
                    st.session_state.selected_dir = selected

            st.divider()

            # 大きなアクションボタン（4列）
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                if st.button("撮影", use_container_width=True,
                             help="PCの画面キャプチャ",
                             disabled=st.session_state.is_streaming):
                    with st.spinner("…"):
                        img = st.session_state.client.get_screenshot()
                        if img:
                            st.session_state.screenshot_bytes = img
                            st.rerun()
            with c2:
                if st.button("更新", use_container_width=True, help="ジョブ履歴更新"):
                    try:
                        jobs = st.session_state.client.list_jobs()
                        st.session_state.job_history = jobs
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
            with c3:
                if st.button("履歴", use_container_width=True, help="PC履歴取得",
                             key="mob_pc_sessions"):
                    try:
                        with st.spinner("…"):
                            sessions = st.session_state.client.list_sessions()
                        st.session_state.pc_sessions = sessions
                        st.session_state.pc_sessions_loaded = True
                        st.rerun()
                    except Exception as e:
                        st.error(f"エラー: {e}")
            with c4:
                if st.button("CLR", use_container_width=True, help="チャット画面クリア"):
                    st.session_state.messages = []
                    st.session_state.screenshot_bytes = None
                    st.rerun()

            # ── モバイル: ジョブ一覧（直近5件）──
            if st.session_state.job_history:
                st.markdown("**ジョブ一覧**")
                _m_running = [j for j in st.session_state.job_history if j.get("status") == "running"]
                _m_others = [j for j in st.session_state.job_history if j.get("status") != "running"]
                _m_sorted = _m_running + _m_others
                for job in _m_sorted[:5]:
                    status = job.get("status", "?")
                    prompt_preview = job.get("prompt", "")[:22]
                    job_id = job.get("job_id", "")
                    job_cwd = job.get("cwd", "")
                    cwd_label = get_path_basename(job_cwd) if job_cwd else ""
                    created = job.get("created_at")
                    time_str = format_timestamp(created) if created else ""
                    icon = {"running": "🔄実行中", "completed": "✅完了", "error": "❌エラー", "cancelled": "⛔中止"}.get(status, "❓")
                    is_active = (job_id == st.session_state.current_job_id)
                    marker = ">" if is_active else ""
                    label = f"{marker}{icon} {time_str} [{cwd_label}] {prompt_preview}"
                    if st.button(label, key=f"job_{job_id}", use_container_width=True):
                        # ストリーミング中なら前ジョブの状態をクリーンアップ
                        if st.session_state.is_streaming:
                            _old_stop = st.session_state.get("_stream_stop")
                            if _old_stop:
                                _old_stop.set()
                            for _k in ("_stream_queue", "_stream_stop", "_stream_text",
                                       "_stream_tools", "_stream_pending_tool",
                                       "_stream_all_events", "_stream_errors",
                                       "_stream_cost_info", "_stream_done"):
                                st.session_state.pop(_k, None)
                            st.session_state.is_streaming = False
                        # 即座に切替（イベント取得なし）
                        st.session_state.messages = []
                        st.session_state.history_offset = 0
                        st.session_state.history_has_more = False
                        st.session_state.current_job_id = job_id
                        sid = job.get("session_id_out")
                        if sid:
                            add_session(sid)
                            st.session_state.session_id = sid
                        _jcwd = job.get("cwd")
                        if _jcwd:
                            st.session_state.active_job_cwd = _jcwd
                            if _jcwd in st.session_state.flat_dirs:
                                st.session_state.selected_dir = _jcwd
                        st.rerun()

            # ── モバイル: PC履歴（直近8件）──
            if st.session_state.pc_sessions:
                st.markdown("**PC履歴**")
                for sess in st.session_state.pc_sessions[:8]:
                    sid = sess.get("session_id", "")
                    last_mod = sess.get("last_modified", 0)
                    last_user = sess.get("last_user_msg", "")
                    last_assist = sess.get("last_assist_msg", "")
                    project = sess.get("project_dir", "")
                    line_count = sess.get("line_count", 0)
                    preview_text = last_user or last_assist or project
                    preview = (preview_text[:28] + "…") if len(preview_text) > 28 else preview_text
                    time_str = format_timestamp(last_mod) if last_mod else ""
                    is_current = (sid == st.session_state.session_id)
                    label = f"{'>' if is_current else '>'} {time_str} {preview}"
                    if st.button(label, key=f"pcsess_{sid}", use_container_width=True,
                                 help=f"{sid[:8]} | {line_count}行"):
                        # ストリーミング中ならクリーンアップ
                        if st.session_state.is_streaming:
                            _old_stop = st.session_state.get("_stream_stop")
                            if _old_stop:
                                _old_stop.set()
                            for _k in ("_stream_queue", "_stream_stop", "_stream_text",
                                       "_stream_tools", "_stream_pending_tool",
                                       "_stream_all_events", "_stream_errors",
                                       "_stream_cost_info", "_stream_done"):
                                st.session_state.pop(_k, None)
                            st.session_state.is_streaming = False
                        # 即座に切替（イベント取得なし）
                        add_session(sid)
                        st.session_state.session_id = sid
                        st.session_state.messages = []
                        st.session_state.history_offset = 0
                        st.session_state.history_has_more = False
                        _pcwd = sess.get("cwd") or sess.get("project_dir")
                        if _pcwd:
                            st.session_state.active_job_cwd = _pcwd
                            if _pcwd in st.session_state.flat_dirs:
                                st.session_state.selected_dir = _pcwd
                        st.rerun()
            elif st.session_state.pc_sessions_loaded:
                st.caption("セッションなし")
            else:
                st.caption("ボタンで履歴取得")

        else:
            # ─────────────────────────────────────
            # デスクトップサイドバー
            # 情報を豊富に、ラベル付きで表示
            # ─────────────────────────────────────

            # ── モデル選択 ──
            st.subheader("モデル")
            selected_model = st.selectbox(
                "Model",
                options=list(MODEL_OPTIONS.keys()),
                format_func=lambda x: MODEL_OPTIONS.get(x, x),
                index=list(MODEL_OPTIONS.keys()).index(
                    st.session_state.selected_model
                ) if st.session_state.selected_model in MODEL_OPTIONS else 0,
                label_visibility="collapsed",
            )
            st.session_state.selected_model = selected_model

            # ── 作業ディレクトリ / セッション状態 ──
            _has_active_session = bool(st.session_state.active_job_cwd or st.session_state.session_id)
            if _has_active_session:
                # セッション中: ディレクトリは固定表示（変更不可）
                _active_cwd = st.session_state.active_job_cwd or st.session_state.selected_dir
                _active_label = get_path_basename(_active_cwd) if _active_cwd else "不明"
                _sid_short = st.session_state.session_id[:8] if st.session_state.session_id else "---"
                st.subheader("セッション中")
                st.info(f"**{_active_label}** | `{_sid_short}`")
                if st.button("新規セッション", use_container_width=True, key="desk_new_session"):
                    # ストリーミング中ならワーカースレッドを停止
                    if st.session_state.is_streaming:
                        _old_stop = st.session_state.get("_stream_stop")
                        if _old_stop:
                            _old_stop.set()
                        for _k in ("_stream_queue", "_stream_stop", "_stream_text",
                                    "_stream_tools", "_stream_pending_tool",
                                    "_stream_all_events", "_stream_errors",
                                    "_stream_cost_info", "_stream_done"):
                            st.session_state.pop(_k, None)
                        st.session_state.is_streaming = False
                        st.session_state.cancel_requested = False
                    st.session_state.active_job_cwd = None
                    st.session_state.session_id = None
                    st.session_state.messages = []
                    st.session_state.current_job_id = None
                    st.session_state.screenshot_bytes = None
                    st.session_state.history_offset = 0
                    st.session_state.history_has_more = False
                    st.session_state.new_session_requested = True
                    st.rerun()
            else:
                # 新規セッション: フォルダ選択可能
                if st.session_state.flat_dirs:
                    st.subheader("作業ディレクトリ")
                    dir_options = st.session_state.flat_dirs
                    dir_labels = {}
                    for group_name, group_dirs in st.session_state.directories.items():
                        group_base = get_path_basename(group_name)
                        for d in group_dirs:
                            dir_labels[d] = f"{group_base}/{get_path_basename(d)}"
                    selected = st.selectbox(
                        "CWD",
                        options=dir_options,
                        format_func=lambda x: dir_labels.get(x, get_path_basename(x)),
                        index=dir_options.index(st.session_state.selected_dir)
                        if st.session_state.selected_dir in dir_options else 0,
                        label_visibility="collapsed",
                    )
                    st.session_state.selected_dir = selected

            # ── ジョブ一覧 ──
            if st.session_state.job_history:
                st.subheader("ジョブ一覧")
                # Running ジョブを先頭に
                _running = [j for j in st.session_state.job_history if j.get("status") == "running"]
                _others = [j for j in st.session_state.job_history if j.get("status") != "running"]
                _sorted_jobs = _running + _others

                for job in _sorted_jobs[:10]:
                    status = job.get("status", "?")
                    prompt_preview = job.get("prompt", "")[:35]
                    job_id = job.get("job_id", "")
                    job_cwd = job.get("cwd", "")
                    cwd_label = get_path_basename(job_cwd) if job_cwd else ""
                    created = job.get("created_at")
                    time_str = format_timestamp(created) if created else ""
                    icon = {"running": "🔄実行中", "completed": "✅完了", "error": "❌エラー", "cancelled": "⛔中止"}.get(status, "❓")
                    is_active = (job_id == st.session_state.current_job_id)
                    marker = "> " if is_active else ""
                    label = f"{marker}{icon} {time_str} [{cwd_label}] {prompt_preview}"
                    if st.button(label, key=f"job_{job_id}", use_container_width=True):
                        # ストリーミング中なら前ジョブの状態をクリーンアップ
                        if st.session_state.is_streaming:
                            _old_stop = st.session_state.get("_stream_stop")
                            if _old_stop:
                                _old_stop.set()
                            for _k in ("_stream_queue", "_stream_stop", "_stream_text",
                                       "_stream_tools", "_stream_pending_tool",
                                       "_stream_all_events", "_stream_errors",
                                       "_stream_cost_info", "_stream_done"):
                                st.session_state.pop(_k, None)
                            st.session_state.is_streaming = False
                        # 即座に切替（イベント取得なし）
                        st.session_state.messages = []
                        st.session_state.history_offset = 0
                        st.session_state.history_has_more = False
                        st.session_state.current_job_id = job_id
                        sid = job.get("session_id_out")
                        if sid:
                            add_session(sid)
                            st.session_state.session_id = sid
                        _jcwd = job.get("cwd")
                        if _jcwd:
                            st.session_state.active_job_cwd = _jcwd
                            if _jcwd in st.session_state.flat_dirs:
                                st.session_state.selected_dir = _jcwd
                        st.rerun()

            # ── スクリーンショット / ジョブ履歴リフレッシュ ──
            st.divider()
            col_ss, col_ref = st.columns(2)
            with col_ss:
                if st.button("撮影", use_container_width=True,
                             disabled=st.session_state.is_streaming):
                    with st.spinner("キャプチャ中..."):
                        img = st.session_state.client.get_screenshot()
                        if img:
                            st.session_state.screenshot_bytes = img
                            st.rerun()
                        else:
                            st.error("失敗しました")
            with col_ref:
                if st.button("履歴更新", use_container_width=True):
                    try:
                        jobs = st.session_state.client.list_jobs()
                        st.session_state.job_history = jobs
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

            # ── PC セッション履歴（20件）──
            st.divider()
            col_pc_title, col_pc_btn = st.columns([3, 1])
            with col_pc_title:
                st.subheader("PC履歴")
            with col_pc_btn:
                if st.button("再接続", key="load_pc_sessions",
                             help="PCのClaude会話履歴を取得"):
                    try:
                        with st.spinner("読み込み中..."):
                            sessions = st.session_state.client.list_sessions()
                        st.session_state.pc_sessions = sessions
                        st.session_state.pc_sessions_loaded = True
                        st.rerun()
                    except Exception as e:
                        st.error(f"取得失敗: {e}")

            if st.session_state.pc_sessions:
                for sess in st.session_state.pc_sessions[:20]:
                    sid = sess.get("session_id", "")
                    last_mod = sess.get("last_modified", 0)
                    last_user = sess.get("last_user_msg", "")
                    last_assist = sess.get("last_assist_msg", "")
                    project = sess.get("project_dir", "")
                    line_count = sess.get("line_count", 0)
                    preview_text = last_user or last_assist or project
                    preview = (preview_text[:38] + "…") if len(preview_text) > 38 else preview_text
                    time_str = format_timestamp(last_mod) if last_mod else ""
                    is_current = (sid == st.session_state.session_id)
                    label = f"{'> ' if is_current else ''}{time_str} {preview}"
                    if st.button(label, key=f"pcsess_{sid}", use_container_width=True,
                                 help=f"Session: {sid[:8]}…\n{line_count}行 | {project[-30:]}"):
                        # 即座に切替（イベント取得なし）
                        add_session(sid)
                        st.session_state.session_id = sid
                        st.session_state.messages = []
                        st.session_state.history_offset = 0
                        st.session_state.history_has_more = False
                        _pcwd = sess.get("cwd") or sess.get("project_dir")
                        if _pcwd:
                            st.session_state.active_job_cwd = _pcwd
                            if _pcwd in st.session_state.flat_dirs:
                                st.session_state.selected_dir = _pcwd
                        st.rerun()
            elif st.session_state.pc_sessions_loaded:
                st.caption("セッションが見つかりません")
            else:
                st.caption("ボタンで一覧を取得")

            # ── 修正リクエスト ──
            st.divider()
            st.subheader("修正リクエスト")
            st.caption("エラーや不具合をPC側のClaude Codeに送信して修正を依頼")
            fix_request = st.text_area(
                "修正内容",
                placeholder="例: ○○のグラフが表示されない、○○のエラーが出る等",
                height=100,
                label_visibility="collapsed",
                key="fix_request_text",
            )
            fix_use_chrome = st.checkbox("Chromeで視覚確認を含める", value=True, key="fix_chrome")
            if st.button("修正リクエスト送信", use_container_width=True,
                         disabled=not fix_request):
                # 修正プロンプトを構築
                fix_prompt = f"以下の修正を行ってください:\n\n{fix_request}"
                if fix_use_chrome:
                    fix_prompt += "\n\n修正後はChromeブラウザで動作を視覚的に確認してください。"
                # 通常のプロンプトとして送信
                cwd = st.session_state.active_job_cwd or st.session_state.selected_dir
                if cwd:
                    st.session_state.messages.append({
                        "role": "user",
                        "content": f"修正リクエスト: {fix_request}",
                        "tool_blocks": [],
                        "cost_info": None,
                    })
                    try:
                        result = st.session_state.client.send_prompt(
                            prompt=fix_prompt,
                            cwd=cwd,
                            session_id=st.session_state.session_id,
                            model=st.session_state.selected_model,
                        )
                        job_id = result.get("job_id")
                        if job_id:
                            st.session_state.current_job_id = job_id
                            st.session_state.is_streaming = True
                            st.session_state.cancel_requested = False
                            st.rerun()
                    except Exception as e:
                        st.error(f"送信エラー: {e}")
                else:
                    st.error("作業ディレクトリを選択してください")

        # ── モバイル: 修正リクエスト（コンパクト版）──
        if IS_MOBILE:
            st.divider()
            st.markdown("**修正リクエスト**")
            fix_request_m = st.text_area(
                "修正内容",
                placeholder="エラー内容や修正依頼を入力",
                height=80,
                label_visibility="collapsed",
                key="fix_request_mobile",
            )
            if st.button("送信", use_container_width=True,
                         disabled=not fix_request_m,
                         key="fix_send_mobile"):
                fix_prompt = f"以下の修正を行ってください:\n\n{fix_request_m}\n\n修正後はChromeブラウザで動作を視覚的に確認してください。"
                cwd = st.session_state.active_job_cwd or st.session_state.selected_dir
                if cwd:
                    st.session_state.messages.append({
                        "role": "user",
                        "content": f"修正リクエスト: {fix_request_m}",
                        "tool_blocks": [],
                        "cost_info": None,
                    })
                    try:
                        result = st.session_state.client.send_prompt(
                            prompt=fix_prompt,
                            cwd=cwd,
                            session_id=st.session_state.session_id,
                            model=st.session_state.selected_model,
                        )
                        job_id = result.get("job_id")
                        if job_id:
                            st.session_state.current_job_id = job_id
                            st.session_state.is_streaming = True
                            st.session_state.cancel_requested = False
                            st.rerun()
                    except Exception as e:
                        st.error(f"送信エラー: {e}")
                else:
                    st.error("作業ディレクトリを選択")


# ─── メインエリア ──────────────────────────────────────────

# タイトル（未接続時）
if not st.session_state.connected:
    if IS_MOBILE:
        # モバイル: コンパクトな案内
        st.markdown("""
        ## Claude Code Remote
        ### セットアップ
        1. ← サイドバー（menu）を開く
        2. **ngrok URL** と **Auth Token** を入力
        3. 接続ボタンをタップ
        """)
    else:
        st.title("CLAUDE TERMINAL v2.0")
        st.markdown("""
        ### セットアップ手順

        1. **Flask バックエンド** を自PC上で起動（ngrok経由で公開）
        2. サイドバーに **ngrok URL** と **Auth Token** を入力
        3. **接続** ボタンをクリック

        > Streamlit Cloud経由でFlask APIにアクセスするため、
        > ngrokドメインがブロックされるネットワークでも利用可能です。
        """)
    st.stop()

# ── スクリーンショット表示 ──
if st.session_state.screenshot_bytes:
    if IS_MOBILE:
        # モバイル: フル幅表示 + 閉じる/更新ボタンを下に配置
        with st.expander("PC画面", expanded=True):
            st.image(st.session_state.screenshot_bytes,
                     use_container_width=True)
            mc1, mc2 = st.columns(2)
            with mc1:
                if st.button("閉じる", key="close_screenshot", use_container_width=True):
                    st.session_state.screenshot_bytes = None
                    st.rerun()
            with mc2:
                if st.button("更新", key="refresh_screenshot", use_container_width=True):
                    with st.spinner("更新中..."):
                        img = st.session_state.client.get_screenshot()
                        if img:
                            st.session_state.screenshot_bytes = img
                            st.rerun()
    else:
        with st.expander("PC画面キャプチャ", expanded=True):
            col_img, col_btn = st.columns([6, 1])
            with col_img:
                st.image(st.session_state.screenshot_bytes,
                         caption="最新のスクリーンショット",
                         use_container_width=True)
            with col_btn:
                if st.button("閉じる", key="close_screenshot"):
                    st.session_state.screenshot_bytes = None
                    st.rerun()
                if st.button("更新", key="refresh_screenshot"):
                    with st.spinner("更新中..."):
                        img = st.session_state.client.get_screenshot()
                        if img:
                            st.session_state.screenshot_bytes = img
                            st.rerun()

# ── ツールブロック表示ヘルパー ──
def _render_tool_block(tool, msg_idx, tool_idx):
    """1つのツールブロックを表示する"""
    tool_name = tool.get("name", "tool")
    tool_input = tool.get("input_str", "")
    tool_result = tool.get("result", "")
    file_path = extract_file_path(tool_input)

    st.markdown(f"**{tool_name}**")
    if tool_input:
        formatted = parse_tool_input_display(tool_input)
        st.code(formatted, language="json")
    if file_path:
        fname = get_path_basename(file_path)
        if is_image_path(file_path):
            st.markdown(f"**{fname}**")
            try:
                img_bytes, mime = st.session_state.client.get_file_bytes(file_path)
                if img_bytes:
                    st.image(img_bytes, caption=fname, use_container_width=True)
            except Exception:
                st.caption(f"画像の読み込みに失敗: {file_path}")
        else:
            st.markdown(f"**{fname}**")
    if tool_result:
        tool_id = tool.get("id", "")
        if len(tool_result) > 500:
            st.text_area(
                "Result", value=tool_result, height=150,
                disabled=True, label_visibility="collapsed",
                key=f"tool_result_{msg_idx}_{tool_idx}_{tool_id}",
            )
        else:
            st.code(tool_result, language=None)
    # Note: caller should add separators between tools in grouped view if needed


# ── チャット履歴表示 ──
for _msg_idx, msg in enumerate(st.session_state.messages):
    role = msg.get("role", "assistant")
    content = msg.get("content", "")
    tool_blocks = msg.get("tool_blocks", [])
    cost_info = msg.get("cost_info")

    if role == "system":
        st.markdown(
            f'<div class="error-msg">{content}</div>',
            unsafe_allow_html=True,
        )
        continue

    with st.chat_message(role):
        # ユーザーメッセージの添付画像サムネイル
        _msg_images = msg.get("images", [])
        if _msg_images and role == "user":
            for _img_info in _msg_images:
                try:
                    _img_bytes = base64.b64decode(_img_info["data"])
                    st.image(_img_bytes, caption=_img_info.get("name", ""), width=200)
                except Exception:
                    st.caption(f"[画像: {_img_info.get('name', '?')}]")

        # テキスト部分
        if content:
            if role == "user":
                st.markdown(f"> {content}")
            else:
                st.markdown(content)

        # ツール使用部分 — 多数ある場合はグループ化してコンパクトに表示
        if tool_blocks:
            _n_tools = len(tool_blocks)
            if _n_tools > 3:
                # 3個超: 1つのexpanderにまとめる
                _tool_names = [t.get("name", "tool") for t in tool_blocks]
                _summary = ", ".join(_tool_names[:4])
                if _n_tools > 4:
                    _summary += f" +{_n_tools - 4}"
                with st.expander(f"> {_n_tools} tools: {_summary}", expanded=False):
                    for _tool_idx, tool in enumerate(tool_blocks):
                        _render_tool_block(tool, _msg_idx, _tool_idx)
            else:
                # 3個以下: 個別expander（従来通り）
                for _tool_idx, tool in enumerate(tool_blocks):
                    tool_name = tool.get("name", "tool")
                    tool_input = tool.get("input_str", "")
                    tool_result = tool.get("result", "")
                    file_path = extract_file_path(tool_input)

                    with st.expander(f"> {tool_name}", expanded=False):
                        _render_tool_block(tool, _msg_idx, _tool_idx)

        # コスト情報
        if cost_info:
            st.markdown(
                f'<div class="cost-info">{cost_info}</div>',
                unsafe_allow_html=True,
            )


# ── セッション履歴のチャンク読み込み ──
_HISTORY_CHUNK = 50
if (st.session_state.session_id
    and not st.session_state.is_streaming
    and st.session_state.client):
    _show_load = (not st.session_state.messages) or st.session_state.history_has_more
    if _show_load:
        # チャットが空の時はスペーサーで下に押し下げる
        if not st.session_state.messages:
            st.markdown("<div style='min-height:30vh'></div>", unsafe_allow_html=True)
        _btn_label = "さらに読み込む" if st.session_state.messages else "履歴を読み込む"
        if st.button(_btn_label, key="load_session_history", use_container_width=True):
            try:
                data = st.session_state.client.get_session_events(
                    st.session_state.session_id,
                    limit=_HISTORY_CHUNK,
                    offset=st.session_state.history_offset,
                )
                events = data.get("events", [])
                new_msgs = process_native_events(events)
                st.session_state.messages = new_msgs + st.session_state.messages
                st.session_state.history_offset += _HISTORY_CHUNK
                st.session_state.history_has_more = data.get("has_more", False)
                st.session_state.history_total_lines = data.get("total_lines", 0)
                st.rerun()
            except Exception as e:
                st.error(f"履歴読み込みエラー: {e}")

# ── 完了通知（rerun後に発火） ──
if st.session_state.notify_completion:
    _np = st.session_state.notify_completion.replace("'", "\\'")
    st.session_state.notify_completion = None  # 1回だけ発火
    # 親フレームで通知音を鳴らす（iframe内のAudioContextはsuspendされやすいため）
    st.components.v1.html(f"""
    <script>
    (function() {{
        var doc = window.parent.document;
        var win = window.parent;

        // 親フレームで音を鳴らす（AudioContextポリシー回避）
        function playNotify() {{
            try {{
                // 親フレームに共有AudioContextを保持（再利用で確実に鳴る）
                if (!win._claudeAudioCtx) {{
                    win._claudeAudioCtx = new (win.AudioContext || win.webkitAudioContext)();
                }}
                var ctx = win._claudeAudioCtx;
                // suspended状態なら復帰を試みる
                if (ctx.state === 'suspended') {{
                    ctx.resume().then(function() {{ doBeep(ctx); }});
                }} else {{
                    doBeep(ctx);
                }}
            }} catch(e) {{
                // フォールバック: iframe内で試行
                try {{
                    var ctx2 = new (window.AudioContext || window.webkitAudioContext)();
                    ctx2.resume().then(function() {{ doBeep(ctx2); }});
                }} catch(e2) {{}}
            }}
        }}

        function doBeep(ctx) {{
            function beep(freq, start, dur) {{
                var o = ctx.createOscillator();
                var g = ctx.createGain();
                o.connect(g); g.connect(ctx.destination);
                o.type = 'sine';
                o.frequency.value = freq;
                g.gain.setValueAtTime(0.3, ctx.currentTime + start);
                g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + start + dur);
                o.start(ctx.currentTime + start);
                o.stop(ctx.currentTime + start + dur);
            }}
            beep(880, 0, 0.15);
            beep(1100, 0.18, 0.2);
        }}

        playNotify();

        // ブラウザ通知（親フレームで発火）
        try {{
            if ('Notification' in win) {{
                if (win.Notification.permission === 'granted') {{
                    new win.Notification('Claude Terminal', {{
                        body: '{_np}',
                        tag: 'claude-done'
                    }});
                }} else if (win.Notification.permission !== 'denied') {{
                    win.Notification.requestPermission();
                }}
            }}
        }} catch(e) {{}}
    }})();
    </script>
    """, height=0)


# ── ストリーミング中のキャンセルボタン ──
if st.session_state.is_streaming:
    if st.button("キャンセル", type="primary", use_container_width=True):
        # サーバーにキャンセル要求
        if st.session_state.current_job_id and st.session_state.client:
            try:
                st.session_state.client.cancel_job(st.session_state.current_job_id)
            except Exception:
                pass
        # ワーカースレッド停止 & ストリーム状態クリア
        _old_stop = st.session_state.get("_stream_stop")
        if _old_stop:
            _old_stop.set()
        for _k in ("_stream_queue", "_stream_stop", "_stream_text",
                    "_stream_tools", "_stream_pending_tool", "_stream_all_events",
                    "_stream_errors", "_stream_cost_info", "_stream_done"):
            st.session_state.pop(_k, None)
        st.session_state.is_streaming = False
        st.session_state.cancel_requested = False
        st.rerun()


# ── ジョブ自動復帰（ブラウザ再接続時） ──
# 接続済み & 復帰チェック未実施 & メッセージ履歴が空 の場合にジョブ復帰を試みる
if (st.session_state.connected
    and not st.session_state.recovery_checked
    and not st.session_state.messages
    and st.session_state.client
    and st.session_state.job_history):
    st.session_state.recovery_checked = True
    # 直近のジョブから running / 最新 completed を探す
    _running_jobs = [j for j in st.session_state.job_history if j.get("status") == "running"]
    _recent_completed = [j for j in st.session_state.job_history
                         if j.get("status") in ("completed", "error")]
    _recovery_target = None
    if _running_jobs:
        _recovery_target = _running_jobs[0]
    elif _recent_completed:
        _recovery_target = _recent_completed[0]

    if _recovery_target:
        _rjob_id = _recovery_target.get("job_id")
        _rjob_status = _recovery_target.get("status")
        _rjob_prompt = _recovery_target.get("prompt", "")[:80]
        _rjob_label = "実行中" if _rjob_status == "running" else "完了"
        st.info(f"{_rjob_label}のジョブを検出: 「{_rjob_prompt}...」")

        col_r1, col_r2 = st.columns(2)
        with col_r1:
            _do_recover = st.button("結果を復帰", type="primary", use_container_width=True)
        with col_r2:
            _skip_recover = st.button("スキップ", use_container_width=True)

        if _do_recover:
            try:
                # ユーザーメッセージを復元
                st.session_state.messages.append({
                    "role": "user",
                    "content": _recovery_target.get("prompt", "(プロンプト復帰)"),
                    "tool_blocks": [],
                    "cost_info": None,
                })

                # cwd を復帰
                _rcwd = _recovery_target.get("cwd")
                if _rcwd:
                    st.session_state.active_job_cwd = _rcwd
                    if _rcwd in st.session_state.flat_dirs:
                        st.session_state.selected_dir = _rcwd

                if _rjob_status == "running":
                    # 実行中ジョブ → ストリーミングに接続
                    st.session_state.current_job_id = _rjob_id
                    st.session_state.is_streaming = True
                    st.session_state.cancel_requested = False
                    st.rerun()
                else:
                    # 完了済みジョブ → イベント取得してメッセージに変換
                    job_data = st.session_state.client.poll_job_events(_rjob_id)
                    recovered_msgs = process_events(job_data.get("events", []))
                    st.session_state.messages.extend(recovered_msgs)
                    # セッションIDを復帰
                    _rsid = _recovery_target.get("session_id_out")
                    if _rsid:
                        add_session(_rsid)
                        st.session_state.session_id = _rsid
                    st.rerun()
            except Exception as e:
                st.error(f"ジョブ復帰エラー: {e}")
        elif _skip_recover:
            st.rerun()


# ── 復帰ストリーミング（実行中ジョブへの再接続） ──
# is_streaming=True かつ current_job_id がある場合、ジョブに再接続する
_is_active_streaming = (
    st.session_state.is_streaming
    and st.session_state.current_job_id
    and st.session_state.client
)

# ── 画像アップロード（サイドバーに配置、session_stateに保持） ──
if st.session_state.connected:
    with st.sidebar:
        _uploaded_files = st.file_uploader(
            "画像を添付", type=["png", "jpg", "jpeg", "gif", "webp"],
            accept_multiple_files=True, key="img_upload",
        )
        if _uploaded_files:
            _new_images = []
            for uf in _uploaded_files[:4]:
                raw = uf.read()
                if len(raw) > 5 * 1024 * 1024:
                    st.warning(f"{uf.name}: 5MBを超えるためスキップ")
                    continue
                ext = uf.name.rsplit(".", 1)[-1].lower()
                mt = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                      "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/png")
                _new_images.append({
                    "data": base64.b64encode(raw).decode(),
                    "media_type": mt,
                    "name": uf.name,
                })
            st.session_state.pending_images = _new_images
            if _new_images:
                st.caption(f"{len(_new_images)}枚の画像を添付中")
        else:
            # ファイルがクリアされたらpending_imagesもクリア
            st.session_state.pending_images = []

# ── プロンプト入力 ──
# ストリーミング中でも常に入力可能（前ジョブはサーバーで継続）
prompt = st.chat_input("プロンプトを入力...")

if prompt:
    if not st.session_state.connected or not st.session_state.client:
        st.error("バックエンドに接続してください")
        st.stop()

    cwd = st.session_state.active_job_cwd or st.session_state.selected_dir
    if not cwd:
        # フォールバック: flat_dirsの先頭を使用
        if st.session_state.flat_dirs:
            cwd = st.session_state.flat_dirs[0]
            st.session_state.selected_dir = cwd
        else:
            st.error("作業ディレクトリを選択してください")
            st.stop()

    # ストリーミング中なら前のジョブのワーカーを停止（ジョブ自体はサーバーで継続）
    _was_streaming = st.session_state.is_streaming
    if _was_streaming and st.session_state.current_job_id:
        _old_stop = st.session_state.get("_stream_stop")
        if _old_stop:
            _old_stop.set()
        # 前ジョブの蓄積イベントからメッセージを保存
        _old_events = st.session_state.get("_stream_all_events", [])
        if _old_events:
            _old_msgs = process_events(_old_events)
            if _old_msgs:
                st.session_state.messages.extend(_old_msgs)
        # ストリーム状態をクリア
        for _k in ("_stream_queue", "_stream_stop", "_stream_text",
                    "_stream_tools", "_stream_pending_tool", "_stream_all_events",
                    "_stream_errors", "_stream_cost_info", "_stream_done"):
            st.session_state.pop(_k, None)
        st.session_state.is_streaming = False
        st.session_state.current_job_id = None

    # session_stateから添付画像を取得（chat_input送信後もrerun前に保持されている）
    _pending = st.session_state.pending_images or []

    # ユーザーメッセージを追加
    st.session_state.messages.append({
        "role": "user",
        "content": prompt,
        "tool_blocks": [],
        "cost_info": None,
        "images": [{"data": img["data"], "media_type": img["media_type"],
                     "name": img["name"]} for img in _pending],
    })

    # ジョブ送信
    try:
        _send_images = None
        if _pending:
            _send_images = [
                {"data": img["data"], "media_type": img["media_type"]}
                for img in _pending
            ]
        # 送信後に画像をクリア
        st.session_state.pending_images = []
        result = st.session_state.client.send_prompt(
            prompt=prompt,
            cwd=cwd,
            session_id=st.session_state.session_id,
            model=st.session_state.selected_model,
            images=_send_images,
        )
        job_id = result.get("job_id")
        if not job_id:
            st.error("ジョブIDが取得できませんでした")
            st.stop()

        st.session_state.current_job_id = job_id
        st.session_state.is_streaming = True
        st.session_state.cancel_requested = False

    except Exception as e:
        st.error(f"プロンプト送信エラー: {e}")
        st.stop()

# ── ストリーミング開始（新プロンプト送信時のワーカー起動） ──
if prompt and st.session_state.is_streaming and not hasattr(st.session_state, "_stream_queue"):
    # 新ジョブのワーカースレッド開始
    _eq = queue.Queue()
    _se = threading.Event()
    _w = threading.Thread(
        target=stream_worker,
        args=(st.session_state.client, st.session_state.current_job_id, _eq, _se),
        daemon=True,
    )
    _w.start()
    st.session_state._stream_queue = _eq
    st.session_state._stream_stop = _se
    st.session_state._stream_text = ""
    st.session_state._stream_tools = []
    st.session_state._stream_pending_tool = None
    st.session_state._stream_all_events = []
    st.session_state._stream_errors = []
    st.session_state._stream_cost_info = None
    st.session_state._stream_done = False
    st.session_state.is_streaming = True
    st.rerun()

# ── リカバリー: ページリロード時に実行中ジョブに再接続 ──
if (_is_active_streaming
    and not hasattr(st.session_state, "_stream_queue")):
    # ワーカースレッドが存在しない → 再接続
    _eq = queue.Queue()
    _se = threading.Event()
    _w = threading.Thread(
        target=stream_worker,
        args=(st.session_state.client, st.session_state.current_job_id, _eq, _se),
        daemon=True,
    )
    _w.start()
    st.session_state._stream_queue = _eq
    st.session_state._stream_stop = _se
    if not hasattr(st.session_state, "_stream_text"):
        st.session_state._stream_text = ""
        st.session_state._stream_tools = []
        st.session_state._stream_pending_tool = None
        st.session_state._stream_all_events = []
        st.session_state._stream_errors = []
        st.session_state._stream_cost_info = None
        st.session_state._stream_done = False

# ── 非ブロッキング・ストリーミング表示 ──
if st.session_state.is_streaming and hasattr(st.session_state, "_stream_queue"):
    _sq = st.session_state._stream_queue
    _stream_done = st.session_state._stream_done

    # キューからイベントを非ブロッキングで全取得
    if not _stream_done:
        _batch = []
        try:
            while True:
                _ev = _sq.get_nowait()
                _batch.append(_ev)
        except queue.Empty:
            pass

        for _ev in _batch:
            if _ev is None:
                st.session_state._stream_done = True
                break

            st.session_state._stream_all_events.append(_ev)
            _etype = _ev.get("type", "")

            if _etype == "system" and _ev.get("subtype") == "init":
                _sid = _ev.get("session_id")
                if _sid:
                    add_session(_sid)
                    st.session_state.session_id = _sid
                    st.session_state.new_session_requested = False
                    _init_cwd = _ev.get("cwd")
                    if _init_cwd:
                        st.session_state.session_dirs[_sid] = _init_cwd
                        # 新規セッションの場合、active_job_cwdも設定
                        if not st.session_state.active_job_cwd:
                            st.session_state.active_job_cwd = _init_cwd

            elif _etype == "stream_event":
                _inner = _ev.get("event", {})
                _inner_type = _inner.get("type", "")
                if _inner_type == "content_block_start":
                    _cb = _inner.get("content_block", {})
                    if _cb.get("type") == "tool_use":
                        _pt = st.session_state._stream_pending_tool
                        if _pt:
                            st.session_state._stream_tools.append(_pt)
                        st.session_state._stream_pending_tool = {
                            "name": _cb.get("name", "tool"),
                            "id": _cb.get("id", ""),
                            "input_str": "",
                            "result": "",
                        }
                elif _inner_type == "content_block_delta":
                    _delta = _inner.get("delta", {})
                    if _delta.get("type") == "text_delta":
                        st.session_state._stream_text += _delta.get("text", "")
                    elif _delta.get("type") == "input_json_delta":
                        _pt = st.session_state._stream_pending_tool
                        if _pt:
                            _pt["input_str"] += _delta.get("partial_json", "")

            elif _etype == "assistant":
                if not st.session_state._stream_text:
                    _msg = _ev.get("message", {})
                    for _block in _msg.get("content", []):
                        if _block.get("type") == "text":
                            st.session_state._stream_text += _block.get("text", "")

            elif _etype == "user":
                _msg = _ev.get("message", {})
                for _block in _msg.get("content", []):
                    if _block.get("type") == "tool_result":
                        _content = _block.get("content", "")
                        if isinstance(_content, list):
                            _content = "\n".join(
                                _item.get("text", "")
                                for _item in _content
                                if isinstance(_item, dict)
                            )
                        _pt = st.session_state._stream_pending_tool
                        if _pt:
                            _pt["result"] = _content
                            st.session_state._stream_tools.append(_pt)
                            st.session_state._stream_pending_tool = None

            elif _etype == "result":
                _sid = _ev.get("session_id")
                if _sid:
                    add_session(_sid)
                    st.session_state.session_id = _sid
                _cost = _ev.get("cost_usd")
                _usage = _ev.get("usage", {})
                _parts = []
                if _cost is not None:
                    _parts.append(f"${_cost:.4f}")
                if _usage.get("input_tokens"):
                    _parts.append(f"in:{_usage['input_tokens']}")
                if _usage.get("output_tokens"):
                    _parts.append(f"out:{_usage['output_tokens']}")
                if _parts:
                    st.session_state._stream_cost_info = " | ".join(_parts)

            elif _etype in ("error", "stderr"):
                _text = _ev.get("text", "")
                if _text:
                    st.session_state._stream_errors.append(_text)

            elif _etype == "done":
                st.session_state._stream_done = True
                break

    # ── 表示 ──
    _s_text = st.session_state._stream_text
    _s_tools = st.session_state._stream_tools
    _s_errors = st.session_state._stream_errors
    _s_done = st.session_state._stream_done
    _s_cost = st.session_state._stream_cost_info
    _s_pending = st.session_state._stream_pending_tool

    with st.chat_message("assistant"):
        # ツール表示
        for _tool in _s_tools:
            with st.expander(f"{_tool['name']}", expanded=False):
                if _tool.get("input_str"):
                    st.code(parse_tool_input_display(_tool["input_str"]), language="json")
                _fp = extract_file_path(_tool.get("input_str", ""))
                if _fp:
                    _fname = get_path_basename(_fp)
                    if is_image_path(_fp):
                        st.markdown(f"**{_fname}**")
                        try:
                            _img_bytes, _mime = st.session_state.client.get_file_bytes(_fp)
                            if _img_bytes:
                                st.image(_img_bytes, caption=_fname, use_container_width=True)
                        except Exception:
                            pass
                    else:
                        st.markdown(f"**{_fname}**")
                if _tool.get("result"):
                    _r = _tool["result"]
                    if len(_r) > 500:
                        st.text_area("r", value=_r, height=150, disabled=True,
                                     label_visibility="collapsed",
                                     key=f"sr_{_tool.get('id', '')}_{hash(_r[:100])}")
                    else:
                        st.code(_r, language=None)

        # 実行中のツール名
        if _s_pending and not _s_done:
            st.caption(f"{_s_pending['name']}...")

        # テキスト表示
        if _s_text:
            if _s_done:
                st.markdown(_s_text)
            else:
                st.markdown(_s_text + " ▌")

        # エラー
        for _err in _s_errors:
            st.markdown(f'<div class="error-msg">[!] {_err}</div>', unsafe_allow_html=True)

        # コスト + セッションID
        if _s_cost and _s_done:
            _sid_tag = ""
            if st.session_state.session_id:
                _sid_tag = f" | sid:{st.session_state.session_id[:8]}"
            st.markdown(f'<div class="cost-info">{_s_cost}{_sid_tag}</div>', unsafe_allow_html=True)

    # ── 完了処理 or 継続リラン ──
    if _s_done:
        # メッセージ履歴に追加
        _all_ev = st.session_state._stream_all_events
        _structured = process_events(_all_ev)
        if _structured:
            st.session_state.messages.extend(_structured)
        elif _s_text:
            st.session_state.messages.append({
                "role": "assistant",
                "content": _s_text,
                "tool_blocks": _s_tools,
                "cost_info": _s_cost,
            })

        # クリーンアップ
        st.session_state.is_streaming = False
        st.session_state.cancel_requested = False
        for _k in ("_stream_queue", "_stream_stop", "_stream_text",
                    "_stream_tools", "_stream_pending_tool", "_stream_all_events",
                    "_stream_errors", "_stream_cost_info", "_stream_done"):
            st.session_state.pop(_k, None)

        # ジョブ履歴更新
        try:
            st.session_state.job_history = st.session_state.client.list_jobs()
        except Exception:
            pass

        # 完了通知
        _notify_text = ""
        if _structured:
            for _m in reversed(_structured):
                if _m.get("content"):
                    _notify_text = _m["content"]
                    break
        _notify_preview = (_notify_text or _s_text or "")[:60].replace("\n", " ")
        st.session_state.notify_completion = _notify_preview or "タスク完了"

        st.rerun()
    else:
        # まだ完了していない → 短い待機後にリラン（UIは操作可能）
        time.sleep(0.3)
        st.rerun()


# ── スクロールボトムボタン ──
with st.sidebar:
    if st.button("↓ 最下部へ", key="scroll_bottom", use_container_width=True):
        st.components.v1.html("""
        <script>
        (function(){
            var doc = window.parent.document;
            // chat_input付近へスクロール（複数セレクタで確実に）
            var targets = [
                doc.querySelector('[data-testid="stChatInput"]'),
                doc.querySelector('[data-testid="stBottom"]'),
                doc.querySelector('[data-testid="stBottomBlockContainer"]'),
                doc.querySelector('.stChatInput'),
            ];
            for (var i = 0; i < targets.length; i++) {
                if (targets[i]) {
                    targets[i].scrollIntoView({behavior:'smooth', block:'end'});
                    return;
                }
            }
            // フォールバック: メインコンテナの最下部へ
            var main = doc.querySelector('[data-testid="stAppViewContainer"]')
                     || doc.querySelector('.main');
            if (main) main.scrollTop = main.scrollHeight;
        })();
        </script>
        """, height=0)
