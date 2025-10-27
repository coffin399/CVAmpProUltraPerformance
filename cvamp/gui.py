import datetime
import logging
import os
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

import psutil
import toml

from . import utils
from .manager import InstanceManager
from .utils import InstanceCommands

logger = logging.getLogger(__name__)


def open_multiple_urls(*urls):
    """Open multiple URLs in order with small delays"""
    for url in urls:
        webbrowser.open(url, new=2)
        time.sleep(0.1)

system_default_color = None


class PerformanceMonitor:
    def __init__(self):
        self.last_network_stats = None
        self.current_network_speed_mbps = 0.0
        self.current_network_speed_mb_s = 0.0
        
    def update_network_speed(self):
        """Calculate network speed in Mbps and MB/s"""
        try:
            net_io = psutil.net_io_counters()
            current_bytes_sent = net_io.bytes_sent
            current_bytes_recv = net_io.bytes_recv
            current_total = current_bytes_sent + current_bytes_recv
            
            if self.last_network_stats:
                elapsed = 1.0  # Assume 1 second between calls
                delta_total = current_total - self.last_network_stats["total"]
                
                # Convert to bits per second (multiply by 8), then to Mbps
                self.current_network_speed_mbps = (delta_total * 8) / 1_000_000 / elapsed
                # Convert to MB/s (divide by 1,000,000)
                self.current_network_speed_mb_s = delta_total / 1_000_000 / elapsed
            else:
                self.current_network_speed_mbps = 0.0
                self.current_network_speed_mb_s = 0.0
            
            self.last_network_stats = {
                "sent": current_bytes_sent,
                "recv": current_bytes_recv,
                "total": current_total
            }
        except Exception as e:
            logger.exception(e)
            self.current_network_speed_mbps = 0.0
            self.current_network_speed_mb_s = 0.0


