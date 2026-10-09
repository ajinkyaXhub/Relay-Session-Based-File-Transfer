/**
 * Relay - App Installation Controller
 * Manages Windows Desktop App Installer download, PWA installation,
 * platform detection, persistent upper-corner install button, and modal state.
 */

(function () {
  'use strict';

  let deferredInstallPrompt = null;

  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredInstallPrompt = e;
  });

  window.addEventListener('appinstalled', () => {
    deferredInstallPrompt = null;
    const modal = document.getElementById('pwaInstallModal');
    if (modal) modal.style.display = 'none';
    sessionStorage.setItem('relay_pwa_installed', '1');
  });

  document.addEventListener('DOMContentLoaded', () => {
    const modal = document.getElementById('pwaInstallModal');
    const navInstallBtn = document.getElementById('navInstallBtn');
    const closeBtn = document.getElementById('pwaCloseBtn');
    const dismissBtn = document.getElementById('pwaDismissBtn');
    const winSection = document.getElementById('winInstallerSection');
    const pwaSection = document.getElementById('pwaSection');
    const pwaIosGuide = document.getElementById('pwaIosGuide');
    const platformBadge = document.getElementById('installPlatformBadge');
    const triggerInstallBtn = document.getElementById('pwaTriggerInstallBtn');
    const downloadWinBtn = document.getElementById('downloadWindowsBtn');

    if (!modal) return;

    // Platform detection
    const ua = navigator.userAgent || '';
    const isWindows = /Windows|Win32|Win64|WOW64/i.test(ua);
    const isIos = /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
    const isAndroid = /Android/i.test(ua);
    const isMac = /Macintosh|MacIntel/i.test(ua);

    function configurePlatformView() {
      if (isWindows) {
        if (platformBadge) platformBadge.textContent = 'Windows App';
        if (winSection) {
          winSection.style.display = 'flex';
          winSection.classList.add('highlight');
        }
        if (pwaIosGuide) pwaIosGuide.style.display = 'none';
        if (pwaSection) pwaSection.style.display = 'flex';
      } else if (isIos) {
        if (platformBadge) platformBadge.textContent = 'iOS App';
        if (pwaIosGuide) pwaIosGuide.style.display = 'flex';
        if (winSection) winSection.style.display = 'none';
        if (pwaSection) pwaSection.style.display = 'none';
      } else if (isAndroid) {
        if (platformBadge) platformBadge.textContent = 'Android App';
        if (pwaIosGuide) pwaIosGuide.style.display = 'none';
        if (pwaSection) {
          pwaSection.style.display = 'flex';
          pwaSection.classList.add('highlight');
        }
      } else {
        if (platformBadge) platformBadge.textContent = 'Desktop & Mobile';
        if (pwaIosGuide) pwaIosGuide.style.display = 'none';
        if (winSection) winSection.style.display = 'flex';
        if (pwaSection) pwaSection.style.display = 'flex';
      }
    }

    function openModal() {
      configurePlatformView();
      modal.style.display = 'block';
    }

    function closeModal() {
      modal.style.display = 'none';
      sessionStorage.setItem('relay_install_dismissed', '1');
    }

    // Upper corner button ALWAYS opens modal, even after discarding auto-suggestion
    if (navInstallBtn) {
      navInstallBtn.addEventListener('click', (e) => {
        e.preventDefault();
        openModal();
      });
    }

    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (dismissBtn) dismissBtn.addEventListener('click', closeModal);

    // Close on backdrop click
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        closeModal();
      }
    });

    // Handle PWA trigger
    if (triggerInstallBtn) {
      triggerInstallBtn.addEventListener('click', async () => {
        if (deferredInstallPrompt) {
          deferredInstallPrompt.prompt();
          const { outcome } = await deferredInstallPrompt.userChoice;
          if (outcome === 'accepted') {
            sessionStorage.setItem('relay_pwa_installed', '1');
            modal.style.display = 'none';
          }
          deferredInstallPrompt = null;
        } else {
          alert('To install Relay as a Web App: click the Install icon (⊕) in your browser address bar or menu.');
          closeModal();
        }
      });
    }

    // Windows download tracking
    if (downloadWinBtn) {
      downloadWinBtn.addEventListener('click', () => {
        setTimeout(() => {
          modal.style.display = 'none';
        }, 800);
      });
    }

    // Auto-suggest only if not previously dismissed and not already in standalone mode
    const isStandalone = window.matchMedia('(display-mode: standalone)').matches ||
                         window.navigator.standalone === true ||
                         sessionStorage.getItem('relay_pwa_installed') === '1';

    if (!isStandalone && sessionStorage.getItem('relay_install_dismissed') !== '1') {
      setTimeout(openModal, 1600);
    }
  });
})();
