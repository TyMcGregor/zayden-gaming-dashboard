// Zayden Gaming HUD — client interactions
(function () {
  "use strict";

  // ---- Stat count-up animation -------------------------------
  function animateCount(el) {
    const target = parseFloat(el.dataset.count || "0");
    const decimals = parseInt(el.dataset.decimals || "0", 10);
    const duration = 1400;
    const start = performance.now();

    function step(now) {
      const t = Math.min((now - start) / duration, 1);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - t, 3);
      const current = target * eased;
      el.textContent = decimals > 0
        ? current.toFixed(decimals)
        : Math.floor(current).toLocaleString();
      if (t < 1) requestAnimationFrame(step);
      else el.textContent = decimals > 0
        ? target.toFixed(decimals)
        : Math.floor(target).toLocaleString();
    }
    requestAnimationFrame(step);
  }

  // ---- XP bar fill -------------------------------------------
  function animateXpBar(el) {
    const target = parseFloat(el.dataset.target || "0");
    // Next frame so the transition animates from the initial 0%
    requestAnimationFrame(() => {
      el.style.width = Math.min(Math.max(target, 0), 100) + "%";
    });
  }

  // ---- Parent panel toggle -----------------------------------
  function wireParentToggle() {
    const btn = document.getElementById("parent-toggle");
    const panel = document.getElementById("parent-panel");
    if (!btn || !panel) return;
    btn.addEventListener("click", () => {
      const open = panel.classList.toggle("open");
      btn.textContent = open ? "🔓 Hide Parent View" : "🔒 Parent View";
    });
  }

  // ---- Generic progress-bar fill -----------------------------
  function animateFill(el) {
    const target = parseFloat(el.dataset.target || "0");
    requestAnimationFrame(() => {
      el.style.width = Math.min(Math.max(target, 0), 100) + "%";
    });
  }

  // ---- Init --------------------------------------------------
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".stat-tile .value[data-count]").forEach(animateCount);
    document.querySelectorAll(".xp-bar .fill[data-target]").forEach(animateXpBar);
    document.querySelectorAll(".m-fill[data-target], .monet-fill[data-target]").forEach(animateFill);
    wireParentToggle();
  });
})();