class GUI:
    def __init__(self, manager: InstanceManager):
        self.manager = manager
        self.instances_boxes = []
        self.performance_monitor = PerformanceMonitor()

        self.root = tk.Tk()
        self.root.configure(bg="#1e1e1e")
        
        self.menu = tk.Menu(self.root)

        self.instances_overview = dict()

        # Modern color scheme
        self.bg_color = "#1e1e1e"
        self.card_color = "#2d2d2d"
        self.accent_color = "#0078d4"
        self.text_color = "#ffffff"
        self.subtext_color = "#a0a0a0"

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=self.bg_color, borderwidth=0)
        style.configure("TNotebook.Tab", padding=[20, 10], background=self.card_color, foreground=self.text_color)
        style.map("TNotebook.Tab", background=[("selected", self.accent_color)])
        style.configure("TFrame", background=self.bg_color)
        style.configure("TLabel", background=self.bg_color, foreground=self.text_color)
        style.configure("TCheckbutton", background=self.bg_color, foreground=self.text_color)

        # Initialize tabs
        self.notebook = ttk.Notebook(self.root, height=200, width=800)

        self.tab_main = TabMain(self.notebook, self.manager, self.bg_color, self.card_color, self.accent_color, self.text_color, self.subtext_color)
        self.notebook.add(self.tab_main, text="Main Controls")

        self.tab_chat = TabChat(self.notebook, self.manager, self.bg_color, self.card_color, self.accent_color, self.text_color, self.subtext_color)
        self.notebook.add(self.tab_chat, text="Chatting")

        self.tab_about = TabAbout(self.notebook, self.bg_color, self.text_color)
        self.notebook.add(self.tab_about, text="About")

        self.notebook.place(x=0, y=0)
        self.notebook.select(self.tab_main)

        # path to use, when the tool is not package with pyinstaller -onefile
        non_pyinstaller_path = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))

        # Pyinstaller fix to find added binaries in extracted project folder in TEMP
        path_to_binaries = getattr(sys, "_MEIPASS", non_pyinstaller_path)  # default to last arg
        path_to_icon = os.path.abspath(os.path.join(path_to_binaries, "cvamp_logo.ico"))

        if os.name == "nt":
            self.root.iconbitmap(path_to_icon)

        path_to_toml = os.path.abspath(os.path.join(path_to_binaries, "pyproject.toml"))
        version = toml.load(path_to_toml)["tool"]["poetry"]["version"]
        self.root.title(f"Crude Viewer Amplifier | v{version} | kevin@blueloperlabs.ch")

    def run(self):
        self.root.geometry("800x550+500+500")
        self.root.resizable(False, False)

        # Console log area
        console_frame = tk.Frame(self.root, bg=self.bg_color)
        console_frame.place(x=0, y=200, width=800, height=100)
        
        text_area = ScrolledText(console_frame, height=6, width=100, font=("Consolas", 9), bg="#1a1a1a", fg="#00ff00", insertbackground="#ffffff")
        text_area.place(x=10, y=5, width=780)
        text_area.configure(state="disabled")

        # Instance visualization
        instance_vis_frame = tk.Frame(self.root, bg=self.bg_color)
        instance_vis_frame.place(x=0, y=300, width=800, height=100)
        
        for row in range(5):
            for col in range(50):
                box = InstanceBox(
                    self.manager,
                    instance_vis_frame,
                    bd=0.5,
                    relief="raised",
                    width=10,
                    height=10,
                )
                box.place(x=10 + col * 15, y=10 + row * 15)
                self.instances_boxes.append(box)

        # Footer
        lbl = tk.Label(
            self.root,
            text=r"blueloperlabs.ch/cvamp",
            fg=self.accent_color,
            cursor="hand2",
            bg=self.bg_color,
        )
        lbl.bind("<Button-1>", lambda event: webbrowser.open("https://blueloperlabs.ch/cvamp/tf"))
        lbl.place(x=330, y=520)

        # redirect stdout
        def redirector(str_input):
            if self:
                text_area.configure(state="normal")
                text_area.insert(tk.END, str_input)
                text_area.see(tk.END)
                text_area.configure(state="disabled")
            else:
                sys.stdout = sys.__stdout__

        sys.stdout.write = redirector

        self.refresher_start()

        self.root.mainloop()

    def refresher_start(self):
        if not self.instances_overview == self.manager.instances_overview:
            self.instances_overview = self.manager.instances_overview.copy()

            for (id, status), box in zip(self.instances_overview.items(), self.instances_boxes):
                box.modify(status, id)

            for index in range(len(self.instances_overview), len(self.instances_boxes)):
                self.instances_boxes[index].modify(utils.InstanceStatus.INACTIVE, None)

            self.tab_main.alive_instances.configure(text=self.manager.instances_alive_count)
            self.tab_main.watching_instances.configure(text=str(self.manager.instances_watching_count))

        # Update performance metrics
        self.performance_monitor.update_network_speed()
        
        cpu_percent = psutil.cpu_percent()
        ram_percent = psutil.virtual_memory().percent
        ram_total_gb = psutil.virtual_memory().total / (1024**3)
        ram_used_gb = psutil.virtual_memory().used / (1024**3)
        
        # Calculate GPU usage (placeholder - actual GPU monitoring requires additional libraries)
        # For now, using a simple estimation based on CPU
        gpu_percent = min(cpu_percent * 0.8, 100)
        
        self.tab_main.cpu_usage_text.configure(text=f"{cpu_percent:.1f}%")
        self.tab_main.gpu_usage_text.configure(text=f"{gpu_percent:.1f}%")
        self.tab_main.ram_usage_text.configure(text=f"{ram_used_gb:.1f}GB / {ram_total_gb:.1f}GB")
        self.tab_main.network_speed_text.configure(text=f"{self.performance_monitor.current_network_speed_mbps:.2f} Mbps\n({self.performance_monitor.current_network_speed_mb_s:.2f} MB/s)")
        
        self.tab_main.proxy_available.configure(text=len(self.manager.proxies.proxy_list))
        
        # Update dead instances count
        dead_count = len(self.manager.browser_instances) - self.manager.instances_alive_count
        self.tab_main.dead_instances.configure(text=dead_count)

        self.root.after(1000, self.refresher_start)


