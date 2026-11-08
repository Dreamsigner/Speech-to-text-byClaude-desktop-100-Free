"""Headless Claude dictation: state machine and Windows entry point."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent
RECOVERY = ROOT / 'recovery'

class StopNotInvoked(RuntimeError):
    """The stop control was never invoked; another stop attempt is safe."""

class ExtractionPending(RuntimeError):
    def __init__(self, message, recovery=None):
        super().__init__(message)
        self.recovery = recovery

class Dictation:
    def __init__(self, backend, status_path=None):
        self.b = backend
        self.status_path = Path(status_path) if status_path else ROOT / 'status.json'
        self.state = 'idle'
        self.pending_stop = False
        self.paste_attempted = False
        self.target = None
        self.lock = threading.Lock()
        self.status()

    def status(self, error=None):
        try:
            tmp = self.status_path.with_suffix('.tmp')
            tmp.write_text(json.dumps({'pid':os.getpid(), 'state':self.state, 'error':str(error) if error else None}, ensure_ascii=False), encoding='utf-8')
            os.replace(tmp, self.status_path)
        except OSError: pass

    def hotkey(self):
        with self.lock:
            if self.state == 'idle':
                self.state = 'starting'
                self.status()
                threading.Thread(target=self._start, daemon=True).start()
            elif self.state == 'starting':
                self.pending_stop = True
            elif self.state == 'blocked':
                self.state = 'checking_recovery'
                self.status()
                threading.Thread(target=self._rearm, daemon=True).start()
            elif self.state in ('recording', 'uncertain_start'):
                self.state = 'stopping'
                self.status()
                threading.Thread(target=self._stop, daemon=True).start()

    def _rearm(self):
        try:
            if not self.b.can_rearm():
                raise RuntimeError('Dictée précédente à vérifier dans Claude ; brouillon conservé.')
            with self.lock:
                self.state = 'starting'
                self.status()
                threading.Thread(target=self._start, daemon=True).start()
        except Exception as exc:
            self.b.error('Reprise impossible', exc)
            with self.lock:
                self.state = 'blocked'
                self.status(exc)

    def _start(self):
        try:
            self.paste_attempted = False
            self.target = self.b.capture_target()
            self.b.start(self.target)
            with self.lock:
                if self.pending_stop:
                    self.pending_stop = False
                    self.state = 'stopping'
                    self.status()
                    threading.Thread(target=self._stop, daemon=True).start()
                else:
                    self.state = 'recording'
                    self.status()
        except Exception as exc:
            self.b.error('Démarrage impossible', exc)
            with self.lock:
                self.state = 'idle' if ('Brouillon Claude non vide' in str(exc) or 'fenêtre cible autre que Claude' in str(exc)) else 'uncertain_start'
                if self.state == 'uncertain_start':
                    self.b.uncertain = True
                    if self.pending_stop:
                        self.state = 'stopping'
                        threading.Thread(target=self._stop, daemon=True).start()
                self.pending_stop = False
                self.status(exc)

    def _stop(self):
        try:
            text = self.b.stop_and_extract()
            if text.strip():
                self.paste_attempted = True
                self.b.paste(self.target, text)
            else:
                self.b.restore(self.target)
        except Exception as exc:
            self.b.error('Dictée interrompue', exc)
            with self.lock:
                self.state = 'recording' if isinstance(exc, StopNotInvoked) else 'blocked'
                self.pending_stop = False
                self.status(exc)
        else:
            with self.lock:
                self.state = 'idle'
                self.pending_stop = False
                self.status()

class Worker:
    def __init__(self):
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        self.proc = subprocess.Popen(['powershell.exe','-STA','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(ROOT/'uia_bridge.ps1')], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', creationflags=flags, bufsize=1)
        self.lines = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.mutex = threading.Lock()
    def _read(self):
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)
    def call(self, command, timeout=30):
        with self.mutex:
            self.proc.stdin.write(json.dumps(command, ensure_ascii=True)+'\n')
            self.proc.stdin.flush()
            try: line = self.lines.get(timeout=timeout)
            except queue.Empty:
                self.proc.terminate()
                raise TimeoutError('Délai UI Automation dépassé ; pont arrêté')
            if line is None: raise RuntimeError('Processus UI Automation arrêté')
            result = json.loads(line)
            if not result.get('ok'):
                error = result.get('error','Erreur UI Automation')
                if result.get('code') == 'stop_not_invoked': raise StopNotInvoked(error)
                if result.get('recovery'): raise ExtractionPending(error, result['recovery'])
                raise RuntimeError(error)
            return result

if os.name == 'nt':
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    class GUITHREADINFO(ctypes.Structure):
        _fields_ = [('cbSize',wintypes.DWORD),('flags',wintypes.DWORD),('hwndActive',wintypes.HWND),('hwndFocus',wintypes.HWND),('hwndCapture',wintypes.HWND),('hwndMenuOwner',wintypes.HWND),('hwndMoveSize',wintypes.HWND),('hwndCaret',wintypes.HWND),('rcCaret',wintypes.RECT)]
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [('wVk',wintypes.WORD),('wScan',wintypes.WORD),('dwFlags',wintypes.DWORD),('time',wintypes.DWORD),('dwExtraInfo',ctypes.c_size_t)]
    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [('dx',wintypes.LONG),('dy',wintypes.LONG),('mouseData',wintypes.DWORD),('dwFlags',wintypes.DWORD),('time',wintypes.DWORD),('dwExtraInfo',ctypes.c_size_t)]
    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [('uMsg',wintypes.DWORD),('wParamL',wintypes.WORD),('wParamH',wintypes.WORD)]
    class INPUTUNION(ctypes.Union):
        _fields_ = [('ki',KEYBDINPUT),('mi',MOUSEINPUT),('hi',HARDWAREINPUT)]
    class INPUT(ctypes.Structure):
        _anonymous_ = ('u',)
        _fields_ = [('type',wintypes.DWORD),('u',INPUTUNION)]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD,ctypes.POINTER(GUITHREADINFO)]
    user32.GetGUIThreadInfo.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetAncestor.argtypes = [wintypes.HWND,wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    kernel32.GetCurrentThreadId.restype=wintypes.DWORD
    user32.PeekMessageW.argtypes=[ctypes.POINTER(wintypes.MSG),wintypes.HWND,wintypes.UINT,wintypes.UINT,wintypes.UINT]
    user32.PeekMessageW.restype=wintypes.BOOL
    user32.AttachThreadInput.argtypes=[wintypes.DWORD,wintypes.DWORD,wintypes.BOOL]
    user32.AttachThreadInput.restype=wintypes.BOOL
    user32.SetFocus.argtypes=[wintypes.HWND]
    user32.SetFocus.restype=wintypes.HWND
    user32.BringWindowToTop.argtypes=[wintypes.HWND]
    user32.BringWindowToTop.restype=wintypes.BOOL
    user32.IsIconic.argtypes=[wintypes.HWND]
    user32.IsIconic.restype=wintypes.BOOL
    user32.ShowWindow.argtypes=[wintypes.HWND,ctypes.c_int]
    user32.ShowWindow.restype=wintypes.BOOL
    user32.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user32.GetClassNameW.restype=ctypes.c_int
    user32.SendMessageTimeoutW.argtypes=[wintypes.HWND,wintypes.UINT,ctypes.c_size_t,ctypes.c_ssize_t,wintypes.UINT,wintypes.UINT,ctypes.POINTER(ctypes.c_size_t)]
    user32.SendMessageTimeoutW.restype=ctypes.c_size_t
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.SendInput.argtypes = [wintypes.UINT,ctypes.POINTER(INPUT),ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT,wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT,ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL

class WindowsBackend:
    def __init__(self): self.worker = Worker(); self.uncertain = False; self.claude_hwnd = None; self.was_minimized = False
    def error(self, label, exc):
        print(f'{label}: {exc}', file=sys.stderr, flush=True)
    def capture_target(self):
        hwnd = user32.GetForegroundWindow()
        if not hwnd: raise RuntimeError('Aucune fenêtre cible active')
        info = GUITHREADINFO(); info.cbSize = ctypes.sizeof(info)
        tid = user32.GetWindowThreadProcessId(hwnd, None)
        if not user32.GetGUIThreadInfo(tid, ctypes.byref(info)): raise ctypes.WinError(ctypes.get_last_error())
        focus=int(info.hwndFocus or hwnd)
        class_name=ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(focus,class_name,256)
        selection=None
        if class_name.value.lower() == 'edit' or class_name.value.lower().startswith('richedit'):
            start=wintypes.DWORD(); end=wintypes.DWORD(); result=ctypes.c_size_t()
            if user32.SendMessageTimeoutW(focus,0x00B0,ctypes.addressof(start),ctypes.addressof(end),2,500,ctypes.byref(result)):
                selection=(start.value,end.value)
        pid=wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        self.worker.call({'op':'capture_target'}, timeout=5)
        return {'window':int(hwnd), 'focus':focus, 'selection':selection, 'pid':pid.value}
    def start(self, target):
        self.target = target
        try:
            hwnd=self.worker.call({'op':'ensure'},timeout=35)['hwnd']
            if hwnd == target['window']:
                raise RuntimeError('Choisir une fenêtre cible autre que Claude.')
            self.claude_hwnd=hwnd
            self.was_minimized=bool(user32.IsIconic(hwnd))
            if self.was_minimized:
                user32.ShowWindow(hwnd,4)  # SW_SHOWNOACTIVATE
                time.sleep(.15)
            self.worker.call({'op':'start'}, timeout=45)
        finally:
            try: self.restore(target)
            finally:
                if self.was_minimized and self.claude_hwnd:
                    user32.ShowWindow(self.claude_hwnd,7)  # SW_SHOWMINNOACTIVE
    def stop_and_extract(self):
        try:
            if self.was_minimized and self.claude_hwnd:
                user32.ShowWindow(self.claude_hwnd,4)
            self.activate_window(self.claude_hwnd)
            if self.uncertain:
                self.worker.call({'op':'adopt_recording'}, timeout=10)
                self.uncertain = False
            self.worker.call({'op':'dispatch_stop'}, timeout=20)
            # Claude may change the foreground window while processing the stop.
            # Reactivate it before waiting for transcription to finish.
            self.activate_window(self.claude_hwnd)
            return self._extract()
        finally:
            try: self.restore(self.target)
            except Exception as exc: self.error('Restauration après arrêt impossible', exc)
            finally:
                if self.was_minimized and self.claude_hwnd:
                    user32.ShowWindow(self.claude_hwnd,7)
    def can_rearm(self):
        result = self.worker.call({'op':'rearm_check', 'hwnd':self.claude_hwnd}, timeout=10)
        if result.get('recovery'):
            self.clipboard(Path(result['recovery']).read_text(encoding='utf-8'))
        return result['safe']
    def _extract(self):
        try:
            result = self.worker.call({'op':'await_text'}, timeout=75)
        except ExtractionPending as exc:
            if exc.recovery:
                try: self.clipboard(Path(exc.recovery).read_text(encoding='utf-8'))
                except Exception as clipboard_error: self.error('Copie de récupération impossible', clipboard_error)
            raise
        if result.get('empty'): return ''
        self.clipboard(result['text'])
        if self.worker.call({'op':'clear_saved','text':result['text']}, timeout=5)['empty']:
            return result['text']
        self.worker.call({'op':'focus_editor'},timeout=5)
        time.sleep(.15)
        if user32.GetForegroundWindow() != result['hwnd']:
            raise RuntimeError('Focus Claude non confirmé ; sauvegarde : ' + result['recovery'])
        self.send_chord(0x41)
        self.send_chord(0x58)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if self.worker.call({'op':'verify_empty'}, timeout=4)['empty']: break
            time.sleep(.1)
        else: raise RuntimeError('Coupe non confirmée ; sauvegarde : ' + result['recovery'])
        if self.read_clipboard() != result['text']:
            raise RuntimeError('Texte coupé différent ; sauvegarde : ' + result['recovery'])
        return result['text']
    def ensure_thread_queue(self):
        # PeekMessage creates this worker thread's message queue even when empty.
        msg=wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg),None,0,0,0)
    def activate_window(self, hwnd):
        if not hwnd or not user32.IsWindow(hwnd): raise RuntimeError('Fenêtre fermée')
        diagnostics=[]
        for attempt in range(1,4):
            if user32.GetForegroundWindow() == hwnd: return
            direct=bool(user32.SetForegroundWindow(hwnd))
            time.sleep(.05)
            if user32.GetForegroundWindow() == hwnd: return
            self.ensure_thread_queue()
            current=kernel32.GetCurrentThreadId()
            foreground=user32.GetForegroundWindow()
            tids={user32.GetWindowThreadProcessId(foreground,None),user32.GetWindowThreadProcessId(hwnd,None)}
            attached=[]; failures=[]
            try:
                for tid in tids:
                    if tid and tid != current:
                        if user32.AttachThreadInput(current,tid,True): attached.append(tid)
                        else: failures.append((int(tid),ctypes.get_last_error()))
                brought=bool(user32.BringWindowToTop(hwnd))
                activated=bool(user32.SetForegroundWindow(hwnd))
                time.sleep(.05)
            finally:
                for tid in reversed(attached): user32.AttachThreadInput(current,tid,False)
            diagnostics.append(f'{attempt}: direct={int(direct)}, attached={attached}, attach_failed={failures}, top={int(brought)}, foreground={int(activated)}')
            if user32.GetForegroundWindow() == hwnd: return
        raise RuntimeError('Impossible de restaurer la fenêtre cible ; tentatives : ' + '; '.join(diagnostics))
    def restore(self, target):
        hwnd = target['window']
        pid=wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value != target['pid']: raise RuntimeError('Processus cible changé')
        verified = False
        try:
            self.activate_window(hwnd)
        except RuntimeError:
            if target.get('selection') is not None: raise
            verified = bool(self.worker.call({'op':'restore_target'}, timeout=5).get('verified'))
            if not verified or user32.GetForegroundWindow() != hwnd: raise
        if target.get('selection') is None and not verified:
            verified = bool(self.worker.call({'op':'restore_target'}, timeout=5).get('verified'))
        if user32.GetForegroundWindow() != hwnd: raise RuntimeError('Fenêtre cible perdue après restauration')
        info = GUITHREADINFO(); info.cbSize = ctypes.sizeof(info)
        tid = user32.GetWindowThreadProcessId(hwnd, None)
        if not user32.GetGUIThreadInfo(tid, ctypes.byref(info)): raise ctypes.WinError(ctypes.get_last_error())
        if int(info.hwndFocus or hwnd) != target['focus'] and target.get('selection') is not None:
            focus=target['focus']
            if not user32.IsWindow(focus) or user32.GetAncestor(focus,2) != hwnd:
                raise RuntimeError('Contrôle cible fermé ou déplacé')
            self.ensure_thread_queue()
            current=kernel32.GetCurrentThreadId()
            thread=user32.GetWindowThreadProcessId(hwnd,None)
            attached=thread != current and bool(user32.AttachThreadInput(current,thread,True))
            try: user32.SetFocus(focus)
            finally:
                if attached: user32.AttachThreadInput(current,thread,False)
            if not user32.GetGUIThreadInfo(tid,ctypes.byref(info)): raise ctypes.WinError(ctypes.get_last_error())
        if int(info.hwndFocus or hwnd) != target['focus'] and not verified:
            raise RuntimeError('Le contrôle cible a changé ; texte conservé dans la récupération')
        if target.get('selection') is not None:
            result=ctypes.c_size_t(); start,end=target['selection']
            if not user32.SendMessageTimeoutW(target['focus'],0x00B1,start,end,2,500,ctypes.byref(result)):
                raise RuntimeError('Position du curseur impossible à restaurer')
    def clipboard(self, text):
        data = (text+'\0').encode('utf-16-le')
        handle = kernel32.GlobalAlloc(2, len(data))
        if not handle: raise ctypes.WinError(ctypes.get_last_error())
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle); raise ctypes.WinError(ctypes.get_last_error())
        ctypes.memmove(ptr,data,len(data)); kernel32.GlobalUnlock(handle)
        opened = False
        try:
            for _ in range(20):
                if user32.OpenClipboard(None): opened=True; break
                time.sleep(.05)
            if not opened: raise RuntimeError('Presse-papiers occupé')
            if not user32.EmptyClipboard(): raise ctypes.WinError(ctypes.get_last_error())
            if not user32.SetClipboardData(13,handle): raise ctypes.WinError(ctypes.get_last_error())
            handle = None
        finally:
            if opened: user32.CloseClipboard()
            if handle: kernel32.GlobalFree(handle)
    def read_clipboard(self):
        user32.GetClipboardData.argtypes=[wintypes.UINT]
        user32.GetClipboardData.restype=wintypes.HANDLE
        for _ in range(20):
            if user32.OpenClipboard(None): break
            time.sleep(.05)
        else: raise RuntimeError('Presse-papiers occupé après coupe')
        try:
            handle=user32.GetClipboardData(13)
            if not handle: raise RuntimeError('Presse-papiers sans texte Unicode')
            ptr=kernel32.GlobalLock(handle)
            if not ptr: raise ctypes.WinError(ctypes.get_last_error())
            try: return ctypes.wstring_at(ptr)
            finally: kernel32.GlobalUnlock(handle)
        finally: user32.CloseClipboard()
    def wait_modifiers(self):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if not any(user32.GetAsyncKeyState(key) & 0x8000 for key in (0x10,0x11,0x12,0x5b,0x5c)): return
            time.sleep(.025)
        raise RuntimeError('Relâcher les touches de modification avant insertion')
    def send_chord(self, key):
        self.wait_modifiers()
        keys=(INPUT*4)()
        for i,(vk,flags) in enumerate([(0x11,0),(key,0),(key,2),(0x11,2)]):
            keys[i].type=1; keys[i].ki=KEYBDINPUT(vk,0,flags,0,0)
        sent=user32.SendInput(4,keys,ctypes.sizeof(INPUT))
        if sent != 4: raise RuntimeError(f'Action clavier incertaine ({sent}/4) ; ne pas réessayer automatiquement')
        time.sleep(.15)
    def paste(self, target, text):
        self.clipboard(text)
        self.wait_modifiers()
        self.restore(target)
        keys = (INPUT*4)()
        for i,(vk,flags) in enumerate([(0x11,0),(0x56,0),(0x56,2),(0x11,2)]):
            keys[i].type=1; keys[i].ki=KEYBDINPUT(vk,0,flags,0,0)
        sent = user32.SendInput(4,keys,ctypes.sizeof(INPUT))
        if sent != 4: raise RuntimeError(f'Insertion incertaine ({sent}/4 événements) ; ne pas réessayer automatiquement')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--diagnose',action='store_true')
    args=parser.parse_args()
    if os.name != 'nt': raise SystemExit('Windows requis')
    if args.check or args.diagnose:
        worker=Worker()
        try: print(json.dumps(worker.call({'op':'diagnose'},timeout=15),ensure_ascii=False,indent=2))
        finally: worker.proc.terminate()
        return
    kernel32.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel32.CloseHandle.restype=wintypes.BOOL
    kernel32.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype=wintypes.HANDLE
    mutex=kernel32.CreateMutexW(None,False,'Local\\ClaudeDictationHeadless')
    if not mutex: raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error()==183: raise SystemExit('Dictée déjà active')
    try:
        backend=WindowsBackend()
        try: backend.worker.call({'op':'ping'},timeout=15)
        except Exception:
            backend.worker.proc.terminate()
            raise
        machine=Dictation(backend)
    except Exception:
        kernel32.CloseHandle(mutex)
        raise
    if not user32.RegisterHotKey(None,1,0x0002|0x4000,0x49):
        error=ctypes.get_last_error()
        backend.worker.proc.terminate()
        kernel32.CloseHandle(mutex)
        raise ctypes.WinError(error)
    print('Dictée Claude active : Ctrl+I pour commencer et terminer.',flush=True)
    msg=wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg),None,0,0)>0:
            if msg.message==0x0312 and msg.wParam==1: machine.hotkey()
    finally:
        user32.UnregisterHotKey(None,1); backend.worker.proc.terminate(); kernel32.CloseHandle(mutex)

if __name__=='__main__': main()
