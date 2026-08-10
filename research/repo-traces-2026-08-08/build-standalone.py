#!/usr/bin/env python3
"""Regenerate data-flow-v2.html (standalone) from data-flow-v2-artifact.html (source).

data-flow-v2-artifact.html is the single source of truth: edit it, then run this.
The standalone copy is the artifact body plus a full HTML document skeleton and a
theme-toggle button + script (which the artifact viewer otherwise provides).
Never edit data-flow-v2.html by hand.
"""
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "data-flow-v2-artifact.html"
DST = HERE / "data-flow-v2.html"

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
"""

BUTTON = '    <button id="themeToggle" type="button" aria-label="Switch colour theme">◐ theme</button>\n'

TAIL = """<script>
(function(){
  var b=document.getElementById('themeToggle');
  var r=document.documentElement;
  function cur(){
    var t=r.getAttribute('data-theme');
    if(t) return t;
    return window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';
  }
  b.addEventListener('click',function(){
    r.setAttribute('data-theme', cur()==='dark'?'light':'dark');
  });
})();
</script>
</body>
</html>
"""

body = SRC.read_text()

seam = '</style>\n\n<div class="wrap">'
assert body.count(seam) == 1, "head/body seam not found exactly once"
body = body.replace(seam, '</style>\n</head>\n<body>\n<div class="wrap">')

anchor = "    </div>\n  </div>\n</header>"
assert body.count(anchor) == 1, "titlerow anchor not found exactly once"
body = body.replace(anchor, "    </div>\n" + BUTTON + "  </div>\n</header>")

DST.write_text(HEAD + body.rstrip("\n") + "\n" + TAIL)
print(f"wrote {DST.name}: {DST.stat().st_size:,} bytes from {SRC.name}")
