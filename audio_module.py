<script>
    // Isolated Audio Recording & Playback Logic
    let isolatedMediaRecorder = null;
    let isolatedAudioChunks = [];
    let isIsolatedRecording = false;
    let isolatedAudioStream = null;

    function toggleIsolatedVoiceRecording() {
        if (!isIsolatedRecording) {
            startIsolatedRecording();
        } else {
            stopAndSendIsolatedRecording();
        }
    }

    async function startIsolatedRecording() {
        try {
            isolatedAudioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            isolatedMediaRecorder = new MediaRecorder(isolatedAudioStream);
            isolatedAudioChunks = [];
            
            isolatedMediaRecorder.ondataavailable = (e) => {
                if (e.data && e.data.size > 0) isolatedAudioChunks.push(e.data);
            };
            
            isolatedMediaRecorder.onstop = async () => {
                if (isolatedAudioChunks.length === 0) return;
                const blob = new Blob(isolatedAudioChunks, { type: "audio/webm" });
                const form = new FormData();
                form.append("file", blob, "voice_" + Date.now() + ".webm");

                try {
                    const res = await fetch("/audio/upload", { method: "POST", body: form });
                    const data = await res.json();
                    if (data.url && typeof executeDispatch === "function") {
                        executeDispatch(data.url, "", "voice");
                    }
                } catch (err) {
                    console.error("Audio upload failed:", err);
                }
            };

            isolatedMediaRecorder.start();
            isIsolatedRecording = true;
        } catch (err) {
            alert("Microphone permission error: " + err.message);
        }
    }

    function stopAndSendIsolatedRecording() {
        if (isolatedMediaRecorder && isolatedMediaRecorder.state !== "inactive") {
            isolatedMediaRecorder.stop();
        }
        if (isolatedAudioStream) {
            isolatedAudioStream.getTracks().forEach(track => track.stop());
            isolatedAudioStream = null;
        }
        isIsolatedRecording = false;
    }
</script>
