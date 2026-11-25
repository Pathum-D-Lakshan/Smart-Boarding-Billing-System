(() => {
    const status = document.getElementById('slip-status'), content = document.getElementById('slip-content');
    const form = document.getElementById('slip-form'), save = document.getElementById('slip-save');
    const photo = document.getElementById('slip-photo'), preview = document.getElementById('slip-preview');
    const actions = document.getElementById('slip-confirm-actions'), remove = document.getElementById('slip-delete');
    const video = document.getElementById('slip-video'), live = document.getElementById('slip-live-camera');
    const cameraStatus = document.getElementById('slip-camera-status'), cameraButton = document.getElementById('slip-open-camera');
    let selected = null, previewUrl = null, csrf = '', limit = 0, busy = false, submitted = false, expired = false;
    let cameraStream = null, cameraOpening = false, cameraTicket = 0, expiryTimer = null;
    function stopCamera() {
        ++cameraTicket;
        if (cameraStream) for (const track of cameraStream.getTracks()) track.stop();
        cameraStream = null; video.srcObject = null; live.hidden = true;
    }
    async function startCamera() {
        if (busy || submitted || expired || cameraOpening) return;
        if (!window.navigator?.mediaDevices?.getUserMedia) {
            cameraStatus.textContent = 'Tap Use Phone Camera or Gallery below. Live camera needs HTTPS and a supported browser.'; return;
        }
        stopCamera(); clearSelection(); cameraOpening = true; cameraButton.disabled = true;
        const ticket = ++cameraTicket; cameraStatus.textContent = 'Allow camera access to photograph your slip.';
        try {
            const stream = await window.navigator.mediaDevices.getUserMedia({audio: false, video: {facingMode: {ideal: 'environment'}, width: {ideal: 1920}, height: {ideal: 1080}}});
            if (ticket !== cameraTicket || busy || submitted) { for (const track of stream.getTracks()) track.stop(); return; }
            cameraStream = stream; video.srcObject = stream; live.hidden = false;
            await video.play(); cameraStatus.textContent = 'Keep the entire slip in frame, then tap Take Photo.';
        } catch {
            if (ticket === cameraTicket) { stopCamera(); cameraStatus.textContent = 'Camera access is unavailable. Allow camera permission and tap Open Camera, or use Phone Camera / Gallery below.'; }
        } finally { cameraOpening = false; cameraButton.disabled = expired || busy || submitted; }
    }
    cameraButton.addEventListener('click', startCamera);
    document.getElementById('slip-capture').addEventListener('click', () => {
        if (busy || submitted || !cameraStream) return;
        if (!video.videoWidth || !video.videoHeight) { cameraStatus.textContent = 'Camera is starting. Please wait a moment.'; return; }
        const canvas = document.createElement('canvas'); canvas.width = video.videoWidth; canvas.height = video.videoHeight;
        canvas.getContext('2d').drawImage(video, 0, 0);
        const ticket = cameraTicket;
        canvas.toBlob(blob => {
            if (!blob || busy || submitted || expired || ticket !== cameraTicket) return;
            selectFile(new File([blob], 'bank-slip.jpg', {type: 'image/jpeg'}));
        }, 'image/jpeg', 0.92);
    });
    async function post(path, body, json = false) {
        const headers = {'X-Mobile-Upload': '1'}; if (json) headers['Content-Type'] = 'application/json';
        const response = await fetch('/mobile/payment-slip/' + path, {method: 'POST', credentials: 'same-origin', cache: 'no-store', headers, body: json ? JSON.stringify(body) : body});
        const type = response.headers?.get('Content-Type');
        if (type && !type.includes('application/json')) throw new Error('Open the upload link again and press Enter site if the demo provider asks.');
        const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Upload unavailable. Check My Payments before trying again.'); return data;
    }
    async function open() {
        const fragment = new URLSearchParams(location.hash.slice(1)); const token = fragment.get('token');
        // Remove bearer secrets from browser history before making any request.
        history.replaceState(null, '', location.pathname);
        try {
            const data = await post('open', token ? {token} : {}, true); csrf = data.csrf_token; limit = data.max_bytes;
            document.getElementById('slip-bank-pending').hidden = data.bank_details_available !== false;
            if (window.setTimeout) expiryTimer = window.setTimeout(() => {
                if (submitted) return;
                stopCamera(); expired = true; save.disabled = true; cameraButton.disabled = true;
                for (const input of document.querySelectorAll('.slip-file')) input.disabled = true;
                status.textContent = 'This upload link has expired. Generate a new link from My Payments.';
            }, Math.max(1, Math.min(900, data.expires_in_seconds ?? 900)) * 1000);
            document.getElementById('slip-invoice').textContent = data.bill_reference;
            document.getElementById('slip-boarding').textContent = data.boarding_name || '';
            document.getElementById('slip-student').textContent = data.student_name;
            document.getElementById('slip-amount').textContent = 'LKR ' + Number(data.amount).toLocaleString('en-LK', {minimumFractionDigits: 2});
            const date = document.getElementById('slip-date'); date.value = data.today; date.max = data.today;
            document.getElementById('slip-limit').textContent = `JPG, PNG or static PDF, up to ${Math.round(limit / 1024 / 1024)} MB. Keep the entire slip clear and readable.`;
            content.hidden = false; status.textContent = 'Ready. Choose a slip, review it, then confirm.';
            await startCamera();
        } catch (error) { status.textContent = error.message; }
    }
    function clearSelection() {
        selected = null; save.disabled = true; preview.hidden = true; actions.hidden = true;
        if (previewUrl) { URL.revokeObjectURL(previewUrl); previewUrl = null; }
        photo.removeAttribute('src'); photo.hidden = true;
        document.getElementById('slip-filename').textContent = '';
        document.getElementById('slip-review').hidden = true;
    }
    function select(event) {
        if (busy || submitted || expired) return;
        selectFile(event.target.files?.[0]);
        if (!selected) event.target.value = '';
    }
    function selectFile(file) {
        stopCamera(); clearSelection();
        cameraStatus.textContent = '';
        const error = document.getElementById('slip-file-error'); error.textContent = '';
        if (!file) return;
        if (!/\.(jpe?g|png|pdf)$/i.test(file.name) || !file.size || file.size > limit) { error.textContent = 'Choose a non-empty JPG, PNG or PDF within the upload limit.'; return; }
        selected = file;
        cameraButton.textContent = 'Retake / Change Photo';
        if (/\.(jpe?g|png)$/i.test(file.name)) { previewUrl = URL.createObjectURL(file); photo.src = previewUrl; photo.hidden = false; }
        document.getElementById('slip-filename').textContent = file.name + ' · ' + Math.ceil(file.size / 1024) + ' KB' + (/\.pdf$/i.test(file.name) ? ' · PDF selected (opens for Owner as a protected document).' : '');
        preview.hidden = false; actions.hidden = false; document.getElementById('slip-review').hidden = false; save.disabled = expired;
        status.textContent = 'Ready to submit. Your slip has not been sent yet.';
    }
    remove.addEventListener('click', () => {
        if (busy || submitted) return;
        // Only local, unsubmitted bytes are discarded. No payment-delete endpoint.
        clearSelection();
        for (const input of document.querySelectorAll('.slip-file')) input.value = '';
        document.getElementById('slip-file-error').textContent = '';
        status.textContent = 'Slip removed. Take or choose another slip.';
        document.getElementById('slip-camera').focus();
    });
    for (const input of document.querySelectorAll('.slip-file')) input.addEventListener('change', select);
    form.addEventListener('submit', async event => {
        event.preventDefault(); if (busy || submitted || expired || !selected || !form.reportValidity()) return;
        stopCamera();
        busy = true; save.disabled = true; remove.disabled = true; save.textContent = 'Submitting…';
        for (const input of document.querySelectorAll('.slip-file')) input.disabled = true;
        const body = new FormData(form); body.append('csrf_token', csrf); body.append('slip', selected);
        try {
            await post('save', body); submitted = true; clearSelection(); content.hidden = true; status.textContent = 'Submitted to your Owner.'; document.getElementById('slip-success').hidden = false;
            if (expiryTimer !== null) window.clearTimeout(expiryTimer);
            csrf = ''; for (const input of document.querySelectorAll('.slip-file')) input.value = '';
        } catch (error) {
            status.textContent = error.message + ' Check My Payments before submitting again. Never pay twice.';
            busy = false; save.disabled = expired; remove.disabled = false; save.textContent = 'Confirm & Save';
            for (const input of document.querySelectorAll('.slip-file')) input.disabled = expired;
        }
    });
    window.addEventListener('pagehide', () => { stopCamera(); if (expiryTimer !== null) window.clearTimeout(expiryTimer); if (previewUrl) URL.revokeObjectURL(previewUrl); });
    document.addEventListener?.('visibilitychange', () => { if (document.hidden) stopCamera(); });
    open();
})();