class TabChat(tk.Frame):
    def __init__(self, parent, manager, bg_color, card_color, accent_color, text_color, subtext_color, *args, **kwargs):
        super().__init__(parent, bg=bg_color, *args, **kwargs)
        self.manager = manager
        self.chat_timer_start_value = tk.StringVar(value="60")
        self.chat_timer_stop_value = tk.StringVar(value="120")
        self.dropdown_selection = tk.StringVar()
        self.dropdown_selection.set("no chatters")
        self.auto_chat_enabled = tk.BooleanVar(value=False)

        # Manual Chat Frame
        manual_frame = tk.Frame(self, bg=card_color, relief="flat")
        manual_frame.place(x=10, y=10, width=780, height=80)

        title_manual = tk.Label(manual_frame, text="Manual Chat", font=("Segoe UI", 12, "bold"), bg=card_color, fg=text_color)
        title_manual.place(x=10, y=10)

        chat_message_box = tk.Entry(manual_frame, width=70, font=("Segoe UI", 10), bg="#353535", fg=text_color, insertbackground=text_color)
        chat_message_box.place(x=10, y=40)
        chat_message_box.insert(0, "Available in the PRO version - now free for everyone!")
        chat_message_box.configure(state="disabled")

        lbl_buy = tk.Label(manual_frame, text="Get PRO Version (Free)", fg=accent_color, cursor="hand2", bg=card_color, font=("Segoe UI", 10))
        lbl_buy.bind("<Button-1>", lambda event: webbrowser.open("https://blueloperlabs.ch/cvamp/tf"))
        lbl_buy.place(x=550, y=42)

        # Auto Chat Frame
        auto_frame = tk.Frame(self, bg=card_color, relief="flat")
        auto_frame.place(x=10, y=100, width=780, height=90)

        title_auto = tk.Label(auto_frame, text="Auto Chat", font=("Segoe UI", 12, "bold"), bg=card_color, fg=text_color)
        title_auto.place(x=10, y=10)

        chat_switch = tk.Checkbutton(
            auto_frame,
            state=tk.DISABLED,
            variable=self.auto_chat_enabled,
            text="Autochat enabled",
            bg=card_color,
            fg=text_color,
            selectcolor="#353535",
            activebackground=card_color,
            activeforeground=text_color,
            font=("Segoe UI", 10),
        )
        chat_switch.place(x=15, y=40)

        self.chat_timer_start = tk.Spinbox(
            auto_frame,
            state='readonly',
            from_=10,
            to=600,
            wrap=True,
            width=5,
            increment=5,
            textvariable=self.chat_timer_start_value,
            bg="#353535",
            fg=text_color,
            font=("Segoe UI", 10),
        )
        self.chat_timer_start.place(x=160, y=40)

        self.chat_timer_stop = tk.Spinbox(
            auto_frame,
            state='readonly',
            from_=10,
            to=600,
            wrap=True,
            width=5,
            increment=5,
            textvariable=self.chat_timer_stop_value,
            bg="#353535",
            fg=text_color,
            font=("Segoe UI", 10),
        )
        self.chat_timer_stop.place(x=210, y=40)

        chat_interval_text = tk.Label(auto_frame, text="Chat interval range (s)", bg=card_color, fg=subtext_color, font=("Segoe UI", 10))
        chat_interval_text.place(x=270, y=42)

        send_auto_chat_button = tk.Button(
            auto_frame,
            width=18,
            height=1,
            text="Send one message",
            state=tk.DISABLED,
            bg="#353535",
            fg=text_color,
            relief="flat",
            font=("Segoe UI", 10),
        )
        send_auto_chat_button.place(x=580, y=37)


