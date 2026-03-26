
import os

def patch_binary(file_path, start_line, end_line, replacement_text):
    try:
        with open(file_path, 'rb') as f:
            lines = f.readlines()
        
        # Determine encoding to use for replacement_text
        # Since the file failed UTF-8 but seems to contain Chinese, it's likely GBK (cp936)
        # However, it might be a mix. Let's try to detect based on what we saw.
        # Most of our replacement is ASCII except prefix.
        
        # Let's try writing the replacement in UTF-8. If the rest of the file is UTF-8, it's fine.
        # If the file is GBK, mixing UTF-8 might cause issues later, but at least the syntax will be valid.
        try:
            replacement_bytes = replacement_text.encode('utf-8')
        except:
            replacement_bytes = replacement_text.encode('gbk', errors='replace')
            
        new_lines_bytes = lines[:start_line-1] + [replacement_bytes] + lines[end_line:]
        
        # Backup
        os.rename(file_path, file_path + ".bak")
        
        with open(file_path, 'wb') as f:
            f.writelines(new_lines_bytes)
            
        print(f"Successfully patched {file_path}. Original saved as .bak")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    replacement = """        if "dpapi" in d_lower:
            return (
                f"❌ 浏览器 Cookie 解密失败 (DPAPI Error)。\\n"
                f"原因：{browser_name} (新版基于 Chromium 127+) 引入了增强加密，外部程序已无法直接解密 Cookie。\\n\\n"
                f"💡 解决方法：\\n"
                f"1. **使用 Firefox**：Firefox 暂不受此限制影响，请在 Firefox 中登录 YouTube 后，在设置中将浏览器改为 firefox (或 auto)。\\n"
                f"2. **手动导出 Cookie**：安装浏览器插件（如 'Get cookies.txt LOCALLY'）导出 cookies.txt，并在设置中提供文件路径。\\n\\n"
                f"原始细节: {details}"
            )
            
        # 2. 针对数据库锁定/无法复制 (常见于浏览器未彻底关闭)
        if any(x in d_lower for x in ["locked", "another process", "could not copy", "32"]):
             return (
                f"❌ 浏览器 Cookie 数据库被锁定或无法访问。\\n"
                f"原因：{browser_name} 正在运行或其数据库文件被占用。\\n\\n"
                f"💡 解决方法：\\n"
                f"1. **彻底关闭浏览器**：请确保所有 {browser_name} 窗口已关闭（包括后台进程），然后重试。\\n"
                f"2. **使用 Firefox 或导出 Cookie**：参考上述方案。\\n\\n"
                f"原始细节: {details}"
            )
        
        return f"❌ 无法从 {browser_name} 获取 Cookie。\\n细节: {details}"

    @staticmethod
    def get_sources(cookies_file: str, cookies_from_browser: str, force_browser_cookie: bool = False) -> list[tuple[str, str]]:
"""
    # Note: added \\n for the newlines in f-strings to escape properly in python string
    patch_binary(r"d:\Program Files\Trae\YouTubeSummarizer\core_logic.py", 243, 256, replacement)
