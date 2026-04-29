@app.route('/health')
def health():
    import subprocess
    env_vars = subprocess.run(['env'], capture_output=True, text=True).stdout
    has_key = 'ANTHROPIC' in env_vars
    return jsonify({"status": "ok", "has_anthropic": has_key, "env_count": len(env_vars.split('\n'))})
