from cvamp.gui import GUI
from cvamp.manager import InstanceManager


SPAWNER_THREAD_COUNT = 3
CLOSER_THREAD_COUNT = 10
PROXY_FILE_NAME = "proxy_list.txt"
HEADLESS = True
AUTO_RESTART = False
SPAWN_INTERVAL_SECONDS = 2
BROWSER_MODE = "standard"  # Options: "standard" (Chrome), "performance" (Firefox), "ultra" (WebKit)

manager = InstanceManager(
    spawn_thread_count=SPAWNER_THREAD_COUNT,
    delete_thread_count=CLOSER_THREAD_COUNT,
    headless=HEADLESS,
    auto_restart=AUTO_RESTART,
    proxy_file_name=PROXY_FILE_NAME,
    spawn_interval_seconds=SPAWN_INTERVAL_SECONDS,
    browser_mode=BROWSER_MODE,
)

print("Available proxies", len(manager.proxies.proxy_list))
print("Available window locations", len(manager.screen.spawn_locations))
print(f"Browser mode: {BROWSER_MODE}")

GUI(manager).run()
