/***************************************************************************
    file                 : mathjax-config.js
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch
 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the GNU General Public License, version 2 or (at your option) any
 * later version. Distributed WITHOUT ANY WARRANTY; see the GPL for details.
 */

// The full TeX/SVG bundle includes its fonts and TeX extensions locally.
// Disable optional menus that would request additional components.
window.MathJax = {
    options: {
        ignoreHtmlClass: 'tex2jax_ignore',
        processHtmlClass: 'tex2jax_process',
        enableMenu: false
    },
    svg: {fontCache: 'local'}
};
