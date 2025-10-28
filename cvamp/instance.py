import datetime
import logging
import threading

from playwright.sync_api import sync_playwright
from abc import ABC


from . import utils

logger = logging.getLogger(__name__)


class Instance(ABC):
    site_name = "BASE"
    site_url = None
    instance_lock = threading.Lock()
    supported_sites = dict()

    def __init__(
        self,
        proxy_dict,
        target_url,
        status_reporter,
        location_info=None,
        headless=False,
        auto_restart=False,
        instance_id=-1,
        browser_mode="standard",
    ):
        self.playwright = None
        self.context = None
        self.browser = None
        self.status_info = {}
        self.status_reporter = status_reporter
        self.thread = threading.current_thread()

        self.id = instance_id
        self._status = "alive"
        self.proxy_dict = proxy_dict
        self.target_url = target_url
        self.headless = headless
        self.auto_restart = auto_restart
        self.browser_mode = browser_mode  # "standard", "performance", "ultra"

        self.last_restart_dt = datetime.datetime.now()

        self.location_info = location_info
        if not self.location_info:
            self.location_info = {
                "index": -1,
                "x": 0,
                "y": 0,
                "width": 500,
                "height": 300,
                "free": True,
            }

        self.command = None
        self.page = None

    def __init_subclass__(cls, **kwargs):
        if cls.site_name != "UNKNOWN":
            cls.supported_sites[cls.site_url] = cls

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, new_status):
        if self._status == new_status:
            return

        self._status = new_status
        self.status_reporter(self.id, new_status)

    def clean_up_playwright(self):
        if any([self.page, self.context, self.browser]):
            self.page.close()
            self.context.close()
            self.browser.close()
            self.playwright.stop()

    def start(self):
        try:
            self.spawn_page()
            self.todo_after_spawn()

            # The debug code is no longer needed, so it has been removed.

            self.loop_and_check()
        except Exception as e:
            message = e.args[0][:25] if e.args else ""
            logger.exception(f"{e} died at page {self.page.url if self.page else None}")
            print(f"{self.site_name} Instance {self.id} died: {type(e).__name__}:{message}... Please see cvamp.log.")
        else:
            logger.info(f"ENDED: instance {self.id}")
            with self.instance_lock:
                print(f"Instance {self.id} shutting down")
        finally:
            self.status = utils.InstanceStatus.SHUTDOWN
            self.clean_up_playwright()
            self.location_info["free"] = True

    def loop_and_check(self):
        page_timeout_s = 10
        while True:
            self.page.wait_for_timeout(page_timeout_s * 1000)
            self.todo_every_loop()
            self.update_status()

            if self.command == utils.InstanceCommands.RESTART:
                self.clean_up_playwright()
                self.spawn_page(restart=True)
                self.todo_after_spawn()
            if self.command == utils.InstanceCommands.SCREENSHOT:
                print("Saved screenshot of instance id", self.id)
                self.save_screenshot()
            if self.command == utils.InstanceCommands.REFRESH:
                print("Manual refresh of instance id", self.id)
                self.reload_page()
            if self.command == utils.InstanceCommands.EXIT:
                return
            self.command = utils.InstanceCommands.NONE

    def save_screenshot(self):
        filename = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + f"_instance{self.id}.png"
        self.page.screenshot(path=filename)

    def spawn_page(self, restart=False):
        proxy_dict = self.proxy_dict
        if not proxy_dict:
            proxy_dict = None

        self.status = utils.InstanceStatus.RESTARTING if restart else utils.InstanceStatus.STARTING

        self.playwright = sync_playwright().start()

        # Select browser based on mode
        if self.browser_mode == "standard":
            # Standard mode - Chrome
            CHROMIUM_ARGS = [
                "--window-position={},{}".format(self.location_info["x"], self.location_info["y"]),
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--no-first-run",
                "--disable-blink-features=AutomationControlled",
                "--mute-audio",
                "--webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--force-webrtc-ip-handling-policy",
                # Lightweight options
                "--disable-extensions",
                "--disable-plugins",
                "--disable-dev-shm-usage",
                "--disable-software-rasterizer",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-breakpad",
                "--disable-component-extensions-with-background-pages",
                "--disable-features=TranslateUI,BlinkGenPropertyTrees",
                "--disable-ipc-flooding-protection",
                "--disable-renderer-backgrounding",
                "--disable-sync",
                "--metrics-recording-only",
                "--no-default-browser-check",
                "--no-pings",
                # GPU acceleration to reduce CPU load
                "--enable-gpu-rasterization",
                "--enable-zero-copy",
                "--enable-features=VaapiVideoDecoder",
                "--ignore-gpu-blocklist",
            ]

            if self.headless:
                CHROMIUM_ARGS.append("--headless")

            self.browser = self.playwright.chromium.launch(
                proxy=proxy_dict,
                channel="chrome",
                headless=False,
                args=CHROMIUM_ARGS,
            )
            major_version = self.browser.version.split(".")[0]
            user_agent = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major_version}.0.0.0 Safari/537.36"

            self.context = self.browser.new_context(
                viewport={"width": 800, "height": 600},
                user_agent=user_agent,
                proxy=proxy_dict,
                ignore_https_errors=True,
                bypass_csp=True,
                color_scheme='no-preference',
                reduced_motion='reduce',
                service_workers='block',
                has_touch=False,
            )

        elif self.browser_mode == "performance":
            # Performance mode - Firefox with GPU acceleration and 30 FPS limit
            FIREFOX_ARGS = [
                "--window-position={},{}".format(self.location_info["x"], self.location_info["y"]),
            ]

            self.browser = self.playwright.firefox.launch(
                proxy=proxy_dict,
                headless=self.headless,
                args=FIREFOX_ARGS,
                firefox_user_prefs={
                    "media.volume_scale": "0.0",
                    # GPU acceleration enabled to reduce CPU load
                    "layers.acceleration.force-enabled": True,
                    "gfx.webrender.all": True,
                    "gfx.webrender.enabled": True,
                    "media.hardware-video-decoding.enabled": True,
                    "media.hardware-video-decoding.force-enabled": True,
                    "media.ffmpeg.vaapi.enabled": True,
                    # Frame rate limit to 30 FPS
                    "layout.frame_rate": 30,
                    # Lightweight options
                    "browser.cache.disk.enable": False,
                    "browser.cache.memory.enable": True,
                    "browser.cache.memory.capacity": 32768,  # 32MB
                    "browser.sessionhistory.max_total_viewers": 0,
                    "browser.tabs.animate": False,
                    "browser.download.folderList": 0,
                    "dom.webdriver.enabled": False,
                    "useAutomationExtension": False,
                    "network.http.pipelining": True,
                    "network.http.proxy.pipelining": True,
                    "network.prefetch-next": False,
                    "browser.safebrowsing.enabled": False,
                    "browser.safebrowsing.malware.enabled": False,
                    "privacy.trackingprotection.enabled": False,
                    # Media optimization
                    "media.autoplay.default": 0,
                    "media.eme.enabled": True,
                    "media.gmp-widevinecdm.enabled": True,
                },
            )
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"

            self.context = self.browser.new_context(
                viewport={"width": 800, "height": 600},
                user_agent=user_agent,
                proxy=proxy_dict,
                ignore_https_errors=True,
                bypass_csp=True,
                color_scheme='no-preference',
                reduced_motion='reduce',
                service_workers='block',
                has_touch=False,
            )

        elif self.browser_mode == "ultra":
            # Ultra Performance mode - Firefox extreme lightweight with 10 FPS limit
            FIREFOX_ARGS = [
                "--window-position={},{}".format(self.location_info["x"], self.location_info["y"]),
            ]

            self.browser = self.playwright.firefox.launch(
                proxy=proxy_dict,
                headless=self.headless,
                args=FIREFOX_ARGS,
                firefox_user_prefs={
                    "media.volume_scale": "0.0",

                    # GPU acceleration maximized to reduce CPU load
                    "layers.acceleration.force-enabled": True,
                    "layers.acceleration.disabled": False,
                    "gfx.webrender.all": True,
                    "gfx.webrender.enabled": True,
                    "gfx.canvas.accelerated": True,
                    "gfx.canvas.accelerated.cache-items": 32768,
                    "gfx.canvas.accelerated.cache-size": 4096,
                    "gfx.content.skia-font-cache-size": 80,
                    "media.hardware-video-decoding.enabled": True,
                    "media.hardware-video-decoding.force-enabled": True,
                    "media.ffmpeg.vaapi.enabled": True,
                    "media.rdd-ffmpeg.enabled": True,
                    "media.navigator.mediadatadecoder_vpx_enabled": True,

                    # Frame rate limit to 5 FPS for extreme CPU savings
                    "layout.frame_rate": 5,

                    # Memory usage reduction (extreme)
                    "browser.cache.disk.enable": False,
                    "browser.cache.memory.enable": True,
                    "browser.cache.memory.capacity": 16384,  # 16MB
                    "browser.cache.memory.max_entry_size": 512,
                    "browser.sessionhistory.max_total_viewers": 0,
                    "browser.sessionstore.interval": 3600000,
                    "browser.sessionstore.max_tabs_undo": 0,
                    "browser.sessionstore.max_windows_undo": 0,

                    # UI/Animation completely disabled
                    "browser.tabs.animate": False,
                    "browser.fullscreen.animate": False,
                    "browser.panorama.animate_zoom": False,
                    "toolkit.cosmeticAnimations.enabled": False,
                    "ui.prefersReducedMotion": 1,

                    # Unnecessary features completely disabled
                    "browser.safebrowsing.enabled": False,
                    "browser.safebrowsing.malware.enabled": False,
                    "browser.safebrowsing.downloads.enabled": False,
                    "browser.safebrowsing.downloads.remote.enabled": False,
                    "privacy.trackingprotection.enabled": False,
                    "extensions.pocket.enabled": False,
                    "extensions.screenshots.disabled": True,
                    "browser.newtabpage.enabled": False,
                    "browser.startup.homepage": "about:blank",
                    "browser.messaging-system.whatsNewPanel.enabled": False,
                    "browser.urlbar.suggest.quicksuggest.sponsored": False,
                    "browser.urlbar.suggest.quicksuggest.nonsponsored": False,

                    # Network optimization
                    "network.http.pipelining": True,
                    "network.http.proxy.pipelining": True,
                    "network.http.max-connections": 48,
                    "network.http.max-persistent-connections-per-server": 6,
                    "network.prefetch-next": False,
                    "network.dns.disablePrefetch": True,
                    "network.dns.disablePrefetchFromHTTPS": True,
                    "network.predictor.enabled": False,
                    "network.predictor.enable-prefetch": False,

                    # Rendering optimization (GPU utilization)
                    "layout.css.backdrop-filter.enabled": False,
                    "layout.css.scroll-behavior.spring-constant": "250",

                    # Media optimization (maintain stream playback)
                    "media.autoplay.default": 0,
                    "media.autoplay.blocking_policy": 0,
                    "media.eme.enabled": True,
                    "media.gmp-widevinecdm.enabled": True,
                    "media.gmp-widevinecdm.visible": True,
                    "media.gmp-widevinecdm.autoupdate": False,
                    "media.gmp.decoder.enabled": True,
                    "media.av1.enabled": True,
                    "media.ffmpeg.low-latency.enabled": True,

                    # Process count reduction (reduce CPU load)
                    "dom.ipc.processCount": 1,
                    "dom.ipc.processCount.webIsolated": 1,
                    "dom.ipc.processPrelaunch.enabled": False,
                    "dom.ipc.keepProcessesAlive.web": 0,

                    # JavaScript optimization
                    "javascript.options.baselinejit": True,
                    "javascript.options.ion": True,
                    "javascript.options.native_regexp": True,
                    "javascript.options.parallel_parsing": True,
                    "javascript.options.asyncstack": False,
                    "javascript.options.throw_on_debuggee_would_run": False,

                    # Image processing optimization (GPU utilization)
                    "image.mem.decode_bytes_at_a_time": 65536,
                    "image.mem.shared.unmap.min_expiration_ms": 60000,
                    "image.cache.size": 5242880,

                    # Other optimizations
                    "permissions.default.image": 1,
                    "permissions.default.stylesheet": 1,
                    "accessibility.force_disabled": 1,
                    "browser.contentblocking.category": "custom",
                    "datareporting.healthreport.uploadEnabled": False,
                    "datareporting.policy.dataSubmissionEnabled": False,

                    # Automation detection bypass
                    "dom.webdriver.enabled": False,
                    "useAutomationExtension": False,
                    "marionette.enabled": False,
                },
            )
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"

            self.context = self.browser.new_context(
                viewport={"width": 800, "height": 600},
                user_agent=user_agent,
                proxy=proxy_dict,
                ignore_https_errors=True,
                bypass_csp=True,
                color_scheme='no-preference',
                reduced_motion='reduce',
                service_workers='block',
                has_touch=False,
                locale='en-US',
                timezone_id='UTC',
            )

        else:
            # Default to Chrome if mode is invalid
            CHROMIUM_ARGS = [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--mute-audio",
            ]

            self.browser = self.playwright.chromium.launch(
                proxy=proxy_dict,
                channel="chrome",
                headless=False,
                args=CHROMIUM_ARGS,
            )
            major_version = self.browser.version.split(".")[0]
            user_agent = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major_version}.0.0.0 Safari/537.36"

            self.context = self.browser.new_context(
                viewport={"width": 800, "height": 600},
                user_agent=user_agent,
                proxy=proxy_dict,
            )

        self.page = self.context.new_page()
        self.page.add_init_script("""navigator.webdriver = false;""")

    def goto_with_retry(self, url, max_tries=3, timeout=20000):
        """
        Tries to navigate to a page max_tries times. Raises the last exception if all attempts fail.
        """
        for attempt in range(1, max_tries + 1):
            try:
                self.page.goto(url, timeout=timeout)
                return
            except Exception:
                logger.warning(f"Instance {self.id} failed connection attempt #{attempt}.")
                if attempt == max_tries:
                    raise

    def todo_after_load(self):
        self.goto_with_retry(self.target_url)
        self.page.wait_for_timeout(1000)

    def reload_page(self):
        self.page.reload(timeout=30000)
        self.todo_after_load()

    def todo_after_spawn(self):
        """
        Basic behaviour after a page is spawned. Override for more functionality
        e.g. load cookies, additional checks before instance is truly called "initialized"
        :return:
        """
        self.status = utils.InstanceStatus.INITIALIZED
        self.goto_with_retry(self.target_url)
        
        # Click the cookie consent button if it exists
        try:
            cookie_button = self.page.get_by_test_id("accept-cookies")
            if cookie_button.is_visible():
                print(f"Instance {self.id} clicking cookie consent button.")
                cookie_button.click(timeout=5000)
        except Exception as e:
            # Button not found or other error, just log and continue
            logger.info(f"Instance {self.id} could not click cookie button (may not exist): {e}")


    def todo_every_loop(self):
        """
        Add behaviour to be executed every loop
        e.g. to fake page interaction to not count as inactive to the website.
        """
        pass

    def update_status(self) -> None:
        """
        Mechanism is called every loop. Figure out if it is watching and working and updated status.
        if X:
            self.status = utils.InstanceStatus.WATCHING
        """
        pass
