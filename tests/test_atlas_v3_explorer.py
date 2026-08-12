"""Atlas explorer browser-template contract tests.

The RDF explorer these tests once opened is retired; the browser template and
the schema contract it is rendered against survive in ``explorer_render``, and
``explorer.py`` renders them from the compact Parquet search view. What is held
here is the template itself: the JavaScript it ships must parse, and the
verified shard load, catalog paging, search scrolling, release filtering, and
control-column resize behaviours it defines must stay wired the way the model
expects. ``render_atlas_explorer`` end to end -- validation included -- is
exercised against a real Parquet-built model in ``test_atlas_parquet_view``.
"""

from __future__ import annotations

import json
import re
import subprocess

import pytest

from refspec.atlas.explorer import render_atlas_explorer
from refspec.atlas.explorer_render import (
    _GRAPH_HTML,
    Atlas3ExplorerError,
    _Atlas3Template,
)


def _rendered_template() -> str:
    """Substitute the browser template without building a model.

    Every assertion below reads the template's own HTML and JavaScript rather
    than model data, so no distribution is opened to produce one.
    """

    return _Atlas3Template(_GRAPH_HTML).substitute(title="Atlas explorer", atlas_data="{}")


def test_rendered_explorer_javascript_is_syntactically_valid() -> None:
    rendered = _rendered_template()
    scripts = re.findall(r"<script(?: [^>]*)?>(.*?)</script>", rendered, re.DOTALL)

    assert len(scripts) == 2
    subprocess.run(
        ["node", "--check", "-"],
        input=scripts[-1],
        check=True,
        capture_output=True,
        text=True,
    )
    verified_load = re.search(
        r"/\* atlas-verified-shard-load:start \*/(.*?)/\* atlas-verified-shard-load:end \*/",
        scripts[-1],
        re.DOTALL,
    )
    assert verified_load is not None
    verification = verified_load.group(1)
    transport_digest = verification.index(
        "observedTransportDigest=await sha256Bytes(transportBytes)"
    )
    decompression = verification.index("contentBytes=await decompressGzip(transportBytes)")
    content_digest = verification.index(
        "observedContentDigest=await sha256Bytes(contentBytes)"
    )
    parsing = verification.index("JSON.parse")
    assert transport_digest < decompression < content_digest < parsing
    assert "index.assertedInventoryDigest!==data.distribution.assertedInventoryDigest" in scripts[-1]
    assert 'location.protocol!=="file:"' in scripts[-1]
    assert 'typeof DecompressionStream==="function"' in scripts[-1]


def test_render_limit_loads_verified_catalog_pages_without_a_second_action() -> None:
    rendered = _rendered_template()

    assert 'id="browse-more"' not in rendered
    assert "function browseMore()" not in rendered
    assert "async function loadCatalogToLimit()" in rendered
    assert "const target=visibleResourceTarget()" in rendered
    assert "while(loaded<target)" in rendered
    assert "limitLoadTimer=setTimeout(applyRenderLimit,140)" in rendered
    assert "if(!fullIndex?.releaseResources)await loadCatalogToLimit()" in rendered
    assert "if(fullMode)void loadSelectedReleaseGraphs()" in rendered
    assert "Move the slider to load more resources." in rendered
    assert "async function loadReleaseGraph(release)" in rendered
    assert "async function loadReleaseResources(release)" in rendered
    assert "active.size>8" not in rendered
    assert "Math.max(1,fullBundle.counts.resources)" in rendered
    assert "state.renderedNodes.length<=5000" in rendered
    assert "let requestedRenderLimit=state.renderLimit" in rendered
    assert 'shard.kind!=="releaseResources"' in rendered
    assert 'shard.kind!=="releaseGraph"' in rendered
    assert "visible relations" in rendered


def test_search_results_scroll_through_ranked_matches() -> None:
    rendered = _rendered_template()

    assert 'id="search-pagination"' not in rendered
    assert 'id="search-previous"' not in rendered
    assert 'id="search-next"' not in rendered
    assert 'id="search-result-status"' in rendered
    assert "const searchPageSize=40" in rendered
    assert "state.searchRows.slice(0,state.searchVisible)" in rendered
    assert "if(localMatches.size>=24)break" not in rendered
    assert 'searchResults.addEventListener("scroll"' in rendered
    assert 'fetch("/api/capabilities"' in rendered
    assert "Ranking results with DuckDB BM25" in rendered
    assert "offset:String(state.searchOffset)" in rendered


