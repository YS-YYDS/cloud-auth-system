import os
import subprocess
import sys

# ===================== 配置信息 =====================
# 强制定位到当前脚本所在文件夹 (CloudAuthSystem)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REMOTE_REPO = "https://github.com/YS-YYDS/cloud-auth-system.git"
BRANCH = "master"

def run_command(cmd, cwd=BASE_DIR):
    print(f">> 正在运行: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"!! 错误信息: {result.stderr}")
        return False
    print(result.stdout)
    return True

def main():
    print("=== YS CloudAuthSystem 自动同步工具 ===")
    
    # 1. 检查状态
    if not os.path.exists(os.path.join(BASE_DIR, ".git")):
        print("!! 错误: 此文件夹未初始化 Git 仓库。正在尝试关联...")
        run_command(["git", "init"])
        run_command(["git", "remote", "add", "origin", REMOTE_REPO])

    # 2. 拉取最新 (可选，防止冲突)
    # run_command(["git", "pull", "origin", BRANCH])

    # 3. 仅添加当前目录下的所有内容
    run_command(["git", "add", "."])

    # 4. 获取用户提交信息或使用默认
    commit_msg = input("请输入本次更新说明 (回车使用默认: 'Update Server Source'): ").strip()
    if not commit_msg:
        commit_msg = "Update Server Source"

    # 5. 提交
    if not run_command(["git", "commit", "-m", commit_msg]):
        print(">> 没有检测到需要更新的文件变更。")

    # 6. 推送
    print(f">> 正在将服务器代码同步至 {REMOTE_REPO}...")
    if run_command(["git", "push", "origin", BRANCH]):
        print("\n[SUCCESS] 同步完成！服务器代码已更新。")
    else:
        print("\n[FAILED] 同步失败，请检查网络连接或权限。")

    input("\n按回车键退出...")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n用户取消操作。")
        sys.exit(0)
