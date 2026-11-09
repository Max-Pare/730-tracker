// SPDX-License-Identifier: AGPL-3.0-or-later
// Progressive enhancement only: every page works without JavaScript.
(function () {
  "use strict";

  // Auto-submit selects (year switcher).
  document.querySelectorAll("[data-autosubmit]").forEach(function (el) {
    el.addEventListener("change", function () { el.form && el.form.submit(); });
  });

  // Confirmation prompts.
  document.addEventListener("submit", function (ev) {
    var btn = ev.submitter;
    var msg = (btn && btn.getAttribute("data-confirm")) || ev.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) { ev.preventDefault(); return; }
    if (ev.target.hasAttribute("data-busy")) { showOverlay(); }
  }, true);

  // Copy / print helpers.
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var src = document.querySelector(btn.getAttribute("data-copy"));
      if (!src || !navigator.clipboard) return;
      navigator.clipboard.writeText(src.textContent.trim()).then(function () {
        var old = btn.textContent; btn.textContent = "Copiato ✓";
        setTimeout(function () { btn.textContent = old; }, 1600);
      });
    });
  });
  document.querySelectorAll("[data-print]").forEach(function (btn) {
    btn.addEventListener("click", function () { window.print(); });
  });

  // Document viewer: switch scan/original, tap to zoom.
  var view = document.querySelector("[data-docview]");
  if (view) {
    var img = view.querySelector("[data-docimg]");
    view.querySelectorAll("[data-img-src]").forEach(function (b) {
      b.addEventListener("click", function () {
        if (!img) return;
        img.src = b.getAttribute("data-img-src");
        view.querySelectorAll("[data-img-src]").forEach(function (o) { o.setAttribute("aria-pressed", o === b ? "true" : "false"); });
      });
    });
    if (img) img.addEventListener("click", function () { view.classList.toggle("zoom"); });
  }

  function showOverlay() {
    var o = document.querySelector("[data-overlay]");
    if (o) o.classList.remove("hidden");
  }

  // Upload: accumulate photos from camera + gallery (+ drag & drop) into one input.
  var form = document.querySelector("form[data-upload]");
  if (!form) return;
  var collector = form.querySelector("[data-collector]");
  var previews = form.querySelector("[data-previews]");
  var sources = form.querySelectorAll("[data-source]");
  var submit = form.querySelector("[data-submit]");
  var canCollect = typeof DataTransfer !== "undefined";
  var files = [];

  if (canCollect) {
    try { new DataTransfer(); } catch (e) { canCollect = false; }
  }
  if (!canCollect) return; // fall back to plain inputs (they keep their name="files")

  sources.forEach(function (input) {
    input.removeAttribute("name");
    input.addEventListener("change", function () {
      add(input.files);
      input.value = "";
    });
  });

  function add(list) {
    for (var i = 0; i < list.length; i++) {
      var f = list[i];
      if (!/^image\//.test(f.type) && f.type !== "application/pdf" && !/\.(jpe?g|png|webp|tiff?|pdf)$/i.test(f.name)) continue;
      files.push(f);
    }
    sync();
  }

  function sync() {
    var dt = new DataTransfer();
    files.forEach(function (f) { dt.items.add(f); });
    collector.files = dt.files;
    render();
  }

  function render() {
    previews.textContent = "";
    files.forEach(function (f, idx) {
      var fig = document.createElement("figure");
      if (/^image\//.test(f.type)) {
        var im = document.createElement("img");
        im.alt = "";
        im.src = URL.createObjectURL(f);
        im.onload = function () { URL.revokeObjectURL(im.src); };
        fig.appendChild(im);
      } else {
        var pdf = document.createElement("div");
        pdf.className = "pdf";
        pdf.textContent = "PDF";
        fig.appendChild(pdf);
      }
      var cap = document.createElement("figcaption");
      cap.textContent = f.name || ("foto " + (idx + 1));
      fig.appendChild(cap);
      var rm = document.createElement("button");
      rm.type = "button";
      rm.setAttribute("aria-label", "Rimuovi " + cap.textContent);
      rm.textContent = "×";
      rm.addEventListener("click", function () { files.splice(idx, 1); sync(); });
      fig.appendChild(rm);
      previews.appendChild(fig);
    });
    if (submit) submit.textContent = files.length > 1 ? "Elabora " + files.length + " documenti" : "Elabora";
  }

  var dz = form.querySelector("[data-dropzone]");
  if (dz) {
    ["dragenter", "dragover"].forEach(function (t) {
      dz.addEventListener(t, function (e) { e.preventDefault(); dz.classList.add("drag"); });
    });
    ["dragleave", "drop"].forEach(function (t) {
      dz.addEventListener(t, function (e) { e.preventDefault(); dz.classList.remove("drag"); });
    });
    dz.addEventListener("drop", function (e) { if (e.dataTransfer) add(e.dataTransfer.files); });
  }

  form.addEventListener("submit", function (e) {
    if (!files.length) { e.preventDefault(); window.alert("Scatta una foto o scegli almeno un file."); return; }
    if (submit) submit.disabled = true;
    showOverlay();
  });
})();