class TabMain(tk.Frame):
    def __init__(self, parent, manager, bg_color, card_color, accent_color, text_color, subtext_color, *args, **kwargs):
        super().__init__(parent, bg=bg_color, *args, **kwargs)
        self.manager = manager
        self.headless = tk.BooleanVar(value=manager.get_headless())
        self.auto_restart = tk.BooleanVar(value=manager.get_auto_restart())
        self.browser_mode = tk.StringVar(value=manager.get_browser_mode())

        # Left Panel - Performance Metrics
        left_frame = tk.Frame(self, bg=card_color, relief="flat")
        left_frame.place(x=10, y=10, width=200, height=180)

        metrics_title = tk.Label(left_frame, text="Performance Metrics", font=("Segoe UI", 12, "bold"), bg=card_color, fg=text_color)
        metrics_title.place(x=10, y=10)

        # CPU
        cpu_label = tk.Label(left_frame, text="CPU:", font=("Segoe UI", 10), bg=card_color, fg=subtext_color)
        cpu_label.place(x=10, y=40)
        self.cpu_usage_text = tk.Label(left_frame, text="0.0%", font=("Segoe UI", 11, "bold"), bg=card_color, fg=accent_color)
        self.cpu_usage_text.place(x=50, y=40)

        # GPU
        gpu_label = tk.Label(left_frame, text="GPU:", font=("Segoe UI", 10), bg=card_color, fg=subtext_color)
        gpu_label.place(x=10, y=60)
        self.gpu_usage_text = tk.Label(left_frame, text="0.0%", font=("Segoe UI", 11, "bold"), bg=card_color, fg=accent_color)
        self.gpu_usage_text.place(x=50, y=60)

        # RAM
        ram_label = tk.Label(left_frame, text="RAM:", font=("Segoe UI", 10), bg=card_color, fg=subtext_color)
        ram_label.place(x=10, y=80)
        self.ram_usage_text = tk.Label(left_frame, text="0.0GB / 0.0GB", font=("Segoe UI", 10), bg=card_color, fg=text_color)
        self.ram_usage_text.place(x=50, y=80)

        # Network
        network_label = tk.Label(left_frame, text="Network:", font=("Segoe UI", 10), bg=card_color, fg=subtext_color)
        network_label.place(x=10, y=100)
        self.network_speed_text = tk.Label(left_frame, text="0.00 Mbps\n(0.00 MB/s)", font=("Segoe UI", 9), bg=card_color, fg=text_color, justify="left")
        self.network_speed_text.place(x=70, y=100)

        # Center Panel - Controls
        center_frame = tk.Frame(self, bg=card_color, relief="flat")
        center_frame.place(x=220, y=10, width=360, height=180)

        controls_title = tk.Label(center_frame, text="Controls", font=("Segoe UI", 12, "bold"), bg=card_color, fg=text_color)
        controls_title.place(x=10, y=10)

        # URL Entry
        url_label = tk.Label(center_frame, text="Channel URL:", font=("Segoe UI", 10), bg=card_color, fg=subtext_color)
        url_label.place(x=10, y=40)
        
        channel_url = tk.Entry(center_frame, width=42, font=("Segoe UI", 9), bg="#353535", fg=text_color, insertbackground=text_color)
        channel_url.place(x=10, y=60)
        channel_url.insert(0, "https://www.twitch.tv/channel_name")
        self.channel_url_entry = channel_url

        # Spawn Buttons
        spawn_frame = tk.Frame(center_frame, bg="#353535", relief="flat")
        spawn_frame.place(x=10, y=90, width=170, height=85)
        
        spawn_label = tk.Label(spawn_frame, text="Spawn Instance", font=("Segoe UI", 9, "bold"), bg="#353535", fg=subtext_color)
        spawn_label.place(x=5, y=5)
        
        spawn_one = tk.Button(spawn_frame, text="Spawn 1", command=lambda: self.spawn_instance(1), bg=accent_color, fg="white", relief="flat", font=("Segoe UI", 9))
        spawn_one.place(x=5, y=25, width=50, height=25)
        spawn_five = tk.Button(spawn_frame, text="Spawn 5", command=lambda: self.spawn_instance(5), bg=accent_color, fg="white", relief="flat", font=("Segoe UI", 9))
        spawn_five.place(x=60, y=25, width=50, height=25)
        spawn_ten = tk.Button(spawn_frame, text="Spawn 10", command=lambda: self.spawn_instance(10), bg=accent_color, fg="white", relief="flat", font=("Segoe UI", 9))
        spawn_ten.place(x=115, y=25, width=50, height=25)
        
        destroy_one = tk.Button(spawn_frame, text="Destroy 1", command=lambda: self.destroy_instance(1), bg="#d32f2f", fg="white", relief="flat", font=("Segoe UI", 9))
        destroy_one.place(x=5, y=55, width=50, height=25)
        destroy_five = tk.Button(spawn_frame, text="Destroy 5", command=lambda: self.destroy_instance(5), bg="#d32f2f", fg="white", relief="flat", font=("Segoe UI", 9))
        destroy_five.place(x=60, y=55, width=50, height=25)
        destroy_ten = tk.Button(spawn_frame, text="Destroy 10", command=lambda: self.destroy_instance(10), bg="#d32f2f", fg="white", relief="flat", font=("Segoe UI", 9))
        destroy_ten.place(x=115, y=55, width=50, height=25)

        # Right Panel - Instance Statistics
        right_frame = tk.Frame(self, bg=card_color, relief="flat")
        right_frame.place(x=590, y=10, width=200, height=180)

        stats_title = tk.Label(right_frame, text="Instance Statistics", font=("Segoe UI", 12, "bold"), bg=card_color, fg=text_color)
        stats_title.place(x=10, y=10)

        # Proxies
        proxy_label = tk.Label(right_frame, text="Proxies:", font=("Segoe UI", 10), bg=card_color, fg=subtext_color)
        proxy_label.place(x=10, y=40)
        self.proxy_available = tk.Label(right_frame, text="0", font=("Segoe UI", 11, "bold"), bg=card_color, fg=accent_color)
        self.proxy_available.place(x=70, y=40)

        # Watching
        watching_label = tk.Label(right_frame, text="Watching:", font=("Segoe UI", 10), bg=card_color, fg=subtext_color)
        watching_label.place(x=10, y=60)
        self.watching_instances = tk.Label(right_frame, text="0", font=("Segoe UI", 11, "bold"), bg=card_color, fg="#4caf50")
        self.watching_instances.place(x=85, y=60)

        # Alive
        alive_label = tk.Label(right_frame, text="Alive:", font=("Segoe UI", 10), bg=card_color, fg=subtext_color)
        alive_label.place(x=10, y=80)
        self.alive_instances = tk.Label(right_frame, text="0", font=("Segoe UI", 11, "bold"), bg=card_color, fg="#2196f3")
        self.alive_instances.place(x=60, y=80)

        # Dead
        dead_label = tk.Label(right_frame, text="Dead:", font=("Segoe UI", 10), bg=card_color, fg=subtext_color)
        dead_label.place(x=10, y=100)
        self.dead_instances = tk.Label(right_frame, text="0", font=("Segoe UI", 11, "bold"), bg=card_color, fg="#f44336")
        self.dead_instances.place(x=60, y=100)

        # Browser Mode Selection (at the top center)
        mode_frame = tk.Frame(self, bg=card_color, relief="flat")
        mode_frame.place(x=220, y=195, width=360, height=45)

        mode_label = tk.Label(mode_frame, text="Browser Mode:", font=("Segoe UI", 10, "bold"), bg=card_color, fg=text_color)
        mode_label.place(x=10, y=5)

        mode_standard = tk.Radiobutton(mode_frame, text="Standard (Chrome)", variable=self.browser_mode, value="standard",
                                        command=self.on_mode_change, bg=card_color, fg=subtext_color, selectcolor="#353535",
                                        activebackground=card_color, activeforeground=text_color, font=("Segoe UI", 9))
        mode_standard.place(x=10, y=25)

        mode_performance = tk.Radiobutton(mode_frame, text="Performance (Firefox)", variable=self.browser_mode, value="performance",
                                          command=self.on_mode_change, bg=card_color, fg=subtext_color, selectcolor="#353535",
                                          activebackground=card_color, activeforeground=text_color, font=("Segoe UI", 9))
        mode_performance.place(x=140, y=25)

        mode_ultra = tk.Radiobutton(mode_frame, text="Ultra (WebKit)", variable=self.browser_mode, value="ultra",
                                    command=self.on_mode_change, bg=card_color, fg=subtext_color, selectcolor="#353535",
                                    activebackground=card_color, activeforeground=text_color, font=("Segoe UI", 9))
        mode_ultra.place(x=260, y=25)

        # Checkboxes at the bottom
        controls_check_frame = tk.Frame(self, bg=card_color, relief="flat")
        controls_check_frame.place(x=10, y=195, width=200, height=45)

        headless_checkbox = tk.Checkbutton(
            controls_check_frame,
            text="Headless Mode",
            variable=self.headless,
            command=lambda: self.manager.set_headless(self.headless.get()),
            bg=card_color,
            fg=text_color,
            selectcolor="#353535",
            activebackground=card_color,
            activeforeground=text_color,
            font=("Segoe UI", 9),
        )
        headless_checkbox.place(x=10, y=0)

        auto_restart_checkbox = tk.Checkbutton(
            controls_check_frame,
            variable=self.auto_restart,
            text="Auto Restart",
            command=lambda: self.manager.set_auto_restart(self.auto_restart.get()),
            bg=card_color,
            fg=text_color,
            selectcolor="#353535",
            activebackground=card_color,
            activeforeground=text_color,
            font=("Segoe UI", 9),
        )
        auto_restart_checkbox.place(x=10, y=25)

    def on_mode_change(self):
        self.manager.set_browser_mode(self.browser_mode.get())
        print(f"Browser mode changed to: {self.browser_mode.get()}")

    def spawn_instance(self, count):
        print(f"Spawning {count} instance(s). Please wait for alive & watching instances increase.")
        target_url = self.channel_url_entry.get()
        if count == 1:
            threading.Thread(target=self.manager.spawn_instance, args=(target_url,)).start()
        else:
            threading.Thread(target=self.manager.spawn_instances, args=(count, target_url)).start()

    def destroy_instance(self, count):
        if not self.manager.browser_instances:
            print("No instances found")
            return
        
        print(f"Destroying {count} instance(s). Please wait for alive & watching instances decrease.")
        
        for _ in range(min(count, len(self.manager.browser_instances))):
            threading.Thread(target=self.manager.delete_latest).start()