def test_release_controls_hide_other_rings_and_clear_only_visible_releases() -> None:
    rendered = _rendered_template()
    controls = re.search(
        r"/\* atlas-release-filter-controls:start \*/(.*?)/\* atlas-release-filter-controls:end \*/",
        rendered,
        flags=re.DOTALL,
    )

    assert controls is not None
    assert 'id="select-no-releases"' in rendered
    script = "\n".join(
        (
            """
const state={ring:"subject",activeReleases:new Set(["subject-a","value-a"]),selected:{},inspectorReturn:{}};
const releaseById=new Map([
  ["subject-a",{id:"subject-a",title:"Subject A",semanticRing:"subject",color:"#111",memberCount:2}],
  ["value-a",{id:"value-a",title:"Value A",semanticRing:"value",color:"#222",memberCount:3}]
]);
const appended=[];
const root={replaceChildren(){appended.length=0;},append(value){appended.push(value);},querySelectorAll(){return[];}};
const clearButton={disabled:false};
const document={getElementById(id){return id==="release-filters"?root:clearButton;},createElement(){return{className:"",innerHTML:""};}};
const search={value:""};
const releaseLabel=row=>row.title;
const esc=value=>String(value);
const format=value=>String(value);
let refreshed=0;
function refresh(){refreshed++;}
function syncRenderCapacity(){}
async function renderSearch(){}
""",
            controls.group(1),
            """
const before={visible:visibleReleaseRows().map(row=>row.id),active:[...activeVisibleReleases()]};
selectNoReleases();
const after={active:[...state.activeReleases],selected:state.selected,inspectorReturn:state.inspectorReturn,refreshed};
state.ring="";
renderReleaseFilters();
process.stdout.write(JSON.stringify({before,after,allRows:appended.map(row=>row.innerHTML)}));
""",
        )
    )
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(completed.stdout)
    assert result["before"] == {"visible": ["subject-a"], "active": ["subject-a"]}
    assert result["after"] == {
        "active": ["value-a"],
        "selected": None,
        "inspectorReturn": None,
        "refreshed": 1,
    }
    assert 'data-release="subject-a"' in result["allRows"][0]
    assert " checked" not in result["allRows"][0]
    assert 'data-release="value-a"' in result["allRows"][1]
    assert " checked" in result["allRows"][1]


def test_left_control_column_supports_pointer_and_keyboard_resize() -> None:
    rendered = _rendered_template()
    controls = re.search(
        r"/\* atlas-controls-resize:start \*/(.*?)/\* atlas-controls-resize:end \*/",
        rendered,
        flags=re.DOTALL,
    )

    assert controls is not None
    assert 'id="controls-resizer"' in rendered
    script = "\n".join(
        (
            """
globalThis.innerWidth=1440;
let width=272,captured=false;
const classes=new Set(),attributes={},handlers={};
const workspace={clientWidth:1400,style:{setProperty(_name,value){width=Number.parseInt(value,10);}},classList:{add(value){classes.add(value);},remove(value){classes.delete(value);}}};
const controlsPanel={getBoundingClientRect(){return{width};}};
const controlsResizer={
  addEventListener(name,handler){handlers[name]=handler;},
  setAttribute(name,value){attributes[name]=value;},
  setPointerCapture(){captured=true;},
  hasPointerCapture(){return captured;},
  releasePointerCapture(){captured=false;}
};
""",
            controls.group(1),
            """
handlers.pointerdown({button:0,pointerId:7,clientX:100,preventDefault(){}});
handlers.pointermove({pointerId:7,clientX:180});
const dragged=width;
handlers.pointerup({pointerId:7});
handlers.keydown({key:"ArrowRight",preventDefault(){}});
const keyboard=width;
handlers.dblclick();
process.stdout.write(JSON.stringify({dragged,keyboard,reset:width,captured,resizing:classes.has("resizing"),attributes}));
""",
        )
    )
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {
        "dragged": 352,
        "keyboard": 368,
        "reset": 272,
        "captured": False,
        "resizing": False,
        "attributes": {"aria-valuemax": "520", "aria-valuenow": "272"},
    }


def test_unversioned_renderer_rejects_retired_atlas_2_shape() -> None:
    with pytest.raises(Atlas3ExplorerError, match="type or schemaVersion"):
        render_atlas_explorer(
            {
                "type": "urn:ref:type:VocabularyAtlasExplorerView",
                "schemaVersion": "4.0",
                "title": "Retired Atlas 2 view",
            }
        )
