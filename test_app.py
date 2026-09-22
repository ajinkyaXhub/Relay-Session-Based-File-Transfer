import unittest
import os
import io
import time
import json
import zipfile
from unittest.mock import patch
from app import app, SessionManager, JOIN_ATTEMPTS, JOIN_RATE_LIMIT, check_join_rate_limit, JOIN_CODE_CHARS

class RelayAppTestCase(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()
        # Clear sessions and rate limits before each test
        SessionManager.cleanup_all()
        JOIN_ATTEMPTS.clear()

    def tearDown(self):
        SessionManager.cleanup_all()
        JOIN_ATTEMPTS.clear()

    def test_healthz(self):
        """Verify /healthz returns 200 OK and active sessions count."""
        res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["active_sessions"], 0)

        # Create a session and check count updates
        SessionManager.create_session()
        res = self.client.get("/healthz")
        data = res.get_json()
        self.assertEqual(data["active_sessions"], 1)

    def test_landing_page(self):
        """Verify GET / renders landing page with Start Transfer and Join forms."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        content = res.get_data(as_text=True)
        self.assertIn("Instant File Transfer with Total Isolation", content)
        self.assertIn('href="/new"', content)
        self.assertIn('id="joinCodeInput"', content)

    def test_create_new_transfer(self):
        """Verify GET /new creates an isolated session and redirects to /s/<session_id>."""
        res = self.client.get("/new", follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.headers["Location"].startswith("/s/"))

        session_id = res.headers["Location"].split("/s/")[1]
        session = SessionManager.get_session(session_id)
        self.assertIsNotNone(session)
        self.assertTrue(os.path.isdir(session["folder"]))
        self.assertIsNotNone(session.get("short_code"))
        # Code should be formatted as XXX-XXX
        self.assertRegex(session["short_code"], r"^[2-9A-HJ-KM-NP-Z]{3}-[2-9A-HJ-KM-NP-Z]{3}$")

    def test_short_code_uniqueness(self):
        """Assert no two active sessions share a short_code."""
        seen_codes = set()
        sessions = []
        for _ in range(50):
            s = SessionManager.create_session()
            sessions.append(s)
            self.assertNotIn(s["short_code"], seen_codes)
            seen_codes.add(s["short_code"])
        self.assertEqual(len(seen_codes), 50)

    def test_join_valid_active_code(self):
        """POST /join with a valid, active code redirects 302 to /s/<session_id>."""
        session = SessionManager.create_session()
        code = session["short_code"]

        # Test with formatted code (XXX-XXX)
        res = self.client.post("/join", data={"code": code}, follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.headers["Location"], f"/s/{session['id']}")

        # Test case-insensitivity and no dash (xxx-xxx -> xxxxxx)
        lower_no_dash = code.replace("-", "").lower()
        res = self.client.post("/join", data={"code": lower_no_dash}, follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.headers["Location"], f"/s/{session['id']}")

        # Test JSON body
        res = self.client.post("/join", json={"code": code})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("redirect"), f"/s/{session['id']}")

    def test_join_nonexistent_code(self):
        """POST /join with a nonexistent code re-renders landing page with inline error."""
        res = self.client.post("/join", data={"code": "999-999"})
        self.assertEqual(res.status_code, 400)
        content = res.get_data(as_text=True)
        self.assertIn("No active session with that code", content)

        # Test JSON response
        res = self.client.post("/join", json={"code": "888-888"})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertIn("No active session with that code", data.get("error", ""))

    def test_join_expired_or_ended_code(self):
        """POST /join with expired/ended code returns identical error without leaking state."""
        session = SessionManager.create_session()
        code = session["short_code"]
        sid = session["id"]

        # End the session
        SessionManager.terminate_session(sid)

        # Joining with that code should produce identical error to nonexistent code
        res = self.client.post("/join", data={"code": code})
        self.assertEqual(res.status_code, 400)
        content = res.get_data(as_text=True)
        self.assertIn("No active session with that code — check for typos, or ask the sender for a new one.", content)

    def test_join_rate_limiting(self):
        """Exceeding 10 join attempts in a minute throttles subsequent attempts (HTTP 429)."""
        ip = "192.168.1.100"
        headers = {"X-Forwarded-For": ip}

        for attempt in range(10):
            res = self.client.post("/join", data={"code": "BAD-COD"}, headers=headers)
            self.assertEqual(res.status_code, 400)

        # 11th attempt should be rate limited
        res = self.client.post("/join", data={"code": "BAD-COD"}, headers=headers)
        self.assertEqual(res.status_code, 429)
        content = res.get_data(as_text=True)
        self.assertIn("Too many join attempts", content)

        # JSON response should also return 429
        res = self.client.post("/join", json={"code": "BAD-COD"}, headers=headers)
        self.assertEqual(res.status_code, 429)
        data = res.get_json()
        self.assertIn("Too many join attempts", data.get("error", ""))

    def test_session_termination_cleans_up_index_and_disk(self):
        """Ending a session removes its folder from disk and cleans CODE_TO_SESSION."""
        session = SessionManager.create_session()
        folder = session["folder"]
        code_raw = session["short_code_raw"]
        sid = session["id"]

        self.assertTrue(os.path.isdir(folder))
        self.assertIn(code_raw, SessionManager._code_to_session)

        # Terminate
        SessionManager.terminate_session(sid)

        self.assertFalse(os.path.exists(folder))
        self.assertNotIn(code_raw, SessionManager._code_to_session)
        self.assertNotIn(sid, SessionManager._sessions)

    def test_upload_and_download(self):
        """Test uploading a file to an isolated session and downloading it."""
        session = SessionManager.create_session()
        sid = session["id"]
        csrf = session["csrf_token"]

        test_data = b"Hello, Relay session isolation!"
        res = self.client.post(
            f"/s/{sid}/upload",
            data={
                "csrf_token": csrf,
                "file": (io.BytesIO(test_data), "test_doc.txt")
            },
            content_type="multipart/form-data"
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(len(data["files"]), 1)

        file_id = data["files"][0]["id"]
        self.assertEqual(data["files"][0]["display_name"], "test_doc.txt")

        # Verify download
        down_res = self.client.get(f"/s/{sid}/download/{file_id}")
        self.assertEqual(down_res.status_code, 200)
        self.assertEqual(down_res.data, test_data)

    def test_download_all_zip(self):
        """Test /download-all generates a valid zip archive in-memory without polluting session folder."""
        session = SessionManager.create_session()
        sid = session["id"]
        csrf = session["csrf_token"]

        # Upload two files
        self.client.post(
            f"/s/{sid}/upload",
            data={"csrf_token": csrf, "file": (io.BytesIO(b"File 1 content"), "file1.txt")},
            content_type="multipart/form-data"
        )
        self.client.post(
            f"/s/{sid}/upload",
            data={"csrf_token": csrf, "file": (io.BytesIO(b"File 2 content"), "file2.txt")},
            content_type="multipart/form-data"
        )

        res = self.client.get(f"/s/{sid}/download-all")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, "application/zip")

        # Verify zip contents
        zip_buf = io.BytesIO(res.data)
        with zipfile.ZipFile(zip_buf, "r") as zf:
            names = zf.namelist()
            self.assertIn("file1.txt", names)
            self.assertIn("file2.txt", names)

        # Confirm zip was not written to the session directory
        session_folder_files = os.listdir(session["folder"])
        for f in session_folder_files:
            self.assertFalse(f.endswith(".zip"))

    def test_path_traversal_defense(self):
        """Path traversal attacks on download should be blocked (404/400)."""
        session = SessionManager.create_session()
        sid = session["id"]

        # Non-existent or traversal file_id
        res = self.client.get(f"/s/{sid}/download/../../etc/passwd")
        self.assertEqual(res.status_code, 404)

    def test_sweeper_prunes_expired_sessions(self):
        """SessionManager.sweep_expired deletes sessions past their expires_at."""
        session = SessionManager.create_session()
        folder = session["folder"]
        code_raw = session["short_code_raw"]
        sid = session["id"]

        self.assertTrue(os.path.exists(folder))

        # Fast-forward expiry
        session["expires_at"] = time.time() - 10

        SessionManager.sweep_expired()

        self.assertFalse(os.path.exists(folder))
        self.assertNotIn(sid, SessionManager._sessions)
        self.assertNotIn(code_raw, SessionManager._code_to_session)

if __name__ == "__main__":
    unittest.main()
