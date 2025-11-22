/**
 * Basic Content Protection Script
 *
 * This script attempts to deter users from inspecting the website code by:
 * 1. Disabling the context menu (Right-Click).
 * 2. Blocking common Developer Tools keyboard shortcuts.
 *
 * NOTE: This is not a foolproof security measure. Experienced users can bypass this.
 */

(function () {
  "use strict";

  // Disable Right Click (Context Menu)
  document.addEventListener("contextmenu", function (e) {
    e.preventDefault();
    return false;
  });

  // Disable Keyboard Shortcuts
  document.addEventListener("keydown", function (e) {
    // Check for Ctrl+Shift+I (Inspect Element)
    if (e.ctrlKey && e.shiftKey && e.key === "I") {
      e.preventDefault();
      return false;
    }

    // Check for Ctrl+Shift+J (Console)
    if (e.ctrlKey && e.shiftKey && e.key === "J") {
      e.preventDefault();
      return false;
    }

    // Check for Ctrl+Shift+C (Inspect Element Mode)
    if (e.ctrlKey && e.shiftKey && e.key === "C") {
      e.preventDefault();
      return false;
    }

    // Check for F12 (Developer Tools)
    if (e.key === "F12") {
      e.preventDefault();
      return false;
    }

    // Check for Ctrl+U (View Source)
    if (e.ctrlKey && e.key === "u") {
      e.preventDefault();
      return false;
    }
  });

  // Optional: Clear console if opened
  // setInterval(function() {
  //     console.clear();
  //     console.log("%cStop!", "color: red; font-size: 50px; font-weight: bold;");
  //     console.log("%cThis is a browser feature intended for developers.", "font-size: 20px;");
  // }, 1000);
})();