class TabAbout(tk.Frame):
    def __init__(self, parent, bg_color, text_color, *args, **kwargs):
        super().__init__(parent, bg=bg_color, *args, **kwargs)
        
        info_text = tk.Label(
            self,
            text="Thank You for your support! The Pro version is now available to everyone as a free executable.\n"
            "We only use GitHub and blueloperlabs.ch. Other sites, users and resellers are fake - be careful!\n"
            "Purchasing recommended proxies helps the project advance.",
            bg=bg_color,
            fg=text_color,
            justify="center",
            font=("Segoe UI", 10),
        )
        info_text.place(relx=0.5, y=30, anchor="n")

        lbl_buy = tk.Label(self, text="Get Recommended Proxies", fg="#0078d4", cursor="hand2", bg=bg_color, font=("Segoe UI", 11, "underline"))
        lbl_buy.bind(
            "<Button-1>",
            lambda event: threading.Thread(
                target=open_multiple_urls,
                args=(
                    "https://blueloperlabs.ch/proxy/tf",
                    "https://blueloperlabs.ch/proxy-ps/tf",
                    "https://github.com/KevinBytesTheDust/cvamp/wiki/Webshare.io-Proxies-Guide",
                ),
            ).start(),
        )
        lbl_buy.place(relx=0.5, y=90, anchor="n")


class InstanceBox(tk.Frame):
    def __init__(self, manager, parent, *args, **kwargs):
        tk.Frame.__init__(self, parent, *args, **kwargs, bg="#1e1e1e")

        self.instance_id = None
        self.manager = manager

        self.bind(
            "<Button-1>", lambda event: self.manager.queue_command(self.instance_id, InstanceCommands.REFRESH)
        )  # left click
        self.bind(
            "<Button-3>", lambda event: self.manager.queue_command(self.instance_id, InstanceCommands.EXIT)
        )  # right click
        self.bind(
            "<Control-1>", lambda event: self.manager.queue_command(self.instance_id, InstanceCommands.SCREENSHOT)
        )  # control left click

    def modify(self, status, instance_id):
        self.instance_id = instance_id

        # todo: enum
        color_codes = {
            "inactive": "#1a1a1a",
            "starting": "#666666",
            "initialized": "#ffc107",
            "restarting": "#ffc107",
            "buffering": "#ff9800",
            "watching": "#44d209",
            "shutdown": "#1a1a1a",
        }

        color = color_codes[status.value]
        self.configure(background=color)
