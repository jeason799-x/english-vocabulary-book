"""Test rapid card changes and real Windows cancellation using muted test speech."""
import base64
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import queue
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
loader = importlib.machinery.SourceFileLoader('desktop_app', str(ROOT / 'desktop_app.pyw'))
spec = importlib.util.spec_from_loader(loader.name, loader)
app = importlib.util.module_from_spec(spec)
loader.exec_module(app)
from review_engine import PracticeSession


class RecordingSpeech:
    def __init__(self):
        self.plays, self.stops = [], 0
    def start(self): pass
    def close(self): pass
    def stop(self): self.stops += 1
    def speak(self, text): return True
    def read_word(self, word, example=''):
        self.plays.append((word, example))
        return True


with TemporaryDirectory() as directory:
    store = app.DataStore(Path(directory) / 'vocabulary.json')
    voice = RecordingSpeech()
    window = app.VocabularyApp(store=store, speech=voice)
    window.withdraw()
    try:
        window.session = PracticeSession(store.words[:2], 'learn', 'off', 4)
        window.show_practice()
        first = window.session.word()
        window.update()
        assert voice.plays[-1] == (first['word'], first['example'])
        # Before idle runs, move through multiple questions; only the last may play.
        voice.plays.clear()
        for _ in range(3):
            window._advance(True, 3)
        latest = window.session.word()
        window.update()
        assert voice.plays == [(latest['word'], latest['example'])], voice.plays
        window.undo_answer()
        previous = window.session.word()
        window.update()
        assert voice.plays[-1] == (previous['word'], previous['example'])
        voice.plays.clear()
        window.show_practice()
        before = voice.stops
        window.show_home()
        window.update()
        assert not voice.plays and voice.stops > before
        window.open_word_detail(store.words[0])
        window.update()
        assert voice.plays[-1] == (store.words[0]['word'], store.words[0]['example'])
        dialog = next(child for child in window.winfo_children() if child.winfo_class() == 'Toplevel')
        before = voice.stops
        dialog.destroy()
        window.update()
        assert voice.stops > before
    finally:
        window._close()
print('UI automatic speech passed: current card only, undo, leave page, detail close.')

# C# event handlers run directly on synthesis threads while PowerShell reads stdin.
trace_setup = r'''
$voice.Volume = 0
Add-Type -ReferencedAssemblies System.Speech -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Speech.Synthesis;
public static class SpeechTrace {
    static readonly Dictionary<Prompt, string> Labels = new Dictionary<Prompt, string>();
    public static void Add(Prompt prompt, string text) {
        lock (Labels) { Labels[prompt] = text.Split(' ')[0]; }
    }
    static string Label(Prompt prompt) { lock (Labels) { return Labels[prompt]; } }
    public static void Attach(SpeechSynthesizer voice) {
        voice.SpeakStarted += (s, e) => Console.WriteLine("START " + Label(e.Prompt));
        voice.SpeakCompleted += (s, e) => Console.WriteLine((e.Cancelled ? "CANCEL " : "DONE ") + Label(e.Prompt));
        voice.SpeakProgress += (s, e) => Console.WriteLine("WORD " + e.Text);
    }
}
"@
[SpeechTrace]::Attach($voice)
[Console]::WriteLine('READY')
'''
script = app.SpeechService.WORKER_SCRIPT.replace('$voice.Volume = 100', trace_setup)
script = script.replace('[void]$voice.SpeakAsync($prompt)', '''
                    $traced = New-Object System.Speech.Synthesis.Prompt($prompt)
                    [SpeechTrace]::Add($traced, [string]$request.texts[0])
                    $voice.SpeakAsync($traced)
''')
encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
process = subprocess.Popen(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, encoding='ascii', bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW)
events = queue.Queue()
threading.Thread(target=lambda: [events.put(line.strip()) for line in process.stdout], daemon=True).start()
seen = []
def expect(value, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        event = events.get(timeout=max(.001, deadline - time.monotonic()))
        seen.append(event)
        if event == value:
            return
    raise AssertionError((value, seen))

speech = app.SpeechService()
speech.process = process
try:
    expect('READY')
    speech.read_word('apple ' * 500, 'Oldexample should never play.')
    expect('START apple')
    began = time.monotonic()
    speech.read_word('pear', 'Newexample contains a ripe pear.')
    expect('START pear', timeout=3)
    switch_ms = (time.monotonic() - began) * 1000
    expect('DONE pear')
    assert 'CANCEL apple' in seen, seen
    assert not any('Oldexample' in event for event in seen), seen
    assert seen.index('WORD pear') < seen.index('WORD Newexample'), seen
    speech.read_word('banana ' * 500, 'Pendingexample should also be cancelled.')
    expect('START banana')
    speech.stop()
    expect('CANCEL banana')
    assert not any('Pendingexample' in event for event in seen), seen
    print(json.dumps({'windows_speech': 'passed', 'switch_ms': round(switch_ms, 1),
                      'old_example_cancelled': True, 'new_word_before_example': True,
                      'stop_cancels_pending_example': True}))
finally:
    speech.close()
    process.wait(timeout=5)
    if process.returncode not in (0, 1):
        print('Speech test worker exit:', process.returncode)
