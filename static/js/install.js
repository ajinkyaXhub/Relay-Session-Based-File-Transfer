/**
 * Relay - Web App (PWA) Installation Controller
 * Manages Web App installation for Windows, Android, iOS, and Desktop.
 * Automatically removes all install options (nav button & modal) once installed.
 */

(function () {
  'use strict';

  let deferredInstallPrompt = null;

  // Check if app is already installed or launched in standalone PWA mode
  function isAppInstalled() {
    return (
      window.matchMedia('(display-mode: standalone)').matches ||
      window.matchMedia('(display-mode: minimal-ui)').matches ||
      window.navigator.standalone === true ||
      document.referrer.includes('android-app://') ||
      localStorage.getItem('relay_app_installed') === '1'
    );
  }

  // Permanently hide all installation entry points
  function hideInstallOption() {
    document.documentElement.classList.add('app-installed');
    if (document.body) document.body.classList.add('app-installed');
    const modal = document.getElementById('pwaInstallModal');
    if (modal) modal.style.display = 'none';
    const navInstallBtns = document.querySelectorAll('.nav-install-btn');
    navInstallBtns.forEach((btn) => {
      btn.style.display = 'none';
    });
  }

  function markAppInstalled() {
    try {
      localStorage.setItem('relay_app_installed', '1');
      sessionStorage.setItem('relay_pwa_installed', '1');
    } catch (_) {}
    hideInstallOption();
  }

  // Early execution to eliminate UI flicker
  if (isAppInstalled()) {
    document.documentElement.classList.add('app-installed');
  }

  // Capture standard PWA install prompt
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredInstallPrompt = e;
  });

  // Fired when the app is successfully installed by the browser
  window.addEventListener('appinstalled', () => {
    deferredInstallPrompt = null;
    markAppInstalled();
  });

  // Monitor standalone display-mode changes
  try {
    const standaloneQuery = window.matchMedia('(display-mode: standalone)');
    if (standaloneQuery && standaloneQuery.addEventListener) {
      standaloneQuery.addEventListener('change', (e) => {
        if (e.matches) markAppInstalled();
      });
    }
  } catch (_) {}

  document.addEventListener('DOMContentLoaded', () => {
    // If already installed, ensure everything stays hidden and exit
    if (isAppInstalled()) {
      hideInstallOption();
      return;
    }

    const modal = document.getElementById('pwaInstallModal');
    const navInstallBtn = document.getElementById('navInstallBtn');
    const closeBtn = document.getElementById('pwaCloseBtn');
    const dismissBtn = document.getElementById('pwaDismissBtn');
    const pwaSection = document.getElementById('pwaSection');
    const pwaIosGuide = document.getElementById('pwaIosGuide');
    const platformBadge = document.getElementById('installPlatformBadge');
    const pwaInstallDesc = document.getElementById('pwaInstallDesc');
    const triggerInstallBtn = document.getElementById('pwaTriggerInstallBtn');

    if (!modal) return;

    // Platform detection for tailored UI messaging
    const ua = navigator.userAgent || '';
    const isWindows = /Windows|Win32|Win64|WOW64/i.test(ua);
    const isIos = /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
    const isAndroid = /Android/i.test(ua);

    function configurePlatformView() {
      if (isIos) {
        if (platformBadge) platformBadge.textContent = 'iOS Web App';
        if (pwaInstallDesc) {
          pwaInstallDesc.textContent = 'Add Relay to your iPhone or iPad home screen for instant, full-screen transfers.';
        }
        if (pwaIosGuide) pwaIosGuide.style.display = 'flex';
        if (pwaSection) pwaSection.style.display = 'none';
      } else if (isAndroid) {
        if (platformBadge) platformBadge.textContent = 'Android Web App';
        if (pwaInstallDesc) {
          pwaInstallDesc.textContent = 'Install Relay on Android for instant file sharing directly from your home screen.';
        }
        if (pwaIosGuide) pwaIosGuide.style.display = 'none';
        if (pwaSection) {
          pwaSection.style.display = 'flex';
          pwaSection.classList.add('highlight');
        }
      } else if (isWindows) {
        if (platformBadge) platformBadge.textContent = 'Windows Web App';
        if (pwaInstallDesc) {
          pwaInstallDesc.textContent = 'Install Relay as a fast Web App on Windows for instant desktop and taskbar access.';
        }
        if (pwaIosGuide) pwaIosGuide.style.display = 'none';
        if (pwaSection) {
          pwaSection.style.display = 'flex';
          pwaSection.classList.add('highlight');
        }
      } else {
        if (platformBadge) platformBadge.textContent = 'Web App';
        if (pwaInstallDesc) {
          pwaInstallDesc.textContent = 'Get Relay for quick, seamless file transfers directly from your desktop or home screen.';
        }
        if (pwaIosGuide) pwaIosGuide.style.display = 'none';
        if (pwaSection) pwaSection.style.display = 'flex';
      }
    }

    function openModal() {
      if (isAppInstalled()) {
        hideInstallOption();
        return;
      }
      configurePlatformView();
      modal.style.display = 'block';
    }

    function closeModal() {
      modal.style.display = 'none';
      try {
        sessionStorage.setItem('relay_install_dismissed', '1');
      } catch (_) {}
    }

    // Upper corner button opens modal if not installed
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

    // Handle PWA installation trigger
    if (triggerInstallBtn) {
      triggerInstallBtn.addEventListener('click', async () => {
        if (deferredInstallPrompt) {
          try {
            deferredInstallPrompt.prompt();
            const choiceResult = await deferredInstallPrompt.userChoice;
            if (choiceResult && choiceResult.outcome === 'accepted') {
              markAppInstalled();
            }
          } catch (err) {
            console.warn('[Relay] Installation prompt error:', err);
          }
          deferredInstallPrompt = null;
        } else {
          // Guided fallback for browsers that don't emit beforeinstallprompt
          alert('To install Relay as a Web App: click the Install icon (⊕) in your browser address bar or use the browser menu (⋮) -> "Install Relay" / "Add to Home screen".');
          closeModal();
        }
      });
    }

    // Auto-suggest only if not previously dismissed and not already installed
    const dismissed = sessionStorage.getItem('relay_install_dismissed') === '1';
    if (!isAppInstalled() && !dismissed) {
      setTimeout(() => {
        if (!isAppInstalled()) {
          openModal();
        }
      }, 1600);
    }
  });
})();
