"""Claude Code Remote – Streamlit Cloud Frontend

Streamlit Cloud → ngrok → Flask バックエンドへのプロキシUI。
ブラウザからは *.streamlit.app のみアクセスするため、
ngrokドメインがブロックされるネットワークでも利用可能。
"""

import json
import queue
import re
import threading
import time
from datetime import datetime

import streamlit as st

from backend_client import BackendClient

# ─── ページ設定 ───────────────────────────────────────────
st.set_page_config(
    page_title="Claude Code Remote",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── カスタムCSS ──────────────────────────────────────────
st.markdown("""
<style>
/* 全体 */
.stApp { font-family: 'Segoe UI', sans-serif; }

/* チャットメッセージ内コードブロック */
.stChatMessage pre {
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 12px;
    overflow-x: auto;
    position: relative;
}
.stChatMessage code {
    font-size: 13px;
    font-family: 'Cascadia Code', 'Fira Code', monospace;
}

/* ツール使用の折りたたみ */
.tool-expander {
    border-left: 3px solid #e94560;
    padding-left: 8px;
    margin: 4px 0;
}

/* コスト表示 */
.cost-info {
    font-size: 11px;
    color: #888;
    text-align: center;
    margin: 4px 0;
}

/* ファイルカード */
.file-card {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #16213e;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 6px 12px;
    margin: 4px;
    font-size: 13px;
}

/* エラーメッセージ */
.error-msg {
    color: #ff6b6b;
    background: rgba(255,107,107,0.1);
    border-radius: 4px;
    padding: 8px;
    margin: 4px 0;
}

/* ステータスバッジ */
.status-running { color: #ffd93d; }
.status-completed { color: #6bcb77; }
.status-error { color: #ff6b6b; }
.status-cancelled { color: #888; }
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
        "selected_model": "claude-sonnet-4-5",  # デフォルトモデル
        "screenshot_bytes": None,               # 最新スクリーンショット
        "pc_sessions": [],                      # PCのClaude履歴セッション一覧
        "pc_sessions_loaded": False,            # 一覧取得済みフラグ
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()


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
    """UnixタイムスタンプをHH:MM形式に変換"""
    return datetime.fromtimestamp(ts).strftime("%H:%M")


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


# ─── ストリーミング処理 ────────────────────────────────────

def stream_worker(client: BackendClient, job_id: str,
                  event_queue: queue.Queue, stop_event: threading.Event):
    """バックグラウンドスレッド: SSEイベントを受信してキューに入れる"""
    try:
        for event in client.stream_job(job_id):
            if stop_event.is_set():
                break
            event_queue.put(event)
        event_queue.put(None)  # 完了マーカー
    except Exception as e:
        event_queue.put({"type": "error", "text": str(e)})
        event_queue.put(None)


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

    for ev in events:
        etype = ev.get("type", "")

        # ── system init ──
        if etype == "system" and ev.get("subtype") == "init":
            sid = ev.get("session_id")
            if sid:
                add_session(sid)
                st.session_state.session_id = sid

        # ── assistant (完成メッセージ) ──
        elif etype == "assistant":
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
                    "cost_info": " | ".join(cost_parts) if cost_parts else None,
                })
                current_text = ""
                current_tools = []

        # ── error / stderr ──
        elif etype in ("error", "stderr"):
            text = ev.get("text", "")
            if text:
                messages.append({
                    "role": "system",
                    "content": f"⚠️ {text}",
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
    st.title("🤖 Claude Code")
    st.caption("Remote Control via Streamlit")

    st.divider()

    # ── 接続設定 ──
    st.subheader("接続設定")

    ngrok_url = st.text_input(
        "ngrok URL",
        placeholder="https://xxxx.ngrok-free.app",
        help="Flask バックエンドの ngrok URL",
    )

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
    )

    col1, col2 = st.columns(2)
    with col1:
        connect_btn = st.button(
            "🔌 接続" if not st.session_state.connected else "🔄 再接続",
            use_container_width=True,
        )
    with col2:
        disconnect_btn = st.button(
            "❌ 切断",
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
            # URLバリデーション
            if not re.match(r"https?://.*\.(ngrok-free\.app|ngrok\.io|ngrok\.app)", ngrok_url):
                st.warning("⚠️ ngrokドメイン以外のURLです。続行しますか？")

            with st.spinner("接続中..."):
                client = BackendClient(ngrok_url)
                ok, msg = client.login(auth_token)
                if ok:
                    st.session_state.client = client
                    st.session_state.connected = True
                    # ディレクトリ取得
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
                    # ジョブ履歴取得
                    try:
                        jobs = client.list_jobs()
                        st.session_state.job_history = jobs
                        # 既存セッションIDを抽出
                        for job in jobs:
                            sid = job.get("session_id_out")
                            if sid:
                                add_session(sid)
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

    # 接続状態表示
    if st.session_state.connected:
        st.success("✅ 接続中")
    else:
        st.info("🔌 未接続")

    st.divider()

    # ── モデル選択 ──
    if st.session_state.connected:
        st.subheader("モデル")
        MODEL_OPTIONS = {
            "claude-sonnet-4-5": "⚡ Sonnet 4.5（速い・安い）",
            "claude-opus-4-5":   "🧠 Opus 4.5（賢い・高い）",
            "claude-haiku-3-5":  "🐦 Haiku 3.5（最速・最安）",
            "claude-opus-4":     "🧠 Opus 4",
            "claude-sonnet-4":   "⚡ Sonnet 4",
        }
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

    # ── 作業ディレクトリ ──
    if st.session_state.connected and st.session_state.flat_dirs:
        st.subheader("作業ディレクトリ")

        # グループ化表示
        dir_options = st.session_state.flat_dirs
        dir_labels = {}
        for group_name, group_dirs in st.session_state.directories.items():
            group_base = get_path_basename(group_name)
            for d in group_dirs:
                dir_labels[d] = f"📁 {group_base}/{get_path_basename(d)}"

        selected = st.selectbox(
            "CWD",
            options=dir_options,
            format_func=lambda x: dir_labels.get(x, get_path_basename(x)),
            index=dir_options.index(st.session_state.selected_dir)
            if st.session_state.selected_dir in dir_options
            else 0,
            label_visibility="collapsed",
        )
        st.session_state.selected_dir = selected

    # ── セッション ──
    if st.session_state.connected and st.session_state.sessions:
        st.subheader("セッション")
        session_options = ["(新規セッション)"] + st.session_state.sessions
        session_labels = {
            s: f"Session {s[:8]}" for s in st.session_state.sessions
        }
        session_labels["(新規セッション)"] = "🆕 新規セッション"

        current = st.session_state.session_id or "(新規セッション)"
        if current not in session_options:
            current = "(新規セッション)"

        sel_session = st.selectbox(
            "Session",
            options=session_options,
            format_func=lambda x: session_labels.get(x, x),
            index=session_options.index(current),
            label_visibility="collapsed",
        )
        if sel_session == "(新規セッション)":
            st.session_state.session_id = None
        else:
            st.session_state.session_id = sel_session

    # ── ジョブ履歴 ──
    if st.session_state.connected and st.session_state.job_history:
        st.subheader("ジョブ履歴")
        for job in st.session_state.job_history[:10]:
            status = job.get("status", "?")
            prompt_preview = job.get("prompt", "")[:40]
            job_id = job.get("job_id", "")
            created = job.get("created_at")
            time_str = format_timestamp(created) if created else ""

            status_icon = {
                "running": "🟡",
                "completed": "🟢",
                "error": "🔴",
                "cancelled": "⚪",
            }.get(status, "❓")

            if st.button(
                f"{status_icon} {time_str} {prompt_preview}",
                key=f"job_{job_id}",
                use_container_width=True,
            ):
                # ジョブの全イベントをロードして表示
                try:
                    job_data = st.session_state.client.get_job(job_id)
                    events = job_data.get("events", [])
                    st.session_state.messages = process_events(events)
                    sid = job_data.get("session_id_out")
                    if sid:
                        add_session(sid)
                        st.session_state.session_id = sid
                    st.session_state.current_job_id = job_id
                    st.rerun()
                except Exception as e:
                    st.error(f"ジョブ読み込みエラー: {e}")

    # ── スクリーンショット / ジョブ履歴リフレッシュ ──
    if st.session_state.connected:
        st.divider()
        col_ss, col_ref = st.columns(2)
        with col_ss:
            if st.button("📷 画面", use_container_width=True,
                         disabled=st.session_state.is_streaming):
                with st.spinner("キャプチャ中..."):
                    img = st.session_state.client.get_screenshot()
                    if img:
                        st.session_state.screenshot_bytes = img
                        st.rerun()
                    else:
                        st.error("失敗しました")
        with col_ref:
            if st.button("🔄 履歴", use_container_width=True):
                try:
                    jobs = st.session_state.client.list_jobs()
                    st.session_state.job_history = jobs
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    # ── PC セッション履歴（~/.claude/projects/）──
    if st.session_state.connected:
        st.divider()
        col_pc_title, col_pc_btn = st.columns([3, 1])
        with col_pc_title:
            st.subheader("💾 PC履歴")
        with col_pc_btn:
            if st.button("🔄", key="load_pc_sessions",
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

                # 表示テキスト: ユーザーの最後の発言を優先
                preview_text = last_user or last_assist or project
                preview = (preview_text[:38] + "…") if len(preview_text) > 38 else preview_text
                time_str = format_timestamp(last_mod) if last_mod else ""

                # 現在選択中のセッションをハイライト
                is_current = (sid == st.session_state.session_id)
                label = f"{'▶ ' if is_current else ''}{time_str} {preview}"

                if st.button(label, key=f"pcsess_{sid}",
                             use_container_width=True,
                             help=f"Session: {sid[:8]}…\n{line_count}行 | {project[-30:]}"):
                    try:
                        with st.spinner("セッション読み込み中..."):
                            data = st.session_state.client.get_session_events(sid)
                        events = data.get("events", [])
                        st.session_state.messages = process_events(events)
                        add_session(sid)
                        st.session_state.session_id = sid
                        st.rerun()
                    except Exception as e:
                        st.error(f"読み込みエラー: {e}")

        elif st.session_state.pc_sessions_loaded:
            st.caption("セッションが見つかりません")
        else:
            st.caption("🔄 ボタンで一覧を取得")


# ─── メインエリア ──────────────────────────────────────────

# タイトル（未接続時）
if not st.session_state.connected:
    st.title("🤖 Claude Code Remote")
    st.markdown("""
    ### セットアップ手順

    1. **Flask バックエンド** を自PC上で起動（ngrok経由で公開）
    2. サイドバーに **ngrok URL** と **Auth Token** を入力
    3. **接続** ボタンをクリック

    > ℹ️ Streamlit Cloud経由でFlask APIにアクセスするため、
    > ngrokドメインがブロックされるネットワークでも利用可能です。
    """)
    st.stop()

# ── スクリーンショット表示 ──
if st.session_state.screenshot_bytes:
    with st.expander("🖥️ PC画面キャプチャ", expanded=True):
        col_img, col_btn = st.columns([6, 1])
        with col_img:
            st.image(st.session_state.screenshot_bytes,
                     caption="最新のスクリーンショット",
                     use_container_width=True)
        with col_btn:
            if st.button("✕ 閉じる", key="close_screenshot"):
                st.session_state.screenshot_bytes = None
                st.rerun()
            if st.button("🔄 更新", key="refresh_screenshot"):
                with st.spinner("更新中..."):
                    img = st.session_state.client.get_screenshot()
                    if img:
                        st.session_state.screenshot_bytes = img
                        st.rerun()

# ── チャット履歴表示 ──
for msg in st.session_state.messages:
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

    with st.chat_message("assistant" if role == "assistant" else "user"):
        # テキスト部分
        if content:
            st.markdown(content)

        # ツール使用部分
        for tool in tool_blocks:
            tool_name = tool.get("name", "tool")
            tool_input = tool.get("input_str", "")
            tool_result = tool.get("result", "")
            file_path = extract_file_path(tool_input)

            with st.expander(f"🔧 {tool_name}", expanded=False):
                # ツール入力
                if tool_input:
                    formatted = parse_tool_input_display(tool_input)
                    st.code(formatted, language="json")

                # ファイルカード
                if file_path:
                    fname = get_path_basename(file_path)
                    if is_image_path(file_path):
                        st.markdown(f"📷 **{fname}**")
                        # 画像表示を試みる
                        try:
                            img_bytes, mime = st.session_state.client.get_file_bytes(file_path)
                            if img_bytes:
                                st.image(img_bytes, caption=fname, use_container_width=True)
                        except Exception:
                            st.caption(f"画像の読み込みに失敗: {file_path}")
                    else:
                        st.markdown(f"📄 **{fname}**")

                # ツール結果
                if tool_result:
                    # 長い結果は折りたたみ
                    if len(tool_result) > 500:
                        st.text_area(
                            "Result",
                            value=tool_result,
                            height=200,
                            disabled=True,
                            label_visibility="collapsed",
                        )
                    else:
                        st.code(tool_result, language=None)

        # コスト情報
        if cost_info:
            st.markdown(
                f'<div class="cost-info">{cost_info}</div>',
                unsafe_allow_html=True,
            )


# ── ストリーミング中のキャンセルボタン ──
if st.session_state.is_streaming:
    if st.button("🛑 キャンセル", type="primary", use_container_width=True):
        st.session_state.cancel_requested = True
        if st.session_state.current_job_id and st.session_state.client:
            try:
                st.session_state.client.cancel_job(st.session_state.current_job_id)
            except Exception:
                pass


# ── プロンプト入力 ──
if prompt := st.chat_input(
    "プロンプトを入力...",
    disabled=st.session_state.is_streaming,
):
    if not st.session_state.connected or not st.session_state.client:
        st.error("バックエンドに接続してください")
        st.stop()

    cwd = st.session_state.selected_dir
    if not cwd:
        st.error("作業ディレクトリを選択してください")
        st.stop()

    # ユーザーメッセージを追加
    st.session_state.messages.append({
        "role": "user",
        "content": prompt,
        "tool_blocks": [],
        "cost_info": None,
    })

    # ジョブ送信
    try:
        result = st.session_state.client.send_prompt(
            prompt=prompt,
            cwd=cwd,
            session_id=st.session_state.session_id,
            model=st.session_state.selected_model,
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

    # ─── SSEストリーミング（バックグラウンドスレッド + ポーリング）───
    event_queue = queue.Queue()
    stop_event = threading.Event()

    worker = threading.Thread(
        target=stream_worker,
        args=(st.session_state.client, job_id, event_queue, stop_event),
        daemon=True,
    )
    worker.start()

    # ストリーミング中の表示エリア
    with st.chat_message("user"):
        st.markdown(prompt)

    streaming_container = st.chat_message("assistant")
    status_placeholder = st.empty()
    text_placeholder = streaming_container.empty()
    tool_container = streaming_container.container()

    accumulated_text = ""
    accumulated_tools = []
    pending_tool = None
    cost_info = None
    all_events = []
    done = False

    while not done:
        # キャンセルチェック
        if st.session_state.cancel_requested:
            stop_event.set()
            break

        # キューからイベント取得（0.3秒タイムアウト）
        batch = []
        try:
            while True:
                ev = event_queue.get_nowait()
                batch.append(ev)
        except queue.Empty:
            pass

        if not batch:
            time.sleep(0.3)
            status_placeholder.caption("⏳ 応答待機中...")
            continue

        for ev in batch:
            if ev is None:
                done = True
                break

            all_events.append(ev)
            etype = ev.get("type", "")

            # system init
            if etype == "system" and ev.get("subtype") == "init":
                sid = ev.get("session_id")
                if sid:
                    add_session(sid)
                    st.session_state.session_id = sid

            # stream_event
            elif etype == "stream_event":
                inner = ev.get("event", {})
                inner_type = inner.get("type", "")

                if inner_type == "content_block_start":
                    cb = inner.get("content_block", {})
                    if cb.get("type") == "text":
                        pass
                    elif cb.get("type") == "tool_use":
                        if pending_tool:
                            accumulated_tools.append(pending_tool)
                        pending_tool = {
                            "name": cb.get("name", "tool"),
                            "id": cb.get("id", ""),
                            "input_str": "",
                            "result": "",
                        }
                        status_placeholder.caption(f"🔧 {cb.get('name', 'tool')}...")

                elif inner_type == "content_block_delta":
                    delta = inner.get("delta", {})
                    if delta.get("type") == "text_delta":
                        accumulated_text += delta.get("text", "")
                        text_placeholder.markdown(accumulated_text + " ▌")
                        status_placeholder.empty()
                    elif delta.get("type") == "input_json_delta":
                        if pending_tool:
                            pending_tool["input_str"] += delta.get("partial_json", "")

            # assistant (完成メッセージ)
            elif etype == "assistant":
                msg = ev.get("message", {})
                for block in msg.get("content", []):
                    if block.get("type") == "text":
                        accumulated_text = block.get("text", "")
                        text_placeholder.markdown(accumulated_text)

            # user = tool_result
            elif etype == "user":
                msg = ev.get("message", {})
                for block in msg.get("content", []):
                    if block.get("type") == "tool_result":
                        content = block.get("content", "")
                        if isinstance(content, list):
                            content = "\n".join(
                                item.get("text", "")
                                for item in content
                                if isinstance(item, dict)
                            )
                        if pending_tool:
                            pending_tool["result"] = content
                            accumulated_tools.append(pending_tool)
                            # ツール表示
                            with tool_container.expander(
                                f"🔧 {pending_tool['name']}", expanded=False
                            ):
                                if pending_tool["input_str"]:
                                    st.code(
                                        parse_tool_input_display(pending_tool["input_str"]),
                                        language="json",
                                    )
                                fp = extract_file_path(pending_tool["input_str"])
                                if fp:
                                    fname = get_path_basename(fp)
                                    if is_image_path(fp):
                                        st.markdown(f"📷 **{fname}**")
                                        try:
                                            img_bytes, mime = st.session_state.client.get_file_bytes(fp)
                                            if img_bytes:
                                                st.image(img_bytes, caption=fname, use_container_width=True)
                                        except Exception:
                                            pass
                                    else:
                                        st.markdown(f"📄 **{fname}**")
                                if content:
                                    if len(content) > 500:
                                        st.text_area(
                                            "r", value=content, height=150,
                                            disabled=True, label_visibility="collapsed",
                                        )
                                    else:
                                        st.code(content, language=None)
                            pending_tool = None

            # result (コスト)
            elif etype == "result":
                sid = ev.get("session_id")
                if sid:
                    add_session(sid)
                    st.session_state.session_id = sid
                cost = ev.get("cost_usd")
                usage = ev.get("usage", {})
                parts = []
                if cost is not None:
                    parts.append(f"${cost:.4f}")
                if usage.get("input_tokens"):
                    parts.append(f"in:{usage['input_tokens']}")
                if usage.get("output_tokens"):
                    parts.append(f"out:{usage['output_tokens']}")
                if parts:
                    cost_info = " | ".join(parts)

            # error / stderr
            elif etype in ("error", "stderr"):
                text = ev.get("text", "")
                if text:
                    streaming_container.markdown(
                        f'<div class="error-msg">⚠️ {text}</div>',
                        unsafe_allow_html=True,
                    )

            # done
            elif etype == "done":
                done = True
                break

    # ストリーミング完了後の処理
    status_placeholder.empty()
    text_placeholder.markdown(accumulated_text)  # カーソル除去

    # pending_toolを片付ける
    if pending_tool:
        accumulated_tools.append(pending_tool)

    # コスト表示
    if cost_info:
        streaming_container.markdown(
            f'<div class="cost-info">{cost_info}</div>',
            unsafe_allow_html=True,
        )

    # メッセージ履歴に追加
    st.session_state.messages.append({
        "role": "assistant",
        "content": accumulated_text,
        "tool_blocks": accumulated_tools,
        "cost_info": cost_info,
    })

    st.session_state.is_streaming = False
    st.session_state.cancel_requested = False

    # ジョブ履歴更新
    try:
        st.session_state.job_history = st.session_state.client.list_jobs()
    except Exception:
        pass

    st.rerun()
