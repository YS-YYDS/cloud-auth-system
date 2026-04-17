import os
import subprocess
import re
import json
import sys
from datetime import datetime

REPO_DIR = r"j:\reaper pro\CloudAuthSystem"
REMOTE_NAME = "origin"

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def run_git(args):
    """封装 Git 命令调用，处理 Windows 下的编码问题"""
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

def get_version_from_file(file_path):
    """从 main.py 头部解析版本号"""
    if not os.path.exists(file_path):
        return "1.0.0"
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read(4096)
            version = re.search(r"VERSION\s*=\s*[\"']([\d\.]+)[\"']", content)
            if version:
                return version.group(1)
            version = re.search(r"@version\s+([\d\.\-]+)", content)
            return version.group(1) if version else "1.0.0"
    except:
        return "1.0.0"

def get_last_commit_version():
    """获取最新一次 commit 的版本号"""
    ok, msg = run_git(["log", "-1", "--pretty=%s"])
    if ok:
        match = re.search(r"V([\d\.]+)", msg)
        if match:
            return match.group(1)
    return None

def check_remote_available():
    """检查远程仓库是否可访问"""
    ok, _ = run_git(["ls-remote", "--heads", REMOTE_NAME, "master"])
    return ok

def publish():
    print("=" * 50)
    print("🚀 CloudAuthSystem 一键发布系统启动...")
    print(f"📁 仓库路径: {REPO_DIR}")
    print(f"⏰ 执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    os.chdir(REPO_DIR)

    ok, status = run_git(["status", "--porcelain"])
    if not ok:
        print(f"❌ Git 状态检查失败: {status}")
        return

    git_status = status.strip()
    is_dirty = git_status != ""

    current_ver = get_version_from_file(os.path.join(REPO_DIR, "main.py"))
    last_ver = get_last_commit_version()
    is_silent = is_dirty and current_ver == last_ver

    if not is_dirty:
        print("\n✅ 代码未变动，无需发布。")
        if check_remote_available():
            print("📡 远程仓库连接正常。")
        return

    print(f"\n🔍 检测到变更:")
    for line in git_status.split("\n"):
        if line:
            status_code = line[:2]
            file_path = line[3:].strip()
            if status_code.strip():
                print(f"   {status_code} {file_path}")

    if is_silent:
        print(f"\n✨ 检测到静默更新 (版本号未变: V{current_ver})")
        commit_msg = f"fix: Silent update V{current_ver}"
    else:
        print(f"\n🚀 检测到新版本 V{current_ver}，准备发布...")
        commit_msg = f"release: V{current_ver}"

    print("\n📦 正在提交代码...")
    run_git(["add", "-A"])
    ok, out = run_git(["commit", "-m", commit_msg])
    if not ok:
        print(f"❌ 提交失败: {out}")
        return
    print(f"✅ 提交成功: {commit_msg}")

    print(f"\n📤 正在推送至 GitHub ({REMOTE_NAME}/master)...")
    ok, out = run_git(["push", REMOTE_NAME, "master"])
    if not ok:
        print(f"❌ 推送失败: {out}")
        print("\n⚠️  可能的原因:")
        print("   1. 网络连接问题")
        print("   2. GitHub 认证失败 (需要 Personal Access Token)")
        print("   3. 远程仓库不存在或无推送权限")
        return

    print("✅ GitHub 推送成功!")
    print("\n" + "=" * 50)
    print("✅ CloudAuthSystem 发布完毕!")
    print(f"   提交: {commit_msg}")
    print(f"   仓库: https://github.com/YS-YYDS/cloud-auth-system")
    print("=" * 50)

if __name__ == "__main__":
    publish()
