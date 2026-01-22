import base64
import json
import os
import tempfile
import time
import subprocess
import requests
import shutil
import platform
import re
import sys
import random
import socket
import urllib3
from urllib.parse import urlparse, parse_qs, unquote
from pathlib import Path

# Отключаем жалобы на SSL (нам важна скорость)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

XRAY_BIN_DIR = "xray-bin"

def ensure_xray_local() -> str:
    # Стандартная проверка наличия файла
    base_path = Path(__file__).parent
    target_dir = base_path / XRAY_BIN_DIR
    exe_suffix = ".exe" if platform.system().lower() == "windows" else ""
    target_path = target_dir / ("xray" + exe_suffix)

    if target_path.exists() and target_path.stat().st_size > 0:
        return str(target_path)
    
    # Если файла нет - возвращаем путь, но пишем в консоль (код скачивания сокращен для читаемости)
    # Предполагается, что файл xray уже лежит в папке xray-bin
    print(f"[CORE WARNING] Xray не найден по пути {target_path}. Пожалуйста, положите файл ядра в папку xray-bin.")
    return str(target_path)

def parse_vless_link(link: str) -> tuple[dict, str]:
    try:
        # Парсинг #Remark
        remark = ""
        if '#' in link:
            parts = link.split('#', 1)
            link = parts[0]
            try: remark = unquote(parts[1]).strip()
            except: pass

        u = urlparse(link)
        qs = parse_qs(u.query)
        def get_p(k, d=None): return qs.get(k, [d])[0]

        uuid = u.username
        addr = u.hostname
        port = u.port or 443
        if not addr or not uuid: raise ValueError("Invalid Link")

        net = get_p('type', get_p('network', 'tcp'))
        if net == 'http': net = 'tcp'
        sec = get_p('security', 'none')
        flow = get_p('flow', '')
        if not sec and flow == 'xtls-rprx-vision': sec = 'tls'

        stream = {"network": net, "security": sec}
        
        sni = None
        if sec in ['tls', 'reality']:
            sni = get_p('sni', get_p('serverName', get_p('host')))
            tls = {
                "serverName": sni if sni else addr,
                "allowInsecure": get_p('allowInsecure') == 'true',
                "fingerprint": get_p('fp', get_p('fingerprint', 'chrome'))
            }
            alpn = get_p('alpn')
            if alpn: tls['alpn'] = [x.strip() for x in re.split(r'[,]', unquote(alpn)) if x.strip()]
            if sec == 'reality':
                tls.update({"publicKey": get_p('pbk'), "shortId": get_p('sid'), "show": False})
                stream['realitySettings'] = tls
                stream['security'] = 'reality'
            else:
                stream['tlsSettings'] = tls

        if net == 'ws':
            stream['wsSettings'] = {"path": get_p('path', '/'), "headers": {"Host": get_p('host') or (sni if sni is not None else None) or addr}}
        elif net == 'grpc':
            stream['grpcSettings'] = {"serviceName": get_p('serviceName', '')}
        elif net == 'xhttp':
            stream['xhttpSettings'] = {"path": get_p('path', '/'), "host": get_p('host') or (sni if sni is not None else None) or addr, "mode": "auto"}

        user = {"id": uuid, "encryption": "none"}
        if flow: user['flow'] = flow

        outbound = {
            "protocol": "vless",
            "settings": {"vnext": [{"address": addr, "port": port, "users": [user]}]},
            "streamSettings": stream
        }
        return outbound, remark
    except Exception as e:
        return {}, str(e)

def fetch_subscription(url: str):
    try:
        # User-Agent важен, некоторые подписки блочат python-requests
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=10, verify=False)
        if not resp.ok: return []
        content = resp.text.strip()
        padded = content + '=' * (-len(content) % 4)
        decoded = base64.b64decode(padded).decode('utf-8', errors='ignore')
        return [l.strip() for l in decoded.splitlines() if l.strip().startswith("vless://")]
    except:
        return []

def wait_for_port(port: int, timeout: float = 2.0) -> bool:
    """
    Ждет, пока локальный порт Xray откроется. 
    Это критически важно для точного замера пинга.
    """
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', port)) == 0:
                return True
        time.sleep(0.05) # Проверяем каждые 50мс
    return False

def check_proxy_core(link: str, xray_path: str, test_urls: list):
    outbound, link_name = parse_vless_link(link)
    if isinstance(outbound, str): 
        return False, f"Error: {outbound}", "", 0, ""

    local_port = random.randint(20000, 50000)

    config = {
        "log": {"loglevel": "none"}, # Отключаем логи для скорости IO
        "inbounds": [{
            "port": local_port, 
            "listen": "127.0.0.1", 
            "protocol": "socks", 
            "settings": {"auth": "noauth", "udp": True}
        }],
        "outbounds": [outbound]
    }

    fd, tmp_path = tempfile.mkstemp(suffix=".json", text=True)
    proc = None
    log_capture = ""
    status = False
    msg = ""
    latency = 0

    try:
        with os.fdopen(fd, 'w') as f: json.dump(config, f)
        
        # Запуск Xray
        proc = subprocess.Popen([xray_path, "-c", tmp_path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        
        # 1. Сначала ждем, пока Xray реально запустится и откроет порт
        # (Это время НЕ входит в measurement пинга)
        if not wait_for_port(local_port, timeout=3.0):
             raise Exception("Xray start timeout")

        if proc.poll() is not None: 
            raise Exception("Xray crashed")

        proxies = {
            "http": f"socks5h://127.0.0.1:{local_port}", 
            "https": f"socks5h://127.0.0.1:{local_port}"
        }
        
        # Лучшие URL для проверки HTTP-latency (без редиректов и тяжелого тела)
        # Если юзер не передал свои, используем Cloudflare CP (очень быстрый)
        targets = test_urls if test_urls else ["http://cp.cloudflare.com", "http://www.gstatic.com/generate_204"]
        
        for url in targets:
            try:
                # 2. Только теперь замеряем время
                t_start = time.perf_counter()
                
                # stream=True скачивает заголовки, но не качает тело сразу.
                # Это дает максимально близкое значение к "ощущению" отклика сайта.
                r = requests.get(url, proxies=proxies, timeout=6, verify=False, stream=True)
                
                # Останавливаем замер сразу после получения заголовков
                t_end = time.perf_counter()
                r.close() # Закрываем соединение
                
                if r.status_code in [200, 204, 301, 302]:
                    status = True
                    latency = int((t_end - t_start) * 1000) # MC
                    msg = "OK"
                    break 
                else: 
                    msg = f"HTTP {r.status_code}"
            except requests.exceptions.Timeout:
                msg = "Timeout"
            except Exception as e:
                # msg = str(e) # Для дебага
                msg = "Conn Err"
        
    except Exception as e:
        msg = str(e)
    finally:
        if proc:
            proc.terminate()
            # Читаем лог только если была ошибка, чтобы не тратить время
            if not status:
                try: out, _ = proc.communicate(timeout=0.5)
                except: out = ""
                if out: log_capture = out
        if os.path.exists(tmp_path): os.remove(tmp_path)

    return status, msg, log_capture, latency, link_name