import os
import subprocess
import sys

REPO_DIR = r"j:\reaper pro\CloudAuthSystem"
REMOTE_NAME = "origin"

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def run_git(args):
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=REPO_DIR,
            capture_output=True,
            encoding="utf-8",
            errors="ignore",
            check=True
        )
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr

def publish():
    print("CloudAuthSystem 同步上传中...")

    os.chdir(REPO_DIR)

    run_git(["add", "-A"])
    ok, out = run_git(["commit", "-m", "Update"])
    if not ok and "nothing to commit" not in out.lower():
        print(f"提交失败: {out}")
        return

    print("正在推送至 GitHub...")
    ok, out = run_git(["push", REMOTE_NAME, "master"])
    if not ok:
        print(f"推送失败: {out}")
        return

    print("同步完成!")

if __name__ == "__main__":
    publish()
