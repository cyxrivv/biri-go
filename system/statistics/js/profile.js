/* Shared profile-picture logic for admin, hr, owner and employee pages.
   Put this file in: system/statistics/js/profile.js

   - Every <span data-profile-avatar> (the initials circles) gets the photo painted over it.
   - Every <img data-profile-img> shows the photo (or the default avatar).
   - #profilePicInput / #profilePicBtn / #profilePicRemove are the upload controls. */
(function () {
  "use strict";
  var URL_PATH = "/account/profile-picture";
  var DEFAULT_URL = "/statistics/images/default-avatar.png";
  var AVATAR_STYLES = ["backgroundImage", "backgroundSize", "backgroundPosition", "color", "textShadow"];

  var input = document.getElementById("profilePicInput");
  var changeBtn = document.getElementById("profilePicBtn");
  var removeBtn = document.getElementById("profilePicRemove");

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
  }

  function applyPicture(url) {
    var custom = !!url && url.indexOf("/profile-pictures/") === 0;

    document.querySelectorAll("img[data-profile-img]").forEach(function (img) {
      img.src = custom ? url : DEFAULT_URL;
    });

    // Inline styles survive the page scripts rewriting the initials text.
    document.querySelectorAll("[data-profile-avatar]").forEach(function (el) {
      if (custom) {
        el.style.backgroundImage = 'url("' + url + '")';
        el.style.backgroundSize = "cover";
        el.style.backgroundPosition = "center";
        el.style.color = "transparent";      // hide the initials
        el.style.textShadow = "none";
      } else {
        AVATAR_STYLES.forEach(function (p) { el.style[p] = ""; });
      }
    });

    if (removeBtn) removeBtn.style.display = custom ? "" : "none";
  }

  async function send(method, body) {
    var res = await fetch(URL_PATH, {
      method: method,
      headers: { "X-CSRF-Token": csrfToken() },   // no Content-Type: the browser sets it for FormData
      body: body,
      credentials: "same-origin",
    });
    var data = await res.json().catch(function () { return {}; });
    if (!res.ok) throw new Error(data.error || "Something went wrong.");
    return data;
  }

  // Show the current picture on every page load
  fetch(URL_PATH, { credentials: "same-origin" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) { if (d && d.url) applyPicture(d.url); })
    .catch(function () {});

  if (input && changeBtn) {
    changeBtn.addEventListener("click", function () { input.click(); });

    input.addEventListener("change", async function () {
      var file = input.files[0];
      if (!file) return;
      if (file.size > 2 * 1024 * 1024) {
        alert("Image is too large (max 2 MB).");
        input.value = "";
        return;
      }
      var fd = new FormData();
      fd.append("picture", file);
      changeBtn.disabled = true;
      try {
        var data = await send("POST", fd);
        applyPicture(data.url);
      } catch (err) {
        alert(err.message);
      } finally {
        changeBtn.disabled = false;
        input.value = "";
      }
    });
  }

  if (removeBtn) {
    removeBtn.addEventListener("click", async function () {
      removeBtn.disabled = true;
      try {
        var data = await send("DELETE");
        applyPicture(data.url);
      } catch (err) {
        alert(err.message);
      } finally {
        removeBtn.disabled = false;
      }
    });
  }
})();