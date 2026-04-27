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
        return False, (e.stderr or "") + (e.stdout or "")

def publish():
    print("CloudAuthSystem 同步上传中...")

    os.chdir(REPO_DIR)

    # 检测当前分支
    ok, branch_out = run_git(["branch", "--show-current"])
    local_branch = branch_out.strip() if ok else "master"
    print(f"当前分支: {local_branch}")

    run_git(["add", "-A"])
    ok, out = run_git(["commit", "-m", "Update"])
    if not ok:
        if "nothing to commit" in out.lower() or "nothing added to commit" in out.lower():
            print("无新改动，跳过提交。")
        else:
            print(f"提交失败: {out}")
            return

    print("正在推送至 GitHub (main)...")
    ok, out = run_git(["push", REMOTE_NAME, f"{local_branch}:main"])
    if not ok:
        print(f"推送失败: {out}")
        if "unrelated histories" in out.lower() or "refusing to merge unrelated histories" in out.lower():
            print("\n提示: 本地和远程历史不相关，需要手动处理。")
            print(f"请运行: git push {REMOTE_NAME} {local_branch}:main --force")
        return

    print("同步完成!")

if __name__ == "__main__":
    publish()
