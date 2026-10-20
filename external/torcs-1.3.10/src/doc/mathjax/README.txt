MathJax 3.2.2 — offline Doxygen formula rendering

Upstream: https://www.mathjax.org/
Source package: npm mathjax@3.2.2
License: Apache License 2.0; see MathJax-LICENSE.txt.

tex-svg.js is an unmodified copy of es5/tex-svg-full.js from that package,
renamed to the filename Doxygen requests for its MathJax 3 SVG renderer.
SHA-256: a4354ff94fd868aea0cc6eaaa79a57fda0588646fc46ee3700a349ee0a11cbe6

The full bundle includes the TeX packages and SVG font data; no CDN, font
download, npm installation, or separate math installation is needed by readers.
mathjax-config.js disables the optional contextual menu and its extra loads.
The custom src/doc/header.html loads the two flat JavaScript files directly:
Doxygen's built-in MathJax 3 header assumes an es5/ subdirectory, whereas
HTML_EXTRA_FILES copies individual files into the output root.
Doxygen copies the bundle, configuration and license through HTML_EXTRA_FILES.
Both torcsdoc.conf and torcsdoc.conf.in must be kept in sync.

The documentation integration is verified with Doxygen 1.14.0, including its
clipboard.js and doxygen.svg assets. Use that version for a matching validation
build, or recheck the custom header/footer when changing Doxygen versions.

When updating, pin the replacement version, preserve its license, update the
digest, and test formula rendering with HTTP(S) requests blocked and file://
viewing. Verify ordinary equations, aligned derivations, and fractions.
