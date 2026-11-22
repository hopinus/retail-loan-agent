"""Interactive launcher with optional current-user encrypted auto-connect."""
import os
import webbrowser
import sys
import json
import threading
import time
from urllib.request import urlopen

from gemini_native import GeminiNativeError, gemini_ping, list_models


def prompt_api_key():
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title('Gemini API 연결')
    root.geometry('540x235')
    root.attributes('-topmost', True)
    root.resizable(False, False)
    value = tk.StringVar()
    count = tk.StringVar(value='입력된 글자: 0')
    result = []
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Gemini API 키를 붙여넣으세요 (Ctrl+V)', font=('', 12)).pack(anchor='w')
    entry = ttk.Entry(frame, textvariable=value, show='*', width=65)
    entry.pack(fill='x', pady=12)
    value.trace_add('write', lambda *_: count.set(f'입력된 글자: {len(value.get())}'))
    ttk.Label(frame, textvariable=count).pack(anchor='w')
    label = '자동연결: 키를 Windows 계정으로 암호화해 저장합니다.' if '--auto' in sys.argv else '키는 파일에 저장하지 않습니다.'
    ttk.Label(frame, text=label).pack(anchor='w', pady=8)

    def submit(*_):
        if value.get().strip():
            result.append(value.get().strip())
            root.destroy()

    def paste():
        try:
            value.set(root.clipboard_get().strip())
        except tk.TclError:
            count.set('클립보드에 텍스트가 없습니다.')

    buttons = ttk.Frame(frame)
    buttons.pack(fill='x', pady=5)
    ttk.Button(buttons, text='클립보드에서 붙여넣기', command=paste).pack(side='left')
    ttk.Button(buttons, text='연결', command=submit).pack(side='right')
    root.bind('<Return>', submit)
    root.after(150, lambda: (root.lift(), entry.focus_force()))
    root.mainloop()
    return result[0] if result else ''


def main():
    auto = '--auto' in sys.argv
    # Reuse an existing Gemini server without requesting the key again.
    try:
        with urlopen('http://127.0.0.1:8001/api/health', timeout=2) as response:
            health = json.load(response)
        if health.get('provider') == 'gemini':
            webbrowser.open('http://127.0.0.1:8001')
            return
    except Exception:
        pass
    saved = None
    if auto:
        from local_credentials import load
        try:
            saved = load()
        except (OSError, ValueError):
            print('저장된 설정을 읽지 못했습니다. 다시 설정해 주세요.')
    print('Gemini 연결: 키는 화면/로그에 표시하지 않습니다.')
    print('모델 목록과 가상 인사말을 Google API로 전송합니다. 사용량이 발생할 수 있습니다.')
    print('이후 대화와 분석 집계자료도 Google로 전송됩니다. 데모 자료만 사용하세요.')
    key = saved['key'] if saved else prompt_api_key()
    if not key:
        print('키가 입력되지 않았습니다.')
        return
    if not key.isascii() or any(char.isspace() or ord(char) < 33 for char in key):
        print('입력값에 공백 또는 잘못된 문자가 있습니다. 키만 복사해서 다시 입력해 주세요.')
        return
    try:
        print('1/2: Google 모델 확인 중...')
        models = [saved['model']] if saved else list_models(key)
        if not models:
            print('generateContent 지원 모델이 반환되지 않았습니다.')
            return
        if saved:
            model = saved['model']
        else:
            for i, model in enumerate(models, 1):
                print(f'{i}. {model}')
            print('목록은 호출 성공이나 무료 할당량을 보장하지 않습니다.')
            while True:
                choice = input('사용할 모델 번호 (숫자만, 예: 26): ').strip().strip('*').strip()
                if choice.isascii() and choice.isdigit() and 1 <= int(choice) <= len(models):
                    break
                print(f'1부터 {len(models)} 사이의 번호를 입력해 주세요.')
            model = models[int(choice) - 1]
        print('2/2: 선택한 모델의 단순 생성 호출 중...')
        reply = gemini_ping(key, model)
        print(f'단순 생성 확인: {reply[:200]}')
    except GeminiNativeError as exc:
        print(f'연결 실패 (HTTP {exc.status}): {exc.public_message}')
        print('위 오류 문구를 알려 주세요. API 키는 공유하지 마세요.')
        return
    os.environ['AI_PROVIDER'] = 'gemini'
    os.environ['GEMINI_API_KEY'] = key
    os.environ['GEMINI_MODEL'] = model
    if auto and not saved:
        from local_credentials import save
        save(key, model)
        print('자동연결 설정을 Windows 계정으로 암호화해 저장했습니다.')
    import uvicorn
    print('실제 대화 서버: http://127.0.0.1:8001 (종료: Ctrl+C)')
    def open_when_ready():
        for _ in range(40):
            try:
                with urlopen('http://127.0.0.1:8001/api/health', timeout=1) as response:
                    if response.status == 200:
                        webbrowser.open('http://127.0.0.1:8001')
                        return
            except Exception:
                time.sleep(0.25)
    threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run('app:app', host='127.0.0.1', port=8001)


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print('\n연결을 종료했습니다.')
