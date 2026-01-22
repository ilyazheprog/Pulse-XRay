from flask import Flask, render_template, request, Response, stream_with_context, jsonify
from functools import wraps
import json
import os
import core
import db_utils as db
from dotenv import load_dotenv

load_dotenv()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "admin")

app = Flask(__name__)
# Инициализация БД
db.init_db()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('X-Api-Token')
        if not token or token != ADMIN_TOKEN: return jsonify({"status": "error", "msg": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index(): return render_template('index.html')

@app.route('/api/login', methods=['POST'])
def login():
    if request.json.get("token") == ADMIN_TOKEN: return jsonify({"status": "ok"})
    return jsonify({"status": "error"}), 401

@app.route('/get_state')
def get_state():
    return jsonify({
        "settings": db.get_settings(),
        "test_urls": db.get_test_urls(),
        "groups": db.get_groups(), 
        "configurations": db.get_monitor_configs()
    })

@app.route('/save_state', methods=['POST'])
@login_required
def save_state():
    try:
        data = request.json
        if "settings" in data:
            s = data["settings"]
            db.save_settings(s.get("auto_run", False), s.get("interval", 60))
        if "test_urls" in data: db.save_test_urls(data["test_urls"])
        
        # Сохранение групп (включая порядок)
        if "groups" in data:
            for g in data["groups"]: db.add_group(g)
            db.update_group_order(data["groups"])
        
        # Сохранение мониторов
        if "configurations" in data:
            configs = []
            for c in data["configurations"]:
                configs.append({"name": c.get("name"), "link": c.get("link"), "group": c.get("group", "General")})
            db.save_monitor_configs(configs)
            
        return jsonify({"status": "ok"})
    except Exception as e: return jsonify({"status": "error", "msg": str(e)})

@app.route('/groups/add', methods=['POST'])
@login_required
def api_add_group():
    if request.json.get("name"): db.add_group(request.json.get("name"))
    return jsonify({"status": "ok"})

@app.route('/groups/delete', methods=['POST'])
@login_required
def api_delete_group():
    n = request.json.get("name")
    if n and n != "General": db.delete_group(n)
    return jsonify({"status": "ok"})

@app.route('/clear_history', methods=['POST'])
@login_required
def api_clear_history():
    db.clear_all_history()
    return jsonify({"status": "ok"})

@app.route('/stream_check')
def stream_check():
    def generate():
        test_urls = db.get_test_urls()
        configs = db.get_monitor_configs()
        xray_path = core.ensure_xray_local()
        
        if not configs: yield f"data: {json.dumps({'type': 'done'})}\n\n"; return

        for item in configs:
            group = item.get("group_name", "General")
            mon_name = item.get("name", "Unnamed")
            link = item.get("link", "").strip()
            
            if not link: continue
            
            yield f"data: {json.dumps({'type': 'start', 'group': group})}\n\n"
            
            links_pool = []
            if link.startswith("vless://"): links_pool = [link]
            elif link.startswith("http"): links_pool = core.fetch_subscription(link)
            
            for i, sub in enumerate(links_pool):
                ok, msg, logs, lat, _ = core.check_proxy_core(sub, xray_path, test_urls)
                # Имя
                final = mon_name if len(links_pool) == 1 else f"{mon_name} #{i+1}"
                
                db.save_check_result(final, ok, lat)
                stats = db.get_proxy_stats(final)
                
                short_log = "\n".join([l for l in logs.splitlines() if l.strip()][-10:]) if logs and not ok else ""
                
                payload = {
                    "type": "result", 
                    "group": group, 
                    "name": final, 
                    "status": ok, 
                    "latency": lat, 
                    "msg": msg, 
                    "log": short_log, 
                    "uptime_1d": stats["1d"], 
                    "uptime_30d": stats["30d"], 
                    "uptime_1y": stats["1y"], 
                    "history": stats["history"],
                    "history_ts": stats["history_ts"] # Time data
                }
                yield f"data: {json.dumps(payload)}\n\n"
        
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

if __name__ == "__main__":
    app.run(debug=False, port=5000, host="0.0.0.0")