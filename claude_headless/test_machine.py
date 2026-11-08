import sys
import ctypes
from pathlib import Path
import tempfile
import threading
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from main import Dictation, StopNotInvoked, WindowsBackend
from unittest.mock import patch, Mock
import main

class Backend:
    def __init__(self):
        self.started=threading.Event(); self.release=threading.Event(); self.done=threading.Event(); self.calls=[]; self.fail=False
    def capture_target(self): self.calls.append('capture'); return 42
    def start(self,target): self.calls.append('start'); self.started.set(); self.release.wait(2)
    def stop_and_extract(self): self.calls.append('stop'); return 'bonjour'
    def paste(self,target,text): self.calls.append(('paste',target,text)); self.done.set()
    def restore(self,target): self.calls.append(('restore',target))
    def error(self,label,exc): self.calls.append('error'); self.done.set()

class MachineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.status=Path(self.tmp.name)/'status.json'
    def tearDown(self):
        for _ in range(100):
            if not any(t.name.startswith('Thread-') and t.is_alive() for t in threading.enumerate()): break
            time.sleep(.01)
        self.tmp.cleanup()
    def test_stop_queued_during_start(self):
        b=Backend(); m=Dictation(b,self.status); m.hotkey(); self.assertTrue(b.started.wait(1)); m.hotkey(); b.release.set(); self.assertTrue(b.done.wait(2))
        self.assertEqual(b.calls,['capture','start','stop',('paste',42,'bonjour')])
    def test_empty_text_is_not_pasted(self):
        b=Backend(); b.stop_and_extract=lambda: (b.done.set() or ''); m=Dictation(b,self.status); m.hotkey(); self.assertTrue(b.started.wait(1)); m.hotkey(); b.release.set(); self.assertTrue(b.done.wait(2)); self.assertNotIn(('paste',42,''),b.calls); self.assertNotIn('error',b.calls)
        for _ in range(100):
            if ('restore',42) in b.calls: break
            time.sleep(.01)
        self.assertIn(('restore',42),b.calls)
    def test_existing_draft_returns_to_idle(self):
        b=Backend()
        def fail(target): raise RuntimeError('Brouillon Claude non vide, conservé.')
        b.start=fail; m=Dictation(b,self.status); m.hotkey(); self.assertTrue(b.done.wait(1))
        for _ in range(100):
            if m.state == 'idle': break
            time.sleep(.01)
        self.assertEqual(m.state,'idle'); self.assertNotIn('stop',b.calls)
    def test_uncertain_start_can_request_stop(self):
        b=Backend()
        def fail(target): raise RuntimeError('Démarrage non confirmé.')
        b.start=fail; m=Dictation(b,self.status); m.hotkey(); self.assertTrue(b.done.wait(1))
        for _ in range(100):
            if m.state == 'uncertain_start': break
            time.sleep(.01)
        self.assertEqual(m.state,'uncertain_start'); b.done.clear(); m.hotkey(); self.assertTrue(b.done.wait(1)); self.assertIn('stop',b.calls); self.assertIn(('paste',42,'bonjour'),b.calls)
    def test_hotkeys_during_stop_do_not_duplicate_paste(self):
        b=Backend(); entered=threading.Event(); release=threading.Event()
        def stop(): b.calls.append('stop'); entered.set(); release.wait(2); return 'bonjour'
        b.stop_and_extract=stop; m=Dictation(b,self.status); m.hotkey(); self.assertTrue(b.started.wait(1)); m.hotkey(); b.release.set(); self.assertTrue(entered.wait(1))
        m.hotkey(); m.hotkey(); release.set(); self.assertTrue(b.done.wait(1)); self.assertEqual(b.calls.count(('paste',42,'bonjour')),1)
    def test_uncertain_paste_is_not_retried(self):
        b=Backend()
        def paste(target,text): b.calls.append('paste-attempt'); raise RuntimeError('insertion incertaine')
        b.paste=paste; m=Dictation(b,self.status); m.hotkey(); self.assertTrue(b.started.wait(1)); m.hotkey(); b.release.set(); self.assertTrue(b.done.wait(1)); m.hotkey(); self.assertEqual(b.calls.count('paste-attempt'),1)
    def test_stop_not_invoked_can_be_retried(self):
        b=Backend(); attempts=[]
        def stop():
            attempts.append('stop')
            if len(attempts) == 1: raise StopNotInvoked('button unavailable')
            return 'bonjour'
        b.stop_and_extract=stop; m=Dictation(b,self.status); m.hotkey(); self.assertTrue(b.started.wait(1)); m.hotkey(); b.release.set(); self.assertTrue(b.done.wait(2))
        for _ in range(100):
            if m.state == 'recording': break
            time.sleep(.01)
        self.assertEqual(m.state,'recording'); b.done.clear(); m.hotkey(); self.assertTrue(b.done.wait(2))
        self.assertEqual(len(attempts),2); self.assertEqual(b.calls.count(('paste',42,'bonjour')),1)
    def test_failure_does_not_paste(self):
        b=Backend()
        def fail(): raise RuntimeError('failed')
        b.stop_and_extract=fail; m=Dictation(b,self.status); m.hotkey(); self.assertTrue(b.started.wait(1)); m.hotkey(); b.release.set(); self.assertTrue(b.done.wait(2)); self.assertEqual(b.calls,['capture','start','error'])
