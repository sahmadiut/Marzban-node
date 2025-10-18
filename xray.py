import atexit
import json
import os
import re
import subprocess
import threading
from collections import deque
from contextlib import contextmanager

from config import DEBUG, SSL_CERT_FILE, SSL_KEY_FILE, XRAY_API_HOST, XRAY_API_PORT, INBOUNDS, XRAY_CONFIG_FILE
from logger import logger


class XRayConfig(dict):
    """
    Loads Xray config json
    config must contain an inbound with the API_INBOUND tag name which handles API requests
    """

    def __init__(self, config: str, peer_ip: str):
        config = json.loads(config)

        self.api_host = XRAY_API_HOST
        self.api_port = XRAY_API_PORT
        self.ssl_cert = SSL_CERT_FILE
        self.ssl_key = SSL_KEY_FILE
        self.peer_ip = peer_ip

        super().__init__(config)
        self._apply_api()
        self._load_custom_config()

    def to_json(self, **json_kwargs):
        return json.dumps(self, **json_kwargs)

    def _load_custom_config(self):
        """
        Load custom routing and outbounds from XRAY_CONFIG_FILE if it exists.
        This allows per-node customization while maintaining backward compatibility.
        """
        if not XRAY_CONFIG_FILE or not os.path.exists(XRAY_CONFIG_FILE):
            return

        try:
            with open(XRAY_CONFIG_FILE, 'r', encoding='utf-8') as f:
                custom_config = json.load(f)
            
            # Override routing if present in custom config
            # But preserve the API routing rule that was added by _apply_api
            if 'routing' in custom_config:
                logger.info(f"[CUSTOM CONFIG] Overriding routing with custom config from {XRAY_CONFIG_FILE}")
                
                # Get the API rule that was inserted at index 0 by _apply_api
                api_rule = self.get('routing', {}).get('rules', [{}])[0] if self.get('routing', {}).get('rules') else None
                
                # Override the routing with custom config
                self['routing'] = custom_config['routing']
                
                # Re-insert the API rule at the beginning to ensure it takes priority
                if api_rule and api_rule.get('outboundTag') == 'API':
                    if 'rules' not in self['routing']:
                        self['routing']['rules'] = []
                    self['routing']['rules'].insert(0, api_rule)
                    logger.info(f"[CUSTOM CONFIG] API routing rule preserved and inserted at index 0")
                else:
                    logger.warning(f"[CUSTOM CONFIG] Could not find API routing rule to preserve!")
            
            # Override outbounds if present in custom config
            if 'outbounds' in custom_config:
                logger.info(f"[CUSTOM CONFIG] Overriding {len(custom_config['outbounds'])} outbound(s) with custom config from {XRAY_CONFIG_FILE}")
                self['outbounds'] = custom_config['outbounds']
            
            logger.info("[CUSTOM CONFIG] Custom config applied successfully")
            logger.info(f"[CUSTOM CONFIG] Final config: {json.dumps(self, indent=2, ensure_ascii=False)}")
        except json.JSONDecodeError as e:
            logger.error(f"[CUSTOM CONFIG] Failed to parse custom config file {XRAY_CONFIG_FILE}: {e}")
        except Exception as e:
            logger.error(f"[CUSTOM CONFIG] Failed to load custom config file {XRAY_CONFIG_FILE}: {e}")

    def _apply_api(self):
        for inbound in self.get('inbounds', []).copy():
            if inbound.get('protocol') == 'dokodemo-door' and inbound.get('tag') == 'API_INBOUND':
                self['inbounds'].remove(inbound)
                
            elif INBOUNDS and inbound.get('tag') not in INBOUNDS:
                self['inbounds'].remove(inbound)

        for rule in self.get('routing', {}).get("rules", []):
            api_tag = self.get('api', {}).get('tag')
            if api_tag and rule.get('outboundTag') == api_tag:
                self['routing']['rules'].remove(rule)

        self["api"] = {
            "services": [
                "HandlerService",
                "StatsService",
                "LoggerService"
            ],
            "tag": "API"
        }
        self["stats"] = {}
        inbound = {
            "listen": self.api_host,
            "port": self.api_port,
            "protocol": "dokodemo-door",
            "settings": {
                "address": "127.0.0.1"
            },
            "streamSettings": {
                "security": "tls",
                "tlsSettings": {
                    "certificates": [
                        {
                            "certificateFile": self.ssl_cert,
                            "keyFile": self.ssl_key
                        }
                    ]
                }
            },
            "tag": "API_INBOUND"
        }
        try:
            self["inbounds"].insert(0, inbound)
        except KeyError:
            self["inbounds"] = []
            self["inbounds"].insert(0, inbound)

        rule = {
            "inboundTag": [
                "API_INBOUND"
            ],
            "source": [
                "127.0.0.1",
                self.peer_ip
            ],
            "outboundTag": "API",
            "type": "field"
        }
        try:
            self["routing"]["rules"].insert(0, rule)
        except KeyError:
            self["routing"] = {"rules": []}
            self["routing"]["rules"].insert(0, rule)


