import subprocess
from typing import Optional


def send_beautiful_notification(message: str, subtitle: Optional[str] = None):
    title = "交易提醒 🚨"
    subtitle = subtitle or "策略告警"

    safe_title = title.replace('"', '\\"').replace('\n', '\\n')
    safe_subtitle = subtitle.replace('"', '\\"').replace('\n', '\\n')
    safe_message = message.replace('"', '\\"').replace('\n', '\\n')

    cmd = f'''
        osascript -e '
            tell application "System Events"
                display notification "{safe_message}" \
                with title "{safe_title}" subtitle "{safe_subtitle}" sound name "Glass"
            end tell
        '
    '''

    try:
        subprocess.run(
            cmd,
            shell=True,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5
        )
    except Exception as e:
        print(f"❌ 通知失败: {e}")


# 用法示例
if __name__ == "__main__":
    send_beautiful_notification(
        subtitle="4小时K线震荡判定",
        message="判定结果：无通道震荡行情\n价格区间：95.23 ~ 104.87\n建议：区间高抛低吸"
    )