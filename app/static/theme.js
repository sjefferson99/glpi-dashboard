// Applies the saved theme before the page is first drawn, so it never flashes the other one. It's loaded in <head>
// without defer, before style.css; the CSP allows no inline script, hence a file of its own. app.js runs the picker.
'use strict';

try {
  const saved = localStorage.getItem('theme');
  if (saved === 'light' || saved === 'dark') document.documentElement.dataset.theme = saved;
} catch { /* storage blocked: follow the system */ }
