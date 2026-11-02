import { useEffect, useRef, useState } from "react";
import { Icon } from "../components/ui";
import { camera, mic, speak, stopCamera, stopSpeaking } from "../runner/media";

export function DeviceCheck() {
  const bar = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const [micError, setMicError] = useState("");
  const [camError, setCamError] = useState("");

  useEffect(() => {
    let timer: ReturnType<typeof setInterval>;
    mic.init().then(() => {
      timer = setInterval(() => {
        if (bar.current) bar.current.style.width = Math.min(100, mic.level * 300) + "%";
      }, 60);
    }).catch((e: Error) => setMicError(e.message));
    camera(video.current!).catch((e: Error) => setCamError(e.message));
    return () => { clearInterval(timer); stopSpeaking(); stopCamera(); };
  }, []);

  return (
    <div className="page narrow">
      <div><h1>Microphone &amp; camera</h1><p className="muted">Check everything works before a test.</p></div>
      <div className="card"><h2>Microphone</h2><p className="muted">Speak and the bar should move.</p>
        <div className="meter"><div ref={bar} /></div><p className="error-text">{micError}</p></div>
      <div className="card"><h2>Voice</h2><p className="muted">Instructions are read aloud by the browser.</p>
        <button className="btn" onClick={() => speak("This is the MoCA voice test. If you can hear this, the voice works.")}><Icon name="play" /> Play a test sentence</button></div>
      <div className="card"><h2>Camera</h2><div className="cam"><video ref={video} autoPlay muted playsInline /></div><p className="error-text">{camError}</p></div>
    </div>
  );
}
