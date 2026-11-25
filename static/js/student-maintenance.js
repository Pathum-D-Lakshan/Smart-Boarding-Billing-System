/* Student report presentation only; authorization and image decoding stay on the server. */
(() => {
    function showFile(input, files) {
        const zone = input.closest('[data-maintenance-upload]');
        if (!zone || input.disabled || input.closest('fieldset')?.disabled) return;
        const message = zone.parentElement.querySelector('[data-maintenance-photo-error]');
        const label = zone.querySelector('[data-maintenance-photo-label]');
        const previousError = zone.parentElement.querySelector('#maint-photo-error');
        if (previousError) previousError.hidden = true;
        let error = '';
        if (files.length > 1) error = 'Choose one photo only.';
        else if (files.length && !/\.(jpe?g|png)$/i.test(files[0].name)) error = 'Choose a JPG, JPEG or PNG photo.';
        else if (files.length && (!files[0].size || files[0].size > 5 * 1024 * 1024)) error = 'Choose a non-empty photo up to 5 MB.';
        input.setCustomValidity(error);
        zone.classList.toggle('has-error', Boolean(error));
        input.setAttribute('aria-invalid', String(Boolean(error)));
        message.textContent = error; message.hidden = !error;
        label.textContent = !error && files.length ? files[0].name : 'Click to upload a photo';
    }
    document.addEventListener('change', event => {
        const input = event.target;
        if (input.matches?.('[data-maintenance-photo]')) showFile(input, input.files || []);
    });
    for (const type of ['dragover', 'dragleave', 'drop']) document.addEventListener(type, event => {
        const zone = event.target.closest?.('[data-maintenance-upload]');
        const input = zone?.querySelector('[data-maintenance-photo]');
        if (!input) return;
        event.preventDefault();
        if (input.disabled || input.closest('fieldset')?.disabled) return;
        zone.classList.toggle('is-dragging', type === 'dragover');
        if (type !== 'drop') return;
        const files = event.dataTransfer?.files || [];
        if (!files.length) return;
        showFile(input, files);
        if (!input.validationMessage) {
            try { input.files = files; } catch (_) { input.setCustomValidity('Click the upload area to choose your photo.');input.reportValidity(); }
        }
    });
})();
