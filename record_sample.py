import sounddevice as sd
import wave
import numpy as np

fs = 16000
print('Recording 3s...')
rec = sd.rec(int(3 * fs), samplerate=fs, channels=1, dtype='int16')
sd.wait()
with wave.open('sample_mic.wav', 'wb') as wf:
	wf.setnchannels(1)
	wf.setsampwidth(2)
	wf.setframerate(fs)
	wf.writeframes(rec.tobytes())
print('Saved sample_mic.wav')
