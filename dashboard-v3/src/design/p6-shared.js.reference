// URA Dashboard v4 — Shared interaction layer
// Tab switching, viewport toggle. Vanilla, no deps.

(function () {
  'use strict';

  function switchTab(tabId) {
    document.querySelectorAll('.tab').forEach(function (el) {
      el.classList.toggle('active', el.dataset.tab === tabId);
    });
    document.querySelectorAll('[data-tab-target]').forEach(function (btn) {
      btn.classList.toggle('active', btn.dataset.tabTarget === tabId);
    });
    // Drive per-tab background mood via body attribute
    document.body.dataset.activeTab = tabId;
    // Persist
    try { localStorage.setItem('ura-v4-tab', tabId); } catch (e) {}
    window.scrollTo({ top: 0 });
  }

  function setViewport(mode) {
    document.body.classList.toggle('mobile', mode === 'mobile');
    document.querySelectorAll('.viewport-toggle button').forEach(function (b) {
      b.classList.toggle('active', b.dataset.viewport === mode);
    });
    try { localStorage.setItem('ura-v4-viewport', mode); } catch (e) {}
  }

  function init() {
    // Tab buttons
    document.querySelectorAll('[data-tab-target]').forEach(function (btn) {
      btn.addEventListener('click', function () { switchTab(btn.dataset.tabTarget); });
    });

    // Viewport buttons
    document.querySelectorAll('.viewport-toggle button').forEach(function (btn) {
      btn.addEventListener('click', function () { setViewport(btn.dataset.viewport); });
    });

    // Zone strip (Spaces tab)
    document.querySelectorAll('[data-zone]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var zoneId = btn.dataset.zone;
        document.querySelectorAll('[data-zone]').forEach(function (z) {
          z.classList.toggle('active', z.dataset.zone === zoneId);
        });
        document.querySelectorAll('[data-zone-rooms]').forEach(function (rooms) {
          rooms.style.display = rooms.dataset.zoneRooms === zoneId ? 'block' : 'none';
        });
      });
    });

    // Pill groups (mode selectors)
    document.querySelectorAll('.pill-group').forEach(function (group) {
      group.querySelectorAll('button').forEach(function (b) {
        b.addEventListener('click', function () {
          group.querySelectorAll('button').forEach(function (x) { x.classList.remove('active'); });
          b.classList.add('active');
        });
      });
    });

    // Toggles — visual only
    // (handled by native input checkbox)

    // Restore state
    var savedTab = null;
    var savedViewport = 'desktop';
    try {
      savedTab = localStorage.getItem('ura-v4-tab');
      savedViewport = localStorage.getItem('ura-v4-viewport') || 'desktop';
    } catch (e) {}
    if (savedTab && document.querySelector('[data-tab="' + savedTab + '"]')) {
      switchTab(savedTab);
    } else {
      // Initialize background mood from the default active tab
      var defaultActive = document.querySelector('.tab.active');
      if (defaultActive) document.body.dataset.activeTab = defaultActive.dataset.tab;
    }
    setViewport(savedViewport);

    // Confirm pattern — buttons with data-confirm reveal sibling .confirm-state
    document.querySelectorAll('[data-confirm]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var parent = btn.closest('.confirmable');
        if (!parent) return;
        parent.classList.add('confirming');
        setTimeout(function () { parent.classList.remove('confirming'); }, 5000);
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
