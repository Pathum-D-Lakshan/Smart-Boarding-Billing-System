/* Native protected POSTs; passwords never enter storage, URLs or JS requests. */
(() => {
    const native=typeof document.createElement('dialog').showModal==='function';
    const theme=window.SmartBoardingTheme;
    const appearance=document.querySelector('[data-settings-appearance]');
    const surface=document.getElementById('settings-surface');
    let posting=false,confirmDialog=null,confirmPassword=null,opener=null;
    function clearPasswords() {
        for(const input of document.querySelectorAll('input[type="password"],input[data-settings-password]')){input.value='';input.type='password';}
        for(const eye of document.querySelectorAll('[data-settings-eye]')){eye.setAttribute('aria-label',eye.dataset.settingsShowLabel);eye.setAttribute('aria-pressed','false');}
    }
    function restoreTheme() {
        if(!appearance||!theme)return;
        const saved=theme.saved();theme.preview(saved);
        for(const input of appearance.querySelectorAll('[data-settings-theme]'))input.checked=input.value===saved;
    }
    for(const eye of document.querySelectorAll('[data-settings-eye]')) {
        const input=document.getElementById(eye.dataset.settingsEye);
        input.dataset.settingsPassword='';eye.dataset.settingsShowLabel=eye.getAttribute('aria-label');eye.hidden=false;
        eye.addEventListener('click',()=>{
            const reveal=input.type==='password';input.type=reveal?'text':'password';
            eye.setAttribute('aria-label',eye.dataset.settingsShowLabel.replace(/^Show /,reveal?'Hide ':'Show '));eye.setAttribute('aria-pressed',String(reveal));
        });
    }
    if(appearance&&theme) {
        const approved=surface?.dataset.settingsApprovedTheme;
        const hasApproval=approved==='light'||approved==='dark';
        if(hasApproval){const persisted=theme.save(approved);delete surface.dataset.settingsApprovedTheme;
            const notice=document.createElement('p');notice.className='settings-notice';notice.setAttribute('role','status');notice.textContent=persisted===false?'Theme applied for this page. Your browser prevented saving the preference.':'Theme saved for this browser.';surface.append(notice);}
        const submitted=appearance.querySelector('[data-settings-theme]:checked');
        const retry=appearance.querySelector('[aria-invalid="true"]');
        const selected=hasApproval?approved:retry&&submitted?submitted.value:theme.saved();theme.preview(selected);
        for(const input of appearance.querySelectorAll('[data-settings-theme]')){
            input.checked=input.value===selected;input.addEventListener('change',()=>{if(input.checked)theme.preview(input.value);});
        }
        for(const cancel of document.querySelectorAll('[data-settings-theme-cancel]'))cancel.addEventListener('click',restoreTheme);
    }
    function closeConfirmation() {
        if(posting||!confirmDialog?.open)return;
        clearPasswords();restoreTheme();confirmDialog.close();
    }
    function openConfirmation() {
        if(posting||confirmDialog?.open)return;
        confirmPassword.disabled=true;
        if(!opener.form.reportValidity())return;
        confirmPassword.disabled=false;confirmPassword.value='';confirmPassword.type='password';
        confirmDialog.showModal();document.body.setAttribute('data-settings-dialog-open','');confirmPassword.focus();
    }
    const form=document.querySelector('[data-settings-confirm-form]');
    if(form&&native) {
        const section=form.querySelector('[data-settings-confirm]');
        confirmPassword=section.querySelector('input[name="current_password"]');
        opener=form.querySelector('[data-settings-open]');opener.hidden=false;
        confirmDialog=document.createElement('dialog');confirmDialog.className='settings-dialog';confirmDialog.setAttribute('aria-labelledby','settings-confirm-title');
        const header=document.createElement('div');header.className='settings-dialog-header';
        const close=document.createElement('button');close.type='button';close.className='settings-button settings-dialog-close';close.textContent='\u00d7';close.setAttribute('aria-label','Close confirmation');close.addEventListener('click',closeConfirmation);
        header.append(close);confirmDialog.append(header,section);form.append(confirmDialog);
        confirmPassword.disabled=true;
        for(const cancel of section.querySelectorAll('[data-settings-confirm-cancel]')){cancel.hidden=false;cancel.addEventListener('click',closeConfirmation);}
        opener.addEventListener('click',openConfirmation);
        confirmDialog.addEventListener('cancel',event=>{event.preventDefault();closeConfirmation();});
        confirmDialog.addEventListener('close',()=>{clearPasswords();confirmPassword.disabled=true;document.body.removeAttribute('data-settings-dialog-open');opener.focus({preventScroll:true});});
        form.addEventListener('invalid',event=>{
            if(confirmDialog.open&&event.target!==confirmPassword){confirmDialog.close();event.target.focus();}
        },true);
        if(section.dataset.passwordRetry==='true')openConfirmation();
    }
    const gate=document.querySelector('[data-settings-gate]');
    if(gate&&native) {
        const dialog=document.createElement('dialog');dialog.className='settings-dialog';dialog.setAttribute('aria-labelledby','settings-gate-title');dialog.append(gate);document.body.append(dialog);
        dialog.addEventListener('cancel',event=>{event.preventDefault();if(!posting)window.location.assign(gate.dataset.cancelUrl);});
        dialog.showModal();document.body.setAttribute('data-settings-dialog-open','');gate.querySelector('input[name="current_password"]')?.focus();
    }
    document.addEventListener('submit',event=>{
        const submitted=event.target;
        if(!submitted.matches?.('[data-settings-post]')||event.defaultPrevented)return;
        if(posting){event.preventDefault();return;}
        const endpoint=new URL(submitted.getAttribute('action'),window.location.href);
        if(endpoint.origin!==window.location.origin){event.preventDefault();clearPasswords();return;}
        if(submitted===form&&confirmDialog&&!confirmDialog.open){event.preventDefault();openConfirmation();return;}
        posting=true;submitted.dataset.settingsSubmitting='true';
        // Keep CSRF, bank/account values and password enabled for native serialization.
        for(const button of submitted.querySelectorAll('button[type="submit"]')){button.dataset.settingsLabel=button.textContent;button.disabled=true;button.textContent='Saving...';}
    });
    window.addEventListener('pagehide',()=>{clearPasswords();restoreTheme();if(surface)surface.hidden=true;});
    window.addEventListener('pageshow',event=>{
        clearPasswords();posting=false;
        if(event.persisted){window.location.reload();return;}
        if(surface)surface.hidden=false;
        // The shared prepaint/pageshow handler restores storage first; keep an
        // unsaved Settings preview visible without persisting it after a retry.
        if(appearance&&theme){const selected=appearance.querySelector('[data-settings-theme]:checked');if(selected)theme.preview(selected.value);}
        for(const submitted of document.querySelectorAll('[data-settings-submitting]'))delete submitted.dataset.settingsSubmitting;
        for(const button of document.querySelectorAll('[data-settings-label]')){button.disabled=false;button.textContent=button.dataset.settingsLabel;delete button.dataset.settingsLabel;}
    });
})();
