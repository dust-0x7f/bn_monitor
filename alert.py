import tkinter as tk
from tkinter import ttk


def show_topmost_popup(message: str):
    # 创建主窗口
    root = tk.Tk()
    root.title("置顶提示")

    # 关键：设置窗口置顶（macOS 兼容）
    root.attributes('-topmost', True)

    # 设置窗口大小和位置（居中显示）
    window_width = 400
    window_height = 180
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width - window_width) // 2
    y = (screen_height - window_height) // 2
    root.geometry(f"{window_width}x{window_height}+{x}+{y}")

    # 禁止调整窗口大小
    root.resizable(False, False)

    # 设置窗口样式（可选，增强美观度）
    root.configure(bg='#f0f0f0')

    # 添加文本内容（自动换行）
    label = ttk.Label(
        root,
        text=message,
        wraplength=380,  # 文本换行宽度
        font=("Arial", 14),
        background='#f0f0f0'
    )
    label.pack(expand=True, padx=20, pady=20)



    # 启动主循环
    root.mainloop()