class XRayCore:
    def __init__(self,
                 executable_path: str = "/usr/bin/xray",
                 assets_path: str = "/usr/share/xray"):
        self.executable_path = executable_path
        self.assets_path = assets_path

        self.version = self.get_version()
        self.process = None
        self.restarting = False

        self._logs_buffer = deque(maxlen=100)
        self._temp_log_buffers = {}
        self._on_start_funcs = []
        self._on_stop_funcs = []
        self._env = {
            "XRAY_LOCATION_ASSET": assets_path
        }

        atexit.register(lambda: self.stop() if self.started else None)

    def get_version(self):
        cmd = [self.executable_path, "version"]
        output = subprocess.check_output(
            cmd, stderr=subprocess.STDOUT).decode('utf-8')
        m = re.match(r'^Xray (\d+\.\d+\.\d+)', output)
        if m:
            return m.groups()[0]

    def __capture_process_logs(self):
        def capture_and_debug_log():
            while self.process:
                output = self.process.stdout.readline()
                if output:
                    output = output.strip()
                    self._logs_buffer.append(output)
                    for buf in list(self._temp_log_buffers.values()):
                        buf.append(output)
                    logger.debug(output)

                elif not self.process or self.process.poll() is not None:
                    break

        def capture_only():
            while self.process:
                output = self.process.stdout.readline()
                if output:
                    output = output.strip()
                    self._logs_buffer.append(output)
                    for buf in list(self._temp_log_buffers.values()):
                        buf.append(output)

                elif not self.process or self.process.poll() is not None:
                    break

        if DEBUG:
            threading.Thread(target=capture_and_debug_log).start()
        else:
            threading.Thread(target=capture_only).start()

    @contextmanager
    def get_logs(self):
        buf = deque(self._logs_buffer, maxlen=100)
        buf_id = id(buf)
        try:
            self._temp_log_buffers[buf_id] = buf
            yield buf
        except (EOFError, TimeoutError):
            pass
        finally:
            del self._temp_log_buffers[buf_id]
            del buf

    @property
    def started(self):
        if not self.process:
            return False

        if self.process.poll() is None:
            return True

        return False

    def start(self, config: XRayConfig):
        if self.started is True:
            raise RuntimeError("Xray is started already")

        if config.get('log', {}).get('logLevel') in ('none', 'error'):
            config['log']['logLevel'] = 'warning'

        cmd = [
            self.executable_path,
            "run",
            '-config',
            'stdin:'
        ]
        self.process = subprocess.Popen(
            cmd,
            env=self._env,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            universal_newlines=True
        )
        self.process.stdin.write(config.to_json())
        self.process.stdin.flush()
        self.process.stdin.close()

        self.__capture_process_logs()

        # execute on start functions
        for func in self._on_start_funcs:
            threading.Thread(target=func).start()

    def stop(self):
        if not self.started:
            return

        self.process.terminate()
        self.process = None
        logger.warning("Xray core stopped")

        # execute on stop functions
        for func in self._on_stop_funcs:
            threading.Thread(target=func).start()

    def restart(self, config: XRayConfig):
        if self.restarting is True:
            return

        self.restarting = True
        try:
            logger.warning("Restarting Xray core...")
            self.stop()
            self.start(config)
        finally:
            self.restarting = False

    def on_start(self, func: callable):
        self._on_start_funcs.append(func)
        return func

    def on_stop(self, func: callable):
        self._on_stop_funcs.append(func)
        return func
