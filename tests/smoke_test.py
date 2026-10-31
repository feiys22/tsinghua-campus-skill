"""smoke_test.py — 底座冒烟测试

一键跑通: 平台检测 → 环境检查 → creds status → vault 加密往返 → session 读写 → login --check
用于开发回归与交付验收。输出汇总 JSON。

用法:
  python smoke_test.py              # 全部检查
  python smoke_test.py --quick      # 只跑不依赖浏览器/凭据的部分
"""
import sys
import os
import json
import tempfile
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "campus", "shared", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "campus", "creds", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "campus", "base-cas", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "campus", "install", "scripts"))
import common
import vault
import session
import creds
import browser


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="跳过浏览器相关")
    args = ap.parse_args()

    results = {}
    ok_all = True

    # 1. 平台
    p = common.detect_platform()
    results["platform"] = p
    common.log(f"[smoke] platform={p}")

    # 2. vault 加解密往返（单文件保险箱，用临时文件避免污染真实凭据）
    try:
        tmpvault = os.path.join(tempfile.gettempdir(), "campus_smoke_vault.enc")
        tmplegacy = os.path.join(tempfile.gettempdir(), "campus_smoke_legacy.json")
        for f in (tmpvault, tmplegacy):
            try:
                os.remove(f)
            except Exception:
                pass
        _ov, _ol = vault.VAULT_FILE, vault.LEGACY_FILE
        vault.VAULT_FILE, vault.LEGACY_FILE = tmpvault, tmplegacy
        try:
            probes = {"k1": "甲", "k2": "乙"}
            vault.vault_write(probes)
            got = vault.vault_read()
            ok = all(got.get(k) == v for k, v in probes.items())
            vault.vault_set("k1", "AAA")
            vault.vault_set("k2", "BBB")
            ok &= (vault.vault_get("k1") == "AAA" and vault.vault_get("k2") == "BBB")
        finally:
            vault.VAULT_FILE, vault.LEGACY_FILE = _ov, _ol
            for f in (tmpvault, tmplegacy):
                try:
                    os.remove(f)
                except Exception:
                    pass
        results["vault"] = {"ok": ok, "master_key_source": vault.master_key_source(),
                            "keyring_ok": vault._keyring_ok()}
        ok_all &= ok
    except Exception as e:
        results["vault"] = {"ok": False, "error": str(e)[:150]}
        ok_all = False

    # 3. session 读写
    try:
        tmp = "smoke_test"
        session.save_session(tmp, {"jsession": "t", "csrf": "t", "url": "x"})
        ok = session.session_valid(tmp)
        session.clear_session(tmp)
        results["session"] = {"ok": ok}
        ok_all &= ok
    except Exception as e:
        results["session"] = {"ok": False, "error": str(e)[:150]}
        ok_all = False

    # 4. creds schema 完整性
    try:
        known = set(creds.CRED_SCHEMA.keys())
        results["creds_schema"] = {"ok": len(known) > 0, "count": len(known)}
        ok_all &= len(known) > 0
    except Exception as e:
        results["creds_schema"] = {"ok": False, "error": str(e)[:150]}
        ok_all = False

    # 5. 浏览器就绪（quick 模式跳过）
    if not args.quick:
        try:
            r = browser.ensure_ready()
            results["browser"] = {"ok": r.get("ok", False), "missing": r.get("missing")}
            if not r.get("ok", False):
                ok_all = False
        except Exception as e:
            results["browser"] = {"ok": False, "error": str(e)[:150]}
            ok_all = False


    # 6. wechat 子技能（合成库，不碰真实微信数据）
    try:
        import subprocess
        from pathlib import Path as _P
        tmp_home = _P(tempfile.mkdtemp(prefix="campus_wechat_smoke_"))
        env = os.environ.copy()
        env["CAMPUS_WECHAT_HOME"] = str(tmp_home)
        env["CAMPUS_WECHAT_BACKEND"] = "index"
        wechat_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "campus", "wechat", "scripts", "wechat.py")
        build_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "wechat", "build_fake_index.py")
        # setup ack
        r1 = subprocess.run([sys.executable, wechat_py, "setup", "--ack", "--note", "smoke"], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=30)
        # build fake index into home
        index_db = tmp_home / "index.db"
        r_build = subprocess.run([sys.executable, build_py, "--out", str(index_db)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        r2 = subprocess.run([sys.executable, wechat_py, "sessions", "--backend", "index", "-n", "10"], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=30)
        r3 = subprocess.run([sys.executable, wechat_py, "search", "--backend", "index", "--query", "作业", "-n", "10"], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=30)
        r4 = subprocess.run([sys.executable, wechat_py, "export-todos", "--backend", "index", "-n", "10"], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=30)
        def _j(r):
            try:
                return json.loads(r.stdout or "{}")
            except Exception:
                return {"status": "error", "raw": (r.stdout or "")[:200], "stderr_len": len(r.stderr or "")}
        j1, j2, j3, j4 = _j(r1), _j(r2), _j(r3), _j(r4)
        ok = (
            r_build.returncode == 0
            and j1.get("status") == "ok"
            and j2.get("status") == "ok"
            and j2.get("count", 0) >= 1
            and j3.get("status") == "ok"
            and j3.get("count", 0) >= 1
            and j4.get("status") == "ok"
            and j4.get("count", 0) >= 1
            and (r2.stderr or "") == ""
            and (r3.stderr or "") == ""
        )
        results["wechat"] = {
            "ok": ok,
            "setup": j1.get("status"),
            "sessions": j2.get("count"),
            "search_hits": j3.get("count"),
            "todos": j4.get("count"),
            "backend_forced": "index",
            "build_ok": r_build.returncode == 0,
        }
        ok_all &= ok
        # cleanup best-effort
        try:
            import shutil
            shutil.rmtree(tmp_home, ignore_errors=True)
        except Exception:
            pass
    except Exception as e:
        results["wechat"] = {"ok": False, "error": str(e)[:150]}
        ok_all = False


    results["status"] = "ok" if ok_all else "error"
    common.output_json(results)
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
