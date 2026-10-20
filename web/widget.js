/* Atithi website chat — paste on any page:
 *   <script src="https://YOUR-ATITHI-SERVER/widget.js" data-atithi="wk_..." async></script>
 * Adds a chat button; the chat itself runs in an iframe served by Atithi,
 * so it can't read or change anything on the host page (and vice versa). */
(function () {
  "use strict";
  var me = document.currentScript;
  if (!me || window.__atithiWidget) return;
  window.__atithiWidget = true;
  var key = me.getAttribute("data-atithi") || "";
  var origin = new URL(me.src).origin;
  var colour = "#0f766e";

  var btn = document.createElement("button");
  btn.type = "button";
  btn.setAttribute("aria-label", "Chat with us");
  var CHAT = '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>';
  var CLOSE = '<path d="M18 6 6 18M6 6l12 12"/>';
  function icon(paths) {
    return '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="#fff" ' +
      'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + paths + '</svg>';
  }
  function place(open) {
    // Open on a small screen the chat fills it: the close button moves to the top corner.
    var top = open && window.innerWidth < 480;
    btn.style.cssText = "position:fixed;right:" + (top ? "10px" : "20px") + ";" +
      (top ? "top:8px;width:40px;height:40px;" : "bottom:20px;width:56px;height:56px;") +
      "border-radius:50%;border:none;background:" + colour + ";cursor:pointer;z-index:2147483647;" +
      "display:flex;align-items:center;justify-content:center;box-shadow:0 8px 24px -6px rgba(0,0,0,.3)";
    btn.innerHTML = icon(open ? CLOSE : CHAT);
    btn.setAttribute("aria-label", open ? "Close chat" : "Chat with us");
  }
  place(false);

  var frame = null;
  function size() {
    var small = window.innerWidth < 480;
    frame.style.cssText = "position:fixed;z-index:2147483646;border:1px solid #e7e5e4;background:#fff;" +
      "box-shadow:0 24px 48px -12px rgba(0,0,0,.25);" +
      (small ? "inset:0;width:100%;height:100%;border-radius:0;"
             : "right:20px;bottom:88px;width:370px;height:560px;max-height:calc(100vh - 110px);border-radius:14px;");
  }
  var open = false;
  btn.onclick = function () {
    if (!frame) {
      frame = document.createElement("iframe");
      frame.title = "Chat";
      frame.src = origin + "/chat?k=" + encodeURIComponent(key);
      document.body.appendChild(frame);
      window.addEventListener("resize", function () { if (open) { size(); place(true); } });
    }
    open = !open;
    if (open) { size(); } else { frame.style.display = "none"; }
    place(open);
  };
  document.body.appendChild(btn);
})();