class RecoveryCyclesTests(unittest.TestCase):
    def wait_state(self, machine, state):
        for _ in range(300):
            if machine.state == state: return
            time.sleep(.01)
        self.fail(f'Expected {state}, got {machine.state}')

    def test_failed_extraction_rearms_and_three_cycles_share_controller(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=Backend(); b.release.set(); b.can_rearm=lambda: True
            attempts=[]
            def stop():
                attempts.append(1)
                if len(attempts)==2: raise RuntimeError('Texte modifié ; sauvegarde conservée')
                return 'cycle'+str(len(attempts))
            b.stop_and_extract=stop
            m=Dictation(b,Path(tmp)/'status.json')
            for cycle in range(3):
                m.hotkey(); self.wait_state(m,'recording')
                m.hotkey(); self.wait_state(m,'blocked' if cycle==1 else 'idle')
                if cycle==1:
                    m.hotkey(); self.wait_state(m,'recording')
                    m.hotkey(); self.wait_state(m,'idle')
                    break
            self.assertEqual(len(attempts),3)
            self.assertEqual([x for x in b.calls if isinstance(x,tuple) and x[0]=='paste'], [('paste',42,'cycle1'),('paste',42,'cycle3')])

    def test_pending_draft_never_restarts_or_repeats_uncertain_paste(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=Backend(); b.release.set(); b.can_rearm=lambda: False
            def paste(target,text): b.calls.append('paste-attempt'); raise RuntimeError('uncertain')
            b.paste=paste; m=Dictation(b,Path(tmp)/'status.json')
            m.hotkey(); self.wait_state(m,'recording'); m.hotkey(); self.wait_state(m,'blocked')
            self.assertTrue(m.paste_attempted)
            m.hotkey(); self.wait_state(m,'blocked')
            self.assertEqual(b.calls.count('paste-attempt'),1)
            self.assertEqual(b.calls.count('start'),1)

class DispatchTests(unittest.TestCase):
    def backend(self, dispatch_error=None):
        b=WindowsBackend.__new__(WindowsBackend); b.was_minimized=False; b.claude_hwnd=123; b.target={'window':456}; b.uncertain=False
        calls=[]
        class Worker:
            def call(self, command, timeout):
                calls.append(command['op'])
                if command['op']=='dispatch_stop' and dispatch_error: raise dispatch_error
                return {'empty':True}
        b.worker=Worker(); b.activate_window=lambda hwnd: calls.append(('activate',hwnd)); b.restore=lambda target: calls.append(('restore',target['window']))
        return b,calls
    def test_transcription_finishes_before_restoring_target(self):
        b,calls=self.backend()
        self.assertEqual(b.stop_and_extract(),'')
        self.assertEqual(calls,[('activate',123),'dispatch_stop',('activate',123),'await_text',('restore',456)])
    def test_restore_failure_does_not_prevent_extraction(self):
        b,calls=self.backend()
        def fail(target): calls.append('restore_failed'); raise RuntimeError('restore failed')
        b.restore=fail; b.error=lambda label,exc: calls.append('reported')
        self.assertEqual(b.stop_and_extract(),'')
        self.assertEqual(calls,[('activate',123),'dispatch_stop',('activate',123),'await_text','restore_failed','reported'])
    def test_extraction_failure_still_restores_target(self):
        b,calls=self.backend()
        def fail(): calls.append('extract_failed'); raise RuntimeError('extract failed')
        b._extract=fail
        with self.assertRaisesRegex(RuntimeError,'extract failed'): b.stop_and_extract()
        self.assertEqual(calls,[('activate',123),'dispatch_stop',('activate',123),'extract_failed',('restore',456)])
    def test_restore_failure_does_not_hide_dispatch_error(self):
        b,calls=self.backend(StopNotInvoked('unavailable'))
        def fail(target): raise RuntimeError('restore failed')
        b.restore=fail; b.error=lambda label,exc: None
        with self.assertRaises(StopNotInvoked): b.stop_and_extract()
        self.assertNotIn('await_text',calls)
    def test_failed_dispatch_restores_without_retry_or_wait(self):
        b,calls=self.backend(StopNotInvoked('unavailable'))
        with self.assertRaises(StopNotInvoked): b.stop_and_extract()
        self.assertEqual(calls,[('activate',123),'dispatch_stop',('restore',456)])

class RestoreSafetyTests(unittest.TestCase):
    def test_changed_child_requires_verified_logical_target(self):
        b=WindowsBackend.__new__(WindowsBackend); b.activate_window=lambda hwnd: None
        user=Mock()
        def pid(hwnd, out):
            if out is not None: ctypes.cast(out,ctypes.POINTER(main.wintypes.DWORD))[0]=77
            return 1
        def info(tid, out):
            ctypes.cast(out,ctypes.POINTER(main.GUITHREADINFO)).contents.hwndFocus=999
            return True
        user.GetWindowThreadProcessId.side_effect=pid; user.GetGUIThreadInfo.side_effect=info; user.GetForegroundWindow.return_value=100
        target={'window':100,'focus':101,'selection':None,'pid':77}
        b.worker=Mock(); b.worker.call.return_value={'verified':False}
        with patch.object(main,'user32',user):
            with self.assertRaisesRegex(RuntimeError,'contr.le cible a chang.'): b.restore(target)
            b.worker.call.return_value={'verified':True}
            b.restore(target)

    def test_uia_can_restore_after_foreground_activation_fails(self):
        b=WindowsBackend.__new__(WindowsBackend)
        b.activate_window=Mock(side_effect=RuntimeError('activation failed'))
        b.worker=Mock(); b.worker.call.return_value={'verified':True}
        user=Mock()
        def pid(hwnd,out):
            if out is not None: ctypes.cast(out,ctypes.POINTER(main.wintypes.DWORD))[0]=77
            return 1
        def info(tid,out):
            ctypes.cast(out,ctypes.POINTER(main.GUITHREADINFO)).contents.hwndFocus=999
            return True
        user.GetWindowThreadProcessId.side_effect=pid; user.GetGUIThreadInfo.side_effect=info; user.GetForegroundWindow.return_value=100
        target={'window':100,'focus':101,'selection':None,'pid':77}
        with patch.object(main,'user32',user):
            b.restore(target)
            b.worker.call.return_value={'verified':False}
            with self.assertRaisesRegex(RuntimeError,'activation failed'): b.restore(target)

class ForegroundTests(unittest.TestCase):
    def test_queue_is_created_before_attach_and_retry_is_bounded(self):
        b=WindowsBackend.__new__(WindowsBackend); events=[]; user=Mock(); kernel=Mock()
        user.IsWindow.return_value=True; user.GetForegroundWindow.return_value=1
        user.SetForegroundWindow.return_value=False; user.BringWindowToTop.return_value=False
        user.GetWindowThreadProcessId.side_effect=lambda hwnd,unused: hwnd+10
        user.PeekMessageW.side_effect=lambda *args: events.append('queue') or False
        user.AttachThreadInput.side_effect=lambda a,b,attach: events.append('attach' if attach else 'detach') or True
        kernel.GetCurrentThreadId.return_value=99
        with patch.object(main,'user32',user), patch.object(main,'kernel32',kernel), patch.object(main.time,'sleep'):
            with self.assertRaisesRegex(RuntimeError,'tentatives'): b.activate_window(2)
        self.assertEqual(events.count('queue'),3)
        self.assertEqual(events.count('attach'),6)
        for i,event in enumerate(events):
            if event == 'attach': self.assertIn('queue',events[:i])
        self.assertEqual(events.count('detach'),6)

if __name__=='__main__': unittest.main()
