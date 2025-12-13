import platform
import subprocess


def pop_up(message: str):
    """系统原生通知（无Tkinter，跨平台，子线程可直接调用）"""
    if platform.system() == "Darwin":  # macOS
        """macOS 长久停留的系统通知（提醒样式，不自动消失）"""
        # 处理特殊字符（避免脚本报错）
        safe_message = message.replace('"', '\\"').replace('\n', '\\n')
        # 发送「提醒样式」通知（长久停留）
        cmd = f'''
           osascript -e 'tell application "System Events"
               display notification "{safe_message}" with title "交易提醒" subtitle "异常合约警告" sound name "Glass"
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

