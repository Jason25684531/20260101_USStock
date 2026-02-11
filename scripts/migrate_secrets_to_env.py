#!/usr/bin/env python3
"""
Migrate Docker Secrets to .env file.

This script reads all files from the `.secrets/` directory and creates a `.env` file
with properly mapped environment variable names.

The mapping rules:
- alpaca_key.txt -> ALPACA_API_KEY
- alpaca_secret.txt -> ALPACA_SECRET_KEY
- db_root_password.txt -> DB_ROOT_PASSWORD
- db_password.txt -> DB_PASSWORD
- web_password.txt -> WEB_PASSWORD
- line_channel_token.txt -> LINE_CHANNEL_TOKEN
- line_channel_secret.txt -> LINE_CHANNEL_SECRET
- line_user_id.txt -> LINE_USER_ID

Author: Automation Script
Created: 2025-02-09
"""

import os
from pathlib import Path

# Define the mapping of secret filenames to environment variable names
SECRET_MAPPING = {
    "alpaca_key.txt": "ALPACA_API_KEY",
    "alpaca_secret.txt": "ALPACA_SECRET_KEY",
    "db_root_password.txt": "DB_ROOT_PASSWORD",
    "db_password.txt": "DB_PASSWORD",
    "web_password.txt": "WEB_PASSWORD",
    "line_channel_token.txt": "LINE_CHANNEL_TOKEN",
    "line_channel_secret.txt": "LINE_CHANNEL_SECRET",
    "line_user_id.txt": "LINE_USER_ID",
}


def migrate_secrets_to_env():
    """Read secrets from .secrets/ and write to .env file."""
    
    # Get project root directory
    project_root = Path(__file__).parent.parent
    secrets_dir = project_root / ".secrets"
    env_file = project_root / ".env"
    
    # Check if secrets directory exists
    if not secrets_dir.exists():
        print(f"❌ 错误：找不到 .secrets 目录在 {secrets_dir}")
        return False
    
    print(f"📂 找到 .secrets 目录：{secrets_dir}")
    
    # Read all secrets and prepare content
    env_content = []
    env_content.append("# automatically generated from .secrets/ directory")
    env_content.append("# Generated on: 2025-02-09")
    env_content.append("")
    
    # Track which secrets were found
    found_secrets = set()
    missing_secrets = set()
    
    for secret_file, env_var in SECRET_MAPPING.items():
        secret_path = secrets_dir / secret_file
        
        if secret_path.exists():
            try:
                # Read the secret value (strip whitespace)
                value = secret_path.read_text().strip()
                env_content.append(f"{env_var}={value}")
                found_secrets.add(secret_file)
                print(f"✓ 已读取：{secret_file} → {env_var}")
            except Exception as e:
                print(f"❌ 读取失败：{secret_file} - {e}")
                missing_secrets.add(secret_file)
        else:
            print(f"⚠ 跳过：找不到 {secret_file}")
            missing_secrets.add(secret_file)
    
    # Find any additional secret files that aren't in the mapping
    all_secret_files = set(f.name for f in secrets_dir.glob("*.txt") if f.is_file())
    unmapped_files = all_secret_files - found_secrets - missing_secrets
    
    if unmapped_files:
        print(f"\n⚠ 发现未映射的 secret 文件：")
        for unmapped in unmapped_files:
            print(f"  - {unmapped}")
    
    # Write .env file
    env_content.append("")
    
    try:
        env_file.write_text("\n".join(env_content))
        print(f"\n✅ .env 文件已生成：{env_file}")
        print(f"   包含 {len(found_secrets)} 个 secret 变量")
        
        # Set appropriate permissions (readable only by owner)
        os.chmod(env_file, 0o600)
        print(f"✅ .env 文件权限已设置为 600 (安全)")
        
        return True
    except Exception as e:
        print(f"❌ 写入 .env 文件失败：{e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Docker Secrets → .env 文件迁移工具")
    print("=" * 60)
    print()
    
    success = migrate_secrets_to_env()
    
    print()
    print("=" * 60)
    if success:
        print("✅ 迁移完成！")
        print("下一步：运行 docker-compose up")
    else:
        print("❌ 迁移失败。请检查上述错误信息。")
    print("=" * 60)
