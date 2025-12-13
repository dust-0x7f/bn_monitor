import threading
import tkinter as tk
from tkinter import ttk


def pop_up(message: str):
    """非阻塞的置顶提示弹窗（子线程运行）"""
    root = tk.Tk()
    root.title("置顶提示")

    # 窗口置顶（跨平台兼容）
    root.attributes('-topmost', True)

    # 居中显示
    window_width = 400
    window_height = 180
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width - window_width) // 2
    y = (screen_height - window_height) // 2
    root.geometry(f"{window_width}x{window_height}+{x}+{y}")

    # 禁止调整大小
    root.resizable(False, False)
    root.configure(bg='#f0f0f0')

    # 添加文本标签
    label = ttk.Label(
        root,
        text=message,
        wraplength=380,
        font=("Arial", 14),
        background='#f0f0f0'
    )
    label.pack(expand=True, padx=20, pady=20)

    # 关键：子线程内运行主循环，关闭时销毁窗口
    root.mainloop()



