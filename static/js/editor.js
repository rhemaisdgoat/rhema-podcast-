/* Article editor: write/preview tabs and inline image upload */
(function () {
  var textarea = document.getElementById("content");
  var preview = document.getElementById("preview");
  var tabs = document.querySelectorAll(".tab[data-tab]");

  tabs.forEach(function (t) {
    t.addEventListener("click", function () {
      tabs.forEach(function (x) { x.classList.remove("active"); });
      t.classList.add("active");
      if (t.dataset.tab === "preview") {
        var body = new FormData();
        body.append("content", textarea.value);
        fetch(window.URLS.preview, {
          method: "POST", body: body, headers: { "X-CSRF-Token": window.CSRF }
        }).then(function (r) { return r.json(); }).then(function (d) {
          preview.innerHTML = d.html || "<p class='muted'>Nothing to preview yet.</p>";
          textarea.hidden = true;
          preview.hidden = false;
        });
      } else {
        preview.hidden = true;
        textarea.hidden = false;
      }
    });
  });

  var insertBtn = document.getElementById("insert-image");
  var fileInput = document.getElementById("image-file");
  insertBtn.addEventListener("click", function () { fileInput.click(); });
  fileInput.addEventListener("change", function () {
    if (!fileInput.files.length) return;
    var body = new FormData();
    body.append("image", fileInput.files[0]);
    insertBtn.textContent = "Uploading...";
    fetch(window.URLS.upload, {
      method: "POST", body: body, headers: { "X-CSRF-Token": window.CSRF }
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (d.url) {
        var md = "\n\n![image description](" + d.url + ")\n\n";
        var pos = textarea.selectionStart || textarea.value.length;
        textarea.value = textarea.value.slice(0, pos) + md + textarea.value.slice(pos);
      } else {
        alert(d.error || "Upload failed");
      }
    }).catch(function () { alert("Upload failed"); }).finally(function () {
      insertBtn.textContent = "Insert image";
      fileInput.value = "";
    });
  });
})();
