"""Flask バックエンド API クライアント

Streamlit Cloud → ngrok → Flask への全APIリクエストをラップする。
requests.Session でCookie認証を自動管理。
"""

import json
import re
import requests


class BackendClient:
    """Flask API プロキシクライアント"""

    def __init__(self, ngrok_url: str):
        self.base_url = ngrok_url.rstrip("/")
        self.session = requests.Session()
        # ngrok free tier の警告ページをバイパス
        self.session.headers.update({
            "ngrok-skip-browser-warning": "true",
            "User-Agent": "StreamlitProxy/1.0",
        })
        self.csrf_token = None
        self.connected = False

    def login(self, auth_token: str) -> tuple[bool, str]:
        """ログイン → Cookie取得 → CSRFトークン取得

        Returns:
            (success: bool, message: str)
        """
        try:
            # Step 1: ログイン（Cookie取得）
            resp = self.session.post(
                f"{self.base_url}/login",
                json={"token": auth_token},
                timeout=10,
            )
            if resp.status_code == 429:
                return False, "レート制限中です。しばらく待ってください。"
            if resp.status_code != 200:
                return False, "認証に失敗しました。トークンを確認してください。"

            # Step 2: CSRFトークン取得（HTMLから抽出）
            index_resp = self.session.get(f"{self.base_url}/", timeout=10)
            match = re.search(r'const CSRF_TOKEN = "([^"]+)"', index_resp.text)
            if match:
                self.csrf_token = match.group(1)
            else:
                return False, "CSRFトークンの取得に失敗しました。"

            self.connected = True
            return True, "接続成功"

        except requests.exceptions.ConnectionError:
            return False, "接続できません。ngrok URLを確認してください。"
        except requests.exceptions.Timeout:
            return False, "接続がタイムアウトしました。"
        except Exception as e:
            return False, f"エラー: {str(e)}"

    def _headers(self) -> dict:
        """POST/DELETE用ヘッダー（CSRF付き）"""
        h = {"Content-Type": "application/json"}
        if self.csrf_token:
            h["X-CSRF-Token"] = self.csrf_token
        return h

    # --- ディレクトリ ---

    def get_directories(self) -> dict:
        """許可ディレクトリ一覧を取得"""
        resp = self.session.get(
            f"{self.base_url}/api/directories", timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    # --- プロンプト / ジョブ ---

    def send_prompt(self, prompt: str, cwd: str, session_id: str = None) -> dict:
        """プロンプトを送信してジョブを作成"""
        payload = {"prompt": prompt, "cwd": cwd}
        if session_id:
            payload["session_id"] = session_id
        resp = self.session.post(
            f"{self.base_url}/api/prompt",
            json=payload,
            headers=self._headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def stream_job(self, job_id: str):
        """SSEストリームからイベントをyieldするジェネレータ"""
        resp = self.session.get(
            f"{self.base_url}/api/jobs/{job_id}/stream",
            stream=True,
            timeout=(5, None),  # 接続5秒、読み取り無制限
        )
        resp.raise_for_status()
        for line in resp.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                try:
                    yield json.loads(line[6:])
                except json.JSONDecodeError:
                    continue

    def get_job(self, job_id: str, offset: int = 0) -> dict:
        """ジョブ詳細を取得（offsetでイベント差分取得可能）"""
        resp = self.session.get(
            f"{self.base_url}/api/jobs/{job_id}",
            params={"offset": offset},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def list_jobs(self) -> list:
        """ジョブ一覧を取得（最新10件）"""
        resp = self.session.get(
            f"{self.base_url}/api/jobs", timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    def cancel_job(self, job_id: str) -> dict:
        """実行中のジョブをキャンセル"""
        resp = self.session.post(
            f"{self.base_url}/api/cancel",
            json={"job_id": job_id},
            headers=self._headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    # --- ファイル ---

    def get_file(self, path: str) -> requests.Response:
        """ファイルを取得（画像・テキスト）"""
        return self.session.get(
            f"{self.base_url}/api/files",
            params={"path": path},
            timeout=30,
        )

    def get_file_bytes(self, path: str) -> tuple[bytes, str]:
        """ファイルのバイトデータとMIMEタイプを取得"""
        resp = self.get_file(path)
        if resp.status_code != 200:
            return None, None
        mime = resp.headers.get("Content-Type", "application/octet-stream")
        return resp.content, mime
