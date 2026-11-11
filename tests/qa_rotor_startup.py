"""Start the actual packaged Rotor Test offscreen and verify the WebChannel UI.

No calculation inputs are loaded. Only processes created by this check are stopped.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

import psutil
import websocket


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    executable = root/'dist_test/GTU_Report_Rotor_Test/GTU_Report_Rotor_Test.exe'
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['QTWEBENGINE_REMOTE_DEBUGGING'] = f'127.0.0.1:{port}'
    env['QTWEBENGINE_CHROMIUM_FLAGS'] = f'--disable-gpu --remote-allow-origins=http://127.0.0.1:{port}'
    system_dir = Path(os.environ['SystemRoot'])/'System32'
    env['PATH'] = ';'.join(p for p in env.get('PATH', '').split(';')
                           if p and (Path(p) == system_dir or not (Path(p)/'icuuc.dll').is_file()))
    started = time.monotonic()
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    process = subprocess.Popen([str(executable)], cwd=executable.parent, env=env,
                               startupinfo=startup, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    try:
        ready = None
        while time.monotonic() - started < 45:
            if process.poll() is not None:
                raise RuntimeError(f'Packaged app exited with {process.returncode}')
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/json', timeout=1) as response:
                    pages = json.load(response)
                page = next(p for p in pages if p.get('url', '').endswith('/desktop_ui/index.html'))
                with closing(websocket.create_connection(page['webSocketDebuggerUrl'], timeout=2,
                        origin=f'http://127.0.0.1:{port}')) as connection:
                    connection.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {
                        'expression': "JSON.stringify({page:document.readyState,stations:document.querySelector('#station')?.options.length||0,chooseEnabled:!document.querySelector('[data-action=\"file\"]')?.disabled,tabs:document.querySelectorAll('[data-tab]').length,sourceBook:!!document.querySelector('[data-action=\"sourceBook\"]'),fullLog:!!document.querySelector('[data-action=\"fullLog\"]'),addStation:!!document.querySelector('[data-action=\"addStation\"]')})",
                        'returnByValue': True}}))
                    while True:
                        result = json.loads(connection.recv())
                        if result.get('id') == 1:
                            ready = json.loads(result['result']['result']['value'])
                            break
                if ready['page'] == 'complete' and ready['stations'] > 1 and ready['chooseEnabled']:
                    break
            except (OSError, StopIteration, KeyError, ValueError, websocket.WebSocketException):
                pass
            time.sleep(.2)
        else:
            raise AssertionError(f'Packaged WebChannel did not become ready: {ready}')
        assert ready['tabs'] == 7, ready
        assert ready['sourceBook'] and ready['fullLog'] and ready['addStation'], ready
        ready['seconds'] = round(time.monotonic()-started, 3)
        args.output.write_text(json.dumps(ready, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(ready, ensure_ascii=False))
    finally:
        try:
            children = psutil.Process(process.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            children = []
        process.terminate()
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        process.wait(timeout=10)
        psutil.wait_procs(children, timeout=5)


if __name__ == '__main__':
    main()
