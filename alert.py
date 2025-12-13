import os
import platform
import subprocess
from typing import Optional


def pop_up(message: str,subTitle: Optional[str]):
    """系统原生通知（无Tkinter，跨平台，子线程可直接调用）"""
    if platform.system() == "Darwin":  # macOS
        """macOS 长久停留的系统通知（提醒样式，不自动消失）"""
        # 处理特殊字符（避免脚本报错）
        safe_message = message.replace('"', '\\"').replace('\n', '\\n')
        # 发送「提醒样式」通知
        subTitle_str = subTitle if subTitle else "正常告警"
        cmd = f'''
           osascript -e 'tell application "System Events"
               display notification "{safe_message}" with title "交易提醒" subtitle {subTitle_str} sound name "Glass"
           end tell'
           '''
        # 执行并打印调试信息
        result = subprocess.run(cmd, shell=True, stderr=subprocess.PIPE, text=True)
        if result.stderr:
            print(f"通知发送失败：{result.stderr}")

    elif platform.system() == "Windows":  # Windows
        pass
        # Windows 通知（需win10+）
        # from win10toast import ToastNotifier
        # toaster = ToastNotifier()
        # toaster.show_toast(
        #     "置顶提示",
        #     message,
        #     duration=10,  # 显示10秒
        #     threaded=True  # 非阻塞
        # )
    elif platform.system() == "Linux":  # Linux（GNOME/KDE）
        pass
        # subprocess.run(['notify-send', '置顶提示', message])


def send_beautiful_notification(message: str, subtitle: Optional[str] = None):
    """
    优化版原生通知（带图标、排版、持久提醒）
    :param title: 主标题
    :param subtitle: 副标题
    :param message: 内容（支持换行/格式化）
    """
    # 1. 特殊字符转义（支持换行、引号）
    title = "交易提醒 🚨"
    safe_title = title.replace('"', '\\"').replace('\n', '\\n')
    safe_subtitle = subtitle.replace('"', '\\"').replace('\n', '\\n') if subtitle else "正常告警"
    safe_message = message.replace('"', '\\"').replace('\n', '\\n')

    # 2. 自定义图标（可选：用本地图标文件，提升辨识度）
    # 推荐尺寸：128x128/256x256，格式：PNG/ICNS
    # icon_path = os.path.abspath("trade_icon.png")  # 替换为你的图标路径
    # icon_arg = f'icon path "{icon_path}"' if os.path.exists(icon_path) else ""

    # 3. 持久化提醒（关键：用「alert」替代普通notification，需手动关闭）
    cmd = f'''
        osascript -e '
            tell application "System Events"
                -- 弹窗式提醒（非右上角通知，需手动点OK，样式更醒目）
                -- 同时发送右上角通知（双保险）
                display notification "{safe_message}" with title "{safe_title}" subtitle "{safe_subtitle}"  sound name "Glass"
            end tell
        '
    '''

    # 执行命令
    result = subprocess.run(cmd, shell=True, stderr=subprocess.PIPE, text=True)
    if result.stderr:
        print(f"通知发送失败：{result.stderr}")


# 用法示例
if __name__ == "__main__":
    send_beautiful_notification(
        subtitle="4小时K线震荡判定",
        message="判定结果：无通道震荡行情\n价格区间：95.23 ~ 104.87\n建议：区间高抛低吸"
    )