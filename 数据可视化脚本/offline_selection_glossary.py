"""Shared browser behavior for embedded, offline poem glossaries."""

from __future__ import annotations

import json
from typing import Any


def offline_selection_glossary_script(
    glossary: dict[str, dict[str, Any]],
    *,
    poem_selector: str,
    poem_card_selector: str,
    dynamic_root_selector: str | None = None,
    script_id: str = "offline-selection-glossary-script",
) -> str:
    """Return one self-contained script with no network-capable code paths."""
    config = {
        "poemSelector": poem_selector,
        "poemCardSelector": poem_card_selector,
        "dynamicRootSelector": dynamic_root_selector,
    }
    config_json = json.dumps(config, ensure_ascii=False, separators=(",", ":"))
    glossary_json = json.dumps(glossary, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    return f"""
<script id="{script_id}">
(function(config, glossary) {{
  "use strict";
  var byTerm = {{}};
  Object.keys(glossary || {{}}).forEach(function(id) {{
    var entry = glossary[id];
    if (entry && entry.term) byTerm[entry.term] = entry;
  }});

  var toolbar = null;
  var popover = null;
  var pending = null;
  var result = null;
  var returnTarget = null;
  var layoutFrame = 0;
  var keyboardSelecting = false;
  var highlightName = "offline-selection-active";
  var hasPersistentHighlight = false;

  function closestElement(node, selector) {{
    var element = node && (node.nodeType === 1 ? node : node.parentElement);
    return element && element.closest ? element.closest(selector) : null;
  }}
  function escapeHtml(value) {{
    return String(value == null ? "" : value).replace(/[&<>"']/g, function(ch) {{
      return {{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}}[ch];
    }});
  }}
  function codePointLength(value) {{ return Array.from(value).length; }}
  function poemForRange(range) {{
    var startPoem = closestElement(range.startContainer, config.poemSelector);
    var endPoem = closestElement(range.endContainer, config.poemSelector);
    return startPoem && startPoem === endPoem ? startPoem : null;
  }}
  function lineRect(range) {{
    var rects = Array.prototype.filter.call(range.getClientRects(), function(rect) {{
      return rect.width > 0 && rect.height > 0;
    }});
    if (!rects.length) return null;
    var center = rects[0].top + rects[0].height / 2;
    for (var i = 1; i < rects.length; i += 1) {{
      var otherCenter = rects[i].top + rects[i].height / 2;
      var tolerance = Math.max(3, Math.min(rects[0].height, rects[i].height) * 0.45);
      if (Math.abs(otherCenter - center) > tolerance) return null;
    }}
    var left = Math.min.apply(null, rects.map(function(rect) {{ return rect.left; }}));
    var right = Math.max.apply(null, rects.map(function(rect) {{ return rect.right; }}));
    var top = Math.min.apply(null, rects.map(function(rect) {{ return rect.top; }}));
    var bottom = Math.max.apply(null, rects.map(function(rect) {{ return rect.bottom; }}));
    return {{left:left, right:right, top:top, bottom:bottom, width:right-left, height:bottom-top}};
  }}
  function validSelection() {{
    var selection = window.getSelection && window.getSelection();
    if (!selection || selection.rangeCount !== 1 || selection.isCollapsed) return null;
    var range = selection.getRangeAt(0);
    var poem = poemForRange(range);
    if (!poem) return null;
    var term = selection.toString().trim();
    if (codePointLength(term) < 1 || codePointLength(term) > 32) return null;
    var rect = lineRect(range);
    if (!rect) return null;
    return {{term:term, range:range.cloneRange(), poem:poem, rect:rect}};
  }}
  function ensureToolbar() {{
    if (toolbar && toolbar.isConnected) return toolbar;
    toolbar = document.createElement("div");
    toolbar.id = "selection-toolbar";
    toolbar.className = "selection-toolbar";
    toolbar.setAttribute("role", "toolbar");
    toolbar.setAttribute("aria-label", "选中文本工具");
    toolbar.innerHTML = '<button type="button" data-selection-action="gloss">查释义</button>';
    document.body.appendChild(toolbar);
    return toolbar;
  }}
  function dismissToolbar(clearSelection) {{
    if (toolbar) {{ toolbar.remove(); toolbar = null; }}
    pending = null;
    if (clearSelection) {{
      var selection = window.getSelection && window.getSelection();
      if (selection) selection.removeAllRanges();
    }}
  }}
  function clearPersistentHighlight() {{
    if (window.CSS && window.CSS.highlights) window.CSS.highlights.delete(highlightName);
    hasPersistentHighlight = false;
  }}
  function setPersistentHighlight(range) {{
    clearPersistentHighlight();
    if (!range || !window.CSS || !window.CSS.highlights || typeof window.Highlight !== "function") return false;
    window.CSS.highlights.set(highlightName, new window.Highlight(range.cloneRange()));
    hasPersistentHighlight = true;
    return true;
  }}
  function boxNearRect(box, rect, gap) {{
    var width = box.offsetWidth;
    var height = box.offsetHeight;
    var left = Math.max(12, Math.min(rect.left + (rect.width - width) / 2, window.innerWidth - width - 12));
    var top = rect.bottom + gap;
    if (top + height > window.innerHeight - 12) top = rect.top - height - gap;
    box.style.left = left + "px";
    box.style.top = Math.max(12, Math.min(top, window.innerHeight - height - 12)) + "px";
  }}
  function showToolbar(selectionInfo) {{
    if (result) closeResult(false);
    dismissToolbar(false);
    pending = selectionInfo;
    var box = ensureToolbar();
    box.querySelector("button").setAttribute("aria-label", "查询“" + selectionInfo.term + "”的本地释义");
    boxNearRect(box, selectionInfo.rect, 8);
    requestAnimationFrame(function() {{ if (box.isConnected) box.classList.add("is-open"); }});
  }}
  function cardFor(poem) {{ return poem.closest(config.poemCardSelector) || poem; }}
  function intersectRect(rect) {{
    var left = Math.max(0, rect.left);
    var right = Math.min(window.innerWidth, rect.right);
    var top = Math.max(0, rect.top);
    var bottom = Math.min(window.innerHeight, rect.bottom);
    return right > left && bottom > top ? {{left:left,right:right,top:top,bottom:bottom,width:right-left,height:bottom-top}} : null;
  }}
  function currentAnchorRect() {{
    if (!result) return null;
    if (result.element && result.element.isConnected) return result.element.getBoundingClientRect();
    if (result.range) return lineRect(result.range) || result.range.getBoundingClientRect();
    return null;
  }}
  function dockRect(anchorRect, poem) {{
    var cardRect = cardFor(poem).getBoundingClientRect();
    var visible = intersectRect(cardRect);
    if (!visible) {{
      var x = Math.max(0, Math.min(cardRect.left + cardRect.width / 2, window.innerWidth));
      var y = Math.max(0, Math.min(cardRect.top + cardRect.height / 2, window.innerHeight));
      return {{left:x,right:x,top:y,bottom:y,width:0,height:0}};
    }}
    var centerX = anchorRect.left + anchorRect.width / 2;
    var centerY = anchorRect.top + anchorRect.height / 2;
    var x = Math.max(visible.left, Math.min(centerX, visible.right));
    var y = Math.max(visible.top, Math.min(centerY, visible.bottom));
    var distances = [Math.abs(y-visible.top), Math.abs(visible.right-x), Math.abs(visible.bottom-y), Math.abs(x-visible.left)];
    var edge = distances.indexOf(Math.min.apply(null, distances));
    if (edge === 0) y = visible.top;
    else if (edge === 1) x = visible.right;
    else if (edge === 2) y = visible.bottom;
    else x = visible.left;
    return {{left:x,right:x,top:y,bottom:y,width:0,height:0}};
  }}
  function positionResult() {{
    layoutFrame = 0;
    if (!result || !popover || !result.poem.isConnected) return;
    var anchorRect = currentAnchorRect();
    if (!anchorRect) return;
    var cardVisible = intersectRect(cardFor(result.poem).getBoundingClientRect());
    var anchorVisible = cardVisible && anchorRect.bottom > cardVisible.top && anchorRect.top < cardVisible.bottom &&
      anchorRect.right > cardVisible.left && anchorRect.left < cardVisible.right;
    boxNearRect(popover, anchorVisible ? anchorRect : dockRect(anchorRect, result.poem), 10);
  }}
  function schedulePosition() {{
    if (!result || layoutFrame) return;
    layoutFrame = requestAnimationFrame(positionResult);
  }}
  function closeResult(restoreFocus) {{
    if (!result && !popover) return;
    if (result && result.element) result.element.setAttribute("aria-expanded", "false");
    var focusTarget = returnTarget;
    if (result && result.range) {{
      var selection = window.getSelection && window.getSelection();
      if (selection) selection.removeAllRanges();
    }}
    if (popover) {{ popover.remove(); popover = null; }}
    result = null;
    returnTarget = null;
    clearPersistentHighlight();
    if (layoutFrame) {{ cancelAnimationFrame(layoutFrame); layoutFrame = 0; }}
    if (restoreFocus && focusTarget && focusTarget.isConnected) focusTarget.focus({{preventScroll:true}});
  }}
  function openResult(entry, term, anchor) {{
    closeResult(false);
    dismissToolbar(false);
    var resolved = entry || {{
      term: term,
      definition: "本地词典暂无该词条。",
      inContext: "离线模式不会调用 AI 或 Web，也不会发起网络请求。",
      category: "本地未收录",
      sourceNote: "仅使用页面内嵌词典"
    }};
    popover = document.createElement("aside");
    popover.id = "gloss-popover";
    popover.className = "gloss-popover";
    popover.setAttribute("role", "dialog");
    popover.setAttribute("aria-label", "词语释义");
    popover.innerHTML = '<div class="gloss-popover-head"><strong>' + escapeHtml(resolved.term || term) + '</strong>' +
      '<button type="button" class="gloss-close" aria-label="关闭释义" title="关闭释义">×</button></div>' +
      '<p>' + escapeHtml(resolved.definition) + '</p>' +
      (resolved.inContext ? '<p><b>句中：</b>' + escapeHtml(resolved.inContext) + '</p>' : '') +
      (resolved.category ? '<span>' + escapeHtml(resolved.category) + '</span>' : '') +
      (resolved.sourceNote ? '<small>' + escapeHtml(resolved.sourceNote) + '</small>' : '');
    document.body.appendChild(popover);
    result = anchor;
    if (anchor.range) setPersistentHighlight(anchor.range);
    returnTarget = anchor.returnTarget || anchor.element || anchor.poem;
    if (anchor.element) {{
      anchor.element.setAttribute("aria-expanded", "true");
      anchor.element.setAttribute("aria-controls", "gloss-popover");
    }}
    positionResult();
    requestAnimationFrame(function() {{ if (popover) popover.classList.add("is-open"); }});
    var close = popover.querySelector(".gloss-close");
    if (close) close.focus({{preventScroll:true}});
  }}
  function processSelection() {{
    var info = validSelection();
    if (!info) {{ if (!result) dismissToolbar(false); return; }}
    showToolbar(info);
  }}
  function desktopFinePointer(event) {{
    var fine = window.matchMedia && window.matchMedia("(any-pointer: fine)").matches;
    var fromTouch = event.sourceCapabilities && event.sourceCapabilities.firesTouchEvents;
    return fine && !fromTouch;
  }}

  document.addEventListener("mouseup", function(event) {{
    if (!desktopFinePointer(event) || event.button !== 0) return;
    if (event.target.closest && event.target.closest("#selection-toolbar")) return;
    if (!(event.target.closest && event.target.closest(config.poemSelector))) {{
      if (!result) dismissToolbar(false);
      return;
    }}
    window.setTimeout(processSelection, 0);
  }});
  document.addEventListener("keydown", function(event) {{
    if (event.key === "Escape") {{
      if (popover) {{ event.preventDefault(); closeResult(true); }}
      dismissToolbar(true);
      return;
    }}
    keyboardSelecting = event.shiftKey || ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a");
  }});
  document.addEventListener("keyup", function() {{
    if (!keyboardSelecting) return;
    keyboardSelecting = false;
    window.setTimeout(processSelection, 0);
  }});
  document.addEventListener("mousedown", function(event) {{
    if (event.target.closest && event.target.closest("#selection-toolbar")) event.preventDefault();
  }});
  document.addEventListener("click", function(event) {{
    var close = event.target.closest && event.target.closest(".gloss-close");
    if (close) {{ closeResult(true); return; }}
    var action = event.target.closest && event.target.closest('[data-selection-action="gloss"]');
    if (action && pending) {{
      event.preventDefault();
      var selected = pending;
      openResult(byTerm[selected.term] || null, selected.term, {{
        range:selected.range, poem:selected.poem, returnTarget:selected.poem
      }});
      var selection = window.getSelection && window.getSelection();
      if (selection && hasPersistentHighlight) selection.removeAllRanges();
      return;
    }}
    var termButton = event.target.closest && event.target.closest(".gloss-term");
    if (termButton) {{
      event.preventDefault();
      var entry = glossary[termButton.getAttribute("data-gloss-id")];
      if (entry) openResult(entry, entry.term, {{element:termButton, poem:termButton.closest(config.poemSelector)}});
      return;
    }}
    if (!popover && toolbar && !(event.target.closest && event.target.closest("#selection-toolbar"))) dismissToolbar(false);
  }});
  document.addEventListener("scroll", function() {{
    if (result) schedulePosition();
    else dismissToolbar(false);
  }}, true);
  window.addEventListener("resize", schedulePosition);
  if (window.visualViewport) {{
    window.visualViewport.addEventListener("resize", schedulePosition);
    window.visualViewport.addEventListener("scroll", schedulePosition);
  }}
  document.addEventListener("toggle", function(event) {{
    if (!event.target.open && result && event.target.contains(result.poem)) closeResult(false);
    if (!event.target.open && pending && event.target.contains(pending.poem)) dismissToolbar(true);
  }}, true);

  var observer = new MutationObserver(function(mutations) {{
    if (!result) return;
    if (!result.poem.isConnected) {{ closeResult(false); return; }}
    if (mutations.some(function(mutation) {{
      return mutation.target === result.poem || result.poem.contains(mutation.target);
    }})) {{ closeResult(false); return; }}
    if (!config.dynamicRootSelector) return;
    var root = result.poem.closest(config.dynamicRootSelector);
    if (!root || !root.isConnected) closeResult(false);
    else mutations.some(function(mutation) {{
      if (mutation.target === root || root.contains(mutation.target)) {{ closeResult(false); return true; }}
      return false;
    }});
  }});
  observer.observe(document.body, {{childList:true, subtree:true}});

  window.OfflineSelectionGlossary = {{
    closeForReplacement: function() {{ closeResult(false); dismissToolbar(true); }},
    reposition: schedulePosition
  }};
}})({config_json}, {glossary_json});
</script>
""".strip()
